"""单元级医疗类别确定性分类。

Issue #19：所有单元区分医疗类别，支持按照医疗类别进行后续结构化处理。
复用 domain_definitions.MEDICAL_CATEGORY 别名表，从单元原文与祖先语境
确定性识别政策标准医疗类别；无命中回退「通用」，保证所有单元都有类别。
不调用模型（确定性、可测、幂等）。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.policy_extract.domain_definitions import (
    MEDICAL_CATEGORY,
)

# 无任何医疗类别信号的显式回退值（语义：不区分医疗类别、各类别均适用）
FALLBACK_MED_TYPE = "通用"

# 别名 → 政策标准值；长别名优先匹配，避免「急诊」截断「急诊留观」等误判
# 复合类别与政策常用变体（Issue #19 用户验证发现）：门（急）诊/门急诊 是北
# 京政策的合并结算类别，归门诊；购药（定点零售药店购药费用）是独立医疗类别。
_EXTRA_ALIASES: dict[str, str] = {
    "门（急）诊": "门诊",
    "门(急)诊": "门诊",
    "门急诊": "门诊",
    "购药": "购药",
}
_ALIAS_TO_STANDARD: dict[str, str] = dict(_EXTRA_ALIASES)
for _value in MEDICAL_CATEGORY.values:
    for _alias in _value.aliases:
        _ALIAS_TO_STANDARD[_alias] = _value.standard_name


def normalize_med_type_value(value: str) -> str:
    """把 LLM/历史数据中的医疗类别原始值归一到政策标准值；未知名原样返回。"""
    text = (value or "").strip()
    return _ALIAS_TO_STANDARD.get(text, text)


def apply_unit_med_type(rules: list, unit_med_type: str) -> None:
    """规则医疗类别就地归一 + 空值继承单元分类（已有值不覆盖）。

    LLM 已提取的值仅做别名归一（门特→门诊特殊病），保持规则自身精度；
    空值回填单元分类，保证每条规则都能按医疗类别参与结构化处理。
    """
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        raw = str(rule.get("med_type") or "").strip()
        rule["med_type"] = normalize_med_type_value(raw) if raw else unit_med_type


def classify_med_type(*texts: str) -> str:
    """从单元原文 + 祖先语境确定性识别医疗类别；无命中回退「通用」。

    传入文本按就近原则排序（单元原文在前，祖先语境在后）：
    更近的文本先匹配，单元内容覆盖上级章节的类别信号。
    同一文本内多个类别信号时，取首次出现位置最前者（同位置取更长别名），
    避免混合条款（如「门诊、急诊、住院…购药」）被字典序任意抢占。
    """
    for text in texts:
        best: tuple[int, int, str] | None = None  # (位置, -别名长度, 标准值)
        for alias in _ALIAS_TO_STANDARD:
            position = (text or "").find(alias)
            if position < 0:
                continue
            candidate = (position, -len(alias), _ALIAS_TO_STANDARD[alias])
            if best is None or candidate < best:
                best = candidate
        if best is not None:
            return best[2]
    return FALLBACK_MED_TYPE


if __name__ == "__main__":
    # 最小自检：分类、归一、回退
    assert classify_med_type("急诊留观费用") == "急诊留观"
    assert classify_med_type("门诊", "第三章 住院治疗") == "门诊"
    assert classify_med_type("本条为费用征缴规定") == FALLBACK_MED_TYPE
    assert normalize_med_type_value("门特") == "门诊特殊病"
    assert normalize_med_type_value("自定义类别") == "自定义类别"
    print("med_type_classifier self-check ok")
