"""城乡居民门特·按项目付费费用分解快照服务（Issue #81，门诊套表胶水层）。

登记号 djh → 居民定位（FUND_TYPE∈91/92/93）→ 适配器读取完整事实快照（mz 套表）
→ 目录独立分解（resident_special_catalog 复用 split_catalog）→ 居民门特内核
→ SettlementDecompositionResult。

与职工门特服务（``snapshot_service_special_mz.py``，Issue #79）的差异：
- 登记定位走居民险种集合（``locate_special_mz_resident_registration``）；
- 周期推导走居民版（``derive_mz_resident_cycle_context``：起付标准不内嵌，
  由内核经 RSP-DED 参数表按人员类别×机构档×周期位置选择）；
- **目录独立分解**：明细行适配 FeeLineItem 后经 split_catalog 独立重算
  tsbybn/tsbybw/grziftw（Issue #81 明确要求，职工门特本期用账面汇总）；
- 目录条目读取复用门诊链路的 load_drug_catalog/load_service_catalog/load_material_catalog
  （yb_ypzdml/yb_xzzlfwxm，险种无关）；
- 资格字段不映射（居民无退休/军残/公疗补充待遇；cblb 保留供起付分档）。
"""
from __future__ import annotations

from typing import Any

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_decomposition_queries import hash_rows
from src.adapters.data_supply.outpatient_special_mz_queries import (
    FEE_FOR_SERVICE_FYFS,
    derive_mz_resident_cycle_context,
    derive_secondary_coverage_context,
    load_special_mz_annual,
    load_special_mz_cycle,
    load_special_mz_fee_items,
    load_special_mz_settlement,
    locate_special_mz_resident_registration,
)
from src.adapters.data_supply.outpatient_special_mz_queries import _to_date
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import (
    decompose_resident_outpatient_special,
)

from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    DecompositionOutcome,
    build_special_mz_facts,
)
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special_mz import (
    _meta_citation,
    _unavailable_result,
)


