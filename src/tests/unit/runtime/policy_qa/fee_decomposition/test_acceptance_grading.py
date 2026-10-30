"""验收判定：逐目标、金额绑定，不再用关键词"假通过"（评审问题 10）。

旧 `.scratch/fee-acceptance-20261024/accept.py` 的判定缺陷：
- 金额用子串比较，`0.00` 被 `50%` 里的字符 `0` 命中；
- 只看回答里有没有金额，不看金额属于哪个字段/行；
- 四要素用 `any(...)`，任一项非空即宣称齐备；
- 总览允许少一个核心金额。

本模块提供可长期运行的确定性判定（`grade_target`）与反例：
每个展示目标必须归入且仅归入一个状态——
`reason_explained`（原因已解释）/ `book_fact`（仅原单事实）/
`not_applicable`（结构性不适用）/ `missing_evidence`（缺证未完成），
"资料不足"不算原因解释完成。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

REASON_EXPLAINED = "reason_explained"
BOOK_FACT = "book_fact"
NOT_APPLICABLE = "not_applicable"
MISSING_EVIDENCE = "missing_evidence"

#: 数值 token：整千分位与小数都算一个 token（不做子串搜索）。
_NUMBER = re.compile(r"(?<![\d.,])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\d,])")
_BOOK_MARKERS = ("原单", "本单", "结算记录", "账面记录", "列示", "账面勾稽", "账面")
#: 可用作“来源已交付”的原单/明细/固定依据措辞（不升级为原因解释）
_SOURCE_RECORD_MARKERS = _BOOK_MARKERS + ("明细", "依据来源")
_NA_MARKER = "不适用"
_MISSING_MARKERS = ("缺", "未取得", "暂无", "待补全", "未核实", "无法核对")
_REASON_MARKERS = ("构成", "比例", "基数", "＝", "=", "计算", "按", "补助", "支付")
#: 真实计算环节标记：只有口头"计算/支付"而没有运算环节不算构成
_COMPOSITION_MARKERS = ("＋", "+", "－", "-", "×", "*", "÷", "/", "取整", "max", "min", "较小值", "最大值")


@dataclass(frozen=True)
class TargetRequirement:
    """一个展示目标的独立预期：目标、金额、预期四态、必要构成与来源、禁止项。

    key 为稳定目标 ID（case + template.key 或 line_id）；label 只用于定位正文，
    不能替代目标 ID。expected 全部来自取证记录/黄金样本/显式 Decimal 算式，
    不取自被测响应。
    """

    key: str
    label: str
    amount: str | None
    #: explainable（本单可独立计算）/ observed_only（只有原单金额）/
    #: not_applicable（结构性不适用）/ missing（缺证）
    kind: str
    #: 必要构成 token（如 "×50%"、"取整"、"＋"、"大病支付"）
    required_tokens: tuple[str, ...] = ()
    #: 必要数值（Decimal 等值比较，不受 550 / 550.00 写法影响）
    required_values: tuple[str, ...] = ()
    #: 禁止出现的内容（错误算式/其他字段金额/未执行候选）
    forbidden_tokens: tuple[str, ...] = ()
    #: 该目标实际应引用的来源标题（正文或本次回答 citations）
    required_sources: tuple[str, ...] = ()
    #: 原单/结算记录可作为该目标的来源（无政策原文的账面事实口径）
    source_record: bool = False
    #: 缺证目标必须点名的具体缺项
    gap_markers: tuple[str, ...] = ()

    @staticmethod
    def check(config: dict) -> None:
        """验收配置自检：explainable 必须登记必要构成/数值/来源，否则配置本身报错。"""
        if config.get("kind") != "explainable":
            return
        if not (config.get("required_values") or config.get("required_tokens")):
            raise ValueError("explainable 目标必须登记必要构成（required_values/required_tokens）")
        if not (config.get("required_sources") or config.get("source_record")):
            raise ValueError("explainable 目标必须登记来源（required_sources 或 source_record）")


@dataclass(frozen=True)
class TargetAssessment:
    """两轴判定：content_status（解释状态）与 delivered（是否如实交付该目标）。"""

    status: str
    delivered: bool
    reason: str = ""


def numeric_tokens(text: str) -> list[Decimal]:
    """回答中的数值 token（Decimal）；`50%` 里的 50 与 `0.00` 不相等。"""
    values: list[Decimal] = []
    for raw in _NUMBER.findall(text or ""):
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:  # pragma: no cover - 正则已排除非法形态
            continue
        if value.is_finite():
            values.append(value)
    return values


def _bound_amount(line: str, amount: str | None, label: str) -> bool:
    """金额按 Decimal 相等比较，且必须是紧跟目标标签的第一个数值（字段绑定）。"""
    if amount is None:
        return label in line
    if label not in line:
        return False
    tail = line.split(label, 1)[1]
    match = _NUMBER.search(tail)
    if match is None:
        return False
    try:
        return Decimal(match.group(0).replace(",", "")) == Decimal(str(amount))
    except InvalidOperation:  # pragma: no cover
        return False


def _target_lines(answer: str, label: str) -> list[str]:
    """目标核验范围：标签所在行；模型正文的标签常在标题行、明细在后续列表时，
    用整段（整个回答）作为该目标的核验范围，但标签本身必须出现。"""
    text = answer or ""
    compact = re.sub(r"\s+", "", text)
    needle = re.sub(r"\s+", "", label or "")
    lines = [line for line in text.splitlines() if line.strip()]
    matched = [line for line in lines
               if needle and needle in re.sub(r"\s+", "", line)]
    if matched:
        return matched
    if needle and needle in compact:
        return [text]
    return []


# ── F5（2026-10-27 复审）：受控算式的独立 Decimal 核验 ─────────────────

_EQ_TOLERANCE = Decimal("0.0000001")
#: 受控渲染器使用的固定函数/运算符（有限集合，不是通用自然语言解析器）
_EQ_FUNCTIONS = {"ROUND": "round", "MIN": "min", "MAX": "max"}
_EQ_TOKEN = re.compile(r"ROUND|MIN|MAX|[-+*/(),]|(?:\d+(?:\.\d+)?)(?:%)?")
_NO_COMPUTATION_MARKERS = (
    "暂无计算", "计算过程尚未提供", "未提供计算", "暂无独立计算记录", "没有计算记录")


@dataclass(frozen=True)
class EquationCheck:
    """受控算式核验结果：checked=实际复算的等式数；failures=不成立的等式（公开文案）。"""

    checked: int
    failures: tuple[str, ...]


def _normalize_equation(text: str) -> str:
    # 行号注解（“（第1行）”“第 2 行”）不参与算式
    text = re.sub(r"（第\s*\d+\s*行）|第\s*\d+\s*行", "", text)
    # 中文标签里的连接号（“在职-其他医院”）不是减号；“2万元”是量词不是数字 2
    text = re.sub(r"(?<=[一-鿿])-|-(?=[一-鿿])", "", text)
    text = re.sub(r"\d+(?:万|亿|千|百)", "", text)
    # 不含运算符/函数的括注是标签或注解（“（医保内）”“（交易前基金累计 0.00 元）”），
    # 从内向外剥离；带运算符的括号保留为算式分组。
    changed = True
    while changed:
        changed = False
        for match in reversed(list(re.finditer(r"（[^（）]*）", text))):
            inner = match.group(0)[1:-1]
            if any(op in inner for op in "+-*/％%×÷－＋") or any(
                    name in inner for name in ("较小值", "最大值", "取整")):
                continue
            text = text[:match.start()] + text[match.end():]
            changed = True
            break
    table = str.maketrans({
        "（": "(", "）": ")", "，": ",", "＋": "+", "－": "-", "×": "*", "÷": "/",
        "％": "%", "＝": "=", "＝": "=", "．": ".", "　": " ",
    })
    text = text.translate(table).replace(" ", "")
    for name, token in (("较小值", "MIN"), ("最大值", "MAX"), ("取整", "ROUND"),
                        ("min", "MIN"), ("max", "MAX"), ("round", "ROUND")):
        text = text.replace(name, token)
    # 去掉剩余中文/全角符号：算式里的文字标签（基数/比例/元）不参与计算
    return re.sub(r"[^\x00-\x7f]", "", text)


class _EquationParser:
    """仅支持 + - * / 、括号、百分比与 ROUND/MIN/MAX 的受控递归下降解析。"""

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def parse(self) -> Decimal:
        value = self._expression()
        if self.index != len(self.tokens):
            raise ValueError("unexpected token")
        return value

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None or (expected is not None and token != expected):
            raise ValueError("unexpected token")
        self.index += 1
        return token

    def _expression(self) -> Decimal:
        value = self._term()
        while self._peek() in ("+", "-"):
            operator = self._take()
            right = self._term()
            value = value + right if operator == "+" else value - right
        return value

    def _term(self) -> Decimal:
        value = self._factor()
        while self._peek() in ("*", "/"):
            operator = self._take()
            right = self._factor()
            if operator == "*":
                value = value * right
            else:
                if right == 0:
                    raise ValueError("division by zero")
                value = value / right
        return value

    def _factor(self) -> Decimal:
        token = self._peek()
        if token is None:
            raise ValueError("unexpected end")
        if token in _EQ_FUNCTIONS:
            self._take()
            args = self._arguments()
            name = _EQ_FUNCTIONS[token]
            if name == "round":
                if len(args) != 1:
                    raise ValueError("round arity")
                return args[0].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if name == "min":
                return min(args)
            return max(args)
        if token == "-":
            self._take()
            return -self._factor()
        if re.fullmatch(r"\d+(?:\.\d+)?%?", token or ""):
            self._take()
            if token.endswith("%"):
                return Decimal(token[:-1]) / Decimal(100)
            return Decimal(token)
        if token == "(":
            self._take()
            value = self._expression()
            self._take(")")
            return value
        raise ValueError("unexpected token")

    def _arguments(self) -> list[Decimal]:
        self._take("(")
        args = [self._expression()]
        while self._peek() == ",":
            self._take(",")
            args.append(self._expression())
        self._take(")")
        return args


def _evaluate_part(part: str) -> Decimal | None:
    tokens = _EQ_TOKEN.findall(_normalize_equation(part))
    if not tokens:
        return None
    try:
        return _EquationParser(tokens).parse()
    except (ValueError, ArithmeticError, InvalidOperation):
        # 纯“标签+数值”段（如“第 1 行 10.00 元”“本行费用 699.00 元”）没有运算，
        # 取最后一个数值作为该侧值；含运算符/函数时失败即不参与核验，不猜。
        if any(token in "+-*/(),%" or token in _EQ_FUNCTIONS for token in tokens):
            return None
        return Decimal(tokens[-1].rstrip("%"))


def evaluate_controlled_equations(text: str) -> EquationCheck:
    """复核正文中受控算式的算术关系（与具体金额/isolation 无关）。"""
    checked = 0
    failures: list[str] = []
    for segment in re.split(r"[；;]", text or ""):
        if "＝" not in segment and "=" not in segment:
            continue
        parts = re.split(r"[＝=]", segment)
        if len(parts) < 2:
            continue
        values = [_evaluate_part(part) for part in parts]
        parsable = [value for value in values if value is not None]
        if len(parsable) < 2:
            continue
        checked += 1
        if any(value != parsable[0] for value in parsable[1:]):
            failures.append(segment.strip()[:120])
    return EquationCheck(checked=checked, failures=tuple(failures))


def _equation_parts(segment: str) -> list[str]:
    return [part for part in re.split(r"[＝=]", segment) if part.strip()]


def _evaluated_amount(part: str) -> Decimal | None:
    return _evaluate_part(part)


def _equation_values(segment: str) -> list[Decimal]:
    """目标行内每个等式的右侧数值（按 ； 分句；一行可有多段中间算式）。"""
    values: list[Decimal] = []
    for sub in re.split(r"[；;]", segment):
        if "＝" not in sub and "=" not in sub:
            continue
        for part in reversed(_equation_parts(sub)):
            value = _evaluate_part(part)
            if value is not None:
                values.append(value)
                break
    return values


def assess_target(
    answer: str, requirement: TargetRequirement, citations: tuple[str, ...] = ()
) -> TargetAssessment:
    """判定单个目标：内容状态 + 是否如实交付（漏答/空文/泛泛资料不足不算交付）。"""
    blocks = _target_lines(answer, requirement.label)
    if not blocks:
        return TargetAssessment(MISSING_EVIDENCE, False, "目标未在正文交付")
    bound = [block for block in blocks if _bound_amount(block, requirement.amount, requirement.label)]
    kind = requirement.kind
    if kind == "not_applicable":
        ok = bound and any(_NA_MARKER in block for block in bound)
        return TargetAssessment(NOT_APPLICABLE if ok else MISSING_EVIDENCE, bool(ok),
                                "" if ok else "不适用未说明")
    if not bound:
        return TargetAssessment(MISSING_EVIDENCE, False, "金额未绑定到该目标")
    segment = bound[0]
    if any(token in segment for token in requirement.forbidden_tokens):
        return TargetAssessment(MISSING_EVIDENCE, False, "正文含禁止内容")
    if kind == "observed_only":
        ok = any(marker in segment for marker in _BOOK_MARKERS)
        return TargetAssessment(BOOK_FACT if ok else MISSING_EVIDENCE, ok,
                                "" if ok else "原单事实未标注来源")
    if kind == "explainable":
        values = numeric_tokens(segment)
        numbers_ok = all(Decimal(str(value)) in values for value in requirement.required_values)
        tokens_ok = all(token in segment for token in requirement.required_tokens)
        sources = requirement.required_sources
        source_ok = (not sources) or any(
            token in segment or token in " ".join(citations) for token in sources)
        has_reason = any(marker in segment for marker in _REASON_MARKERS)
        # 构成必须真实存在：至少一个算术/取整环节，且除目标金额外还有数值（0=0＋0 也算）
        has_composition = (any(marker in segment for marker in _COMPOSITION_MARKERS)
                           and len(numeric_tokens(segment)) >= 2)
        equations = evaluate_controlled_equations(segment)
        target_amount = Decimal(str(requirement.amount or "0"))
        # 0 元目标允许以“本次未发生 + 分支输入”文字成立（如起付已由累计覆盖），
        # 但算式必须全部成立且已登记必要输入；非 0 目标必须有算式落在本目标金额。
        arithmetic_ok = (not equations.failures and (
            (equations.checked >= 1 and target_amount in _equation_values(segment))
            or (target_amount == 0 and (equations.checked >= 1
                                        or len(set(numeric_tokens(segment))) >= 2))))
        no_computation = any(marker in segment for marker in _NO_COMPUTATION_MARKERS)
        record_ok = (requirement.source_record
                     and any(marker in segment for marker in _SOURCE_RECORD_MARKERS))
        source_ok = source_ok or record_ok
        ok = (numbers_ok and tokens_ok and source_ok and has_reason and has_composition
              and arithmetic_ok and not no_computation)
        return TargetAssessment(REASON_EXPLAINED if ok else MISSING_EVIDENCE, ok,
                                "" if ok else "必要构成/来源缺失")
    # kind == "missing"：允许诚实说明未完成，但必须点名具体缺项
    markers = requirement.gap_markers or _MISSING_MARKERS
    ok = any(marker in segment for marker in markers)
    return TargetAssessment(MISSING_EVIDENCE, ok, "" if ok else "缺项未点名")


def grade_target(
    answer: str, requirement: TargetRequirement, citations: tuple[str, ...] = ()
) -> str:
    """兼容包装：只返回内容状态。"""
    return assess_target(answer, requirement, citations).status


def acceptance_summary(
    answer: str, requirements: list[TargetRequirement], citations: tuple[str, ...] = ()
) -> dict[str, list[str]]:
    """逐目标状态分组：原因解释/原单事实/结构性不适用/缺证未完成各自统计。"""
    summary: dict[str, list[str]] = {
        REASON_EXPLAINED: [], BOOK_FACT: [], NOT_APPLICABLE: [], MISSING_EVIDENCE: []}
    for requirement in requirements:
        summary[assess_target(answer, requirement, citations).status].append(requirement.key)
    return summary


def undelivered(
    answer: str, requirements: list[TargetRequirement], citations: tuple[str, ...] = ()
) -> list[str]:
    """未如实交付的目标（漏答、金额错绑、缺项未点名、夹带禁止内容）。"""
    return [requirement.key for requirement in requirements
            if not assess_target(answer, requirement, citations).delivered]


# ── 评审问题 10 的三个"假通过"反例 ────────────────────────────────

def test_zero_amount_is_not_matched_by_percent_sign_digits():
    """旧判定：`本次采用50%的比例。` 能"通过" 0.00（子串含字符 0）。"""
    answer = "本次采用50%的比例。"
    requirement = TargetRequirement(key="regression.first_pay", label="本次起付承担", amount="0.00",
                      kind="explainable", required_tokens=("起付",))
    assert grade_target(answer, requirement) == MISSING_EVIDENCE
    assert Decimal("0.00") not in numeric_tokens(answer)


def test_amount_found_elsewhere_does_not_prove_this_target():
    """旧判定：`总费用1837.50元，按比例计算。` 能"通过"为 1837.50；但金额属于别的字段。"""
    answer = "总费用1837.50元，按比例计算。"
    requirement = TargetRequirement(
        key="regression.big_pay", label="大额支付", amount="1597.50", kind="explainable",
        required_tokens=("3195.00", "50%"))
    assert grade_target(answer, requirement) == MISSING_EVIDENCE


def test_full_coverage_requires_every_visible_target():
    """总览漏一个核心金额即不通过（旧判定允许少一个）。"""
    answer = "\n".join([
        "- 费用总金额 3435.00 元；构成：3195.00＋240.00＝3435.00 元；来源：本单结算记录。",
        "- 大额支付 1597.50 元；构成：取整（3195.00×50%）＝1597.50 元；来源：本单结算记录。",
    ])
    requirements = [
        TargetRequirement("regression.fee_all", "费用总金额", "3435.00", "explainable",
                          required_tokens=("＋",), required_values=("3195",),
                          source_record=True),
        TargetRequirement("regression.big_pay", "大额支付", "1597.50", "explainable",
                          required_tokens=("取整",), required_values=("3195",),
                          source_record=True),
        TargetRequirement("regression.personal_total", "个人支付总金额", "1837.50", "explainable",
                          required_tokens=("＋",), required_values=("240",),
                          source_record=True),
    ]
    summary = acceptance_summary(answer, requirements)
    assert "regression.personal_total" in summary[MISSING_EVIDENCE]
    assert len(summary[REASON_EXPLAINED]) == 2


def test_wrong_field_amount_fails_even_when_it_appears_in_answer():
    """1837.50（个人支付）出现在大额支付句子里也必须失败。"""
    answer = "- 大额支付 1837.50 元；构成：基数 3195.00 元×50%＝1597.50 元。"
    requirement = TargetRequirement(
        key="regression.big_pay", label="大额支付", amount="1597.50", kind="explainable",
        required_tokens=("3195.00", "50%"))
    assert grade_target(answer, requirement) == MISSING_EVIDENCE


def test_reason_explained_requires_amount_bound_tokens_and_source():
    answer = ("- 大额支付 1597.50 元；构成：min(max(取整（基数 3195.00 元×比例 50%）,"
              " -2304.50), 2195.50)＝1597.50 元；来源：居民门诊待遇参数表。")
    requirement = TargetRequirement(
        key="regression.big_pay", label="大额支付", amount="1597.50", kind="explainable",
        required_tokens=("3195.00", "50%", "2195.50"),
        required_sources=("居民门诊待遇参数表",))
    assert grade_target(answer, requirement) == REASON_EXPLAINED


def test_book_fact_and_not_applicable_are_not_counted_as_reason_explained():
    answer = ("\n".join([
        "- 退役医疗费支付 0.00 元；按原单记录列入，资格与待遇公式未推导。",
        "- 公疗补助 不适用（本险种/医疗类别未发生该渠道）。",
    ]))
    book = TargetRequirement("regression.retire_officer", "退役医疗费支付", "0.00", "observed_only")
    na = TargetRequirement("regression.official_pay", "公疗补助", None, "not_applicable")
    summary = acceptance_summary(answer, [book, na])
    assert summary[BOOK_FACT] == ["regression.retire_officer"]
    assert summary[NOT_APPLICABLE] == ["regression.official_pay"]
    assert summary[REASON_EXPLAINED] == []


def test_missing_evidence_is_reported_not_hidden():
    answer = "- 大额超封顶金额：本字段无独立计算或费用归属映射，暂未取得可核对依据。"
    requirement = TargetRequirement("regression.beyond_cap", "大额超封顶金额", None, "missing")
    assert grade_target(answer, requirement) == MISSING_EVIDENCE
    summary = acceptance_summary(answer, [requirement])
    assert summary[MISSING_EVIDENCE] == ["regression.beyond_cap"]
