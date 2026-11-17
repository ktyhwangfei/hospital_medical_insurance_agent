"""统一费用解释：确定性分解提供事实，模型按独立提示词组织正文，校验失败回退证据。"""
from __future__ import annotations

import logging
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from skills.mzsettlement_verify_skill.models import OutpatientSettlementContext
from src.runtime.policy_qa.fee_decomposition.answer_validation import equation_issues
from src.runtime.policy_qa.fee_decomposition.billing_boundary import (
    BillingBoundaryPayload, build_billing_boundary_payload)
from src.runtime.policy_qa.fee_decomposition.explanation_evidence import input_id
from src.runtime.policy_qa.fee_decomposition.formula_text import trim_trailing_zeros as _trim_trailing_zeros
from src.runtime.policy_qa.fee_decomposition.field_explanations import (
    FieldExplanationView, render_field_explanation)
from src.runtime.policy_qa.public_contract import FeeDecompositionPublic

logger = logging.getLogger(__name__)


class PaymentShare(BaseModel):
    label: str
    amount: str
    total_fee: str
    share_percent: str


class AmountLine(BaseModel):
    label: str
    amount: str


class PaymentReconciliation(BaseModel):
    """个人支付/基金合计的确定性勾稽：只给已列示分项与差额，不猜差额归属。"""

    book_fund_total: str | None = None
    fund_channels: list[AmountLine] = Field(default_factory=list)
    itemized_fund_total: str | None = None
    fund_gap: str | None = None
    book_personal_total: str | None = None
    personal_components: list[AmountLine] = Field(default_factory=list)
    identity_personal_total: str | None = None
    personal_gap: str | None = None
    note: str | None = None


class SelfPay2Line(BaseModel):
    item_name: str
    basis: str
    ratio: str | None = None
    amount: str


class SelfPay2Breakdown(BaseModel):
    """自付二逐项构成：回答"自付二为什么这么多"时直接使用，不必重讲整张结算单。"""

    total: str | None = None
    lines: list[SelfPay2Line] = Field(default_factory=list)
    zero_item_count: int = 0
    full_out_items: list[AmountLine] = Field(default_factory=list)
    note: str | None = None


class RenderedRatio(BaseModel):
    """后端渲染的比例档：档位、值、命中条件、确认状态。"""

    title: str
    chosen: str
    checks: list[str] = Field(default_factory=list)
    confirmation_status: str | None = None


class TargetEvidence(BaseModel):
    """目标字段的确定性事实：金额、算式、比例、确认状态；确定性正文的唯一事实来源。"""

    field_code: str
    field_label: str
    amount: str | None = None
    formula: str | None = None
    ratios: list[RenderedRatio] = Field(default_factory=list)
    sentence: str | None = None


class BilledItemFact(BaseModel):
    """同单收费线索，不携带其他行金额，也不代表执行或实际联合用药。"""

    display_no: int
    item_name: str
    item_type: str | None = None
    association: Literal["same_settlement_charge_only"] = "same_settlement_charge_only"


class FeeExplanationInput(BaseModel):
    question: str
    decomposition: FeeDecompositionPublic
    actual_payment_shares: list[PaymentShare] = Field(default_factory=list)
    payment_reconciliation: PaymentReconciliation = Field(default_factory=PaymentReconciliation)
    self_pay_2_breakdown: SelfPay2Breakdown = Field(default_factory=SelfPay2Breakdown)
    target_evidence: list[TargetEvidence] = Field(default_factory=list)
    line_evidence: LineTargetEvidence | None = None
    # 多行/全覆盖问题：逐行证据各自独立（单行问题只用 line_evidence）
    line_evidences: list[LineTargetEvidence] = Field(default_factory=list)
    # 问题目标形态（fee_line/multi_line/cover_all/comparison/summary_fields/whole_settlement）
    target_kind: str | None = None
    # 对比题：后端组装的字段口径关系说明（固定说明+构成差异），直接进入正文
    comparison_note: str | None = None
    unexplained_fields: list[str] = Field(default_factory=list)
    #: 被点名但未产出证据的目标逐项缺口（确定性正文逐项列明，不整题吞掉已有证据）
    target_gaps: list[str] = Field(default_factory=list)
    billed_items: list[BilledItemFact] = Field(default_factory=list)
    #: 收费边界解释（Issue #85）：诊疗/价格项目内涵「不含/除外内容/另收/包含」
    #: 对上同单费用行的事实与预组句子；对不上内涵或费用的行不在其中。
    billing_boundaries: BillingBoundaryPayload | None = Field(
        default=None, exclude_if=lambda value: value is None)


#: 问题里的口语说法 → 后端字段；命中后才提供该字段的证据（Issue #83 第 3 项）。
_TARGET_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("统筹基金支付", "统筹支付", "统筹基金", "统筹"), ("TCZHF", "统筹基金支付", "统筹支付")),
    (("统筹自付",), ("TCZIF", "统筹自付")),
    (("大额个人自付", "大额自付"), ("T_BigSelfPay", "DEGWYZIF", "大额个人自付", "大额自付")),
    (("大额支付", "大额互助", "大额"), ("T_BigPay", "DEGWYZHF", "大额支付", "大额互助支付")),
    (("起付",), ("T_FirstPay", "YBNQFJE", "本次起付承担", "本次起付金额", "起付金额")),
    (("自付二", "自付（二）", "自付(二)", "先行自付"), ("T_SelfPay2", "GRZIFTW", "自付二", "先行自付")),
    (("自付一", "自付（一）", "自付(一)"), ("T_SelfPay1", "GRZIF1", "自付一")),
    (("个人支付", "个人承担", "个人应付"), ("T_SelfPayAll", "PERSON_PAYABLE", "个人支付总金额", "最终个人承担")),
    (("退休补助", "退休补充"), ("T_BCPay", "BCZHF", "退休补充保险补助", "退休补助")),
    (("军残", "残疾军人"), ("T_JCPay", "JCZHF", "军残支付", "军残补助")),
    (("公疗", "单位补充医疗保险"), ("T_OfficalPay", "GFYLBCHBX", "公疗补充支付", "公疗补助")),
    (("退役医疗费",), ("RETIRE_OFFICER_PAY", "退役医疗费支付")),
    (("大病",), ("T_BigillPay", "BIG_ILL_PAY", "大病保险支付")),
    (("救助",), ("NT_CivilPay", "CIVIL_IN", "民政救助支付", "医疗救助支付")),
    (("现金", "现金支付"), ("T_CashPay", "XJZF", "现金支付")),
    (("账户", "账户支付", "个人账户支付"), ("T_PersonCountPay", "ZHZF", "账户支付")),
    (("医保内", "医保范围内", "范围内"), (
        "T_FeeIn", "YBN", "TSBYBN", "医保内费用", "医保范围内金额")),
    (("医保外", "医保范围外", "范围外"), (
        "T_FeeOut", "YBW", "TSBYBW", "医保外费用", "医保范围外金额")),
    (("总费用", "费用总金额"), ("T_FeeAll", "ZJE", "总费用", "费用总金额")),
)


class LineRef(BaseModel):
    """多行指向中的单行引用（按前端展示序号定位）。"""

    line_id: str
    display_no: int
    attributes: list[str] = Field(default_factory=list)


class QuestionTarget(BaseModel):
    """问题指向的确定目标：整单 / 汇总字段 / 唯一明细行 / 多行 / 全覆盖 / 字段对比 / 字段+行混合 / 歧义 / 无法定位。

    空 targets 不再同时代表"问整单"和"没识别出来"：kind 显式区分各态，
    ambiguous/invalid 携带给用户的定位提示文案（调用方据此短路，不渲染正文）。
    multi_line 的 lines 逐行携带 line_id/display_no/attributes；comparison 的
    field_codes 至少两个字段；mixed 同时携带 field_codes 与 lines（两类显式目标共存，
    行命中不再提前丢弃汇总目标）；cover_all 的 field_codes 为全覆盖集合
    （可见模板字段含 bill.*，并集主字段）。
    """

    kind: Literal["whole_settlement", "summary_fields", "fee_line", "multi_line",
                  "cover_all", "comparison", "mixed", "ambiguous", "invalid"]
    field_codes: list[str] = Field(default_factory=list)
    line_id: str | None = None
    display_no: int | None = None
    attributes: list[str] = Field(default_factory=list)
    lines: list[LineRef] = Field(default_factory=list)
    prompt: str | None = None


class LineTargetEvidence(BaseModel):
    """目标明细行的确定性事实：金额、判定路径、已执行公式与来源；确定性正文直接引用。"""

    display_no: int
    line_id: str
    item_name: str = ""
    item_code: str = ""
    unit_price: str | None = None
    quantity: str | None = None
    total_fee: str | None = None
    observed_in_scope: str | None = None
    observed_out_scope: str | None = None
    observed_self_pay_2: str | None = None
    calculated_in_scope: str | None = None
    calculated_out_scope: str | None = None
    calculated_self_pay_2: str | None = None
    division_method: str = "unknown"
    unit_price_limit: str | None = None
    self_pay_ratio: str | None = None
    limit_source: str | None = None
    ratio_source: str | None = None
    decision_path: list[Any] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    explainable: bool = False
    explanation_reason: str | None = None
    attributes: list[str] = Field(default_factory=list)
    sentence: str = ""


#: “第 6 行／第 6 项／第 6 笔”等显式行号（按前端展示序号，即 fee_items 列表 index+1）；
#: 支持多行并列：“第1行和第2行”（两次匹配）与“第1、2行”（尾部并列数字）。
_MULTI_ORDINAL = re.compile(
    r"第\s*(\d{1,3})\s*((?:[、,，和与]\s*\d{1,3})*)\s*(?:行|项|条|笔|个)")
#: 列表记号“6. 项目名”：数字后随句点/顿号且下一个是非数字（排除 0.15、50.65 这类小数）。
_LIST_MARKER = re.compile(r"(?<![\d.])(\d{1,2})\s*[.、．]\s*(?=[^\d])")
#: 同名项目消歧的金额线索：“200块那个晶体”“1935元的那支”。
_AMOUNT_CLUE = re.compile(r"(?<![\d.])(\d+(?:\.\d{1,2})?)\s*(?:块|元)")
#: 全覆盖意图：逐项说明全部明细。
_COVER_ALL_MARKERS = (
    "全部费用", "所有费用", "全部明细", "所有明细", "逐项", "逐条",
    "每条费用", "每笔费用", "每条明细", "所有项目", "全部项目",
)
#: 对比意图：命中至少两个汇总字段且带对比措辞时升级为 comparison。
_COMPARISON_MARKERS = (
    "区别", "不同", "差异", "差别", "对比", "相比", "哪个多", "哪个高", "哪个大",
)


#: 项目名里的括号缩写（总蛋白(TP)测定、抗HCV）去掉后再与问句比整名。
_PAREN_GROUP = re.compile(r"[（(][^（）()]{0,20}[）)]")
#: 收费项目内涵 / 为何还要单收是同一类。覆盖换说法，不按已出现过的原句逐条登记。
#: 「个人支付为什么还要收」不含这些说法，仍按汇总金额解释。
_BILLING_BOUNDARY_QUESTION = re.compile(
    r"内涵|含什么|包含什么|含哪些|包含哪些|"
    r"(?:单独|另行|另外|分开|单|另)收|(?:单独|另行|另外|分开)计费"
)


def _name_without_paren(name: str) -> str:
    return _PAREN_GROUP.sub("", name).strip()


def _is_billing_boundary_question(text: str) -> bool:
    return _BILLING_BOUNDARY_QUESTION.search(text or "") is not None


def _longest_name_span(name: str, text: str) -> tuple[int, int] | None:
    """名称里出现在问句中的最长连续片段（至少两字）。"""
    for length in range(len(name), 1, -1):
        for start in range(0, len(name) - length + 1):
            piece = name[start:start + length]
            at = text.find(piece)
            if at >= 0:
                return at, at + length
    return None


def _billing_name_hits(names: list[str], text: str) -> list[int]:
    """收费边界问题里的短项目名：两字及以上的名称片段即可对上，不受四字阈值限制。

    较长片段盖住被它包含的短片段。「总蛋白」盖住「蛋白」。问句写出「活检钳」时只对活检钳；
    只说「活检」时，活检术和活检钳都保留。
    """
    spans: dict[int, tuple[int, int]] = {}
    for index, name in enumerate(names):
        if not name:
            continue
        variants = {name, _name_without_paren(name)}
        best: tuple[int, int] | None = None
        for variant in variants:
            span = _longest_name_span(variant, text)
            if span is not None and (best is None or span[1] - span[0] > best[1] - best[0]):
                best = span
        if best is not None:
            spans[index] = best
    kept: list[int] = []
    for index, span in spans.items():
        if any(
            other != index
            and other_span[0] <= span[0] and span[1] <= other_span[1]
            and other_span[1] - other_span[0] > span[1] - span[0]
            for other, other_span in spans.items()
        ):
            continue
        kept.append(index)
    return kept