def decompose_special_mz_resident_settlement(
    conn: Any,
    djh: str,
    hospital_code: str,
    rounding_mode: RoundingMode,
    *,
    profile: tuple[str, str] | None = ("resident", "outpatient_special"),
) -> DecompositionOutcome:
    """登记号 → mz 套表完整事实快照 → 居民门特·按项目付费费用分解（结果 + 事实侧车）。

    profile 默认 ('resident','outpatient_special'：评估/已确认链路)；生产接入由
    integration 经语义层 profile 映射显式给出，None → 内核 UNSUPPORTED_PROFILE。
    事实区独立于算法（方案 §53）：结算行已取到后，unavailable 早退同样携带 facts。
    """
    # 1. 定位居民门特登记（yllb='12'，FUND_TYPE∈91/92/93）
    located = locate_special_mz_resident_registration(conn, djh)
    if located.status != AdapterCallStatus.SUCCESS:
        return DecompositionOutcome(_unavailable_result(djh, "READ_FAILED", located.message or "居民门特登记定位查询失败"))
    if located.data["match_status"] != "unique_match":
        code = ("REGISTRATION_NOT_FOUND" if located.data["match_status"] == "not_found"
                else "REGISTRATION_AMBIGUOUS")
        return DecompositionOutcome(_unavailable_result(djh, code, located.message or "居民门特登记定位不唯一"))
    registration_row = located.data["registration_row"]

    # 2. 结算行（每 djh 恰好 1 行；fyfs 须为项目付费）
    settlement_res = load_special_mz_settlement(conn, djh)
    if settlement_res.status != AdapterCallStatus.SUCCESS:
        return DecompositionOutcome(_unavailable_result(djh, "READ_FAILED", settlement_res.message or "结算读取失败"))
    if settlement_res.data["settlement_row"] is None:
        return DecompositionOutcome(_unavailable_result(djh, "SETTLEMENT_ROW_ANOMALY",
                                   settlement_res.data.get("note") or "结算行数据异常"))
    settlement_row = settlement_res.data["settlement_row"]
    facts = build_special_mz_facts(settlement_row, registration_row)
    from src.adapters.data_supply.settlement_dictionary_queries import load_settlement_dictionaries
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import label_facts
    from src.runtime.policy_qa.fee_decomposition.fee_items import attach_item_rows
    domains = load_settlement_dictionaries(conn).data.get("domains", {})
    item_rows = []

    def _outcome(result: SettlementDecompositionResult) -> DecompositionOutcome:
        from src.runtime.policy_qa.fee_decomposition.payment_condition_context import attach_payment_condition_context
        result = attach_item_rows(result, item_rows, special=True)
        labeled = label_facts(facts, domains)
        result = attach_payment_condition_context(result, conn, djh, special=True,
            hospital_level=labeled.hospital_level,
            hospital_level_name=labeled.metadata_names.get("hospital_level"))
        # 自付一：项目付费单 grzif1 列不维护，展示值取内核按本单分量计算的结果。
        self_pay_1 = next((f for f in result.fields if f.field_code == "GRZIF1"), None)
        if self_pay_1 is not None and self_pay_1.calculated_amount is not None:
            value = self_pay_1.calculated_amount
            items = [
                item.model_copy(update={"value": value})
                if item.label == "个人支付自付（一）金额" else item
                for item in facts.items
            ]
            template = facts.display_template
            if template is not None:
                template = template.model_copy(update={"fields": [
                    field.model_copy(update={"value": value})
                    if field.field_code == "GRZIF1" else field
                    for field in template.fields
                ]})
            patched = facts.model_copy(update={"items": items, "display_template": template})
            return DecompositionOutcome(
                result,
                label_facts(patched, domains))
        return DecompositionOutcome(result, labeled)

    fyfs = settlement_row.get("fyfs")
    fyfs_s = None if fyfs is None else str(fyfs).strip()
    if fyfs_s != FEE_FOR_SERVICE_FYFS:
        return _outcome(_unavailable_result(
            djh, "UNSUPPORTED_FEE_METHOD",
            f"费用方式 fyfs={fyfs_s} 非项目付费（'0'），本流程不支持，不套用项目付费公式"))

    # 3. 明细完整读取 + 目录批量读取（Issue #81 目录独立分解）
    items_res = load_special_mz_fee_items(conn, djh)
    if items_res.status != AdapterCallStatus.SUCCESS:
        return _outcome(_unavailable_result(djh, "READ_FAILED", items_res.message or "费用明细读取失败"))
    item_rows = items_res.data["item_rows"]
    if not item_rows:
        return _outcome(_unavailable_result(djh, "DETAIL_MISSING", "未取得本笔费用明细，不能把缺失记录按零费用分解"))

    settle_date = _to_date(settlement_row.get("jyrq"))
    if settle_date is None:
        return _outcome(_unavailable_result(djh, "SNAPSHOT_ASSEMBLY_FAILED",
                                   "结算行缺少结算日期 jyrq，无法锚定快照时点"))
    from src.runtime.policy_qa.fee_decomposition.special_catalog_service import read_special_catalog
    catalog_read = read_special_catalog(conn, item_rows, settle_date, hospital_code, rounding_mode)
    if catalog_read.error:
        return _outcome(_unavailable_result(djh, "READ_FAILED", catalog_read.error))
    split = catalog_read.split
    facts.hospital_level = catalog_read.h_level
    notes = list(catalog_read.notes)

    # 5. 周期/年度待遇（交易后快照 → 交易前口径推导，居民版）
    cycle_res = load_special_mz_cycle(conn, djh)
    if cycle_res.status != AdapterCallStatus.SUCCESS:
        return _outcome(_unavailable_result(djh, "READ_FAILED", cycle_res.message or "结算周期读取失败"))
    annual_res = load_special_mz_annual(conn, djh)
    if annual_res.status != AdapterCallStatus.SUCCESS:
        return _outcome(_unavailable_result(djh, "READ_FAILED", annual_res.message or "年度待遇读取失败"))
    if cycle_res.data.get("note"):
        notes.append(cycle_res.data["note"])
    if annual_res.data.get("note"):
        notes.append(annual_res.data["note"])

    cycle_context, cycle_notes = derive_mz_resident_cycle_context(
        cycle_res.data["cycle_row"], annual_res.data["annual_row"], settlement_row)
    notes.extend(cycle_notes)

    # 6. 组装门特快照（复用职工组装函数；居民无资格映射，cblb 保留供起付分档；
    # ptybn/ptybw≠0 由其前置拦截（普通门诊费用本期不支持））
    from src.adapters.data_supply.outpatient_special_mz_queries import (
        build_special_mz_snapshot,
    )

    insurance_type, medical_category = profile if profile is not None else ("unknown", "unknown")
    try:
        snapshot, snap_notes = build_special_mz_snapshot(
            registration_row=registration_row,
            settlement_row=settlement_row,
            item_rows=item_rows,
            institution_h_level=catalog_read.h_level,
            hospital_code=hospital_code,
            rounding_mode=rounding_mode,
            cycle_context=cycle_context,
            insurance_type=insurance_type,
            medical_category=medical_category,
            retirement_category=None,
            allow_observed_deductible=False,
            segment_coordinate_guard=False,
            secondary_coverage=derive_secondary_coverage_context(annual_res.data["annual_row"], settlement_row),
        )
    except ValueError as exc:
        return _outcome(_unavailable_result(djh, "SNAPSHOT_ASSEMBLY_FAILED", str(exc)))
    notes.extend(snap_notes)

    # 7. 读取元数据（来源/行数/内容哈希）
    from datetime import datetime, timezone
    read_at = datetime.now(timezone.utc).isoformat()
    content_hash = hash_rows([registration_row], [settlement_row], item_rows,
                             [annual_res.data["annual_row"] or {}], [cycle_res.data["cycle_row"] or {}],
                             list(catalog_read.source_rows),
                             # 机构等级决定起付档与支付比例档，纳入摘要。
                             [{"h_level": catalog_read.h_level}])

    # 8. 居民门特内核（目录独立分解结果一并传入）+ 读元数据写入 citations
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    result = attach_evidence(decompose_resident_outpatient_special(snapshot, split), snapshot)
    return _outcome(result.model_copy(update={
        "citations": [*result.citations,
                      _meta_citation(read_at, "hospital_record_store",
                                     {
                                         "registration": located.data["row_count"],
                                         "settlement": settlement_res.data["row_count"],
                                         "fee_items": items_res.data["row_count"],
                                         **dict(catalog_read.row_counts),
                                         "cycle": cycle_res.data["row_count"],
                                         "annual": annual_res.data["row_count"],
                                     },
                                     content_hash, tuple(notes))],
    }))
