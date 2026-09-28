"""门特（门诊特殊病）费用分解快照服务（Issue #78 第二流程，胶水层）。

登记号 djh → 适配器读取完整事实快照 → 确定性分解内核 → SettlementDecompositionResult。

边界：
- 险种/医疗类别由调用方显式确认（profile 参数）：ESP-CODE-001/002 为实测待码表确认，
  默认 profile=None 时置 unknown，内核自然走 UNSUPPORTED_PROFILE/unavailable；
- rounding_mode 无默认（ESP-RND-001 待确认），必须显式传入；
- 周期上下文默认 evidence_status="unknown"：院端数据抽取不含跨院累计，无法证明完整，
  不强行推断；预留 cycle_context_override 供评估注入（如 confirmed/assumed 口径）；
- allow_observed_deductible（评估口径开关，默认 False）透传入快照；
- 适配器任一环节 FAILED/歧义 → 返回带 uncertainties 的 unavailable 结果，不抛异常栈；
- 读元数据（来源/行数/内容哈希）写入结果 citations（kind="source_catalog"）；
- 出生日期等身份原文不进入结果（结果 citations 仅含规则来源与读取元数据）。
"""
from __future__ import annotations

from typing import Any

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_decomposition_queries import hash_rows
from src.adapters.data_supply.outpatient_special_queries import (
    build_special_snapshot,
    load_same_person_settlements,
    load_special_fee_items,
    load_special_institution_level,
    load_special_settlement,
    locate_special_registration,
)
from src.domain.insurance.fee_decomposition import (
    RoundingMode,
    SpecialCycleContext,
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


def decompose_outpatient_special_settlement(
    conn: Any,
    djh: str,
    hospital_code: str,
    rounding_mode: RoundingMode,
    *,
    allow_observed_deductible: bool = False,
    cycle_context_override: SpecialCycleContext | None = None,
    profile: tuple[str, str] | None = None,
) -> SettlementDecompositionResult:
    """登记号 → 完整事实快照 → 职工门特费用分解。

    - profile=None：险种/医疗类别置 unknown（ESP-CODE-001/002 实测待码表确认，不猜测）；
    - cycle_context_override=None：周期上下文 evidence_status="unknown"
      （院端抽取不含跨院累计，证据不足标 unknown，不强行推断）。
    """
    # 1. 定位门特登记：0 条未找到 / >1 条歧义均降级，不取首条
    located = locate_special_registration(conn, djh)
    if located.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", located.message or "门特登记定位查询失败")
    if located.data["match_status"] != "unique_match":
        code = ("REGISTRATION_NOT_FOUND" if located.data["match_status"] == "not_found"
                else "REGISTRATION_AMBIGUOUS")
        return _unavailable_result(djh, code, located.message or "门特登记定位不唯一")
    registration_row = located.data["registration_row"]

    # 2. 结算行（每 djh 恰好 1 行；否则数据异常降级）
    settlement_res = load_special_settlement(conn, djh)
    if settlement_res.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(djh, "READ_FAILED", settlement_res.message or "结算读取失败")
    if settlement_res.data["settlement_row"] is None:
        return _unavailable_result(djh, "SETTLEMENT_ROW_ANOMALY",
                                   settlement_res.data.get("note") or "结算行数据异常")
    settlement_row = settlement_res.data["settlement_row"]

    # 3. 明细完整读取
    items_res = load_special_fee_items(conn, djh)
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

    # 5. 同人历史结算（供周期上下文重建参考；证据不完整，仅留痕行数，不强行推断）
    history_res = load_same_person_settlements(conn, djh)
    history_count = 0
    if history_res.status == AdapterCallStatus.SUCCESS:
        history_count = history_res.data["row_count"]
        notes.append(
            f"CYCLE_HISTORY_REFERENCE_ONLY：同人历史住院类结算 {history_count} 行；"
            "院端抽取不含跨院数据，周期上下文证据不完整，默认 unknown")
    else:
        notes.append(f"CYCLE_HISTORY_READ_FAILED：{history_res.message}")

    # 6. 周期上下文：默认 unknown；override 供评估注入（confirmed/assumed）
    cycle_context = cycle_context_override or SpecialCycleContext(
        evidence_status="unknown",
        evidence_note="院端数据抽取无法完整重建结算周期/年度累计（不含跨院数据），证据不足",
    )

    # 7. 险种/医疗类别：仅由调用方显式确认
    insurance_type, medical_category = profile if profile is not None else ("unknown", "unknown")

    # 8. 组装快照（脏数据抛 ValueError → 降级 unavailable）
    try:
        snapshot, asm_notes = build_special_snapshot(
            registration_row=registration_row,
            settlement_row=settlement_row,
            item_rows=item_rows,
            institution_h_level=inst_res.data["h_level"],
            hospital_code=hospital_code,
            rounding_mode=rounding_mode,
            cycle_context=cycle_context,
            insurance_type=insurance_type,
            medical_category=medical_category,
            allow_observed_deductible=allow_observed_deductible,
        )
    except ValueError as exc:
        return _unavailable_result(djh, "SNAPSHOT_ASSEMBLY_FAILED", str(exc))
    notes.extend(asm_notes)

    # 9. 读取元数据（来源/行数/内容哈希；门特用实测物理表，不经 RecordQueryMapping）
    from datetime import datetime, timezone
    read_at = datetime.now(timezone.utc).isoformat()
    content_hash = hash_rows([registration_row], [settlement_row], item_rows)

    # 10. 确定性分解 + 读元数据写入 citations（kind="source_catalog"）
    result = decompose_employee_outpatient_special(snapshot)
    return result.model_copy(update={
        "citations": [*result.citations,
                      _meta_citation(read_at, "hospital_record_store",
                                     {
                                         "registration": located.data["row_count"],
                                         "settlement": settlement_res.data["row_count"],
                                         "fee_items": items_res.data["row_count"],
                                         "institution": inst_res.data["row_count"],
                                         "person_history": history_count,
                                     },
                                     content_hash, tuple(notes))],
    })
