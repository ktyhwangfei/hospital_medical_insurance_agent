"""政策知识提取的确定性校验器。

原则：LLM 产候选，代码做验收。全部纯函数、确定性、可重放。

三类校验：
1. check_value_coverage —— 数值覆盖率：源段落出现的每个比例/金额都必须
   能在该单元的某条规则里找到（防止整张表被静默漏抽）；反向检查规则值
   必须出自原文（防止幻觉数值）。
2. check_dimension_honesty —— 维度诚实：规则的医院等级/金额区间/人群必须
   能在源段落里找到字样（防止原文只说「医院/社区」却被幻觉展开成一/二/三级）。
3. check_key_uniqueness —— 键唯一性：同一（险种, 人群, 医疗类别, 医院等级,
   金额区间, 规则类型）不允许两个不同的比例值（防止归一化冲突）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from src.knowledge_extension.rule_explanation.fund_ratio_guard import to_percent


@dataclass(frozen=True)
class ValidationIssue:
    """一条校验结论。level=ERROR 阻断发布；level=REVIEW 转人工。"""

    code: str
    level: str
    message: str
    context: Mapping[str, Any] = field(default_factory=dict)


# ── 数值抽取 ─────────────────────────────────────────────────

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[%％]")
_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(万)?元")

_VALUE_FIELDS = (
    "payment_ratio", "personal_payment_ratio",
    "deductible_amount", "cap_amount", "rule_value",
)


def _plain(value: Any) -> str:
    if isinstance(value, dict) and "value" in value:
        return str(value["value"] or "")
    return str(value or "")


def _percent_set(text: str) -> set[float]:
    return {float(m) for m in _PERCENT_RE.findall(text)}


def _amount_set(text: str) -> set[float]:
    return {
        float(num) * (10000 if wan else 1)
        for num, wan in _AMOUNT_RE.findall(text)
    }


def _rule_numbers(rule: Mapping[str, Any]) -> tuple[set[float], set[float]]:
    """规则命中的（比例集合, 金额集合），比例统一为百分数。

    比例字段只走 to_percent/正则，金额字段只进金额集合，避免
    「1800元」被误判成 1800% 之类的交叉污染；amount_band 参与金额覆盖。
    """
    percents: set[float] = set()
    amounts: set[float] = set()
    for key in _VALUE_FIELDS:
        text = _plain(rule.get(key))
        if not text:
            continue
        if key in ("payment_ratio", "personal_payment_ratio"):
            single = to_percent(text)
            if single is not None:
                percents.add(single)
            percents.update(_percent_set(text))
        elif key in ("deductible_amount", "cap_amount"):
            amounts.update(_amount_set(text))
        else:  # rule_value 混合文本，两类都抽
            percents.update(_percent_set(text))
            amounts.update(_amount_set(text))
    # 金额区间是维度但也是原文数值的载体
    amounts.update(_amount_set(_plain(rule.get("amount_band"))))
    return percents, amounts


def check_value_coverage(
    source_text: str, rules: Iterable[Mapping[str, Any]]
) -> list[ValidationIssue]:
    """数值覆盖率双向校验（单元级）。

    - 原文每个比例/金额都要被某条规则覆盖（漏抽检测）；
    - 每条规则的比例/金额都要出自原文（幻觉检测）。
    """
    source = str(source_text or "")
    if not source.strip():
        return []
    src_percents = _percent_set(source)
    src_amounts = _amount_set(source)

    covered_percents: set[float] = set()
    covered_amounts: set[float] = set()
    issues: list[ValidationIssue] = []
    for rule in rules:
        rule_percents, rule_amounts = _rule_numbers(rule)
        covered_percents |= rule_percents & src_percents
        covered_amounts |= rule_amounts & src_amounts
        for value in sorted(rule_percents - src_percents):
            issues.append(ValidationIssue(
                code="RULE_VALUE_NOT_IN_SOURCE",
                level="REVIEW",
                message=f"规则比例 {value:g}% 在原文中不存在",
                context={"rule_id": _plain(rule.get("rule_id")), "value": value},
            ))

    for value in sorted(src_percents - covered_percents):
        issues.append(ValidationIssue(
            code="SOURCE_VALUE_UNCOVERED",
            level="REVIEW",
            message=f"原文比例 {value:g}% 未被任何规则提取",
            context={"value": value},
        ))
    for value in sorted(src_amounts - covered_amounts):
        issues.append(ValidationIssue(
            code="SOURCE_VALUE_UNCOVERED",
            level="REVIEW",
            message=f"原文金额 {value:g}元 未被任何规则提取",
            context={"value": value},
        ))
    return issues


# ── 维度诚实 ─────────────────────────────────────────────────

_DIMENSION_PATTERNS: dict[str, tuple[str, ...]] = {
    "hosp_lv": ("三级", "二级", "一级", "社区", "无等级", "未定级"),
    "psn_type": (),  # 人群词直接按原文包含判断
    "amount_band": (),
}


def check_dimension_honesty(
    source_text: str, rules: Iterable[Mapping[str, Any]]
) -> list[ValidationIssue]:
    """维度值必须能在源段落找到字样；找不到视为幻觉维度（REVIEW）。

    hosp_lv 例外：归一化后的值（如「社区」）允许其常见原文写法命中。
    """
    source = re.sub(r"\s+", "", str(source_text or ""))
    if not source:
        return []
    issues: list[ValidationIssue] = []
    for rule in rules:
        rule_id = _plain(rule.get("rule_id"))
        hosp = _plain(rule.get("hosp_lv")).strip()
        if hosp:
            candidates = [hosp]
            if hosp == "社区":
                candidates.extend(["社区卫生", "社区医院"])
            if not any(token in source for token in candidates):
                issues.append(ValidationIssue(
                    code="DIMENSION_NOT_IN_SOURCE",
                    level="REVIEW",
                    message=f"规则的医院等级「{hosp}」在原文中不存在",
                    context={"rule_id": rule_id, "dimension": "hosp_lv", "value": hosp},
                ))
        band = _plain(rule.get("amount_band")).strip()
        if band and re.sub(r"\s+", "", band) not in source:
            issues.append(ValidationIssue(
                code="DIMENSION_NOT_IN_SOURCE",
                level="REVIEW",
                message=f"规则的金额区间「{band}」在原文中不存在",
                context={"rule_id": rule_id, "dimension": "amount_band", "value": band},
            ))
        psn = _plain(rule.get("psn_type")).strip()
        if psn and psn not in source:
            issues.append(ValidationIssue(
                code="DIMENSION_NOT_IN_SOURCE",
                level="REVIEW",
                message=f"规则的人群标签「{psn}」在原文中不存在",
                context={"rule_id": rule_id, "dimension": "psn_type", "value": psn},
            ))
    return issues


# ── 键唯一性 ─────────────────────────────────────────────────

_KEY_FIELDS = (
    "insu_type", "psn_type", "med_type", "hosp_lv", "amount_band", "rule_type",
    "jjgs",  # 基金归属：统筹基金 / 大额医疗互助资金是不同业务度量
)

_CROSS_FUND_HINT = "大额医疗互助"


def _cross_fund_conflict(rules: list[Mapping[str, Any]]) -> bool:
    """冲突双方 source_text 涉及不同资金口径（如一方为大额医疗互助资金）→ 非同一度量。"""
    texts = [_plain(r.get("source_text")) for r in rules]
    return any(_CROSS_FUND_HINT in t for t in texts) and any(
        _CROSS_FUND_HINT not in t for t in texts
    )


def check_key_uniqueness(rules: Iterable[Mapping[str, Any]]) -> list[ValidationIssue]:
    """同一维度键下不允许出现两个不同的统筹基金支付比例。

    - 正常冲突 → ERROR（阻断发布）；
    - 全维度为空的泛规则（缴费比例/划入比例等不同业务主体共用「支付比例」类型）
      → REVIEW，不阻断；
    - 冲突双方涉及不同资金口径（大额医疗互助 vs 统筹基金）→ REVIEW，
      属业务主体标化问题，走主体拆分而非门禁阻断。
    """
    groups: dict[tuple[str, ...], list[Mapping[str, Any]]] = {}
    for rule in rules:
        ratio = to_percent(_plain(rule.get("payment_ratio")))
        if ratio is None:
            continue
        key = tuple(_plain(rule.get(name)).strip() for name in _KEY_FIELDS)
        groups.setdefault(key, []).append(rule)
    issues: list[ValidationIssue] = []
    for key, group in groups.items():
        ratios = {
            ratio
            for ratio in (to_percent(_plain(r.get("payment_ratio"))) for r in group)
            if ratio is not None
        }
        if len(ratios) <= 1:
            continue
        rule_ids = [_plain(r.get("rule_id")) or "?" for r in group]
        message = (
            f"同一维度键 {key} 存在冲突比例: "
            + "/".join(f"{r:g}%" for r in sorted(ratios))
        )
        dimensionless = not any(key[2:5])  # med_type/hosp_lv/amount_band 全空
        if dimensionless or _cross_fund_conflict(group):
            level = "REVIEW"
        else:
            level = "ERROR"
        issues.append(ValidationIssue(
            code="KEY_CONFLICT",
            level=level,
            message=message,
            context={"key": key, "ratios": sorted(ratios), "rule_ids": rule_ids},
        ))
    return issues
