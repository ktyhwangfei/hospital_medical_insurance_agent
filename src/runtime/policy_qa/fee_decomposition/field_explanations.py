"""字段四要素固定说明（阶段 B）：按 (链路, 字段) 确定性合成，不调用模型。

四要素：
- meaning（金额含义）：这笔钱代表什么，属于费用/基金支付/个人负担/支付方式口径；
- composition（金额构成）：由哪些金额相加、相减或按比例得出；无计算记录时写明
  "仅账面列示"等诚实口径；
- basis_text（本单依据）：本单采用的比例/限价/待遇档与来源标题；无关联来源不编造，
  缺项归到 boundary；
- boundary（解释边界）：零金额三态、结论分级、解释理由与缺口消息；四要素的缺项
  必须在此显式声明（缺什么写什么，不写泛泛"待核实"）。

同输入同输出：全部素材来自模板字段字典、公开字段投影与已渲染的依据链。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict


class FieldExplanationView(BaseModel):
    """字段固定说明四要素（公开契约；各部分可 None，缺项由 boundary 显式声明）。"""

    model_config = ConfigDict(extra="forbid")

    meaning: str | None = None
    composition: str | None = None
    basis_text: str | None = None
    boundary: str | None = None


# ── 链路识别 ─────────────────────────────────────────────────────────

_FAMILY_BY_ALGORITHM = {
    "employee_outpatient_v1": "employee_outpatient",
    "resident_outpatient_v1": "resident_outpatient",
    "employee_outpatient_special_v1": "employee_special",
    "resident_outpatient_special_v1": "resident_special",
    # 定额（肾）模板是职工门特家族的扩展形态，含义字典同族复用
    "employee_special_fixed_kidney_v1": "employee_special",
}


def chain_family(algorithm_version: str) -> str | None:
    return _FAMILY_BY_ALGORITHM.get(algorithm_version)


# ── 金额含义字典（按模板 key；门诊两链同构、门特两链同构，差异项按 family 覆盖）──

_BASE_MEANING: dict[str, str] = {
    "fee_all": "本笔结算的全部费用合计，属费用口径，不等于医保报销金额。",
    "personal_total": "本笔结算后由个人支付的总金额，属个人负担口径。",
    "fee_in": "费用中属于医保目录范围内、参与待遇计算的金额，属费用口径。",
    "fee_out": "本单基本医保费用划分中的范围外金额，可能包含比例先行自付、超限价自付和全自费；最终个人负担还需结合本单后续保障。",
    "self_pay_1": "医保范围内费用中按待遇政策由个人承担的部分（自付一），属个人负担口径。",
    "self_pay_2": "部分项目按规定比例先行自付或超限价自付的金额（自付二），属个人负担口径；该金额已包含在医保范围外金额中，不重复相加。",
    "first_pay": "起付线以下由个人先行承担的金额，属个人负担口径。",
    "big_self_pay": "大额段费用中由个人承担的部分，属个人负担口径。",
    "fund_total": "本笔医保基金支付合计，属基金支付口径。",
    "big_pay": "门诊大额医疗互助资金支付金额，属基金支付口径。",
    "pool_pay": "门诊特殊病统筹基金支付金额，属基金支付口径。",
    "pool_self": "统筹段费用中由个人承担的部分，属个人负担口径。",
    "retire_pay": "退休补充保险补助支付金额，属基金支付口径（补助）。",
    "military_pay": "残疾军人补助支付金额，属基金支付口径（补助）。",
    "official_pay": "单位补充医疗保险（原公费医疗）补助支付金额，属基金支付口径（补助）。",
    "big_ill_pay": "大病保险支付金额，属基金支付口径（二次保障）。",
    "aid_pay": "医疗（民政）救助支付金额，属基金支付口径（救助）。",
    "beyond_cap": "超出大额基金封顶线的金额，属个人负担口径。",
    # 支付渠道：与个人承担是同一笔钱的支付拆分（与 T_SelfPayAll.channel /
    # XJZF.identity 恒等行口径一致），不重复相加。
    "account_pay": "支付方式：以个人账户支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。",
    "cash_pay": "支付方式：以现金支付的金额；与个人支付总金额是同一笔钱的支付拆分，不重复相加。",
    # 定额（肾）扩展键：医院定额清算口径，不是患者待遇金额。
    "quota_amount": "医院核定定额，属医院定额清算口径，不是患者待遇金额。",
    "agency_pay": "医院垫付基金合计，属医院定额清算口径。",
    "initial_self": "原始个人自付一（定额清算口径），属医院定额清算口径。",
    "hospital_pool_pay": "医院定额口径下的统筹基金支付，属医院定额清算口径。",
    "hospital_pool_self": "医院定额口径下的统筹自付，属医院定额清算口径。",
    "hospital_big_pay": "医院定额口径下的门诊大额基金支付，属医院定额清算口径。",
    "hospital_big_self": "医院定额口径下的大额自付，属医院定额清算口径。",
    "hospital_retire_pay": "医院定额口径下的补充保险支付，属医院定额清算口径。",
    "hospital_military_pay": "医院定额口径下的残疾军人补助支付，属医院定额清算口径。",
    "hospital_official_pay": "医院定额口径下的单位补充医疗保险（原公疗）支付，属医院定额清算口径。",
}

_FAMILY_MEANING_OVERRIDES: dict[tuple[str, str], str] = {
    # 居民门诊大额是"门诊大额基金支付"，不写成职工"大额医疗互助"
    ("resident_outpatient", "big_pay"): "门诊大额基金支付金额，属基金支付口径。",
    ("resident_special", "big_pay"): "门诊大额基金支付金额，属基金支付口径。",
    # 居民无退休/军残/公疗补充待遇（对应字段恒不适用）
    ("resident_outpatient", "retire_pay"): "退休补充保险补助支付金额；居民医保无此待遇项目，正常应为不适用。",
    ("resident_outpatient", "military_pay"): "残疾军人补助支付金额；居民医保无此待遇项目，正常应为不适用。",
    ("resident_outpatient", "official_pay"): "单位补充医疗保险（原公费医疗）补助支付金额；居民医保无此待遇项目，正常应为不适用。",
    ("resident_special", "retire_pay"): "退休补充保险补助支付金额；居民医保无此待遇项目，正常应为不适用。",
    ("resident_special", "military_pay"): "残疾军人补助支付金额；居民医保无此待遇项目，正常应为不适用。",
    ("resident_special", "official_pay"): "单位补充医疗保险（原公费医疗）补助支付金额；居民医保无此待遇项目，正常应为不适用。",
    # GRZIF1（门特自付一）：该列在已核样本中未维护，账面值不可得，
    # 含义统一为"补助或二次保障前的计算构成"（分量计算值，不作账面核对）。
    ("employee_special", "self_pay_1"): "医保范围内由个人承担的自付一部分，为补助或二次保障前的计算构成，属个人负担口径。",
    ("resident_special", "self_pay_1"): "医保范围内由个人承担的自付一部分，为补助或二次保障前的计算构成，属个人负担口径。",
}

#: 模板缺失时的 field_code → key 回退映射（派生核对行 "X.detail" 不在内，不生成含义）
_OUTPATIENT_KEY_BY_CODE = {
    "T_FeeAll": "fee_all", "T_SelfPayAll": "personal_total", "T_FeeIn": "fee_in",
    "T_FeeOut": "fee_out", "T_SelfPay1": "self_pay_1", "T_SelfPay2": "self_pay_2",
    "T_FirstPay": "first_pay", "T_BigSelfPay": "big_self_pay", "T_FundPay": "fund_total",
    "T_PersonCountPay": "account_pay", "T_BigPay": "big_pay", "T_JCPay": "military_pay",
    "T_CashPay": "cash_pay", "T_BCPay": "retire_pay", "T_BigillPay": "big_ill_pay",
    "NT_CivilPay": "aid_pay", "RETIRE_OFFICER_PAY": "retire_officer_pay",
    "T_OfficalPay": "official_pay",
}

_SPECIAL_KEY_BY_CODE = {
    "ZJE": "fee_all", "PERSON_PAYABLE": "personal_total", "YBN": "fee_in",
    "TSBYBN": "fee_in", "YBW": "fee_out", "TSBYBW": "fee_out", "YBNQFJE": "first_pay",
    "GRZIFTW": "self_pay_2", "GRZIF1": "self_pay_1", "TCZHF": "pool_pay",
    "TCZIF": "pool_self", "DEGWYZHF": "big_pay", "DEGWYZIF": "big_self_pay",
    "BCZHF": "retire_pay", "JCZHF": "military_pay", "BIG_ILL_PAY": "big_ill_pay",
    "CIVIL_IN": "aid_pay", "ZHZF": "account_pay", "XJZF": "cash_pay",
    "RETIRE_OFFICER_PAY": "retire_officer_pay", "GFYLBCHBX": "official_pay",
    "QUOTA_AMOUNT": "quota_amount", "AGENCY_PAY": "agency_pay",
}

_KEY_BY_CODE = {
    "employee_outpatient": _OUTPATIENT_KEY_BY_CODE,
    "resident_outpatient": _OUTPATIENT_KEY_BY_CODE,
    "employee_special": _SPECIAL_KEY_BY_CODE,
    "resident_special": _SPECIAL_KEY_BY_CODE,
}


def field_meaning(family: str | None, template_key: str | None, field_code: str | None) -> str | None:
    """(链路, 模板 key/field_code) → 金额含义固定文案；未登记返回 None。"""
    if family is None:
        return None
    key = resolve_field_key(family, template_key, field_code)
    if key is None:
        return None
    return _FAMILY_MEANING_OVERRIDES.get((family, key)) or _BASE_MEANING.get(key)


def resolve_field_key(family: str | None, template_key: str | None, field_code: str | None) -> str | None:
    """模板 key 缺省时按 field_code 回退映射（与 field_meaning 同一口径）。"""
    if template_key:
        return template_key
    if family is None:
        return None
    return _KEY_BY_CODE.get(family, {}).get(field_code or "")


def _dec_or_none(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value)) if value is not None else None
        return number if number is not None and number.is_finite() else None
    except InvalidOperation:
        return None


def _two_dp(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


#: 范围外金额的本单二次保障覆盖分量（field_code → 保障名）
_FEE_OUT_COVERAGE_CODES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("FEEOUT_DB_PAY",), "大病保险支付"),
    (("FEEOUT_MAF_PAY",), "医疗救助支付"),
)


def _fee_out_coverage_sentence(
    field: Mapping[str, Any], siblings: Mapping[str, Mapping[str, Any]]
) -> str | None:
    """范围外金额的本单二次保障覆盖：只列本单确实执行的大病/救助分量（评审问题 4）。

    不据此推广为所有医保外都能获得救助；账面关系不成立（覆盖合计超过范围外金额）时不编造。
    """
    observed = _dec_or_none(field.get("observed_amount"))
    if observed is None:
        return None
    parts: list[str] = []
    covered_total = Decimal("0")
    for codes, name in _FEE_OUT_COVERAGE_CODES:
        sibling = next((siblings[code] for code in codes if code in siblings), None)
        amount = _dec_or_none((sibling or {}).get("observed_amount"))
        if amount is None:
            amount = _dec_or_none((sibling or {}).get("calculated_amount"))
        if amount is not None and amount > 0:
            parts.append(f"{name}覆盖 {_two_dp(amount)} 元")
            covered_total += amount
    if not parts:
        return None
    remainder = observed - covered_total
    if remainder < 0:
        return None
    return "本单后续保障：" + "、".join(parts) + f"，剩余由个人承担 {_two_dp(remainder)} 元。"


# ── 零金额三态（不适用 / 符合但为零 / 资格资料不足）────────────────────

#: 资格确定不满足（模块 not_applicable）的 reason_code
_ELIGIBILITY_NOT_APPLICABLE = {
    "NOT_APPLICABLE", "NOT_RETIRED", "NOT_DISABLED_VETERAN", "NOT_PUBLIC_MEDICAL",
    "NO_MILITARY_DISABILITY_BENEFIT", "PUBLIC_MEDICAL_CHANNEL_NOT_SELECTED",
    "RESIDENT_SUPPLEMENT_NOT_APPLICABLE", "RESIDENT_SPECIAL_NO_POOL",
    "RESIDENT_BIGILL_NOT_APPLICABLE",
}

#: 资格资料不足（outcome=UNKNOWN → not_verifiable）的 reason_code
_ELIGIBILITY_UNKNOWN = {
    "PERSON_KIND_UNKNOWN", "PERSON_TYPE_UNKNOWN", "RETIREMENT_CATEGORY_UNKNOWN",
    "MILITARY_ELIGIBILITY_FIELD_UNMAPPED", "PMED_ELIGIBILITY_FIELD_UNMAPPED",
}

#: 待遇支付类字段：matched 零值表达"符合但为零"，区别于"不适用"
_BENEFIT_FIELD_CODES = {
    "T_BigPay", "T_BCPay", "T_JCPay", "T_OfficalPay", "RETIRE_OFFICER_PAY",
    "T_BigillPay", "NT_CivilPay", "T_FundPay", "TCZHF", "DEGWYZHF",
    "BIG_ILL_PAY", "CIVIL_IN", "FEEIN_DB_PAY", "FEEOUT_DB_PAY",
    "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY",
}


def _is_zero(value: str | None) -> bool:
    if value is None:
        return False
    try:
        from decimal import Decimal

        return Decimal(value) == 0
    except Exception:
        return False


def zero_amount_sentence(
    check_status: str,
    reason_code: str | None,
    observed_amount: str | None,
    calculated_amount: str | None,
    field_code: str,
) -> str | None:
    """零金额/不适用三态固定措辞；不适用三态之一返回 None（走通用措辞）。

    不能只凭零金额判没有资格：资格资料不足与"不符合条件"必须分开表达。
    """
    if check_status == "not_applicable":
        if reason_code == "ELIGIBILITY_CONFLICT_WITH_BOOK":
            return "本单不符合该待遇条件，但账面存在非零金额，资格与账面冲突已标记。"
        if reason_code in _ELIGIBILITY_NOT_APPLICABLE:
            return "本单不符合该待遇条件，该项待遇不适用。"
        return None
    if (check_status == "matched" and field_code in _BENEFIT_FIELD_CODES
            and _is_zero(observed_amount) and _is_zero(calculated_amount)):
        return "符合待遇条件，本笔金额为零。"
    if (check_status == "not_verifiable" and reason_code in _ELIGIBILITY_UNKNOWN
            and (observed_amount is None or _is_zero(observed_amount))):
        return "资格资料不足，不能仅凭零金额判断没有资格。"
    return None


# ── 内核未产出字段的具体缺项声明 ──────────────────────────────────────

_UNPRODUCED_BOUNDARY: dict[tuple[str, str], str] = {
    ("employee_outpatient", "beyond_cap"): "模板未绑定计算目标（field_code 为空），内核未产出该字段的分解记录；超封顶金额无独立计算或费用归属映射，仅按原单列示。",
    ("resident_outpatient", "beyond_cap"): "模板未绑定计算目标（field_code 为空），内核未产出该字段的分解记录；超封顶金额无独立计算或费用归属映射，仅按原单列示。",
    ("employee_outpatient", "aid_pay"): "内核普通门诊链未产出该字段的分解记录；救助金额仅作为基金合计恒等的账面分量出现，缺民政救助资格与计算规则。",
    ("resident_outpatient", "aid_pay"): "内核居民门诊链未产出该字段的分解记录；救助金额仅作为基金合计恒等的账面分量出现，缺民政救助资格与计算规则。",
    # 退役医疗费 0 元只需说明原单标志；此句仅在调用方未提供标志时作为缺项说明
    ("resident_outpatient", "retire_officer_pay"): "本笔结算记录未提供退役医疗费标志。",
}

_DEFAULT_UNPRODUCED_BOUNDARY = "内核未产出该字段的分解记录，仅按原单模板列示账面金额。"

#: GRZIF1 诚实口径（与 _field_line/_conclusion_of/_field_brief 三处措辞一致）
_SELF_PAY_1_UNMAINTAINED_BOUNDARY = "该列在已核样本中未维护，当前金额由本单分量计算，不作账面核对。"

#: 支付渠道键：无政策依据属正常形态，边界用专门措辞而非"未记录依据"
_CHANNEL_KEYS = {"account_pay", "cash_pay"}


def _basis_text_of(basis: Mapping[str, Any] | None, rule_excerpts: Sequence[str]) -> str | None:
    parts = list(rule_excerpts)
    source_titles = [str(title) for title in (basis or {}).get("source_titles", []) if title]
    if source_titles:
        parts.append("依据来源：" + "、".join(source_titles) + "。")
    return "；".join(parts) or None


def build_field_explanation(
    *,
    family: str | None,
    template_key: str | None,
    field_code: str | None,
    label: str,
    field: Mapping[str, Any] | None,
    gap_messages: Sequence[str] = (),
    rule_excerpts: Sequence[str] = (),
    siblings: Mapping[str, Mapping[str, Any]] | None = None,
    composition_notes: Sequence[str] = (),
    composition_override: str | None = None,
) -> FieldExplanationView:
    """合成单字段四要素固定说明（纯函数；field=None 表示内核未产出该字段）。

    field 为公开字段投影 dict（含 check_status/reason_code/brief/conclusion/
    conclusion_text/explanation_reason/basis/observed_amount/calculated_amount）。
    siblings 为同单其他字段投影（field_code → dict），供范围外金额列示本单实际
    执行的二次保障覆盖分量；composition_notes 为本单实际构成的补充说明（如自付二
    的全自费剔除说明）。
    """
    meaning = field_meaning(family, template_key, field_code)
    key = resolve_field_key(family, template_key, field_code)
    missing: list[str] = []
    if meaning is None:
        missing.append("字段含义说明未登记。")

    status = str(field.get("check_status") or "") if field else ""
    reason_code = (field or {}).get("reason_code")
    state = zero_amount_sentence(
        status, reason_code,
        (field or {}).get("observed_amount"), (field or {}).get("calculated_amount"),
        field_code or "")

    # 金额构成：优先复用 brief/计算记录措辞；无计算记录写明诚实口径
    composition: str | None = None
    if composition_override:
        # 该字段的构成口径由调用方给定（如退役医疗费只讲原单标志），不再追加通用填充语
        composition = composition_override
    elif field is None:
        missing.append(_UNPRODUCED_BOUNDARY.get(
            (family or "", key or ""), _DEFAULT_UNPRODUCED_BOUNDARY))
    elif status == "not_applicable":
        composition = None  # 不产生金额构成，由状态句说明
    else:
        composition = field.get("brief") or None
        if composition is None:
            if field.get("check_type") == "identity_check":
                composition = "账面勾稽：仅核对各分量关系，未独立重算。"
            elif field.get("observed_amount") is not None:
                composition = "仅账面列示，暂无独立计算记录。"
            else:
                missing.append("账面与计算值均未取得，金额构成无法列示。")
        # 范围外金额：本单实际执行的二次保障覆盖分量（688：69.90 由大病/救助覆盖、最终个人 0）
        if key == "fee_out" and composition:
            coverage = _fee_out_coverage_sentence(field, siblings or {})
            if coverage:
                composition += "；" + coverage
        if composition and composition_notes:
            composition += "；" + "；".join(note for note in composition_notes if note)

    if composition_override:
        # 调用方已给定该字段唯一口径（退役医疗费：只讲原单标志），不叠加通用缺项套话
        return FieldExplanationView(meaning=meaning, composition=composition,
                                    basis_text=None, boundary=None)

    # 本单依据：采用档 + 来源标题；为空不编造，归到边界
    basis_text = _basis_text_of((field or {}).get("basis"), rule_excerpts)
    if basis_text is None and status != "not_applicable" and field is not None:
        if (key or "") in _CHANNEL_KEYS:
            missing.append("支付渠道按原单记录列示，无待遇政策依据项。")
        else:
            missing.append("本字段未记录关联政策依据来源。")

    # 解释边界：状态句 → GRZIF1 诚实口径 → 解释理由 → 结论分级 → 缺口 → 缺项声明
    boundary_parts: list[str] = []
    if state:
        boundary_parts.append(state)
    if reason_code == "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED":
        boundary_parts.append(_SELF_PAY_1_UNMAINTAINED_BOUNDARY)
    if field is not None:
        if field.get("explanation_reason"):
            boundary_parts.append(str(field["explanation_reason"]).rstrip("。") + "。")
        conclusion_text = str(field.get("conclusion_text") or "")
        if (conclusion_text and status != "not_applicable"
                and field.get("conclusion") != "basis_confirmed"
                and reason_code != "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED"):
            boundary_parts.append(conclusion_text.rstrip("。") + "。")
    boundary_parts.extend(str(message) for message in gap_messages if message)
    boundary_parts.extend(missing)
    boundary = "；".join(dict.fromkeys(part for part in boundary_parts if part)) or None
    return FieldExplanationView(
        meaning=meaning, composition=composition, basis_text=basis_text, boundary=boundary)


def render_field_explanation(explanation: FieldExplanationView) -> list[str]:
    """四要素 → 有序文本行（面板与聊天同源的展开文字，同源同文）。"""
    return [text for text in (
        explanation.meaning, explanation.composition,
        explanation.basis_text, explanation.boundary) if text]