def _item_name_hits(public: FeeDecompositionPublic, text: str) -> list[int]:
    """项目名称命中（返回 fee_items 下标）：整名包含，或与行名最长公共子串达阈值。"""
    names = [(item.item_name or "").strip() for item in public.fee_items]
    hits: list[int] = []
    for index, name in enumerate(names):
        if not name:
            continue
        # 长名允许口语片段（如“人工晶体”），短名（阈值=全长）需整名出现。
        threshold = min(len(name), 4)
        matched = SequenceMatcher(None, text, name).find_longest_match().size >= threshold
        if not matched:
            bare = _name_without_paren(name)
            # 问句写出去掉括号缩写后的全名才命中（总蛋白测定 → 总蛋白(TP)测定）。
            # 必须整名包含，避免「总蛋白测定」误中「白蛋白测定」。
            matched = len(bare) >= 4 and bare != name and bare in text
        if matched:
            hits.append(index)
    if _is_billing_boundary_question(text):
        for index in _billing_name_hits(names, text):
            if index not in hits:
                hits.append(index)
    return hits


def _line_attributes(question: str) -> list[str]:
    """问题中点名的行内属性：映射到本行金额口径，不命中整单合计字段。"""
    attributes: list[str] = []
    for label, attribute in _LINE_LEVEL_AMOUNTS.items():
        if label in question and attribute not in attributes:
            attributes.append(attribute)
    return attributes


def _fmt_amount(value: str | None) -> str:
    return _text(_dec(value)) or (value or "0.00")


def _narrow_by_amount_clues(
    public: FeeDecompositionPublic, text: str, hits: list[int]
) -> list[int]:
    """同名项目多命中时按金额线索（“200块那个”）收敛：匹配行费用或单价的留下。"""
    clues: list[Decimal] = []
    for raw in _AMOUNT_CLUE.findall(text):
        value = _dec(raw)
        if value is not None:
            clues.append(value)
    if not clues:
        return hits
    matched = [
        index for index in hits
        if any(
            _dec(public.fee_items[index].total_fee) == clue
            or _dec(public.fee_items[index].unit_price) == clue
            for clue in clues
        )
    ]
    return matched or hits


def _invalid_line_prompt(public: FeeDecompositionPublic, display_no: int) -> QuestionTarget:
    return QuestionTarget(kind="invalid", prompt=(
        f"本单费用明细共 {len(public.fee_items)} 行，没有第 {display_no} 行；"
        f"请用 1 到 {len(public.fee_items)} 之间的行号指定要解释的明细。"))


#: 行属性词（混合问法中从汇总字段识别文本剥离，避免"第1行医保内"误命中整单医保内字段）。
_LINE_ATTRIBUTE_WORDS = ("医保范围内外", "医保内外", "医保范围内", "医保范围外", "先行自付", "医保内", "医保外", "自付二")
#: 问法/属性词：剥离后剩余的中文/字母片段视为显式项目名（任务 6 名称一致性校验）。
_QUESTION_WORDS = (
    "医保范围内外", "医保内外", "医保范围内", "医保范围外", "先行自付", "费用总金额",
    "医保内", "医保外",
    "自付一", "自付二", "总费用", "费用", "金额", "多少", "为什么", "怎么样",
    "怎么算", "怎么", "咋", "便宜", "贵", "明细", "项目", "自费", "的", "是", "各",
    "如何", "钱", "一下",
)
_QUOTED_NAME = re.compile(r"[「《\"“]([^」》\"”]{2,})[」》\"”]")


#: 名称槽噪声词：请求前缀、连接词、属性、问句尾与通用名词（不构成项目名）。
_NAME_NOISE_WORDS = tuple(sorted(
    set(_QUESTION_WORDS) | set(_LINE_ATTRIBUTE_WORDS) | {
        "请", "麻烦", "帮忙", "解释", "说明", "包含", "包括", "尤其", "其中", "每一个",
        "每个", "所有", "全部", "整单", "本单", "这单", "结算单", "单据", "数量", "单价",
        "分别", "是什么", "多少", "哪个", "哪行", "各项", "展示", "显示", "字段",
        "两个", "两项", "两行", "都",
        "和", "与", "以及", "及", "或", "那", "这", "个", "行", "项", "呢", "吗", "吧",
        "啊", "有", "无", "为", "分别是什么",
    }, key=len, reverse=True))


def _summary_terms(public: FeeDecompositionPublic) -> tuple[str, ...]:
    """汇总字段的展示名与口语别名：这些词只说明整单口径，不是项目名。"""
    terms: set[str] = set()
    template = (public.settlement_facts.display_template
                if public.settlement_facts and public.settlement_facts.display_template else None)
    if template is not None:
        terms.update(tf.label for tf in template.fields if tf.label)
    for keywords, _codes in _TARGET_ALIASES:
        terms.update(keywords)
    return tuple(sorted(terms, key=len, reverse=True))


def _strip_name_terms(public: FeeDecompositionPublic, text: str) -> str:
    """剥离请求前缀/连接词/属性/汇总字段词与标点，剩下的才可能是显式项目名。

    所有词按长度降序统一剥离（长词优先），否则"医保内"会先吃掉"医保内外"留下"外"。
    """
    words = set(_summary_terms(public)) | set(_NAME_NOISE_WORDS)
    remainder = text
    for word in sorted(words, key=len, reverse=True):
        remainder = remainder.replace(word, "")
    return re.sub(r"[\s，。,。？?！!、；;：:（）()「」《》\"\"“”]+", "", remainder)


#: 子句里遇到这些词即认为名称槽结束（请求/属性/问句/连接词，不是项目名的一部分）
_CLAUSE_NAME_STOPS = (
    "的", "是", "和", "与", "以及", "及", "各", "都", "分别", "怎么", "如何", "咋",
    "为什么", "多少", "哪个", "哪行", "报销", "比例", "纳入", "医保", "自费", "费用",
    "金额", "数量", "单价", "总", "明细", "项目", "计算", "算", "一共", "共", "能",
    "可", "该", "这", "那", "为", "有", "无", "里", "内", "外", "呢", "吗", "？",
    "?", "，", ",", "、", "。", "全部", "所有", "解释", "说明", "逐项", "逐条", "每",
    "详细", "列示", "列出",
)
_CLAUSE_LEAD = re.compile(r"^[\s的：:，,、和与及]+")
_ITEM_NAME_RUN = re.compile(r"[一-鿿A-Za-z][一-鿿A-Za-z0-9]{1,}")
#: 明确整单口径词：其后紧跟的“医保内/外”等仍是汇总字段，不能当行属性删掉
_WHOLE_SCOPE_PREFIX = ("整单", "全单", "整笔", "本单", "整张", "全部")


def _claimed_name_from_clause(clause: str) -> str | None:
    """显式名称槽才可能是项目名：子句开头、遇到请求/属性/问句词即结束。"""
    quoted = _QUOTED_NAME.search(clause)
    if quoted:
        return quoted.group(1)
    text = _CLAUSE_LEAD.sub("", clause)
    if not text:
        return None
    for word in ("是", "怎么", "如何", "咋", "为什么", "多少", "报销", "比例", "纳入"):
        if text.startswith(word):
            return None
    run = _ITEM_NAME_RUN.match(text)
    if run is None:
        return None
    candidate = run.group(0)
    cut = len(candidate)
    for word in _CLAUSE_NAME_STOPS:
        index = candidate.find(word)
        if index >= 0:
            cut = min(cut, index)
    candidate = candidate[:cut]
    candidate = re.sub(r"(和|与|及|以及|的|各|都|分别)+$", "", candidate)
    return candidate if len(candidate) >= 2 else None


def _line_name_state(
    public: FeeDecompositionPublic, clause: str
) -> tuple[str, str | int | list[int]]:
    """单个行子句的局部名称判定：known(命中下标) / claimed(声称名称) / none。"""
    hits = _item_name_hits(public, clause)
    if hits:
        return "known", hits
    claimed = _claimed_name_from_clause(clause)
    return ("claimed", claimed) if claimed else ("none", "")


def _name_mismatch_target(items, display_no: int, claimed: str) -> QuestionTarget:
    located = items[display_no - 1]
    return QuestionTarget(kind="invalid", prompt=(
        f"第 {display_no} 行是「{located.item_name or located.item_code}」"
        f"（{_fmt_amount(located.total_fee)} 元），与问题中提到的项目名称不符；"
        "请核对行号或项目名称后重新提问。"))


def _unknown_name_target(items, display_no: int, claimed: str) -> QuestionTarget:
    located = items[display_no - 1]
    return QuestionTarget(kind="invalid", prompt=(
        f"第 {display_no} 行是「{located.item_name or located.item_code}」"
        f"（{_fmt_amount(located.total_fee)} 元），未找到名为「{claimed}」的项目；"
        "请核对行号或项目名称后重新提问。"))


def _conflict_line_target(display_no: int, first: str, second: str) -> QuestionTarget:
    return QuestionTarget(kind="invalid", prompt=(
        f"第 {display_no} 行被同时指向了不同项目（「{first}」与「{second}」），"
        "请核对行号和项目名称后重新提问。"))


