"""门诊费用分解快照服务（Issue #78 设计 §15 步骤 1 胶水层）。

交易号 → 适配器读取完整事实快照 → 确定性分解内核 → SettlementDecompositionResult。

边界：
- 险种/医疗类别映射未确认（设计 §6.1 P0：不能用 T_CureType=11 推断职工）：
  默认 profile_resolver=None 时 insurance_type/medical_category 置 "unknown"，
  内核自然走 UNSUPPORTED_PROFILE/unavailable；只有调用方显式提供经确认的
  resolver 才产出 employee/outpatient；
- rounding_mode 无默认（EOP-RND-001 待确认），必须显式传入；
- 适配器任一环节 FAILED/歧义 → 返回带 uncertainties 的 unavailable 结果，不抛异常栈；
- 读元数据（来源/行数/内容哈希/映射指纹）写入结果 citations（kind="source_catalog"）；
- 出生日期等身份原文不进入结果（结果 citations 仅含规则来源与读取元数据）。
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_decomposition_queries import (
    SnapshotReadMeta,
    assemble_read_meta,
    build_snapshot,
    derive_in_hospital_accumulation,
    extract_item_codes,
    hash_rows,
    load_drug_catalog,
    load_institution_level,
    load_material_catalog,
    load_outpatient_fee_items,
    load_service_catalog,
    locate_outpatient_trade,
)
from src.adapters.data_supply.record_query_mappings import (
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
)
from src.adapters.data_supply.settlement_record_queries import _k
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    decompose_employee_outpatient,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CitationModel,
    CoverageSummary,
    DecompositionProfile,
    SettlementDecompositionResult,
    UncertaintyModel,
)

#: 险种/医疗类别解析器：交易行 → (insurance_type, medical_category)；None 表示未确认。
#: 只有经确认码表映射的 resolver 才允许返回非 unknown 组合（设计 §6.1 P0）。
ProfileResolver = Callable[[Mapping[str, Any]], tuple[str, str] | None]


def _meta_citation(meta: SnapshotReadMeta) -> CitationModel:
    """读元数据证据：来源、内容哈希、映射指纹、各表行数（设计 §5.3-7/§9）。"""
    return CitationModel(
        id="source.snapshot_read_meta",
        kind="source_catalog",
        ref=f"{meta.source_system}#mapping:{meta.mapping_fingerprint[:12]}",
        value=meta.content_hash,
        values=[f"{table}={count}" for table, count in sorted(meta.row_counts.items())],
        approval_status=None,
    )


def _unavailable_result(
    trade_no: str,
    code: str,
    message: str,
    citations: list[CitationModel] | None = None,
) -> SettlementDecompositionResult:
    """读取/组装失败的降级结果：带 uncertainties 的 unavailable，不抛异常栈。"""
    return SettlementDecompositionResult(
        settlement_ref=f"settlement:{trade_no}",
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


def decompose_outpatient_trade(
    conn: Any,
    trade_no: str,
    hospital_code: str,
    rounding_mode: RoundingMode,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
    profile_resolver: ProfileResolver | None = None,
    # 年度累计口径确认（实证依据见决策记录 D3/D4/D5）：仅评估/签核链路显式开启；
    # 默认 False 保持 fail-closed（PRIOR_ACCUMULATION_CALIBER_UNCONFIRMED）
    accumulation_caliber_confirmed: bool = False,
    # 从院内码表列派生待遇资格（决策记录 D6/D7/D8）：签核前仅评估链路开启
    derive_eligibility_from_codes: bool = False,
) -> SettlementDecompositionResult:
    """交易号 → 完整事实快照 → 职工门诊费用分解。

    默认 profile_resolver=None：险种/医疗类别未确认，置 unknown，
    内核返回 UNSUPPORTED_PROFILE/unavailable（不猜测职工身份）。
    """
    # 1. 定位交易：0 条未找到 / >1 条歧义均降级，不取首条
    located = locate_outpatient_trade(conn, trade_no, hospital_code, mapping)
    if located.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(
            trade_no, "READ_FAILED", located.message or "交易定位查询失败")
    if located.data["match_status"] != "unique_match":
        code = "TRADE_NOT_FOUND" if located.data["match_status"] == "not_found" else "TRADE_AMBIGUOUS"
        return _unavailable_result(trade_no, code, located.message or "交易定位不唯一")
    trade_row = located.data["trade_row"]

    # 2. 明细完整读取
    items_res = load_outpatient_fee_items(conn, trade_no, mapping)
    if items_res.status != AdapterCallStatus.SUCCESS:
        return _unavailable_result(
            trade_no, "READ_FAILED", items_res.message or "费用明细读取失败")
    item_rows = items_res.data["item_rows"]

    # 3. 目录批量读取（药品/非药品分流；全版本，不在 WHERE 排除日期）
    drug_codes, non_drug_codes = extract_item_codes(item_rows, mapping)
    drug_res = load_drug_catalog(conn, drug_codes, mapping)
    svc_res = load_service_catalog(conn, non_drug_codes, mapping)
    mat_res = load_material_catalog(conn, non_drug_codes, mapping)
    inst_res = load_institution_level(conn, hospital_code, mapping)
    for res in (drug_res, svc_res, mat_res, inst_res):
        if res.status != AdapterCallStatus.SUCCESS:
            return _unavailable_result(
                trade_no, "READ_FAILED", res.message or "目录/机构读取失败")

    notes: list[str] = []
    if inst_res.data.get("note"):
        notes.append(inst_res.data["note"])

    # 4.5 年度累计口径（仅在调用方显式确认时）：
    # TB_Year=交易年 → 账面 TB_FeeIn/TB_BigPay 即交易前累计（实证，决策记录 D3/D4）；
    # TB_Year≠交易年（实测全为 TB_Year=2000 未维护）→ 按同人同年本院历史推导下界
    # （决策记录 D16，候选口径，结果附 ACCUMULATION_DERIVED_IN_HOSPITAL 不确定性）
    derived_uncertainties: list[UncertaintyModel] = []
    prior_in_scope_override = None
    prior_fund_override = None
    use_book_accumulation = accumulation_caliber_confirmed
    if accumulation_caliber_confirmed:
        raw_dt = trade_row.get(_k(mapping, "op_trade_date"))
        raw_year = trade_row.get(_k(mapping, "op_year"))
        trade_year = getattr(raw_dt, "year", None)
        if trade_year is not None and str(raw_year or "").strip() != str(trade_year):
            card_ic = trade_row.get(_k(mapping, "op_card_ic"))
            fund_type = trade_row.get(_k(mapping, "op_fund_type"))
            drv = derive_in_hospital_accumulation(
                conn, str(card_ic), str(fund_type), raw_dt, trade_no, mapping)
            if drv.status != AdapterCallStatus.SUCCESS:
                return _unavailable_result(
                    trade_no, "READ_FAILED", drv.message or "年度累计推导读取失败")
            prior_in_scope_override = drv.data["prior_in_scope_fee"]
            prior_fund_override = drv.data["prior_fund_payment"]
            use_book_accumulation = False
            derived_uncertainties.append(UncertaintyModel(
                id="u.accum.derived", code="ACCUMULATION_DERIVED_IN_HOSPITAL",
                message=(
                    f"账面年度累计未维护（TB_Year={raw_year}），交易前累计按同人同年本院历史推导"
                    f"（锚点 {drv.data['anchor_count']} 个、历史 {drv.data['prior_trade_count']} 笔）；"
                    "跨院部分不可得，属候选口径（决策记录 D16，待签核）。"),
                affected_fields=["T_FirstPay", "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_OfficalPay"],
            ))
            notes.append(
                f"ACCUMULATION_DERIVED：TB_Year={raw_year} 未维护，累计按同人同年推导"
                f"（锚点 {drv.data['anchor_count']}，历史 {drv.data['prior_trade_count']} 笔）")

    # 4. 险种/医疗类别：仅由经确认的 resolver 产出；默认 unknown 不猜测（设计 §6.1）
    insurance_type, medical_category = "unknown", "unknown"
    if profile_resolver is not None:
        try:
            resolved = profile_resolver(trade_row)
        except Exception:  # noqa: BLE001 — resolver 异常按未知处理，不猜测
            resolved = None
            notes.append("PROFILE_RESOLVER_FAILED：险种/医疗类别解析器异常，按 unknown 处理")
        if resolved is not None:
            insurance_type, medical_category = resolved

    # 5. 组装快照（脏数据抛 ValueError → 降级 unavailable）
    try:
        snapshot, asm_notes = build_snapshot(
            trade_row=trade_row,
            item_rows=item_rows,
            drug_catalog_rows=drug_res.data["catalog_rows"],
            service_catalog_rows=svc_res.data["catalog_rows"],
            material_catalog_rows=mat_res.data["catalog_rows"],
            institution_h_level=inst_res.data["h_level"],
            institution_h_type=inst_res.data.get("h_type"),
            mapping=mapping,
            rounding_mode=rounding_mode,
            insurance_type=insurance_type,
            medical_category=medical_category,
            prior_in_scope_fee_is_pre_trade=accumulation_caliber_confirmed,
            prior_fund_payment=prior_fund_override,
            prior_fund_payment_is_pre_trade=accumulation_caliber_confirmed,
            use_book_prior_big_pay=use_book_accumulation,
            prior_in_scope_fee_override=prior_in_scope_override,
            in_scope_basis_aligned=accumulation_caliber_confirmed,
            derive_eligibility_from_codes=derive_eligibility_from_codes,
        )
    except ValueError as exc:
        return _unavailable_result(trade_no, "SNAPSHOT_ASSEMBLY_FAILED", str(exc))
    notes.extend(asm_notes)

    # 6. 读取元数据（来源/行数/内容哈希/映射指纹）
    meta = assemble_read_meta(
        row_counts={
            "trade": located.data["row_count"],
            "fee_items": items_res.data["row_count"],
            "drug_catalog": drug_res.data["row_count"],
            "service_catalog": svc_res.data["row_count"],
            "material_catalog": mat_res.data["row_count"],
            "institution": inst_res.data["row_count"],
        },
        content_hash=hash_rows(
            [trade_row], item_rows,
            drug_res.data["catalog_rows"], svc_res.data["catalog_rows"],
            mat_res.data["catalog_rows"],
        ),
        mapping=mapping,
        notes=tuple(notes),
    )

    # 7. 确定性分解 + 读元数据写入 citations（kind="source_catalog"）
    result = decompose_employee_outpatient(snapshot)
    return result.model_copy(update={
        "citations": [*result.citations, _meta_citation(meta)],
        "uncertainties": [*result.uncertainties, *derived_uncertainties],
    })
