"""P7.3 policy_discovery_scanner 测试 — 扫描 rules 高频信号产出候选指标。

输入 policy_rules_v2 entity（详情字段为 FieldTrace dict {value,...}），统计高频
实体/关系/值域，产出候选指标列表（设计文档 §8.1），供人工确认后回写语义层。
"""
from src.knowledge_extension.rule_explanation.policy_discovery_scanner import (
    scan_rules_for_candidates,
)


def _ft(value):
    """构造 FieldTrace dict（policy_rules_v2 详情字段格式）。"""
    return {"value": value, "extracted_at": "2026-01-01", "schema_version": 1, "confidence": 0.9}


def _rule(rule_type="报销比例", entities=None, relations=None, payment_ratio=None):
    rule = {"rule_type": rule_type, "insu_type": "城镇职工"}
    if entities is not None:
        rule["entities"] = _ft(entities)
    if relations is not None:
        rule["relations"] = _ft(relations)
    if payment_ratio is not None:
        rule["payment_ratio"] = _ft(payment_ratio)
    return rule


def test_scan_frequent_entity_type():
    rules = [
        _rule(entities=[{"name": "阿司匹林", "type": "药品"}, {"name": "CT", "type": "检查"}]),
        _rule(entities=[{"name": "布洛芬", "type": "药品"}]),
    ]
    result = scan_rules_for_candidates(rules, min_count=2)
    ents = [c for c in result["candidates"] if c["kind"] == "entity"]
    assert any(c["value"] == "药品" and c["count"] == 2 for c in ents)
    assert not any(c["value"] == "检查" for c in ents)  # 只 1 次，不进


def test_scan_frequent_relation_pattern():
    rules = [
        _rule(relations=[{"subject": "规则", "predicate": "包含", "object": "药品"}]),
        _rule(relations=[{"subject": "规则", "predicate": "包含", "object": "药品"}]),
    ]
    result = scan_rules_for_candidates(rules, min_count=2)
    rels = [c for c in result["candidates"] if c["kind"] == "relation"]
    assert len(rels) == 1
    assert rels[0]["count"] == 2
    assert "包含" in rels[0]["value"]


def test_scan_value_domain_candidate():
    rules = [
        _rule(payment_ratio="85%"),
        _rule(payment_ratio="85%"),
        _rule(payment_ratio="90%"),
    ]
    result = scan_rules_for_candidates(rules, min_count=1)
    vds = [c for c in result["candidates"] if c["kind"] == "value_domain"]
    vd = next(c for c in vds if c["field"] == "payment_ratio")
    assert set(vd["values"]) == {"85%", "90%"}


def test_scan_respects_min_count():
    """min_count 过滤：单次出现的 entity type 不进候选。"""
    rules = [_rule(entities=[{"name": "x", "type": "T"}])]
    result = scan_rules_for_candidates(rules, min_count=2)
    assert not any(c["kind"] == "entity" for c in result["candidates"])


def test_scan_empty_rules():
    result = scan_rules_for_candidates([], min_count=2)
    assert result["candidates"] == []
    assert result["total_rules"] == 0


def test_scan_unpacks_fieldtrace_and_bare_values():
    """兼容 FieldTrace dict 与裸值（entities 裸 list + payment_ratio FieldTrace）。"""
    rules = [{
        "rule_type": "封顶线",
        "entities": [{"name": "统筹基金", "type": "基金"}],  # 裸 list
        "payment_ratio": _ft("88%"),  # FieldTrace
    }, {
        "rule_type": "封顶线",
        "entities": [{"name": "大病基金", "type": "基金"}],
    }]
    result = scan_rules_for_candidates(rules, min_count=2)
    ents = [c for c in result["candidates"] if c["kind"] == "entity"]
    assert any(c["value"] == "基金" and c["count"] == 2 for c in ents)