def _strip_local_attributes(text: str) -> str:
    """只剥离“行内属性词”；紧跟整单/全单等口径词的属性保留给汇总字段识别。"""
    protected: list[str] = []

    def protect(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    pattern = re.compile(r"(?:%s)(?:的|整体)?(?:%s)" % (
        "|".join(_WHOLE_SCOPE_PREFIX),
        "|".join(re.escape(word) for word in _LINE_ATTRIBUTE_WORDS)))
    text = pattern.sub(protect, text)
    for word in sorted(_LINE_ATTRIBUTE_WORDS, key=len, reverse=True):
        text = text.replace(word, "")
    for index, value in enumerate(protected):
        text = text.replace(f"\x00{index}\x00", value)
    return text


def _remove_item_names(public: FeeDecompositionPublic, text: str) -> str:
    """从范围文本里去掉本单已知项目名称，避免名称被当成汇总字段依据。"""
    remainder = text
    for item in public.fee_items:
        for name in (item.item_name, item.item_code):
            if name:
                remainder = remainder.replace(name, "，")
    return remainder


def _named_scope_text(public: FeeDecompositionPublic, text: str) -> str:
    """名称问句的汇总字段识别文本：去掉项目名及其紧邻的行属性词，其余原样保留。

    不能全局删属性词（“自付一和自付二有什么区别”是字段对比，不是行属性）。
    """
    attributes = "|".join(re.escape(word) for word in _LINE_ATTRIBUTE_WORDS)
    remainder = text
    for item in public.fee_items:
        for name in (item.item_name, item.item_code):
            if not name:
                continue
            remainder = re.sub(
                re.escape(name) + r"(?:的)?" + r"(?:%s)?" % attributes, "，", remainder)
    return remainder


def _scope_texts(
    public: FeeDecompositionPublic, occurrences: list[tuple[int, str]], head: str,
) -> list[str]:
    """汇总字段识别文本：行号前原文 + 每个行子句去掉名称/行属性后的残余。"""
    parts = [head]
    for _display_no, clause in occurrences:
        cleaned = _remove_item_names(public, clause)
        parts.append(_strip_local_attributes(cleaned))
    return parts


def _mixed_summary_codes(
    public: FeeDecompositionPublic, occurrences: list[tuple[int, str]], head: str,
) -> list[str]:
    """汇总字段：行号前原文 + 各局部子句去名称/行属性后的残余一起识别。"""
    return _resolve_summary_field_codes(
        public, "，".join(_scope_texts(public, occurrences, head)))


def _cover_all_field_codes(public: FeeDecompositionPublic) -> list[str]:
    """全覆盖集合：可见模板字段（绑定→field_code，未绑定→bill.<key>）∪ 主字段。

    不能只用 public.fields 推断全部展示项（bill.* 模板未绑定字段也在展示范围内）。
    """
    codes: list[str] = []
    template = (public.settlement_facts.display_template
                if public.settlement_facts and public.settlement_facts.display_template else None)
    if template is not None:
        for tf in template.fields:
            if tf.section == "basic":
                continue
            codes.append(tf.field_code if tf.field_code else f"bill.{tf.key}")
    for field in public.fields:
        if "." not in field.field_code and field.field_code not in codes:
            codes.append(field.field_code)
    return codes


def _has_cover_all(text: str) -> bool:
    return any(marker in text for marker in _COVER_ALL_MARKERS)


def resolve_question_target(public: FeeDecompositionPublic, question: str) -> QuestionTarget:
    """解析问题目标：局部子句先各自绑定，再统一合并汇总字段与范围意图。

    - 每个行号出现都先做局部名称/属性校验，再合并相同行；同一行被指向不同项目时澄清；
    - 行号前提、行子句中间、行子句之后的显式汇总字段都保留（mixed）；
    - 行属性只在所属子句内消费，不提升为整单字段；
    - “解释全部费用/逐项说明”→ cover_all（含 bill.*），列表编号入口同样合并；
    - 名称只给时：唯一命中直接定位，重复名先按金额/行号线索收敛，否则澄清。
    """
    text = (question or "").strip()
    ordinal_matches = list(_MULTI_ORDINAL.finditer(text))
    if ordinal_matches:
        head = text[:ordinal_matches[0].start()]
        occurrences = _expand_ordinal_occurrences(text, ordinal_matches)
        return _merge_line_targets(public, text, occurrences, head)
    marker = _LIST_MARKER.search(text)
    if marker is not None:
        display_no = int(marker.group(1))
        if not 1 <= display_no <= len(public.fee_items):
            return _invalid_line_prompt(public, display_no)
        return _merge_line_targets(
            public, text, [(display_no, text[marker.end():])], text[:marker.start()])
    hits = _item_name_hits(public, text)
    codes = _resolve_summary_field_codes(public, _named_scope_text(public, text))
    if _has_cover_all(text):
        return QuestionTarget(kind="cover_all", field_codes=_cover_all_field_codes(public))
    if hits:
        return _name_only_target(public, text, hits, codes)
    if codes:
        if len(codes) >= 2 and any(marker in text for marker in _COMPARISON_MARKERS):
            return QuestionTarget(kind="comparison", field_codes=codes)
        return QuestionTarget(kind="summary_fields", field_codes=codes)
    return QuestionTarget(kind="whole_settlement")


def _expand_ordinal_occurrences(
    text: str, ordinal_matches: list[re.Match]
) -> list[tuple[int, str]]:
    """展开每一次行号声明（不去重）：同一行号重复出现时各自保留自己的子句。"""
    occurrences: list[tuple[int, str]] = []
    for index, match in enumerate(ordinal_matches):
        end = ordinal_matches[index + 1].start() if index + 1 < len(ordinal_matches) else len(text)
        clause = text[match.end():end]
        numbers = list(dict.fromkeys(
            int(number) for number in (match.group(1), *re.findall(r"\d{1,3}", match.group(2)))))
        occurrences.extend((display_no, clause) for display_no in numbers)
    return occurrences


def _merge_line_targets(
    public: FeeDecompositionPublic, text: str, occurrences: list[tuple[int, str]], head: str,
) -> QuestionTarget:
    """行号/列表编号/名称共用：逐次局部校验 → 合并相同行 → 合并汇总字段与范围意图。"""
    items = public.fee_items
    claims: dict[int, str] = {}
    attributes: dict[int, list[str]] = {}
    order: list[int] = []
    for display_no, clause in occurrences:
        if not 1 <= display_no <= len(items):
            return _invalid_line_prompt(public, display_no)
        state, payload = _line_name_state(public, clause)
        claim: str | None = None
        if state == "known":
            if (display_no - 1) not in payload:  # type: ignore[operator]
                return _name_mismatch_target(items, display_no, clause)
            claim = items[display_no - 1].item_name or items[display_no - 1].item_code
        elif state == "claimed":
            located = items[display_no - 1]
            if (str(payload) not in (located.item_name or "")
                    and str(payload) not in (located.item_code or "")):
                return _unknown_name_target(items, display_no, str(payload))
            claim = str(payload)
        if claim is not None and display_no in claims and claims[display_no] != claim:
            return _conflict_line_target(display_no, claims[display_no], claim)
        if claim is not None:
            claims.setdefault(display_no, claim)
        if display_no not in order:
            order.append(display_no)
            attributes[display_no] = []
        for attribute in _line_attributes(clause):
            if attribute not in attributes[display_no]:
                attributes[display_no].append(attribute)
    lines = [LineRef(line_id=items[display_no - 1].line_id, display_no=display_no,
                     attributes=attributes[display_no]) for display_no in order]
    if _has_cover_all(text):
        return QuestionTarget(kind="cover_all", field_codes=_cover_all_field_codes(public))
    codes = _mixed_summary_codes(public, occurrences, head)
    if codes:
        return QuestionTarget(kind="mixed", field_codes=codes, lines=lines)
    if len(lines) == 1:
        return QuestionTarget(kind="fee_line", line_id=lines[0].line_id,
                              display_no=lines[0].display_no,
                              attributes=lines[0].attributes)
    return QuestionTarget(kind="multi_line", lines=lines)


def _name_only_target(
    public: FeeDecompositionPublic, text: str, hits: list[int], codes: list[str]
) -> QuestionTarget:
    """无行号、按项目名定位；属性只来自本句，不提升为整单字段。"""
    items = public.fee_items
    if len(hits) > 1:
        narrowed = _narrow_by_amount_clues(public, text, hits)
        if len(narrowed) == 1:
            hits = narrowed
        elif re.search(r"都|两项|两行|全部|所有", text) or _is_billing_boundary_question(text):
            # 收费边界问题点到多行（含同名采血管）时一起解释，不追问是哪一行。
            lines = [LineRef(line_id=items[index].line_id, display_no=index + 1,
                             attributes=_line_attributes(text)) for index in hits]
            if codes:
                return QuestionTarget(kind="mixed", field_codes=codes, lines=lines)
            return QuestionTarget(kind="multi_line", lines=lines)
        else:
            choices = "；".join(
                f"第 {index + 1} 行 {items[index].item_name or items[index].item_code}"
                f"（{_fmt_amount(items[index].total_fee)} 元）" for index in hits)
            return QuestionTarget(kind="ambiguous", prompt=(
                f"您问到的项目在本单费用明细中有多行记录，请指明是哪一行：{choices}。"))
    located = items[hits[0]]
    line = LineRef(line_id=located.line_id, display_no=hits[0] + 1,
                   attributes=_line_attributes(text))
    if codes:
        return QuestionTarget(kind="mixed", field_codes=codes, lines=[line])
    return QuestionTarget(kind="fee_line", line_id=located.line_id,
                          display_no=hits[0] + 1, attributes=line.attributes)


def _resolve_summary_field_codes(public: FeeDecompositionPublic, question: str) -> list[str]:
    """从问题里识别目标字段：返回命中的 field_code 列表（未命中返回空）。"""
    known = {field.field_code for field in public.fields}
    targets: list[str] = []
    matched_labels: list[str] = []
    template = public.settlement_facts.display_template if public.settlement_facts else None
    if template:
        matches = [field for field in template.fields if field.section != 'basic' and field.label in question]
        # 一句里可能同时问多个字段（如“费用总金额…个人支付总金额…”），全部保留；
        # 只在短标签完全被另一个命中标签包含时才剔除（避免“起付金额”吞掉“本次起付金额”）。
        kept = [field for field in matches
                if not any(field.label != other.label and field.label in other.label for other in matches)]
        matched_labels = [field.label for field in kept]
        # 原单字段未绑定计算时只提供账面事实，不猜成同名的另一清算口径。
        targets.extend(field.field_code if field.field_code in known else f'bill.{field.key}'
                       for field in kept)
    for keywords, codes in _TARGET_ALIASES:
        if not any(keyword in question for keyword in keywords):
            continue
        if any(keyword in label for label in matched_labels for keyword in keywords):
            continue
        hit = next((code for code in codes if code in known), None)
        if hit and hit not in targets:
            targets.append(hit)
    return targets


def resolve_target_fields(public: FeeDecompositionPublic, question: str) -> list[str]:
    """兼容包装：summary_fields/comparison/mixed 返回 field_codes，其余形态（含行指向）返回空。"""
    target = resolve_question_target(public, question)
    if target.kind in ("summary_fields", "comparison", "mixed"):
        return list(target.field_codes)
    return []


def _linked_ratio_groups(public: FeeDecompositionPublic, calc_ids: set[str]):
    return [
        group for group in public.rule_choices
        if group.calculation_refs and calc_ids.intersection(group.calculation_refs)
    ]


def _bill_target_evidence(public: FeeDecompositionPublic, code: str) -> TargetEvidence | None:
    """bill.<key> 模板字段的目标证据：名称/金额取自本单展示模板，固定说明取自
    template_explanations[key]（评审问题 8）；归属未经确认时不补造公式、不借相邻字段状态。"""
    key = code[len("bill."):]
    template = (public.settlement_facts.display_template
                if public.settlement_facts and public.settlement_facts.display_template else None)
    located = next((tf for tf in template.fields if tf.key == key), None) if template else None
    if located is None:
        return None
    explanation = public.template_explanations.get(key)
    sentence_parts = [f"{located.label} {located.value} 元"] if located.value is not None else [located.label]
    if explanation is not None:
        # 同源同文：模板固定说明（面板展开的同一份文字）
        view = (FieldExplanationView.model_validate(explanation)
                if isinstance(explanation, dict) else explanation)
        sentence_parts.extend(render_field_explanation(view))
    else:
        sentence_parts.append("本字段无独立计算或费用归属映射，暂未取得可核对依据。")
    return TargetEvidence(
        field_code=code, field_label=located.label, amount=located.value,
        formula=None, ratios=[],
        sentence="；".join(part for part in sentence_parts if part))


#: GRZIF1 允许展示的“本单分量构成”公式类别（补助前构成，不作原单账面核对）
_COMPOSITION_FORMULA_IDS = frozenset({"self_pay_1_components_v1"})


def _terminal_calculation(
    public: FeeDecompositionPublic, field, *, composition_only: bool,
) -> Any | None:
    """按字段归属、终端公式类别、结果一致和上游可解释选择终端计算，与数组顺序无关。

    - 只在字段自己的 calculation_refs 中找；
    - 结果必须与字段金额一致（composition_only 时还要求公式属于构成类别）；
    - 引用的上游计算必须存在且 explainable，不允许未知/未算平上游；
    - 多个候选时不猜（返回 None），由调用方保留事实与缺口。
    """
    by_id = {calc.calculation_id: calc for calc in public.calculations}
    amount = _dec(field.calculated_amount if field.calculated_amount is not None
                  else field.observed_amount)
    if amount is None:
        return None
    candidates = [by_id[ref] for ref in field.calculation_refs if ref in by_id]
    matched = [calc for calc in candidates
               if _dec(calc.result) == amount
               and (calc.explainable or composition_only)
               and (calc.formula_id in _COMPOSITION_FORMULA_IDS if composition_only else True)]
    if len(matched) != 1:
        return None
    calc = matched[0]
    for operand in calc.operands:
        if operand.calculation_ref is None and operand.display_name == "计算中间量":
            # 投影中无法解析的 calc.* 上游（记录缺失或未被装载）→ 不当作可用构成
            return None
        ref = operand.calculation_ref
        if not ref:
            continue
        upstream = by_id.get(ref)
        if upstream is None or not upstream.explainable:
            return None
        if _dec(upstream.result) is None or abs(_dec(upstream.result)) != abs(_dec(operand.value) or Decimal("0")):
            return None
    return calc


def build_target_evidence(public: FeeDecompositionPublic, targets: list[str]) -> list[TargetEvidence]:
    """目标字段的金额、算式、比例与确认状态由后端渲染，确定性正文直接引用。"""
    evidence: list[TargetEvidence] = []
    for code in targets:
        if code.startswith("bill."):
            bill = _bill_target_evidence(public, code)
            if bill is not None:
                evidence.append(bill)
            continue
        field = next((item for item in public.fields if item.field_code == code), None)
        if field is None:
            continue
        calc_ids = set(field.calculation_refs)
        # 解释资格先行：未算平/依赖未核对的字段不装载任何候选计算或采用档（R3）。
        # GRZIF1 例外只放行“自己的终端构成”（公式类别 + 结果一致 + 上游可解释），
        # 不按数组顺序挑记录，也不能仅凭原因码豁免（F1）。
        explainable = bool(field.explainable)
        unmaintained = field.reason_code == "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED"
        calc = (_terminal_calculation(public, field, composition_only=False)
                if explainable else
                _terminal_calculation(public, field, composition_only=True)
                if unmaintained else None)
        ratios: list[RenderedRatio] = []
        for group in (_linked_ratio_groups(public, calc_ids) if explainable else ()):
            candidate = next((row for row in group.candidates if row.status in ("selected", "eligible")), None)
            if candidate is None:
                continue
            value = "" if candidate.value is None else f"{candidate.value}{candidate.unit}"
            ratios.append(RenderedRatio(
                title=group.title.replace(" · 不适用", ""),
                chosen=f"{candidate.name} {value}".strip(),
                checks=[f"{check.name}：{check.actual}（要求{check.expected}）"
                        for check in candidate.checks if check.outcome == "met" and check.actual],
                confirmation_status=candidate.confirmation_status or None,
            ))
        sentence_parts = [f"{field.label} {field.observed_amount} 元"] if field.observed_amount is not None else [field.label]
        if unmaintained and calc is None:
            # 构成依据不可用：保留账面/已有事实，明确缺口，不追加候选原因
            sentence_parts.append("本项计算构成的上游计算未核对或缺失，暂不展示构成算式。")
        if field.explanation is not None:
            # 同源同文：sentence 复用字段四要素固定说明（面板展开的同一份文字），不另造措辞
            sentence_parts.extend(render_field_explanation(field.explanation))
        else:
            if calc is not None and calc.formula:
                sentence_parts.append(calc.formula)
            for ratio in ratios:
                sentence_parts.append(f"采用「{ratio.chosen}」")
            if field.check_type == "identity_check":
                # 账面勾稽字段没有独立计算：明确标注“原单事实”，不等于原因已解释（评审问题 4/10）
                sentence_parts.append("按原单记录列示，仅用于账面关系核对。")
            elif not explainable and field.explanation_reason:
                # 未可解释：只交付原单事实与具体缺口，候选公式/比例不作为本项原因
                sentence_parts.append(field.explanation_reason.rstrip("。") + "。")
            # 确认状态只留在来源说明（selected_ratio_policy_evidence），不进正文
        evidence.append(TargetEvidence(
            field_code=field.field_code, field_label=field.label,
            amount=field.observed_amount,
            formula=_trim_trailing_zeros(calc.formula) if calc is not None else None,
            ratios=ratios, sentence="；".join(part for part in sentence_parts if part),
        ))
    return evidence


def _whole_field_codes(public: FeeDecompositionPublic) -> list[str]:
    """整单问题的固定说明装载范围：全部主字段（不含派生核对行），保持输入有界。"""
    return [field.field_code for field in public.fields if "." not in field.field_code]


def _missing_target_gaps(
    public: FeeDecompositionPublic, targets: list[str], evidence: list[TargetEvidence]
) -> list[str]:
    """被点名但未产出证据的目标逐项缺口说明；bill.* 取模板字段名，缺映射如实声明。"""
    delivered = {item.field_code for item in evidence}
    template_fields = (public.settlement_facts.display_template.fields
                       if public.settlement_facts and public.settlement_facts.display_template else [])
    gaps: list[str] = []
    for code in targets:
        if code in delivered:
            continue
        if code.startswith("bill."):
            key = code[len("bill."):]
            located = next((tf for tf in template_fields if tf.key == key), None)
            label = located.label if located is not None else key
            gaps.append(f"{label}：本字段无独立计算或费用归属映射，暂未取得可核对依据。")
        else:
            gaps.append(f"{code}：未识别到对应的展示字段，暂未取得可核对依据。")
    return gaps


class FeeModelExplanation(BaseModel):
    answer: str
    used_model: bool = False
    model_attempted: bool = False
    fallback_reason: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
    #: 证据回答状态：rendered=有可交付的证据正文（路由据此判 partial）；
    #: none=无可交付证据（维持 unavailable）或仅输出澄清提示。
    evidence_answer_status: Literal["rendered", "none"] = "none"


class DeterministicAnswer(BaseModel):
    """确定性正文渲染结果：正文 + 随文不确定性声明（逐项缺口与目标关联边界）。"""

    body: str
    uncertainties: list[str] = Field(default_factory=list)
    #: 是否含可交付证据正文（False=只有缺口说明，调用方维持 unavailable）
    has_evidence: bool = True


def settlement_context_from_fee(public: FeeDecompositionPublic) -> OutpatientSettlementContext:
    observed = {field.field_code: field.observed_amount for field in public.fields}
    facts = public.settlement_facts
    fact_values = {item.label: item.value for item in facts.items} if facts else {}
    def amount(*keys: str) -> Decimal | None:
        value = next((observed.get(key) or fact_values.get(key) for key in keys if observed.get(key) is not None or fact_values.get(key) is not None), None)
        try:
            number = Decimal(value) if value is not None else None
            return number if number is not None and number.is_finite() else None
        except InvalidOperation:
            return None
    names = facts.metadata_names if facts else {}
    return OutpatientSettlementContext(total_amount=amount('T_FeeAll', 'ZJE', '费用总金额', '总费用'),
        in_scope_amount=amount('T_FeeIn', 'TSBYBN', 'YBN'), out_of_scope_amount=amount('T_FeeOut', 'TSBYBW', 'YBW'),
        deductible_amount=amount('T_FirstPay', 'YBNQFJE'), personal_total_amount=amount('T_SelfPayAll', 'PERSON_PAYABLE', '个人支付总金额'),
        insurance_type=names.get('insurance_type') or (facts.insurance_type if facts else None),
        person_type=names.get('person_type') or (facts.person_type if facts else None),
        service_type=names.get('medical_category') or (facts.medical_category if facts else None),
        hospital_level=names.get('hospital_level') or (facts.hospital_level if facts else None),
        settlement_date=facts.trade_date if facts else None, record_found=bool(facts or public.fields))


_FUND_CHANNELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("统筹基金支付", ("TCZHF", "统筹基金支付", "统筹支付")),
    ("大额支付", ("T_BigPay", "DEGWYZHF", "大额支付", "大额互助支付")),
    ("退休补助", ("T_BCPay", "BCZHF", "退休补充保险补助", "退休补助")),
    ("军残补助", ("T_JCPay", "JCZHF", "军残支付", "军残补助")),
    ("公疗补助", ("T_OfficalPay", "GFYLBCHBX", "公疗补充支付", "公疗补助")),
    ("退役医疗费支付", ("RETIRE_OFFICER_PAY", "退役医疗费支付")),
    ("大病保险支付", ("T_BigillPay", "BIG_ILL_PAY", "大病保险支付")),
    ("民政救助支付", ("NT_CivilPay", "CIVIL_IN", "民政救助支付")),
)


