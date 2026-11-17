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
from dataclasses import replace
from decimal import Decimal

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
from src.domain.insurance.fee_decomposition import RoundingMode, OriginalPolicyContext
from src.runtime.policy_qa.fee_decomposition.employee_outpatient import (
    decompose_employee_outpatient,
)
from src.runtime.policy_qa.fee_decomposition.resident_outpatient import (
    decompose_resident_outpatient,
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
    build_outpatient_facts,
)

#: 险种/医疗类别解析器：交易行 → (insurance_type, medical_category)；None 表示未确认。
#: 只有经确认码表映射的 resolver 才允许返回非 unknown 组合（设计 §6.1 P0）。
ProfileResolver = Callable[[Mapping[str, Any]], tuple[str, str] | None]

#: 标准组合 → 内核函数（Issue #80 居民门诊注册；未注册组合 fail-closed 不可用，
#: 不猜测套用任一内核公式——设计 §1「险种＋医疗类别决定整体流程」）
_KERNEL_BY_PROFILE = {
    ("employee", "outpatient"): decompose_employee_outpatient,
    ("resident", "outpatient"): decompose_resident_outpatient,
}


#: 增量恒等式容差（与探针 scripts/eval/probe_accumulation_identity.py 一致：money 4 位小数）
_IDENTITY_TOLERANCE = Decimal("0.005")


def _identity_holds(prior: Decimal | None, after: Decimal | None, current: Decimal | None) -> bool:
    """TA−TB==T 增量恒等式：任一缺失即不成立（未知不是零）；负交易前累计非合法累计形态。"""
    if prior is None or after is None or current is None:
        return False
    if prior < 0:
        return False
    return abs((after - prior) - current) < _IDENTITY_TOLERANCE


