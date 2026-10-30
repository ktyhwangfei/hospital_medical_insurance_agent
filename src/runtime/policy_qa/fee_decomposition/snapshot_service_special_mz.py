"""职工门特·按项目付费费用分解快照服务（Issue #79，门诊套表胶水层）。

登记号 djh → 适配器读取完整事实快照（mz 套表）→ 确定性分解内核 → SettlementDecompositionResult。

读取与计算约定：
- 数据源为 yb_brdjxx(yllb='12')/yb_mzjyxx(fyfs='0')/yb_mzfymx + yb_dyxxtsb/yb_dyxxnd；
- 周期上下文由 dyxxtsb/dyxxnd 交易后快照推导（confirmed）；无行 → unknown；
- 资格字段（cjjrdj 军残 / gwydybz 公疗 / cblb=61 社会化退休）按 Issue #79 候选口径映射，
  内核据此独立计算军残/公疗补助；
- segment_coordinate_guard=True：分段坐标未确认时不按下界硬算（统筹/大额 not_verifiable）；
- fyfs != '0'（非项目付费）→ 明确返回不支持，不套用项目付费公式。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_decomposition_queries import hash_rows
from src.adapters.data_supply.outpatient_special_mz_queries import (
    FEE_FOR_SERVICE_FYFS,
    _to_date,
    build_special_mz_snapshot,
    derive_mz_cycle_context,
    derive_secondary_coverage_context,
    load_special_institution_level,
    load_special_mz_annual,
    load_special_mz_cycle,
    load_special_mz_fee_items,
    load_special_mz_settlement,
    locate_special_mz_registration,
)
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    RETIRED_PERSON_TYPE_CODES,
)
from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import (
    ALGORITHM_VERSION,
    decompose_employee_outpatient_special,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CitationModel,
    CoverageSummary,
    DecompositionProfile,
    SettlementDecompositionResult,
    UncertaintyModel,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    DecompositionOutcome,
    build_special_mz_facts,
)


def _meta_citation(read_at: str, source: str, row_counts: dict[str, int],
                   content_hash: str, notes: tuple[str, ...]) -> CitationModel:
    """读元数据证据：来源、内容哈希、各表行数、降级留痕（设计 §5.3-7/§9）。"""
    return CitationModel(
        id="source.snapshot_read_meta",
        kind="source_catalog",
        ref=f"{source}#special:{read_at}",
        value=content_hash,
        values=[f"{table}={count}" for table, count in sorted(row_counts.items())]
        + list(notes),
        approval_status=None,
    )


def _unavailable_result(
    djh: str,
    code: str,
    message: str,
    citations: list[CitationModel] | None = None,
) -> SettlementDecompositionResult:
    """读取/组装失败的降级结果：带 uncertainties 的 unavailable，不抛异常栈。"""
    return SettlementDecompositionResult(
        algorithm_version=ALGORITHM_VERSION,
        settlement_ref=f"special_settlement:{djh}",
        profile=DecompositionProfile(insurance_type="unknown", medical_category="unknown"),
        execution_status="unavailable",
        reconciliation_status="not_verifiable",
        uncertainties=[UncertaintyModel(id=f"u.read.{code.lower()}", code=code, message=message)],
        citations=citations or [],
        coverage=CoverageSummary(
            target_field_count=0, independently_explained_count=0,
            amount_reconciled_count=0, observed_only_count=0),
        answer_constraints=AnswerConstraints(
            may_claim_full_explanation=False, may_infer_missing_rules=False),
    )


def map_retirement_category(cblb: str | None) -> str | None:
    """cblb → 退休补充类别（Issue #79：cblb=61 原社会化退休大额段 60%；其他退休 50%）。"""
    if cblb == "61":
        return "prepaid"
    if cblb is not None and cblb in RETIRED_PERSON_TYPE_CODES:
        return "normal"
    return None