def _field_amount(public: FeeDecompositionPublic, codes: tuple[str, ...]) -> str | None:
    observed = {field.field_code: field.observed_amount for field in public.fields}
    facts = {item.label: item.value for item in public.settlement_facts.items} if public.settlement_facts else {}
    for key in codes:
        if observed.get(key) is not None:
            return str(observed[key])
    for key in codes:
        if facts.get(key) is not None:
            return str(facts[key])
    return None


def _dec(value: str | None) -> Decimal | None:
    try:
        number = Decimal(value) if value is not None else None
        return number if number is not None and number.is_finite() else None
    except InvalidOperation:
        return None


def _percent(value: Decimal) -> str:
    """比例百分数：数值等价、不截断有效精度（0.0005→0.05，1/3 不压成 33.33）。"""
    return _num_text(value * 100) or "0"


def _num_text(value: Decimal | None) -> str | None:
    """非金额数值（数量/单价/限价/比例）：保留有效精度，仅去尾零，不做舍入。"""
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return text


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    raw = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return str(Decimal("0.00") if raw == 0 else raw)


def _apply_alternatives(
    pair: tuple[str, str],
    present: list[AmountLine],
    not_applicable: list[str],
    missing: list[str],
) -> tuple[list[str], list[str]]:
    """同一待遇阶段的两条链路（统筹/大额）：一条有数时，另一条算本链不适用而不是缺数。"""
    labels = {line.label for line in present}
    for name in pair:
        if name in missing and any(other in labels for other in pair if other != name):
            missing = [item for item in missing if item != name]
            if name not in not_applicable:
                not_applicable.append(name)
    return not_applicable, missing


def _channel_gaps(
    public: FeeDecompositionPublic, channels: tuple[tuple[str, tuple[str, ...]], ...]
) -> tuple[list[str], list[str], list[str]]:
    """区分本链不适用 / 投影漏映射 / 源数据缺失，避免把三者都说成"未返回"。"""
    observed = {field.field_code: field for field in public.fields}
    facts = {item.label: item for item in public.settlement_facts.items} if public.settlement_facts else {}
    not_applicable: list[str] = []
    unmapped: list[str] = []
    missing: list[str] = []
    for label, codes in channels:
        field = next((observed.get(code) for code in codes if code in observed), None)
        if field is None:
            fact = next((facts.get(code) for code in codes if code in facts), None)
            if fact is not None and fact.value is not None:
                unmapped.append(label)
            else:
                missing.append(label)
            continue
        if field.check_status == "not_applicable":
            not_applicable.append(label)
        elif field.observed_amount is None:
            missing.append(label)
    return not_applicable, unmapped, missing


def build_payment_reconciliation(public: FeeDecompositionPublic) -> PaymentReconciliation:
    """基金合计与个人支付的确定性勾稽：差额只标记"未归属"，不推断补助类型。"""
    channels = [(label, _dec(_field_amount(public, codes))) for label, codes in _FUND_CHANNELS]
    present = [AmountLine(label=label, amount=_text(value) or "0.00") for label, value in channels if value is not None]
    itemized = sum((value for _, value in channels if value is not None), Decimal("0")) if present else None
    book_fund = _dec(_field_amount(public, ("T_FundPay", "基金合计")))
    # 三种情况分开表达：本链不适用 / 投影漏映射 / 源数据缺失。
    not_applicable, unmapped, missing_channels = _channel_gaps(public, _FUND_CHANNELS)
    # 统筹/大额是同一待遇阶段的两条链路：一条有数时另一条属于本链不适用，不是缺数。
    not_applicable, missing_channels = _apply_alternatives(
        ("统筹基金支付", "大额支付"), present, not_applicable, missing_channels)
    fund_gap = book_fund - itemized if book_fund is not None and itemized is not None and not missing_channels else None

    components: list[AmountLine] = []
    missing_components: list[str] = []
    for label, codes, sign in (("起付金额", ("T_FirstPay", "YBNQFJE", "本次起付承担", "起付金额"), 1),
                               ("医保范围外金额", ("T_FeeOut", "YBW", "医保范围外金额"), 1),
                               ("统筹自付", ("TCZIF", "统筹自付"), 1),
                               ("大额个人自付", ("T_BigSelfPay", "DEGWYZIF", "大额个人自付", "大额自付"), 1),
                               ("退休补助", ("T_BCPay", "BCZHF", "退休补充保险补助", "退休补助"), -1),
                               ("军残补助", ("T_JCPay", "JCZHF", "军残支付", "军残补助"), -1),
                               ("退役医疗费支付", ("RETIRE_OFFICER_PAY", "退役医疗费支付"), -1),
                               ("公疗补助", ("T_OfficalPay", "GFYLBCHBX", "公疗补充支付", "公疗补助"), -1)):
        value = _dec(_field_amount(public, codes))
        if value is not None:
            components.append(AmountLine(label=label, amount=_text(value * sign) or "0.00"))
        else:
            missing_components.append(label)
    not_applicable, missing_components = _apply_alternatives(
        ("统筹自付", "大额个人自付"), components, not_applicable, missing_components)
    identity = sum((_dec(line.amount) or Decimal("0") for line in components), Decimal("0")) if components and not missing_components else None
    book_personal = _dec(_field_amount(public, ("T_SelfPayAll", "PERSON_PAYABLE", "个人支付总金额")))
    personal_gap = identity - book_personal if identity is not None and book_personal is not None else None

    notes: list[str] = []
    if not_applicable:
        notes.append("本链不适用：" + "、".join(not_applicable) + "（该渠道在本险种/医疗类别下未发生，不是缺数）。")
    if unmapped:
        notes.append("投影未映射：" + "、".join(unmapped) + "（原单有该渠道记录但未进入金额投影）。")
    if missing_channels:
        notes.append("源数据缺失：" + "、".join(missing_channels) + "（原单未返回该渠道金额），已列示小计不代表完整基金构成，不计算未归属差额。")
    if missing_components:
        notes.append("个人支付构成缺少源数据：" + "、".join(missing_components) + "；不按零处理，不计算构成合计与差额。")
    retire_pay = _dec(_field_amount(public, ("RETIRE_OFFICER_PAY", "退役医疗费支付")))
    if retire_pay is not None and retire_pay != 0:
        notes.append(f"退役医疗费支付 {_text(retire_pay)} 元按原单记录列入基金支付构成、从个人负担中扣除；本项资格、比例与待遇公式未推导。")
    if fund_gap is not None and fund_gap != 0:
        notes.append(f"基金合计 {_text(book_fund)} 元中已列示基金渠道合计 {_text(itemized)} 元，尚差 {_text(fund_gap)} 元无对应分项；分解未提供该项名称与计算路径，不得归为任何补助。")
    if personal_gap is not None and personal_gap != 0:
        notes.append(f"按起付＋医保范围外＋大额个人自付－补助合计 {_text(identity)} 元，与原单个人支付 {_text(book_personal)} 元相差 {_text(personal_gap)} 元。")
    return PaymentReconciliation(
        book_fund_total=_text(book_fund), fund_channels=present, itemized_fund_total=_text(itemized),
        fund_gap=_text(fund_gap), book_personal_total=_text(book_personal), personal_components=components,
        identity_personal_total=_text(identity), personal_gap=_text(personal_gap),
        note="；".join(notes) or None)


