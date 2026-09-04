"""query_rules_by_doc 测试 — P5 执行器的真实 read（按 doc_id 查 policy_rules_v2）。

注入 fake collection，隔离 Milvus。
[依据: docs/steering/政策知识管线设计.md §6.1 read-modify-write]
"""
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    _parse_amount_band,
    query_rules_by_doc,
    rule_to_entity,
)


class _FakeCol:
    """pymilvus Collection 替身：记录 query 调用，按 doc_id 过滤返回。"""

    def __init__(self, rows):
        self._rows = rows
        self.last_query: tuple | None = None

    def load(self):
        pass

    def query(self, expr, output_fields, limit):
        self.last_query = (expr, output_fields, limit)
        # 简化：按 expr 里出现的 "doc_id" 值过滤
        return [r for r in self._rows if f'"{r["doc_id"]}"' in expr]


def test_query_returns_rules_for_doc():
    rows = [
        {"rule_id": "r1", "doc_id": "d1"},
        {"rule_id": "r2", "doc_id": "d2"},
    ]
    col = _FakeCol(rows)
    result = query_rules_by_doc("d1", col=col)
    assert len(result) == 1
    assert result[0]["rule_id"] == "r1"


def test_query_empty_when_no_match():
    col = _FakeCol([{"rule_id": "r1", "doc_id": "d1"}])
    assert query_rules_by_doc("no_such", col=col) == []


def test_query_expr_filters_by_doc_id():
    """query expr 应含 doc_id == "d1"。"""
    col = _FakeCol([{"rule_id": "r1", "doc_id": "d1"}])
    query_rules_by_doc("d1", col=col)
    expr = col.last_query[0]
    assert "doc_id" in expr
    assert '"d1"' in expr


def test_query_uses_star_output_fields():
    """output_fields=['*'] 取全部字段（含 dynamic 详情字段）。"""
    col = _FakeCol([{"rule_id": "r1", "doc_id": "d1"}])
    query_rules_by_doc("d1", col=col)
    assert col.last_query[1] == ["*"]


def test_parse_amount_band_over_x_to_y():
    """超过3万元至4万元 → (30000, 40000)。"""
    assert _parse_amount_band("超过3万元至4万元") == (30000, 40000)


def test_parse_amount_band_over_x():
    """超过4万元 → (40000, -1)。"""
    assert _parse_amount_band("超过4万元") == (40000, -1)


def test_parse_amount_band_deductible_to_cap():
    """起付标准至3万元 → (1300, 30000)，默认起付线 1300。"""
    assert _parse_amount_band("起付标准至3万元") == (1300, 30000)


def test_parse_amount_band_uses_deductible_amount():
    """起付标准至3万元 + deductible_amount=1500 → (1500, 30000)。"""
    assert _parse_amount_band("起付标准至3万元", deductible_amount="1500") == (1500, 30000)


def test_parse_amount_band_plain_yuan():
    """1000元至2000元 → (1000, 2000)。"""
    assert _parse_amount_band("1000元至2000元") == (1000, 2000)


def test_parse_amount_band_unparseable_returns_zero():
    """第1档 / 空字符串 → (0, 0)。"""
    assert _parse_amount_band("第1档") == (0, 0)
    assert _parse_amount_band("") == (0, 0)
    assert _parse_amount_band(None) == (0, 0)


def test_parse_amount_band_below_x():
    """Issue #33：2万元以下 / 不超过4万元 → (0, 20000) / (0, 40000)，下限 0 可与未解析哨兵 (0,0) 区分。"""
    assert _parse_amount_band("2万元以下") == (0, 20000)
    assert _parse_amount_band("2000元以内") == (0, 2000)
    assert _parse_amount_band("不超过4万元") == (0, 40000)


def test_rule_to_entity_parses_amount_band():
    """rule_to_entity 应把 amount_band 解析为 amount_band_min/max。"""
    rule = {
        "rule_id": "r1",
        "amount_band": "超过3万元至4万元",
        "source_text": "测试文本",
    }
    entity = rule_to_entity(rule, vector=[0.0] * 768)
    assert entity["amount_band_min"] == 30000
    assert entity["amount_band_max"] == 40000
    # 原始文本作为 detail 字段保留
    assert entity["amount_band"]["value"] == "超过3万元至4万元"
