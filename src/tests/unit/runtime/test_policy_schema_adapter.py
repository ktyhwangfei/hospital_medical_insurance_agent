"""P10.1a policy_rules 新旧 schema 适配层测试。

新 collection（policy_rules_v2）与旧 policy_rules 有 3 处不兼容：
1. 向量字段名：旧 `embedding` → 新 `vector`
2. 详情字段值：旧裸值 `"85%"` → 新 FieldTrace dict `{value, extracted_at, ...}`
3. 政策标识：旧 `policy_id`/`clause_id` → 新 `doc_id`

读入口切换 collection 时需适配，下游消费者无感（始终拿裸值）。

依据：docs/steering/政策知识管线开发计划.md P10.1。
"""
from __future__ import annotations

from src.runtime.policy_qa.policy_rules_search import (
    normalize_rule_entity,
    resolve_anns_field,
)


def test_resolve_anns_field_legacy():
    """旧 collection 向量字段名为 embedding。"""
    assert resolve_anns_field("policy_rules") == "embedding"


def test_resolve_anns_field_v2():
    """v2 collection 向量字段名为 vector。"""
    assert resolve_anns_field("policy_rules_v2") == "vector"


def test_normalize_v2_detail_dict_unwrapped_to_value():
    """v2 的 detail 字段是 FieldTrace dict，归一化为裸 value（下游无感）。"""
    entity = {
        "payment_ratio": {"value": "85%", "extracted_at": "t", "confidence": 0.9},
        "source_text": {"value": "原文", "extracted_at": "t"},
        "rule_type": "支付比例",  # 核心维度（裸值）不变
        "insu_type": "城镇职工基本医疗保险",
    }
    r = normalize_rule_entity(entity, is_v2=True)
    assert r["payment_ratio"] == "85%"
    assert r["source_text"] == "原文"
    assert r["rule_type"] == "支付比例"  # 核心维度保持裸值
    assert r["insu_type"] == "城镇职工基本医疗保险"


def test_normalize_legacy_unchanged():
    """旧 schema 的裸值 detail 不被改动。"""
    entity = {"payment_ratio": "85%", "rule_type": "支付比例"}
    r = normalize_rule_entity(entity, is_v2=False)
    assert r == entity


def test_normalize_v2_missing_value_key_kept_as_is():
    """dict 无 value 键时保持原样（防御异常数据）。"""
    entity = {"payment_ratio": {"foo": "bar"}}
    r = normalize_rule_entity(entity, is_v2=True)
    assert r["payment_ratio"] == {"foo": "bar"}