def build_self_pay_2_breakdown(public: FeeDecompositionPublic) -> SelfPay2Breakdown:
    """自付二逐项构成：项目、作用基数、采用比例、金额；全自费项目不计入。"""
    lines: list[SelfPay2Line] = []
    full_out: list[AmountLine] = []
    zero = 0
    for item in public.fee_items:
        if item.explainable is False:
            continue
        amount = _dec(item.observed_self_pay_2)
        if item.division_method == "full_out":
            full_out.append(AmountLine(label=item.item_name or item.item_code, amount=_text(_dec(item.total_fee)) or ""))
            continue
        ratio = _dec(item.self_pay_ratio)
        if amount is not None and amount != 0:
            percent = _percent(ratio) if ratio is not None else None
            lines.append(SelfPay2Line(item_name=item.item_name or item.item_code,
                                      basis=_text(_dec(item.total_fee)) or "",
                                      ratio=f"{percent}%" if percent is not None else None,
                                      amount=_text(amount) or ""))
        elif item.division_method != "full_out":
            zero += 1
    total = _dec(_field_amount(public, ("T_SelfPay2", "GRZIFTW", "自付二", "先行自付")))
    note_parts: list[str] = []
    if zero:
        note_parts.append(f"其余 {zero} 个项目自付二为 0")
    if full_out:
        note_parts.append("、".join(f"{line.label} {line.amount} 元" for line in full_out) + "属于全自费，不计入自付二")
    return SelfPay2Breakdown(total=_text(total), lines=lines, zero_item_count=zero,
                             full_out_items=full_out, note="；".join(note_parts) or None)


def _quantity_text(value: str | None) -> str | None:
    """数量保留原始有效精度（0.125 不能变 0.13）。"""
    return _num_text(_dec(value))


def _line_sentence(item, display_no: int) -> str:
    """单行确定性表述：费用构成＋本行已执行的拆分路径；不可解释行只给原单事实。"""
    name = item.item_name or item.item_code or "未命名项目"
    parts = [f"第 {display_no} 行{name}"]
    fee = _text(_dec(item.total_fee))
    fee_value = _dec(item.total_fee)
    # 单价/限价是公式输入，可能超过两位小数：保留精度（金额两位规则只用于金额）
    price = _num_text(_dec(item.unit_price))
    quantity = _quantity_text(item.quantity)
    product = (_dec(item.unit_price) * _dec(item.quantity)
               if _dec(item.unit_price) is not None and _dec(item.quantity) is not None else None)
    # 三个值同时存在不等于存在等式：只有本行已核对且乘积与账面费用一致时才写“＝”（F2）
    equation_ok = (bool(item.explainable) and fee_value is not None
                   and product is not None and product == fee_value)
    if equation_ok:
        parts.append(f"本行费用 {fee} 元＝单价 {price} 元×数量 {quantity}")
    elif fee is not None and price is not None and quantity is not None:
        # 缺核对依据/乘积不符：并列展示原单事实，不声明恒等
        parts.append(f"本行费用 {fee} 元；原单单价 {price} 元、数量 {quantity}")
    elif fee is not None:
        parts.append(f"本行费用 {fee} 元")
    inside = _text(_dec(item.observed_in_scope))
    outside = _text(_dec(item.observed_out_scope))
    sp2 = _text(_dec(item.observed_self_pay_2))
    if not item.explainable:
        # 只给事实不给原因：账面金额按原单记录，计算候选不进入表述。
        facts = [text for text in (
            f"医保范围内 {inside} 元" if inside is not None else None,
            f"医保范围外 {outside} 元" if outside is not None else None,
            f"先行自付 {sp2} 元" if sp2 is not None else None) if text]
        if facts:
            parts.append("按原单记录：" + "、".join(facts))
        if item.explanation_reason:
            parts.append(item.explanation_reason)
        return "；".join(parts) + "。"
    if item.division_method == "limit" and _dec(item.unit_price_limit) is not None and inside is not None:
        limit = _num_text(_dec(item.unit_price_limit))
        source = item.limit_source or "本行结算时限价"
        segment = f"本笔结算采用限价 {limit} 元（{source}），{inside} 元进入医保范围内"
        if outside is not None and _dec(outside) > 0:
            segment += (f"，超出 {outside} 元进入医保范围外并计入先行自付，"
                        f"该 {outside} 元已包含在医保外金额中不重复相加")
        parts.append(segment)
    elif item.division_method == "ratio" and inside is not None and outside is not None:
        segment = f"{inside} 元进入医保范围内，{outside} 元进入医保范围外"
        if sp2 is not None and _dec(sp2) > 0:
            ratio_note = f"（{item.ratio_source}）" if item.ratio_source else ""
            segment += f"，其中先行自付 {sp2} 元{ratio_note}已包含在医保外金额中不重复相加"
        parts.append(segment)
    elif item.division_method == "full_in" and fee is not None:
        parts.append(f"本行全部纳入医保范围内：医保范围内 {fee} 元、医保范围外 0 元")
    elif item.division_method == "full_out" and fee is not None:
        parts.append(f"本行全部由个人承担：医保范围内 0 元、医保范围外 {fee} 元")
    if inside is not None and _dec(inside) > 0:
        parts.append("医保范围内金额还需按本单待遇规则计算基金与个人分担，不等于基金实际报销金额")
    return "；".join(parts) + "。"


def build_line_target_evidence(public: FeeDecompositionPublic, target: QuestionTarget) -> LineTargetEvidence:
    """目标行的确定性证据：本行金额（observed 与 calculated）、判定路径、公式与来源。

    共享证据装载入口：explainable=False 的行只交付原单事实与缺口，
    候选判定路径/公式/限价/比例/备注一律不进入可信正文（R3）。
    """
    item = public.fee_items[target.display_no - 1]
    if not item.explainable:
        item = item.model_copy(update=dict(
            calculated_in_scope=None, calculated_out_scope=None,
            calculated_self_pay_2=None, calculated_proportional_self_pay=None,
            self_pay_ratio=None, included_ratio=None, unit_price_limit=None,
            conditions=[], formulas=[], notes=[], ratio_source=None,
            ratio_basis=None, limit_source=None, decision_path=[],
            calculation_refs=[], reconciliations=[]))
    return LineTargetEvidence(
        display_no=target.display_no, line_id=item.line_id,
        item_name=item.item_name, item_code=item.item_code,
        unit_price=item.unit_price, quantity=item.quantity, total_fee=item.total_fee,
        observed_in_scope=item.observed_in_scope,
        observed_out_scope=item.observed_out_scope,
        observed_self_pay_2=item.observed_self_pay_2,
        calculated_in_scope=item.calculated_in_scope,
        calculated_out_scope=item.calculated_out_scope,
        calculated_self_pay_2=item.calculated_self_pay_2,
        division_method=item.division_method,
        unit_price_limit=item.unit_price_limit, self_pay_ratio=item.self_pay_ratio,
        limit_source=item.limit_source, ratio_source=item.ratio_source,
        decision_path=list(item.decision_path), formulas=list(item.formulas),
        notes=list(item.notes), explainable=item.explainable,
        explanation_reason=item.explanation_reason, attributes=list(target.attributes),
        sentence=_line_sentence(item, target.display_no))


def _build_lines_model_input(
    public: FeeDecompositionPublic, question: str, refs: list[LineRef]
) -> FeeExplanationInput:
    """单行/多行问题共用：证据载荷只带目标行及其实际依赖；整单基金渠道与其他行不进 payload。

    逐行证据各自独立（line_evidences），金额互不作证；单行时同时填 line_evidence
    保持既有消费方兼容。
    """
    # 未取得独立计算依据的明细仍提供原单事实，候选金额及原因不进入证据（与整单口径一致）。
    items = []
    for ref in refs:
        located = public.fee_items[ref.display_no - 1]
        items.append(located if located.explainable else located.model_copy(update=dict(
            calculated_in_scope=None, calculated_out_scope=None, calculated_self_pay_2=None,
            calculated_proportional_self_pay=None, self_pay_ratio=None, included_ratio=None,
            unit_price_limit=None, conditions=[], formulas=[], notes=[], ratio_source=None,
            ratio_basis=None, limit_source=None, decision_path=[], calculation_refs=[],
            reconciliations=[], explanation_reason=None)))
    calc_seed = {ref_id for item in items for ref_id in item.calculation_refs} | {
        ref for item in items for decision in item.decision_path for ref in decision.calculation_refs}
    # 沿操作数向上闭包：目标行公式由哪些上游计算得出，正文需要完整链条。
    by_id = {calc.calculation_id: calc for calc in public.calculations}
    closure: set[str] = set()
    pending = list(calc_seed)
    while pending:
        cid = pending.pop()
        if cid in closure or cid not in by_id:
            continue
        closure.add(cid)
        pending.extend(op.calculation_ref for op in by_id[cid].operands if op.calculation_ref)
    calculations = [calc for calc in public.calculations
                    if calc.explainable and calc.calculation_id in closure]
    ids = {calc.calculation_id for calc in calculations}
    inputs = {op.input_ref for calc in calculations for op in calc.operands}
    groups = [group for group in public.rule_choices
              if group.calculation_refs and ids.intersection(group.calculation_refs)]
    inputs.update(ref for group in groups for ref in group.input_refs)
    steps = [step for step in public.path_steps if ids.intersection(step.calculation_refs)]
    condition_ids = {ref for step in steps for ref in step.condition_refs}
    # 来源只保留目标行实际执行分支（decision_path 的 rule_refs）。
    rule_refs = {ref for item in items for decision in item.decision_path for ref in decision.rule_refs}
    source_ids = rule_refs | {f"rule.{ref}" for ref in rule_refs}
    data = public.model_copy(update=dict(
        summary_text='', fields=[], calculations=calculations, fee_items=items,
        sources=[source for source in public.sources if source.ref_id in source_ids],
        formula_inputs=[node for node in public.formula_inputs if node.input_id in inputs],
        rule_choices=groups,
        conditions=[condition for condition in public.conditions
                    if condition.step_id in condition_ids
                    or ids.intersection(condition.calculation_refs)],
        path_steps=steps))
    # 收费边界问题只留被点名的费用行。整单汇总金额和退休补充缺证留在资料里时，
    # 模型会先讲内涵，再被要求补全其余目标金额，并把缺证写进「尚待核实」。
    if _is_billing_boundary_question(question):
        data = _drop_bill_summary(data)
    evidences = [build_line_target_evidence(public, QuestionTarget(
        kind="fee_line", line_id=ref.line_id, display_no=ref.display_no,
        attributes=ref.attributes)) for ref in refs]
    # 整单口径块不默认进入行问题。
    return FeeExplanationInput(question=question, decomposition=data,
        actual_payment_shares=[], payment_reconciliation=PaymentReconciliation(),
        self_pay_2_breakdown=SelfPay2Breakdown(), target_evidence=[],
        line_evidence=evidences[0] if len(evidences) == 1 else None,
        line_evidences=[] if len(evidences) == 1 else evidences,
        target_kind="fee_line" if len(evidences) == 1 else "multi_line",
        unexplained_fields=[],
        billing_boundaries=build_billing_boundary_payload(
            public.fee_items, {ref.display_no for ref in refs}),
        billed_items=[BilledItemFact(display_no=index + 1,
            item_name=item.item_name or item.item_code, item_type=item.item_type)
            for index, item in enumerate(public.fee_items)]
        if any(item.payment_condition_context and item.payment_condition_context.bz for item in items) else [])


