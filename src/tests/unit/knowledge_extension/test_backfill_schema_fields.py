"""LLM 输出契约回填测试（闭环 B：提取遵循度兜底）。

背景（实测 2026-08-14）：提示词含 24 字段，DeepSeek 只回 4 字段。
契约要求"原文未提及填空字符串\"\""——LLM 省略键时由后端补齐，下游消费才稳定。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    _backfill_schema_fields,
)


def test_backfill_fills_missing_field_keys() -> None:
    facts = [{"fact_text": "退休人员报销90%", "rules": [{"psn_type": "退休人员"}]}]
    result = _backfill_schema_fields(facts, ["psn_type", "dyylhzzj", "payment_ratio"])
    rule = result[0]["rules"][0]
    assert rule["psn_type"] == "退休人员", "已有值不被覆盖"
    assert rule["dyylhzzj"] == ""
    assert rule["payment_ratio"] == ""


def test_backfill_skips_non_dict_rules_and_empty_codes() -> None:
    facts = [{"fact_text": "x", "rules": ["not-a-dict"]}]
    assert _backfill_schema_fields(facts, ["a"]) == facts, "非 dict 规则原样保留"
    assert _backfill_schema_fields(facts, []) == facts, "无契约字段时不改动"


def test_backfill_keeps_llm_added_extra_fields() -> None:
    facts = [{"fact_text": "x", "rules": [{"confidence": 0.9}]}]
    result = _backfill_schema_fields(facts, ["psn_type"])
    rule = result[0]["rules"][0]
    assert rule["confidence"] == 0.9, "LLM 自加字段（如 confidence）保留"
    assert rule["psn_type"] == ""


def test_backfill_splits_multi_population_rule_into_atomic_rules() -> None:
    facts = [{
        "fact_text": "在职职工和退休人员最高支付限额为20万元",
        "rules": [{
            "rule_id": "rule_001",
            "rule_type": "封顶线",
            "psn_type": "在职职工, 退休人员",
            "cap_amount": "20万元",
        }],
    }]

    result = _backfill_schema_fields(facts, ["rule_id", "psn_type", "cap_amount"])

    assert [rule["psn_type"] for rule in result[0]["rules"]] == [
        "在职职工",
        "退休人员",
    ]
    assert len({rule["rule_id"] for rule in result[0]["rules"]}) == 2
