"""query_rules_by_doc 测试 — P5 执行器的真实 read（按 doc_id 查 policy_rules_v2）。

注入 fake collection，隔离 Milvus。
[依据: docs/steering/政策知识管线设计.md §6.1 read-modify-write]
"""
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    query_rules_by_doc,
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