def _build_line_model_input(
    public: FeeDecompositionPublic, question: str, target: QuestionTarget
) -> FeeExplanationInput:
    """单行问题：收敛到目标行（委托多行共用实现）。"""
    return _build_lines_model_input(public, question, [LineRef(
        line_id=target.line_id or "", display_no=target.display_no or 0,
        attributes=target.attributes)])


#: 字段对比的口径关系固定说明（按别名组的语义键登记；未登记的组合回退各字段含义拼接）。
_COMPARISON_RELATIONS: dict[frozenset[str], str] = {
    frozenset({"自付一", "自付二"}): (
        "两者同属个人负担口径的并列分量：自付一按待遇政策对医保范围内费用计算，"
        "自付二是部分项目按规定比例先行自付；自付二已包含在医保范围外金额中，两者不重复相加。"),
    frozenset({"账户", "现金"}): (
        "两者是个人支付总金额的支付渠道拆分，是同一笔钱的支付方式，不重复相加。"),
    frozenset({"医保内", "医保外"}): (
        "医保内费用与医保外费用按医保目录范围划分，共同构成总费用，互不重叠。"),
}


def _semantic_key_of(field_code: str) -> str | None:
    for keywords, codes in _TARGET_ALIASES:
        if field_code in codes:
            return keywords[0]
    return None


def _comparison_note(public: FeeDecompositionPublic, codes: list[str]) -> str | None:
    """对比题的确定性关系说明：已登记字段对用固定口径关系，否则拼接各字段含义。"""
    fields = [field for field in public.fields if field.field_code in codes]
    if len(fields) < 2:
        return None
    keys = {key for key in (_semantic_key_of(field.field_code) for field in fields) if key}
    relation = _COMPARISON_RELATIONS.get(frozenset(keys)) if len(keys) == len(fields) else None
    if relation is not None:
        return relation
    meanings = [field.explanation.meaning for field in fields
                if field.explanation is not None and field.explanation.meaning]
    return "；".join(meanings) or None


def _boundary_display_nos(boundaries: BillingBoundaryPayload) -> set[int]:
    numbers = {line.display_no for line in boundaries.line_explanations}
    for source in boundaries.source_explanations:
        numbers.add(source.display_no)
        for match in source.matches:
            numbers.update(target.display_no for target in match.targets)
    return numbers


def _drop_bill_summary(public: FeeDecompositionPublic) -> FeeDecompositionPublic:
    """去掉整单汇总金额、模板说明和内部缺证，避免进入收费边界问题的模型资料。"""
    return public.model_copy(update=dict(
        summary_text="", settlement_facts=None, uncertainties=[],
        template_explanations={}, stages=[], trace=None, coverage=None))


def _billing_boundary_only_input(
    public: FeeDecompositionPublic, question: str, boundaries: BillingBoundaryPayload,
) -> FeeExplanationInput:
    """内涵或单独收费问题：只装载收费边界和被解释的费用行，不装载整单汇总金额。"""
    mentioned = _boundary_display_nos(boundaries)
    items = [item for index, item in enumerate(public.fee_items) if index + 1 in mentioned]
    data = _drop_bill_summary(public.model_copy(update=dict(
        fields=[], calculations=[], fee_items=items,
        sources=[], formula_inputs=[], rule_choices=[], conditions=[],
        path_steps=[])))
    return FeeExplanationInput(
        question=question, decomposition=data, target_evidence=[],
        target_kind="billing_boundary", billing_boundaries=boundaries)


