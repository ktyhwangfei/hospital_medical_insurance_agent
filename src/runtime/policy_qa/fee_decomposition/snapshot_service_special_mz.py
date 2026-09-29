"""职工门特·按项目付费费用分解快照服务（Issue #79，门诊套表胶水层）。

登记号 djh → 适配器读取完整事实快照（mz 套表）→ 确定性分解内核 → SettlementDecompositionResult。

与住院套表服务（``snapshot_service_special.py``）的差异：
- 数据源为 yb_brdjxx(yllb='12')/yb_mzjyxx(fyfs='0')/yb_mzfymx + yb_dyxxtsb/yb_dyxxnd；
- 周期上下文由 dyxxtsb/dyxxnd 交易后快照推导（confirmed）；无行 → unknown；
- 资格字段（cjjrdj 军残 / gwydybz 公疗 / cblb=61 社会化退休）按 Issue #79 候选口径映射，
  内核据此独立计算军残/公疗补助（住院套表流程字段未映射，保持 observed_only）；
- segment_coordinate_guard=True：分段坐标未确认时不按下界硬算（统筹/大额 not_verifiable）；
- fyfs != '0'（非项目付费）→ 明确返回不支持，不套用项目付费公式。
"""
from __future__ import annotations

from typing import Any

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_decomposition_queries import hash_rows
from src.adapters.data_supply.outpatient_special_mz_queries import (
    FEE_FOR_SERVICE_FYFS,
    build_special_mz_snapshot,
    derive_mz_cycle_context,
    load_special_mz_annual,
    load_special_mz_cycle,
    load_special_mz_fee_items,
    load_special_mz_settlement,
    locate_special_mz_registration,
)
from src.adapters.data_supply.outpatient_special_queries import (
    _to_date,
    load_special_institution_level,
)
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    RETIRED_PERSON_TYPE_CODES,
)
from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import (
    decompose_employee_outpatient_special,
)
from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult
from src.runtime.policy_qa.fee_decomposition.snapshot_service_special import (
    _meta_citation,
    _unavailable_result,
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
    profile: tuple[str, str] | None = None,
) -> SettlementDecompositionResult:
    """登记号 → mz 套表完整事实快照 → 职工门特·按项目付费费用分解。

    - profile=None：险种/医疗类别置 unknown（ESP-CODE-001/002 实测待码表确认，不猜测）；
    - 周期上下文：dyxxtsb/dyxxnd 推导 confirmed；无行 unknown（allow_observed_deductible
      为评估口径开关，此时可取账面起付作条件输入，勾稽级）；
    - segment_coordinate_guard 恒 True：分段坐标未确认时统筹/大额 not_verifiable。
    """
    # 1. 定位门特登记（yllb='12' 职工）
    located = locate_special_mz_registration(conn, djh)
    if located.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", located.message or "门特登记定位查询失败")
    if located.data["match_status"] != "unique_match":
        code = ("REGISTRATION_NOT_FOUND" if located.data["match_status"] == "not_found"
                else "REGISTRATION_AMBIGUOUS")
        return _unavailable_result(djh, code, located.message or "门特登记定位不唯一")
    registration_row = located.data["registration_row"]

    # 2. 结算行（每 djh 恰好 1 行；fyfs 须为项目付费）
    settlement_res = load_special_mz_settlement(conn, djh)
    if settlement_res.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", settlement_res.message or "结算读取失败")
    if settlement_res.data["settlement_row"] is None:
        return _unavailable_result(djh, "SETTLEMENT_ROW_ANOMALY",
                                   settlement_res.data.get("note") or "结算行数据异常")
    settlement_row = settlement_res.data["settlement_row"]
    fyfs = settlement_row.get("fyfs")
    fyfs_s = None if fyfs is None else str(fyfs).strip()
    if fyfs_s != FEE_FOR_SERVICE_FYFS:
        return _unavailable_result(
            djh, "UNSUPPORTED_FEE_METHOD",
            f"费用方式 fyfs={fyfs_s} 非项目付费（'0'），本流程不支持，不套用项目付费公式")

    # 3. 明细完整读取
    items_res = load_special_mz_fee_items(conn, djh)
    if items_res.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", items_res.message or "费用明细读取失败")
    item_rows = items_res.data["item_rows"]

    # 4. 机构等级
    inst_res = load_special_institution_level(conn, hospital_code)
    if inst_res.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", inst_res.message or "机构等级读取失败")
    notes: list[str] = []
    if inst_res.data.get("note"):
        notes.append(inst_res.data["note"])

    # 5. 周期/年度待遇（交易后快照 → 交易前口径推导）
    cycle_res = load_special_mz_cycle(conn, djh)
    if cycle_res.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", cycle_res.message or "结算周期读取失败")
    annual_res = load_special_mz_annual(conn, djh)
    if annual_res.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", annual_res.message or "年度待遇读取失败")
    if cycle_res.data.get("note"):
        notes.append(cycle_res.data["note"])
    if annual_res.data.get("note"):
        notes.append(annual_res.data["note"])

    settle_date = _to_date(settlement_row.get("jyrq"))
    cycle_context, cycle_notes = derive_mz_cycle_context(
        cycle_res.data["cycle_row"], annual_res.data["annual_row"], settlement_row,
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
        )
    except ValueError as exc:
        return _unavailable_result(djh, "SNAPSHOT_ASSEMBLY_FAILED", str(exc))
    notes.extend(asm_notes)

    # 8. 读取元数据（来源/行数/内容哈希）
    from datetime import datetime, timezone
    read_at = datetime.now(timezone.utc).isoformat()
    content_hash = hash_rows([registration_row], [settlement_row], item_rows)

    # 9. 确定性分解 + 读元数据写入 citations（kind="source_catalog"）
    result = decompose_employee_outpatient_special(snapshot)
    return result.model_copy(update={
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
    })
