"""business_sentence 生成质量修复测试（迭代 19 反思）。

复现缺陷（用户反馈）：知识审核详情页的 knowledge business_sentence 变成
「entities为[{'name': '退休人员', ...}]，priority为高，险种为...」——LLM 提取的
rule 含 entities/relations/priority 等结构化字段，_NON_BUSINESS_FIELDS 未排除，
_sentence 兜底把它们拼进业务句子，导致展示不可读、不利于计算。

修复目标：
1. entities / relations / priority / time_period / admission_order 等
   非业务句子成分不参与 business_sentence 拼接。
2. 兜底优先用 rule_value（LLM 生成的自然业务描述），无则拼业务标量字段。
"""
from __future__ import annotations

import pytest

from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    _NON_BUSINESS_FIELDS,
    _sentence,
)


def _rule_with_structured_fields(**overrides: object) -> dict[str, object]:
    rule: dict[str, object] = {
        "rule_type": "通用规则",
        "psn_type": "退休人员",
        "med_type": "住院",
        "rule_value": "退休人员个人支付比例 = 职工支付比例 × 60%",
        "entities": [{"name": "退休人员", "type": "PERSON", "highlight": "退休人员"}],
        "relations": [{"subject": "退休人员", "predicate": "个人支付比例", "object": "60%"}],
        "priority": "高",
        "time_period": "年度",
        "admission_order": "首次",
        "setl_type": "按项目",
        "confidence": 0.9,
        "source_text": "退休人员个人支付比例为职工支付比例的60%。",
    }
    rule.update(overrides)
    return rule


def test_non_business_fields_exclude_structured_arrays() -> None:
    """entities / relations / priority / time_period 必须在 _NON_BUSINESS_FIELDS 中。"""
    for key in ("entities", "relations", "priority", "time_period", "admission_order", "setl_type", "confidence", "source_text"):
        assert key in _NON_BUSINESS_FIELDS, f"{key} 应排除出业务句子"


def test_sentence_fallback_uses_rule_value_not_entities_transcription() -> None:
    """兜底生成 business_sentence：优先 rule_value，不出现 entities 转述。"""
    rule = _rule_with_structured_fields()
    sentence = _sentence(rule)
    assert "退休人员个人支付比例 = 职工支付比例 × 60%" in sentence
    assert "entities" not in sentence
    assert "relations" not in sentence


def test_sentence_fallback_without_rule_value_picks_business_scalars() -> None:
    """无 rule_value 时兜底拼业务标量字段，不含 entities/relations。"""
    rule = _rule_with_structured_fields(rule_value="")
    sentence = _sentence(rule)
    assert "退休人员" in sentence
    assert "entities" not in sentence
    assert "relations" not in sentence


def test_sentence_known_rule_type_unchanged() -> None:
    """payment_ratio 等已知类型的句子生成保持原样。"""
    rule = _rule_with_structured_fields(rule_type="payment_ratio", payment_ratio="80%")
    sentence = _sentence(rule)
    assert sentence == "退休人员住院时，统筹基金支付比例为80%。"