def check_accumulation_self_proof(
    trade_row: Mapping[str, Any],
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> dict[str, Decimal] | None:
    """逐交易自证（阶段 E，独立于 accumulation_caliber_confirmed 评估开关）。

    TB_Year==交易年 且 TA_FeeIn−TB_FeeIn==T_FeeIn、TA_BigPay−TB_BigPay==T_BigPay
    两条增量恒等式同时成立 → 账面 TB_FeeIn/TB_BigPay 为"院内已自证的交易前累计"，
    返回恒等式两侧数值证据（供公开投影引用）；任一不满足（TB_Year=2000/0 哨兵、
    恒等式不成立、负累计）→ None，调用方维持 fail-closed（下界/未知语义不变）。

    自证只证明院内 HIS 表内一致（探针：TB_Year==交易年子集非 17/18 通道 181/181 成立，
    17/18 通道按险种而异，不能全局假设成立，故必须逐交易自证）：
    - 跨院累计物理上不在本院库，口径未独立核实，由调用方挂 uncertainty（待签核）；
    - 居民 L1 分档列（TB_FeeInL1/TB_BigPayL1）在本院（H_LEVEL=02 二级）近乎全 0、
      语义未证实，本阶段不读取（探针 Q3 结论，待签核）。
    """
    from src.adapters.data_supply.outpatient_decomposition_queries import _to_date, _to_decimal
    raw_dt = trade_row.get(_k(mapping, "op_trade_date"))
    raw_year = trade_row.get(_k(mapping, "op_year"))
    trade_date = _to_date(raw_dt)
    if trade_date is None:
        return None
    if str(raw_year or "").strip() != str(trade_date.year):
        return None  # 含 TB_Year=2000/0 哨兵与未维护行
    tb_fee = _to_decimal(trade_row.get(_k(mapping, "op_prior_fee_in")))
    ta_fee = _to_decimal(trade_row.get(_k(mapping, "op_after_fee_in")))
    t_fee = _to_decimal(trade_row.get(_k(mapping, "op_fee_in")))
    tb_big = _to_decimal(trade_row.get(_k(mapping, "op_prior_big_pay")))
    ta_big = _to_decimal(trade_row.get(_k(mapping, "op_after_big_pay")))
    t_big = _to_decimal(trade_row.get(_k(mapping, "op_big_pay")))
    if not (_identity_holds(tb_fee, ta_fee, t_fee) and _identity_holds(tb_big, ta_big, t_big)):
        return None
    return {"tb_fee": tb_fee, "ta_fee": ta_fee, "t_fee": t_fee,
            "tb_big": tb_big, "ta_big": ta_big, "t_big": t_big}


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
) -> DecompositionOutcome:
    """交易号 → 完整事实快照 → 职工门诊费用分解（结果 + 结算事实侧车）。

    默认 profile_resolver=None：险种/医疗类别未确认，置 unknown，
    内核返回 UNSUPPORTED_PROFILE/unavailable（不猜测职工身份）。
    事实区独立于算法（方案 §53）：交易行已取到后，后续任何 unavailable
    早退同样携带 facts；交易行未取到 → facts=None（不冒充已取到全单字段）。
    """
    # 1. 定位交易：0 条未找到 / >1 条歧义均降级，不取首条
    located = locate_outpatient_trade(conn, trade_no, hospital_code, mapping)
    if located.status != AdapterCallStatus.SUCCESS:
        return DecompositionOutcome(_unavailable_result(
            trade_no, "READ_FAILED", located.message or "交易定位查询失败"))
    if located.data["match_status"] != "unique_match":
        code = "TRADE_NOT_FOUND" if located.data["match_status"] == "not_found" else "TRADE_AMBIGUOUS"
        return DecompositionOutcome(_unavailable_result(
            trade_no, code, located.message or "交易定位不唯一"))
    trade_row = located.data["trade_row"]
    facts = build_outpatient_facts(trade_row, mapping)
    from src.adapters.data_supply.settlement_dictionary_queries import load_settlement_dictionaries
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import label_facts
    from src.runtime.policy_qa.fee_decomposition.fee_items import attach_item_rows
    domains = load_settlement_dictionaries(conn).data.get("domains", {})
    item_rows = []

    def _outcome(result: SettlementDecompositionResult) -> DecompositionOutcome:
        from src.runtime.policy_qa.fee_decomposition.payment_condition_context import attach_payment_condition_context
        labeled = label_facts(facts, domains)
        result = attach_item_rows(result, item_rows, special=False, mapping=mapping)
        result = attach_payment_condition_context(result, conn, trade_no, special=False,
            mapping=mapping, hospital_level=labeled.hospital_level,
            hospital_level_name=labeled.metadata_names.get("hospital_level"))
        return DecompositionOutcome(result, labeled)

    # 2. 明细完整读取
    items_res = load_outpatient_fee_items(conn, trade_no, mapping)
    if items_res.status != AdapterCallStatus.SUCCESS:
        return _outcome(_unavailable_result(
            trade_no, "READ_FAILED", items_res.message or "费用明细读取失败"))
    item_rows = items_res.data["item_rows"]

    # 3. 目录批量读取（药品/非药品分流；全版本，不在 WHERE 排除日期）
    drug_codes, non_drug_codes = extract_item_codes(item_rows, mapping)
    drug_res = load_drug_catalog(conn, drug_codes, mapping)
    svc_res = load_service_catalog(conn, non_drug_codes, mapping)
    mat_res = load_material_catalog(conn, non_drug_codes, mapping)
    inst_res = load_institution_level(conn, hospital_code, mapping)
    for res in (drug_res, svc_res, mat_res, inst_res):
        if res.status != AdapterCallStatus.SUCCESS:
            return _outcome(_unavailable_result(
                trade_no, "READ_FAILED", res.message or "目录/机构读取失败"))

    level = inst_res.data.get("h_level")
    facts.hospital_level = str(level) if level is not None else None
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
    from src.adapters.data_supply.outpatient_decomposition_queries import _to_date, _to_decimal, _to_str
    refund_read = (any((_to_decimal(row.get(_k(mapping, "opf_fee"))) or 0) < 0 for row in item_rows)
                   or bool(_to_str(trade_row.get(_k(mapping, "op_ref_original_no")))
                           or _to_str(trade_row.get(_k(mapping, "op_reversal_original_no")))))
    # 4.6 逐交易自证门控（阶段 E，独立于 accumulation_caliber_confirmed）：
    # TB_Year==交易年 且两条增量恒等式成立 → 账面累计按"院内已自证的交易前累计"参战，
    # 主链（评估口径关闭）同样生效；自证不成立的退费/哨兵行维持 fail-closed。
    self_proof = None if refund_read else check_accumulation_self_proof(trade_row, mapping)
    use_book_accumulation = accumulation_caliber_confirmed or self_proof is not None
    if self_proof is not None:
        derived_uncertainties.append(UncertaintyModel(
            id="u.accum.cross_hospital", code="ACCUMULATION_CROSS_HOSPITAL_UNVERIFIED",
            message=(
                "交易前年度累计经本笔恒等式自证（交易后累计−交易前累计＝本笔金额，院内记录一致）；"
                "跨院就医的累计部分不在本院库，未能独立核实，待业务签核。"),
            affected_fields=["T_FirstPay", "T_BigPay", "T_BigSelfPay", "T_BCPay", "T_OfficalPay"]))
        notes.append(
            "ACCUMULATION_SELF_PROVEN：TB_Year==交易年且 TA−TB==T 恒等式成立（容差 0.005），"
            "账面累计按院内自证口径参战；跨院口径待签核")
    if accumulation_caliber_confirmed and not refund_read:
        raw_dt = trade_row.get(_k(mapping, "op_trade_date"))
        raw_year = trade_row.get(_k(mapping, "op_year"))
        trade_year = getattr(raw_dt, "year", None)
        if trade_year is not None and str(raw_year or "").strip() != str(trade_year):
            card_ic = trade_row.get(_k(mapping, "op_card_ic"))
            fund_type = trade_row.get(_k(mapping, "op_fund_type"))
            drv = derive_in_hospital_accumulation(
                conn, str(card_ic), str(fund_type), raw_dt, trade_no, mapping)
            if drv.status != AdapterCallStatus.SUCCESS:
                return _outcome(_unavailable_result(
                    trade_no, "READ_FAILED", drv.message or "年度累计推导读取失败"))
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
    # 推导累计只是下界：跨院未知，不能当作“已确认交易前累计”参与硬算。
    # 逐交易自证（self_proof）与评估开关并列：任一路径成立即按交易前口径参战；
    # in_scope_basis_aligned（起付与公疗门槛累计口径一致，§7.5.4）恒等式不能证明，
    # 仍仅由评估开关开启。
    derived_lower_bound = prior_fund_override is not None and not use_book_accumulation
    accumulation_pre_trade = (accumulation_caliber_confirmed or self_proof is not None) and not derived_lower_bound
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
            prior_in_scope_fee_is_pre_trade=accumulation_pre_trade,
            prior_fund_payment=prior_fund_override,
            prior_fund_payment_is_pre_trade=accumulation_pre_trade,
            use_book_prior_big_pay=use_book_accumulation,
            prior_in_scope_fee_override=prior_in_scope_override,
            in_scope_basis_aligned=accumulation_caliber_confirmed,
            derive_eligibility_from_codes=derive_eligibility_from_codes,
        )
    except ValueError as exc:
        return _outcome(_unavailable_result(trade_no, "SNAPSHOT_ASSEMBLY_FAILED", str(exc)))
    notes.extend(asm_notes)
    if derived_lower_bound and accumulation_caliber_confirmed:
        # 同人同年本院历史推导＝下界（跨院缺失），保留属性供解释门控使用。
        from dataclasses import replace as _replace
        snapshot = _replace(snapshot, accumulation=_replace(snapshot.accumulation, prior_is_lower_bound=True))
    if self_proof is not None:
        # 逐交易自证成立：保留属性供解释投影升级措辞（院内自证≠跨院口径已核实）。
        snapshot = replace(snapshot, accumulation=replace(snapshot.accumulation, self_proven=True))

    # 居民退费原单取证：身份、原政策时点与累计年度，禁止用本年历史代替被退年度。
    original_rows = []
    if refund_read and insurance_type == "resident" and snapshot.trade.original_trade_no:
        original_res = locate_outpatient_trade(conn, snapshot.trade.original_trade_no, hospital_code, mapping)
        if original_res.status != AdapterCallStatus.SUCCESS:
            return _outcome(_unavailable_result(
                trade_no, "READ_FAILED", original_res.message or "退费原交易读取失败"))
        if original_res.data["match_status"] == "unique_match":
            original_row = original_res.data["trade_row"]
            original_rows = [original_row]
            original_date = _to_date(original_row.get(_k(mapping, "op_trade_date")))
            current_card = _to_str(trade_row.get(_k(mapping, "op_card_ic")))
            original_card = _to_str(original_row.get(_k(mapping, "op_card_ic")))
            original_fund = _to_str(original_row.get(_k(mapping, "op_fund_type")))
            current_fund = _to_str(trade_row.get(_k(mapping, "op_fund_type")))
            try:
                accumulation_year = int(str(trade_row.get(_k(mapping, "op_year"))))
            except (TypeError, ValueError):
                accumulation_year = None
            # 同日同机构共用一次机构快照；跨日缺历史等级档案时保持未知，不默猜机构未变。
            if (original_date is not None and original_date == snapshot.trade.trade_date
                and current_card and current_card == original_card
                and current_fund in ("91", "92", "93") and original_fund == current_fund
                and _to_str(original_row.get(_k(mapping, "op_trade_no"))) == snapshot.trade.original_trade_no):
                original_snapshot, original_notes = build_snapshot(
                    trade_row=original_row, item_rows=(), drug_catalog_rows=(), service_catalog_rows=(),
                    material_catalog_rows=(), institution_h_level=inst_res.data["h_level"],
                    institution_h_type=inst_res.data.get("h_type"), mapping=mapping,
                    rounding_mode=rounding_mode, insurance_type=insurance_type, medical_category=medical_category,
                    derive_eligibility_from_codes=derive_eligibility_from_codes)
                snapshot = replace(snapshot, original_policy_context=OriginalPolicyContext(
                    original_date, original_snapshot.person, original_snapshot.institution,
                    insurance_type, medical_category, accumulation_year,
                    original_snapshot.trade.cure_type, original_snapshot.trade.no_right_reason))
                notes.extend(original_notes)
            else:
                notes.append("ORIGINAL_POLICY_CONTEXT_UNCONFIRMED：原交易关联身份或历史机构口径无法确认")
        else:
            notes.append("ORIGINAL_POLICY_CONTEXT_UNCONFIRMED：原交易缺失/歧义，不查询退费本年度历史兜底")

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
            [trade_row], original_rows, item_rows,
            drug_res.data["catalog_rows"], svc_res.data["catalog_rows"],
            mat_res.data["catalog_rows"],
            # 机构等级/类型直接决定起付档与比例档：必须纳入摘要，否则“机构变→金额变”仍同哈希。
            [inst_res.data or {}],
        ),
        mapping=mapping,
        notes=tuple(notes),
    )

    # 7. 确定性分解（按险种×医疗类别分发到已注册内核）+ 读元数据写入 citations
    kernel = _KERNEL_BY_PROFILE.get((snapshot.insurance_type, snapshot.medical_category))
    if kernel is None:
        return _outcome(_unavailable_result(
            trade_no, "UNSUPPORTED_PROFILE",
            f"险种×医疗类别组合 {snapshot.insurance_type}+{snapshot.medical_category} 未注册内核，"
            "不猜测套用其他组合公式",
            citations=[_meta_citation(meta)]))
    from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
    result = attach_evidence(kernel(snapshot), snapshot)
    extra_citations = [_meta_citation(meta)]
    if self_proof is not None:
        # 自证证据（恒等式两侧数值）供公开投影引用；中文口径名，不带物理列名
        extra_citations.append(CitationModel(
            id="source.accumulation_self_check", kind="settlement_fact",
            ref=f"snapshot:settlement:{trade_no}/accumulation_identity",
            values=[
                f"交易后医保内累计−交易前医保内累计＝本笔医保内费用："
                f"{self_proof['ta_fee']}−{self_proof['tb_fee']}={self_proof['t_fee']}",
                f"交易后大额累计−交易前大额累计＝本笔大额支付："
                f"{self_proof['ta_big']}−{self_proof['tb_big']}={self_proof['t_big']}",
            ]))
    return _outcome(result.model_copy(update={
        "citations": [*result.citations, *extra_citations],
        "uncertainties": [*result.uncertainties, *derived_uncertainties],
    }))