def build_model_input(
    public: FeeDecompositionPublic, question: str,
    question_target: QuestionTarget | None = None,
) -> FeeExplanationInput:
    # 先确定问题目标；行问题收敛到目标行（Issue #78 明细行目标；阶段 D 支持多行）。
    question_target = question_target or resolve_question_target(public, question)
    if question_target.kind == "fee_line":
        return _build_line_model_input(public, question, question_target)
    if question_target.kind == "multi_line":
        return _build_lines_model_input(public, question, question_target.lines)
    if question_target.kind == "mixed":
        # 混合目标：汇总字段按 summary_fields 口径收敛，行证据独立装载（评审问题 2）
        field_payload = build_model_input(public, question, QuestionTarget(
            kind="summary_fields", field_codes=list(question_target.field_codes)))
        line_evidences = [build_line_target_evidence(public, QuestionTarget(
            kind="fee_line", line_id=ref.line_id, display_no=ref.display_no,
            attributes=ref.attributes)) for ref in question_target.lines]
        return field_payload.model_copy(update=dict(
            line_evidences=line_evidences, target_kind="mixed",
            billing_boundaries=build_billing_boundary_payload(
                public.fee_items, {ref.display_no for ref in question_target.lines})))
    # 没点名行、也没点名汇总字段，只问内涵或单独收费：不把整单金额当目标。
    if question_target.kind == "whole_settlement" and _is_billing_boundary_question(question):
        boundaries = build_billing_boundary_payload(public.fee_items, None)
        if boundaries is not None:
            return _billing_boundary_only_input(public, question, boundaries)
    # 再确定目标字段，只提供该字段需要的证据（Issue #83 第 3 项）；对比题同样按字段收敛。
    targets = question_target.field_codes if question_target.kind in ("summary_fields", "comparison") else []
    source_ids: set[str] | None = None
    if targets:
        fields = [field for field in public.fields
                  if field.field_code in targets and "." not in field.field_code]
        # 与字段证据共用资格：未核对字段的候选公式不能从 JSON 旁路进入模型。
        approved = build_target_evidence(public, targets)
        approved_formulas = {item.formula for item in approved if item.formula}
        referenced = {ref for field in fields for ref in field.calculation_refs}
        calc_ids = {ref for field in fields if field.explainable for ref in field.calculation_refs}
        calc_ids.update(calc.calculation_id for calc in public.calculations
                        if calc.calculation_id in referenced
                        and _trim_trailing_zeros(calc.formula) in approved_formulas)
        # 沿操作数向上闭包：目标公式由哪些上游计算得出，正文需要完整链条。
        closure: set[str] = set()
        pending = list(calc_ids)
        by_id = {calc.calculation_id: calc for calc in public.calculations}
        while pending:
            cid = pending.pop()
            if cid in closure or cid not in by_id:
                continue
            closure.add(cid)
            pending.extend(op.calculation_ref for op in by_id[cid].operands if op.calculation_ref)
        calculations = [calc for calc in public.calculations if calc.explainable and calc.calculation_id in closure]
        source_ids = {ref for field in fields for ref in field.source_refs}
    else:
        calculations = [calc for calc in public.calculations if calc.explainable]
        fields = [field for field in public.fields
                  if field.explainable and "." not in field.field_code]
    ids = {calc.calculation_id for calc in calculations}
    field_ids = {field.field_code for field in fields}
    inputs = {op.input_ref for calc in calculations for op in calc.operands}
    inputs.update(input_id(ref) for field in fields for ref in field.source_refs)
    groups = [group for group in public.rule_choices if ids.intersection(group.calculation_refs) or field_ids.intersection(group.field_refs)]
    inputs.update(ref for group in groups for ref in group.input_refs)
    steps = [step for step in public.path_steps if ids.intersection(step.calculation_refs) or field_ids.intersection(step.field_refs)]
    condition_ids = {ref for step in steps for ref in step.condition_refs}
    # 未取得独立计算依据的明细仍提供原单事实，候选金额及原因不进入证据。
    # 明细始终保留：总额/个人支付要能逐笔展开（每行费用如何进入医保内外与自付），
    # 不能因为识别到目标字段就把“为什么每笔这么多”的证据删掉。
    fee_items_source = public.fee_items
    fee_items = [item if item.explainable else item.model_copy(update=dict(
        calculated_in_scope=None, calculated_out_scope=None, calculated_self_pay_2=None,
        calculated_proportional_self_pay=None, self_pay_ratio=None, included_ratio=None,
        unit_price_limit=None, conditions=[], formulas=[], notes=[], ratio_source=None,
        ratio_basis=None, limit_source=None, decision_path=[], calculation_refs=[],
        reconciliations=[], explanation_reason=None)) for item in fee_items_source]
    # 目标题只带本单采用的档位；已排除档位留待比较题再加载（Issue #83 第 3 项）。
    if targets:
        groups = [group.model_copy(update={"candidates": [
            row for row in group.candidates if row.status in ("selected", "eligible")
        ]}) if group.candidates else group for group in groups]
    data = public.model_copy(update=dict(summary_text='', fields=fields, calculations=calculations,
        fee_items=fee_items,
        sources=[source for source in public.sources if source_ids is None or source.ref_id in source_ids],
        formula_inputs=[node for node in public.formula_inputs if node.input_id in inputs], rule_choices=groups,
        conditions=[condition for condition in public.conditions if condition.step_id in condition_ids or ids.intersection(condition.calculation_refs)],
        path_steps=steps))
    shares = []
    total = next((field.observed_amount for field in public.fields if field.field_code in ('T_FeeAll', 'ZJE')), None)
    if total is not None and Decimal(total) > 0:
        for field in public.fields:
            if field.field_code in ('T_FundPay', 'T_SelfPayAll', 'PERSON_PAYABLE') and field.observed_amount is not None:
                percent = (Decimal(field.observed_amount) * 100 / Decimal(total)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                shares.append(PaymentShare(label=field.label, amount=field.observed_amount, total_fee=total, share_percent=str(percent)))
    # 整单问题也装载全字段固定说明（阶段 B），未点名字段按同一份固定说明列示
    if targets:
        evidence_codes = targets
    elif question_target.kind == "cover_all" and question_target.field_codes:
        # 全覆盖集合：可见模板字段（含 bill.*）∪ 主字段（评审问题 2/8）
        evidence_codes = question_target.field_codes
    else:
        evidence_codes = _whole_field_codes(public)
    target_evidence = build_target_evidence(public, evidence_codes)
    return FeeExplanationInput(question=question, decomposition=data, actual_payment_shares=shares,
        payment_reconciliation=build_payment_reconciliation(public),
        self_pay_2_breakdown=build_self_pay_2_breakdown(public),
        target_evidence=target_evidence,
        # 全覆盖意图：逐行证据全量装载（不可解释行只给事实，口径同行问题清理逻辑）
        line_evidences=[build_line_target_evidence(public, QuestionTarget(
            kind="fee_line", line_id=item.line_id, display_no=index + 1))
            for index, item in enumerate(public.fee_items)]
        if question_target.kind == "cover_all" else [],
        target_kind=question_target.kind,
        # 对比题：后端按字段固定说明+口径差异组装关系说明，直接进入正文
        comparison_note=_comparison_note(public, targets)
        if question_target.kind == "comparison" else None,
        unexplained_fields=_unexplained_fields(public),
        # 收费边界（Issue #85）：整单/全覆盖装载全量；字段题/对比题与费用行无关，不装载。
        billing_boundaries=None if question_target.kind in ("summary_fields", "comparison")
        else build_billing_boundary_payload(public.fee_items, None),
        # 被点名但未产出证据的目标逐项列缺口（bill.* 等未绑定字段不借用其他字段的成功）
        target_gaps=_missing_target_gaps(public, evidence_codes, target_evidence)
        if targets or question_target.kind == "cover_all" else [])


def _selected_candidate_excerpt(group, candidate) -> str | None:
    """本单实际采用候选档的来源摘录；非采用档或无量纲值不进入。"""
    if candidate.status != "selected" or not candidate.value:
        return None
    unit = candidate.unit.strip()
    if not unit.startswith(("%", "％", "元")):
        return None
    checks = [
        f"{check.name}：{check.actual}（要求{check.expected}）"
        for check in candidate.checks
        if check.outcome == "met" and check.actual
    ]
    shown = candidate.value
    if unit.startswith("元"):
        try:
            shown = str(Decimal(candidate.value).quantize(Decimal("0.01")))
        except Exception:
            shown = candidate.value
    title = re.sub(r"\s*·\s*(不适用|已采用|未采用|待核实|未确认)\s*$", "", group.title)
    parts = [f"本次采用：{title} · {candidate.name} {shown}{unit}"]
    if checks:
        parts.append("适用条件：" + "；".join(checks))
    if candidate.effective_from:
        parts.append(f"生效日期：{candidate.effective_from}")
    if candidate.effective_to:
        parts.append(f"截止日期：{candidate.effective_to}")
    if candidate.version:
        parts.append(f"版本：{candidate.version}")
    if candidate.confirmation_status:
        parts.append(f"确认状态：{candidate.confirmation_status}")
    return "；".join(parts)


def selected_ratio_policy_evidence(
    public: FeeDecompositionPublic, target_fields: list[str] | None = None
) -> list[tuple[str, str]]:
    """仅返回与目标字段相关、且本单实际采用的比例档或执行分支来源。

    提供 target_fields 时按计算引用关联该字段（不再按标题是否含"比例"筛选），
    使引用与问题指向同一份证据（Issue #83 第 3 项）。
    """
    calc_ids: set[str] = set()
    if target_fields:
        calc_ids = {ref for field in public.fields if field.field_code in target_fields for ref in field.calculation_refs}
    grouped: dict[str, list[str]] = {}
    for group in public.rule_choices:
        if target_fields and not (group.calculation_refs and calc_ids.intersection(group.calculation_refs)):
            continue
        for candidate in group.candidates:
            excerpt = _selected_candidate_excerpt(group, candidate)
            if excerpt is not None:
                grouped.setdefault(candidate.source or candidate.name, []).append(excerpt)
    source_ids = {
        ref for field in public.fields
        if not target_fields or field.field_code in target_fields
        for ref in field.source_refs
    }
    for source in public.sources:
        if source.ref_id not in source_ids or source.category != "policy_basis":
            continue
        parts = ["本单实际计算分支引用"]
        if source.values:
            parts.append("版本：" + "、".join(source.values))
        if source.confirmation_status:
            parts.append(f"确认状态：{source.confirmation_status}")
        grouped.setdefault(source.title, []).append("；".join(parts))
    return [(source, "；".join(dict.fromkeys(excerpts))) for source, excerpts in grouped.items()]


def selected_line_policy_evidence(
    public: FeeDecompositionPublic, target: QuestionTarget
) -> list[tuple[str, str]]:
    """单行问题的来源：本行实际执行的限价/比例路径（decision_path 的 rule_refs、
    limit_source、ratio_source），不默认附整单全部待遇比例。"""
    if target.display_no is None or not 1 <= target.display_no <= len(public.fee_items):
        return []
    item = public.fee_items[target.display_no - 1]
    grouped: dict[str, list[str]] = {}
    rule_refs = {ref for decision in item.decision_path for ref in decision.rule_refs}
    wanted = rule_refs | {f"rule.{ref}" for ref in rule_refs}
    for source in public.sources:
        if source.ref_id not in wanted:
            continue
        parts = ["本行实际执行分支引用"]
        if source.values:
            parts.append("版本：" + "、".join(source.values))
        if source.confirmation_status:
            parts.append(f"确认状态：{source.confirmation_status}")
        grouped.setdefault(source.title, []).append("；".join(parts))
    calc_ids = set(item.calculation_refs) | {
        ref for decision in item.decision_path for ref in decision.calculation_refs}
    for group in public.rule_choices:
        if not (group.calculation_refs and calc_ids.intersection(group.calculation_refs)):
            continue
        for candidate in group.candidates:
            excerpt = _selected_candidate_excerpt(group, candidate)
            if excerpt is not None:
                grouped.setdefault(candidate.source or candidate.name, []).append(excerpt)
    if item.limit_source and _dec(item.unit_price_limit) is not None:
        grouped.setdefault(item.limit_source, []).append(
            f"本行实际执行：单价 {_fmt_amount(item.unit_price)} 元，"
            f"采用限价 {_fmt_amount(item.unit_price_limit)} 元")
    if item.ratio_source and _dec(item.self_pay_ratio) is not None:
        grouped.setdefault(item.ratio_source, []).append(
            f"本行实际执行：采用自付比例 {_percent(_dec(item.self_pay_ratio))}%")
    return [(source, "；".join(dict.fromkeys(excerpts))) for source, excerpts in grouped.items()]


#: 可以合法按“明细行金额”引用的口语标签（总额仍按字段值校验）。
_LINE_LEVEL_AMOUNTS = {
    "医保内": "observed_in_scope",
    "医保范围内": "observed_in_scope",
    "医保外": "observed_out_scope",
    "医保范围外": "observed_out_scope",
    "自付二": "observed_self_pay_2",
    "先行自付": "observed_self_pay_2",
    "总费用": "total_fee",
    "费用总金额": "total_fee",
}


def _unexplained_fields(public: FeeDecompositionPublic) -> list[str]:
    """不能解释的字段名：派生审计行（含“.”）与主字段的明细汇总行不重复列出。"""
    main = {field.field_code.split(".")[0] for field in public.fields if field.explainable}
    labels: list[str] = []
    for field in public.fields:
        if field.explainable or field.check_type == "identity_check" or field.check_status == "not_applicable":
            continue
        if "." in field.field_code:
            continue
        if field.field_code in main:
            continue
        if "（明细账面汇总" in field.label:
            continue
        labels.append(field.label)
    return list(dict.fromkeys(labels))


def _target_evidence_text(evidence: TargetEvidence) -> str | None:
    """单目标正文块：金额先行，再按“说明/金额构成/适用比例/依据”分组，仍是一行一目标。

    分组只改变同一证据的呈现顺序与连接词，不新增、不改写任何金额/算式/比例；
    固定说明与已渲染公式去重，确认状态只留在来源说明里，不进正文。
    """
    lead = (f"{evidence.field_label} {evidence.amount} 元"
            if evidence.amount is not None else evidence.field_label)
    raw = evidence.sentence or ""
    rest = raw[len(lead):] if raw.startswith(lead) else raw
    segments = [part.strip().strip("。；;") for part in re.split(r"[；;]", rest)]
    segments = [part for part in segments if part]

    notes: list[str] = []
    formulas: list[str] = []
    ratios: list[str] = []

    def _add_formula(value: str | None) -> None:
        text = _trim_trailing_zeros(value) if value else None
        if not text:
            return
        # 同一算式可能只是带/不带“本次XX：”前缀，按包含关系去重。
        if not any(text in item or item in text for item in formulas):
            formulas.append(text)

    for part in segments:
        bare = part.rstrip("。")
        if bare.startswith(("采用「", "本次采用")):
            value = bare
            for prefix in ("本次采用：", "采用："):
                if value.startswith(prefix):
                    value = value[len(prefix):]
            if value.startswith("采用「") and value.endswith("」"):
                value = value[len("采用「"):-1]
            ratios.append(value.strip("。；;"))
        elif ("＝" in bare or "=" in bare or bare.startswith(("计算", "上游基数"))):
            _add_formula(bare)
        elif bare.startswith(("依据", "来源")):
            # 来源已在 citations / 来源对话框里，正文不再重复“依据：…”。
            continue
        else:
            if any(marker in bare for marker in _HIDDEN_ANSWER_MARKERS):
                continue
            notes.append(bare)

    _add_formula(evidence.formula)
    for ratio in evidence.ratios:
        if not any(ratio.chosen in item for item in ratios):
            ratios.append(ratio.chosen)

    sections: list[str] = []
    if notes:
        sections.append("说明：" + "；".join(dict.fromkeys(notes)))
    if formulas:
        sections.append("金额构成：" + "；".join(dict.fromkeys(formulas)))
    if ratios:
        sections.append("适用比例：" + "；".join(dict.fromkeys(ratios)))
    # 用“；”分隔：算式分段核验按“；”切句，项目符号“-”不会并入算式。
    return "；".join([lead, *sections]) + ("。" if sections else "") or None


def render_evidence_answer(payload: FeeExplanationInput) -> DeterministicAnswer | None:
    """离线及异常回退的证据正文；正常模型回答不受此处的固定排版约束。

    输入为解析后的目标与它的可信证据；只渲染目标实际依赖且允许解释的计算，
    未执行候选档不写成"采用"。账面事实、计算构成与不适用项目按字段固定说明区分；
    部分目标有缺口时逐项列明，不整题吞掉已有证据；无数据且无证据返回 None
    （调用方维持 unavailable）。
    """
    body_lines: list[str] = []
    if payload.target_kind == "comparison" and payload.comparison_note:
        body_lines.append(payload.comparison_note)
    line_evidences = ([payload.line_evidence] if payload.line_evidence is not None
                      else list(payload.line_evidences))
    field_lines = [
        text for text in (_target_evidence_text(item) for item in payload.target_evidence) if text]
    if line_evidences:
        if payload.target_kind in ("cover_all", "mixed"):
            # 全覆盖/混合目标 = 字段证据 + 行证据都交付，不允许只剩行证据。
            body_lines.extend(field_lines)
        for evidence in line_evidences:
            if evidence.sentence:
                body_lines.append(evidence.sentence)
            body_lines.extend(formula for formula in evidence.formulas if formula != evidence.sentence)
    else:
        body_lines.extend(field_lines)
    # 收费边界（Issue #85）：目录内涵对上同单费用行的句子，与金额证据并列交付；
    # 只做收费边界说明，不含符合性、违规或超收判断（构造侧已剔除）。
    if payload.billing_boundaries is not None:
        body_lines.extend(line.sentence for line in payload.billing_boundaries.line_explanations)
        for source in payload.billing_boundaries.source_explanations:
            body_lines.extend(source.sentences)
    if not body_lines and payload.target_kind in (None, "whole_settlement"):
        # 整单问法未识别到具体目标字段时，用本单已可解释的计算记录兜底（最多 6 条）。
        body_lines.extend(calc.formula for calc in payload.decomposition.calculations
                          if calc.explainable and calc.formula)
    gaps = [gap for gap in dict.fromkeys(payload.target_gaps)
            if not any(marker in gap for marker in _HIDDEN_ANSWER_MARKERS)]
    if not body_lines:
        if not gaps:
            return None
        return DeterministicAnswer(
            body="本单没有可交付的核对依据。\n以下目标暂未取得可核对依据：\n"
                 + chr(10).join(f"- {gap}" for gap in gaps),
            uncertainties=gaps, has_evidence=False)
    # 与目标关联的不确定性（边界/来源待核声明）是正文的一部分，不靠结尾通用声明补救。
    target_codes = {evidence.field_code for evidence in payload.target_evidence}
    qualifiers = [uncertainty.message for uncertainty in payload.decomposition.uncertainties
                  if target_codes.intersection(uncertainty.affected_fields)
                  and not any(marker in uncertainty.message for marker in _HIDDEN_ANSWER_MARKERS)]
    body_lines.extend(qualifiers)
    body = chr(10).join(f"- {line}" for line in dict.fromkeys(body_lines))
    if gaps:
        body += chr(10) + "以下目标暂未取得可核对依据：" + chr(10) + chr(10).join(
            f"- {gap}" for gap in gaps)
    return DeterministicAnswer(
        body=body, uncertainties=gaps + [q for q in qualifiers if q not in gaps], has_evidence=True)

#: 回答出口不得出现的内部字段名/物理列名：分解内部编码（T_/TA_/TB_ 前缀、
#: GRZIF1/BCZHF/TCZHF 等原单物理列）一律替换为中性表述，公开口径只用字段标签。
_INTERNAL_ANSWER_TOKENS = sorted(
    {code for _keywords, codes in _TARGET_ALIASES for code in codes
     if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", code)},
    key=len, reverse=True)
_INTERNAL_ANSWER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:T[AB]?_[A-Za-z0-9]+|[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)*|"
    + "|".join(re.escape(code) for code in _INTERNAL_ANSWER_TOKENS)
    + r")(?![A-Za-z0-9_])")


#: 业务规则/参数编号（ROP-RND-001、EOP-RND-001、ESP-RATE-101 等）是可公开口径，
#: 不能被“内部字段”消毒按连字符拆成“结算数据字段-结算数据字段-001”。
_PUBLIC_RULE_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]{1,})+(?![A-Za-z0-9_])")