def decompose_special_mz_settlement(
    conn: Any,
    djh: str,
    hospital_code: str,
    rounding_mode: RoundingMode,
    *,
    allow_observed_deductible: bool = False,
    _kidney_fixed: bool = False,
    profile: tuple[str, str] | None = None,
) -> DecompositionOutcome:
    """登记号 → mz 套表完整事实快照 → 职工门特·按项目付费费用分解（结果 + 事实侧车）。

    - profile=None：险种/医疗类别置 unknown（ESP-CODE-001/002 实测待码表确认，不猜测）；
    - 周期上下文：dyxxtsb/dyxxnd 推导 confirmed；无行 unknown（allow_observed_deductible
      为评估口径开关，此时可取账面起付作条件输入，勾稽级）；
    - segment_coordinate_guard 恒 True：分段坐标未确认时统筹/大额 not_verifiable；
    - 事实区独立于算法（方案 §53）：结算行已取到后，后续任何 unavailable 早退
      同样携带 facts；登记/结算行未取到 → facts=None。
    """
    # 1. 定位门特登记（yllb='12' 职工）
    if _kidney_fixed:
        from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import locate_special_fixed_kidney_registration
        located = locate_special_fixed_kidney_registration(conn, djh)
    else:
        located = locate_special_mz_registration(conn, djh)
    if located.status != AdapterCallStatus.SUCCESS:
        return DecompositionOutcome(_unavailable_result(djh, "READ_FAILED", located.message or "门特登记定位查询失败"))
    if located.data["match_status"] != "unique_match":
        code = ("REGISTRATION_NOT_FOUND" if located.data["match_status"] == "not_found"
                else "REGISTRATION_AMBIGUOUS")
        return DecompositionOutcome(_unavailable_result(djh, code, located.message or "门特登记定位不唯一"))
    registration_row = located.data["registration_row"]

    # 2. 结算行（每 djh 恰好 1 行；fyfs 须为项目付费）
    if _kidney_fixed:
        from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import load_special_fixed_kidney_settlement
        settlement_res = load_special_fixed_kidney_settlement(conn, djh)
    else:
        settlement_res = load_special_mz_settlement(conn, djh)
    if settlement_res.status != AdapterCallStatus.SUCCESS:
        return DecompositionOutcome(_unavailable_result(djh, "READ_FAILED", settlement_res.message or "结算读取失败"))
    if settlement_res.data["settlement_row"] is None:
        return DecompositionOutcome(_unavailable_result(djh, "SETTLEMENT_ROW_ANOMALY",
                                   settlement_res.data.get("note") or "结算行数据异常"))
    settlement_row = settlement_res.data["settlement_row"]
    facts = build_special_mz_facts(settlement_row, registration_row, fixed=_kidney_fixed)
    from src.adapters.data_supply.settlement_dictionary_queries import load_settlement_dictionaries
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import label_facts
    from src.runtime.policy_qa.fee_decomposition.fee_items import attach_item_rows
    domains = load_settlement_dictionaries(conn).data.get("domains", {})
    item_rows = []

    def _outcome(result: SettlementDecompositionResult) -> DecompositionOutcome:
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
                attach_item_rows(result, item_rows, special=True),
                label_facts(patched, domains))
        return DecompositionOutcome(attach_item_rows(result, item_rows, special=True), label_facts(facts, domains))

    fyfs = settlement_row.get("fyfs")
    fyfs_s = None if fyfs is None else str(fyfs).strip()
    if fyfs_s != FEE_FOR_SERVICE_FYFS:
        return _outcome(_unavailable_result(
            djh, "UNSUPPORTED_FEE_METHOD",
            f"费用方式 fyfs={fyfs_s} 非项目付费（'0'），本流程不支持，不套用项目付费公式"))

    # 3. 明细完整读取
    items_res = load_special_mz_fee_items(conn, djh)
    if items_res.status != AdapterCallStatus.SUCCESS:
        return _outcome(_unavailable_result(djh, "READ_FAILED", items_res.message or "费用明细读取失败"))
    item_rows = items_res.data["item_rows"]
    if not item_rows:
        return _outcome(_unavailable_result(djh, "DETAIL_MISSING", "未取得本笔费用明细，不能把缺失记录按零费用分解"))

    # 4. 机构等级
    inst_res = load_special_institution_level(conn, hospital_code)
    if inst_res.status != AdapterCallStatus.SUCCESS:
        return _outcome(_unavailable_result(djh, "READ_FAILED", inst_res.message or "机构等级读取失败"))
    level = inst_res.data.get("h_level")
    facts.hospital_level = str(level) if level is not None else None
    notes: list[str] = []
    if inst_res.data.get("note"):
        notes.append(inst_res.data["note"])

    # 5. 周期/年度待遇（交易后快照 → 交易前口径推导）
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

    settle_date = _to_date(settlement_row.get("jyrq"))
    accumulation_row = settlement_row
    if _kidney_fixed:
        from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import fixed_accumulation_settlement
        accumulation_row = fixed_accumulation_settlement(settlement_row)
    cycle_context, cycle_notes = derive_mz_cycle_context(
        cycle_res.data["cycle_row"], annual_res.data["annual_row"], accumulation_row,
        special_record_start=_to_date(registration_row.get("tsbqsrq")),
        settle_date=settle_date,
    )
    notes.extend(cycle_notes)

    # 6. 险种/医疗类别：仅由调用方显式确认
    insurance_type, medical_category = profile if profile is not None else ("unknown", "unknown")

    # 7. 组装快照（脏数据抛 ValueError → 降级 unavailable）
    try:
        snapshot, asm_notes = build_special_mz_snapshot(
            registration_row=registration_row,
            settlement_row=settlement_row,
            item_rows=item_rows,
            institution_h_level=inst_res.data["h_level"],
            hospital_code=hospital_code,
            rounding_mode=rounding_mode,
            cycle_context=cycle_context,
            insurance_type=insurance_type,
            medical_category=medical_category,
            retirement_category=map_retirement_category(
                registration_row.get("cblb") and str(registration_row.get("cblb")).strip()),
            allow_observed_deductible=allow_observed_deductible,
            segment_coordinate_guard=True,
            secondary_coverage=derive_secondary_coverage_context(annual_res.data["annual_row"], settlement_row),
        )
    except ValueError as exc:
        return _outcome(_unavailable_result(djh, "SNAPSHOT_ASSEMBLY_FAILED", str(exc)))
    notes.extend(asm_notes)
    if _kidney_fixed:
        from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import attach_fixed_quota
        snapshot = attach_fixed_quota(snapshot, registration_row, settlement_row, cycle_res.data["cycle_row"])

    catalog_read = None
    # grziftw非零时独立区分比例先行负担与限价排除费用，不能整桶纳入二次保障。
    needs_secondary_split = any(item.full_self_pay_advance is not None and item.full_self_pay_advance != 0 for item in snapshot.items)
    # 所有行保留目录解释，既有二次保障基数仅沿原条件采用目录结果。
    if snapshot.items:
        from src.runtime.policy_qa.fee_decomposition.special_catalog_service import read_special_catalog
        catalog_read = read_special_catalog(conn, item_rows, snapshot.settle_date, hospital_code, rounding_mode)
        if catalog_read.error and needs_secondary_split:
            notes.append(catalog_read.error)
        elif catalog_read.split is not None and needs_secondary_split:
            snapshot = replace(snapshot, proportional_self_pay_2=catalog_read.split.total_proportional_self_pay)
            notes.extend(catalog_read.notes)

    # 8. 读取元数据（来源/行数/内容哈希）
    from datetime import datetime, timezone
    read_at = datetime.now(timezone.utc).isoformat()
    content_hash = hash_rows([registration_row], [settlement_row], item_rows,
                             [annual_res.data["annual_row"] or {}], [cycle_res.data["cycle_row"] or {}],
                             list(catalog_read.source_rows) if catalog_read is not None else [],
                             # 机构等级/类型决定起付档与比例档，必须纳入读取摘要。
                             [inst_res.data or {}])

    # 9. 确定性分解 + 读元数据写入 citations（kind="source_catalog"）
    if _kidney_fixed:
        from src.runtime.policy_qa.fee_decomposition.employee_special_fixed_kidney import decompose_kidney_fixed_quota
        result = decompose_kidney_fixed_quota(snapshot)
    else:
        result = decompose_employee_outpatient_special(snapshot)
    if catalog_read is not None and catalog_read.split is not None:
        result = result.model_copy(update={"fee_items": list(catalog_read.split.explanations)})
    if catalog_read is not None and catalog_read.split is not None and needs_secondary_split:
        from src.runtime.policy_qa.fee_decomposition.result import branch_to_model, calc_to_model, uncertainty_to_model
        split = catalog_read.split
        result = result.model_copy(update={
            "branches": [*result.branches, *(branch_to_model(branch) for branch in split.branches)],
            "calculations": [*result.calculations, *(calc_to_model(calc) for calc in split.calculations)],
            "uncertainties": [*result.uncertainties, *(uncertainty_to_model(uncertainty) for uncertainty in split.uncertainties)],
        })
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    result = attach_evidence(result, snapshot)
    return _outcome(result.model_copy(update={
        "citations": [*result.citations,
                      _meta_citation(read_at, "hospital_record_store",
                                     {
                                         "registration": located.data["row_count"],
                                         "settlement": settlement_res.data["row_count"],
                                         "fee_items": items_res.data["row_count"],
                                         "institution": inst_res.data["row_count"],
                                         "cycle": cycle_res.data["row_count"],
                                         "annual": annual_res.data["row_count"],
                                     },
                                     content_hash, tuple(notes))],
    }))