def _public_safe_answer(text: str, protect_phrases: tuple[str, ...] = ()) -> str:
    """回答出口消毒：内部字段名/物理列名替换为中性表述（与路由层 _public_text 同口径）。

    业务规则编号先占位保护，其余内部编码再替换；回答正文与 uncertainties 共用本函数，
    避免同一事实两处写法不一致。protect_phrases 为原单项目名等原文短语：其中的
    全大写片段（抗HCV、ALT 测定等）是项目名称的一部分，不是内部编码，先占位保护。
    """
    source = text or ""
    protected: list[str] = []

    def placeholder(value: str) -> str:
        protected.append(value)
        # 占位符用小写字母，避免被只匹配大写内部编码的正则再次命中
        return f"ruleidkeep{len(protected) - 1}end"

    def protect(match: re.Match) -> str:
        return placeholder(match.group(0))

    masked = source
    for phrase in sorted(protect_phrases, key=len, reverse=True):
        if phrase:
            masked = masked.replace(phrase, placeholder(phrase))
    masked = _PUBLIC_RULE_ID_PATTERN.sub(protect, masked)
    masked = _INTERNAL_ANSWER_PATTERN.sub("结算数据字段", masked)
    for index, value in enumerate(protected):
        masked = masked.replace(f"ruleidkeep{index}end", value)
    return masked


def _item_name_protection(public: FeeDecompositionPublic) -> tuple[str, ...]:
    """原单项目名原文：消毒时整体保护，避免 ALT/抗HCV 等名称片段被误当内部编码。"""
    return tuple(dict.fromkeys(
        item.item_name for item in public.fee_items if item.item_name))


#: 回答正文不再展示的来源/取整/累计待签核类说明（保留在 citations 与结果审计里）。
#: 注意：不能把“取整”本身当隐藏词——取整式正是分桶/比例的推导过程；
#: 只去掉“取整规则…待确认”这类状态说明（由“待确认/签核”等词覆盖）。
_HIDDEN_ANSWER_MARKERS = ("显式采用", "跨院", "恒等式", "自证",
                          "签核", "依据来源", "采用依据", "依据待", "待确认",
                          "核证", "政策文件", "不默认已纳入")

#: 正常解释只有一份提示词；adjust 作为历史配置别名使用同一条生成链路。
_MODE_ENV = "FEE_EXPLANATION_MODE"
_PROMPT_PATH = Path(__file__).with_name("explanation_prompt.yaml")


def _load_prompt() -> tuple[str, str]:
    import yaml

    config = yaml.safe_load(_PROMPT_PATH.read_text(encoding="utf-8"))
    system, repair = config["system_prompt"], config["repair_prompt"]
    if not isinstance(system, str) or not system.strip() or not isinstance(repair, str) or not repair.strip():
        raise ValueError("费用解释提示词不能为空")
    return system, repair


def _mode() -> str:
    mode = os.getenv(_MODE_ENV, "structured").strip().lower()
    if mode not in ("structured", "adjust", "deterministic"):
        logger.warning("[FEE-EXPLANATION] invalid mode; using structured")
        return "structured"
    return mode


def _supported_numbers(value: Any) -> set[Decimal]:
    if isinstance(value, dict):
        return set().union(*(_supported_numbers(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_supported_numbers(item) for item in value))
    return _decimal_set(str(value)) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else set()


def _field_aliases(code: str, label: str) -> set[str]:
    names = {label}
    for keywords, codes in _TARGET_ALIASES:
        if code in codes:
            names.update(keywords)
    return names


def _target_issues(text: str, payload: FeeExplanationInput, public: FeeDecompositionPublic) -> list[str]:
    """只校验目标交付，不规定分段、句式或采用哪一种等价公式。"""
    aliases = {name for field in public.fields for name in _field_aliases(field.field_code, field.label)}
    aliases.update(item.field_label for item in payload.target_evidence)
    pattern = re.compile("|".join(re.escape(name) for name in sorted(aliases, key=len, reverse=True))) if aliases else None
    segments = re.split(r"[。；;\n]", text)
    issues: list[str] = []
    for evidence in payload.target_evidence:
        names = _field_aliases(evidence.field_code, evidence.field_label)
        matched = [segment for segment in segments if pattern is not None
                   and any(match.group() in names for match in pattern.finditer(segment))]
        if not matched or (evidence.amount is not None and not any(
                _dec(evidence.amount) in {_dec(value.replace(',', '')) for value in _NUMBER_TOKEN.findall(segment)}
                for segment in matched)):
            issues.append(f"未回答目标「{evidence.field_label}」及其本单金额。")
    lines = [payload.line_evidence] if payload.line_evidence is not None else payload.line_evidences
    for line in lines:
        if not ((line.item_name and line.item_name in text)
                or re.search(rf"第\s*{line.display_no}\s*行", text)):
            issues.append(f"遗漏第{line.display_no}行。")
    return issues


def _component_issues(text: str, payload: FeeExplanationInput) -> list[str]:
    """合计的直接计算分量不能遗漏；依据引用关系检查，不绑定业务字段或表达式写法。"""
    numbers = _decimal_set(text)
    formulas = {item.formula for item in payload.target_evidence if item.formula}
    missing: list[str] = []
    for calc in payload.decomposition.calculations:
        if _trim_trailing_zeros(calc.formula) not in formulas or calc.layout not in ("sum", "subtract_rest"):
            continue
        for operand in calc.operands:
            amount = _dec(operand.value)
            if operand.calculation_ref and amount is not None and abs(amount) not in numbers:
                missing.append(f"未交代合计分量「{operand.display_name}」的金额。")
    return list(dict.fromkeys(missing))


def _answer_issues(text: str, payload: FeeExplanationInput, public: FeeDecompositionPublic) -> list[str]:
    if not text:
        return ["回答为空。"]
    issues = []
    allowed = _supported_numbers(payload.model_dump(mode="json"))
    if not _decimal_set(text).issubset(allowed):
        unsupported = list(dict.fromkeys(raw for raw in _NUMBER_TOKEN.findall(text)
                                         if not _decimal_set(raw).issubset(allowed)))
        issues.append("出现资料之外的数字：" + "、".join(unsupported) + "。请只使用已提供的分量和合计。")
    if not _attribution_ok(text, _label_amounts(public)):
        issues.append("字段金额归属不符。")
    issues.extend(_target_issues(text, payload, public))
    issues.extend(_component_issues(text, payload))
    target_amounts = {name: amount for item in payload.target_evidence
                      if (amount := _dec(item.amount)) is not None
                      for name in _field_aliases(item.field_code, item.field_label)}
    issues.extend(equation_issues(text, target_amounts))
    return issues


def _structured_answer(payload: FeeExplanationInput,
                       public: FeeDecompositionPublic) -> FeeModelExplanation:
    from src.model_service.gateway import ModelGateway
    from src.model_service.models import Message

    system, repair = _load_prompt()
    # 模型读取事实与计算依赖，不读取已经拼好的四段式答案或页面布局。
    model_data = payload.model_copy(update={"decomposition": payload.decomposition.model_copy(update={
        "fields": [field if field.explainable else field.model_copy(update={"calculated_amount": None})
                   for field in payload.decomposition.fields],
    })})
    data = model_data.model_dump_json(exclude={
        "target_evidence": {"__all__": {"sentence": True, "ratios": {"__all__": {"confirmation_status"}}}},
        "line_evidence": {"sentence"},
        "line_evidences": {"__all__": {"sentence"}},
        "decomposition": {
            "template_explanations": True, "summary_text": True,
            "stages": True, "trace": True, "coverage": True,
            "uncertainties": {"__all__": {"message"}},
            "calculations": {"__all__": {"rounding_rule", "verification_status", "verification_reason"}},
            "sources": {"__all__": {"confirmation_status"}},
            "rule_choices": {"__all__": {"candidates": {"__all__": {"confirmation_status", "reason"}}}},
            "settlement_facts": {"display_template"},
            "fee_items": {"__all__": {"payment_condition_context": {"source_hash", "read_at"}}},
            "fields": {"__all__": {"brief": True, "conclusion_text": True, "explanation_reason": True,
                                  "explanation": {"composition", "basis_text", "boundary"}}},
        },
    })
    messages = [Message(role="system", content=system), Message(role="user", content=data)]
    gateway = ModelGateway()
    for attempt in range(2):
        response = gateway.generate(
            messages=messages, model_type="llm", scene="fee_explanation", max_tokens=3000)
        text = _public_safe_answer((response.content or "").strip(),
                                   _item_name_protection(public))
        issues = _answer_issues(text, payload, public)
        if not issues:
            return FeeModelExplanation(answer=text, used_model=True, model_attempted=True)
        logger.info("[FEE-EXPLANATION] validation rejected attempt=%s issue_count=%s", attempt + 1, len(issues))
        messages = [*messages, Message(role="assistant", content=text),
                    Message(role="user", content=repair + "\n" + "\n".join(issues))]
    return FeeModelExplanation(
        answer="", model_attempted=True, fallback_reason="validation_rejected")


_NUMBER_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
#: 说明“标准/累计/明细行”等其它口径时不做字段归因（与本单字段总额无关）。
_OTHER_BASIS = ("标准", "累计", "明细", "第", "其中", "比例", "单价", "限额",
                "起付线", "封顶线", "剩余", "上限", "下限", "门槛")


def _decimal_set(text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for raw in _NUMBER_TOKEN.findall(text or ""):
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        values.add(value)
        values.add(abs(value))
        if Decimal("0") <= value <= Decimal("1"):
            values.add(value * 100)
        if value != 0:
            values.add(value / 100)
    return values


def _label_amounts(public: FeeDecompositionPublic) -> dict[str, Decimal]:
    """可归因的字段/原单事实 → 金额；用于拦截“把 A 的金额说成 B”。"""
    amounts: dict[str, Decimal] = {}
    for field in public.fields:
        value = _dec(field.observed_amount)
        if value is not None:
            amounts[field.label] = value
    if public.settlement_facts:
        for item in (*public.settlement_facts.items, *public.settlement_facts.payment_items):
            value = _dec(item.value)
            if value is not None:
                amounts[item.label] = value
    return amounts


def _attribution_ok(text: str, amounts: dict[str, Decimal]) -> bool:
    labels = sorted(amounts, key=len, reverse=True)
    for match in re.finditer(
            r"([一-鿿]{2,16})\s*[：:，,、=＝]?\s*(?:为|是|约|共计|一共)?\s*"
            r"(-?\d[\d,]*(?:\.\d+)?)\s*元", text):
        captured, figure = match.group(1), match.group(2)
        if any(marker in captured for marker in _OTHER_BASIS):
            continue
        label = next((key for key in labels if captured.endswith(key)), None)
        if label is None:
            continue
        if abs(Decimal(figure.replace(",", "")) - amounts[label]) > Decimal("0.005"):
            return False
    return True


def explain_decomposition(
    public: FeeDecompositionPublic, question: str,
    question_target: QuestionTarget | None = None,
) -> FeeModelExplanation:
    """所有字段和明细共用模型正文入口；仅离线、故障或事实拒绝时回退确定性证据。"""
    question_target = question_target or resolve_question_target(public, question)
    if question_target.kind in ("ambiguous", "invalid"):
        return FeeModelExplanation(
            answer=_public_safe_answer(question_target.prompt or "请指明要解释的费用明细行。"),
            fallback_reason="clarification")
    payload = build_model_input(public, question, question_target)
    rendered = render_evidence_answer(payload)
    if rendered is None:
        reason = "本单没有可交付的核对依据，无法形成可靠费用解释。"
        return FeeModelExplanation(
            answer=_public_safe_answer(f"{reason}本单费用及计算依据仍可查看。"),
            uncertainties=[reason], fallback_reason="no_evidence")
    mode = _mode()
    generated = FeeModelExplanation(answer="", fallback_reason="deterministic")
    if rendered.has_evidence and mode != "deterministic":
        try:
            generated = _structured_answer(payload, public)
        except Exception as exc:  # noqa: BLE001 - 故障不影响原单事实与计算证据交付
            logger.warning("[FEE-EXPLANATION] model error type=%s", type(exc).__name__)
            generated = FeeModelExplanation(
                answer="", model_attempted=True, fallback_reason="model_error")
    elif not rendered.has_evidence:
        generated.fallback_reason = "no_evidence"
    logger.info("[FEE-EXPLANATION] mode=%s attempted=%s used_model=%s fallback_reason=%s",
                mode, generated.model_attempted, generated.used_model, generated.fallback_reason)
    return generated.model_copy(update={
        "answer": generated.answer if generated.used_model else _public_safe_answer(
            rendered.body, _item_name_protection(public)),
        "uncertainties": [_public_safe_answer(message) for message in rendered.uncertainties],
        "evidence_answer_status": "rendered" if rendered.has_evidence else "none",
    })
