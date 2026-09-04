"""MVU-3 单元测试：MilvusRuleKnowledgePort 适配器与工厂 fail-closed。"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.answer_verification import milvus_port
from src.knowledge_extension.rule_explanation.answer_verification.milvus_port import (
    MilvusRuleKnowledgePort,
    _like_needle,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    source_text_hash,
)

_SOURCE = "起付标准至3万元职工支付15%。\n\n超过3万元至4万元职工支付12%。"


class _FakeMilvusClient:
    """确定性 Milvus 客户端桩：按 filter 关键字路由到预置记录。"""

    def __init__(self, records: list[dict] | None = None, collections: list[str] | None = None) -> None:
        self.records = records or []
        self.collections = collections or []
        self.queries: list[dict] = []

    def list_collections(self) -> list[str]:
        return self.collections

    def query(self, *, collection_name: str, filter: str, output_fields: list, limit: int) -> list[dict]:
        self.queries.append({"collection": collection_name, "filter": filter, "limit": limit})
        if 'rule_id == "rule-1"' in filter:
            return [record for record in self.records if record.get("rule_id") == "rule-1"][:limit]
        if "source_text like" in filter:
            needle = filter.split('%')[1]
            return [record for record in self.records if needle in str(record.get("source_text", ""))][:limit]
        return []


def _field_trace_record() -> dict:
    """模拟 policy_rules_v2 落库形态：detail 字段是 FieldTrace dict。"""
    return {
        "rule_id": "rule-1",
        "doc_id": "doc-1",
        "rule_type": "支付比例",
        "psn_type": "退休人员",
        "source_text": {"value": _SOURCE, "trace": "ignored"},
        "payment_ratio": {"value": "0.15"},
        "amount_band": {"value": "650-30000"},
        "rule_value": {"value": "15%"},
    }


class TestLikeNeedle:
    def test_strips_trailing_ellipsis_and_whitespace(self):
        # % 是 LIKE 通配符：按通配符切段取最长连续段作为检索针
        assert _like_needle("  起付标准至3万元职工支付15%。...  ") == "起付标准至3万元职工支付15"

    def test_truncates_to_needle_length(self):
        assert len(_like_needle("一" * 100)) == milvus_port._NEEDLE_LENGTH

    def test_strips_wildcards_and_quotes(self):
        assert _like_needle('10%_x"') == "10"

    def test_empty_text_returns_empty(self):
        assert _like_needle("") == ""
        assert _like_needle("   ") == ""


class TestMilvusRuleKnowledgePort:
    def test_get_rule_by_id_unpacks_field_trace(self):
        client = _FakeMilvusClient(records=[_field_trace_record()])
        port = MilvusRuleKnowledgePort(client=client)
        rule = port.get_rule_by_id("rule-1")
        assert rule is not None
        assert rule.rule_id == "rule-1"
        assert rule.policy_id == "doc-1"
        assert rule.source_text == _SOURCE
        assert rule.source_text_hash == source_text_hash(_SOURCE)
        assert rule.payment_ratio == "0.15"
        assert rule.amount_band == "650-30000"
        assert rule.psn_type == "退休人员"

    def test_get_rule_by_id_missing_returns_none(self):
        port = MilvusRuleKnowledgePort(client=_FakeMilvusClient())
        assert port.get_rule_by_id("rule-x") is None
        assert port.get_rule_by_id("") is None

    def test_find_rules_by_text_uses_like_needle(self):
        client = _FakeMilvusClient(records=[_field_trace_record()])
        port = MilvusRuleKnowledgePort(client=client)
        # 输入含 LIKE 通配符 %，剔除后检索针仍是 source_text 片段
        rules = port.find_rules_by_text("起付标准至3万元职工支付15%")
        assert len(rules) == 1
        assert client.queries[0]["filter"].startswith("source_text like")

    def test_find_rules_by_text_empty_skips_query(self):
        client = _FakeMilvusClient()
        port = MilvusRuleKnowledgePort(client=client)
        assert port.find_rules_by_text("") == []
        assert client.queries == []

    def test_find_rules_by_title_degrades_to_text_search(self):
        client = _FakeMilvusClient(records=[_field_trace_record()])
        port = MilvusRuleKnowledgePort(client=client)
        rules = port.find_rules_by_title("起付标准至3万元职工支付15%。...")
        assert len(rules) == 1

    def test_find_similar_rules_returns_empty_fail_closed(self):
        client = _FakeMilvusClient()
        port = MilvusRuleKnowledgePort(client=client)
        assert port.find_similar_rules("任意文本") == []
        assert client.queries == []


class TestRuleKnowledgePortFactory:
    def test_factory_returns_none_when_collection_missing(self, monkeypatch):
        monkeypatch.setattr(
            milvus_port,
            "MilvusRuleKnowledgePort",
            lambda **kwargs: MilvusRuleKnowledgePort(client=_FakeMilvusClient(collections=[])),
        )
        milvus_port.reset_rule_knowledge_port_cache()
        assert milvus_port.get_rule_knowledge_port() is None
        milvus_port.reset_rule_knowledge_port_cache()

    def test_factory_returns_port_when_collection_present(self, monkeypatch):
        monkeypatch.setattr(
            milvus_port,
            "MilvusRuleKnowledgePort",
            lambda **kwargs: MilvusRuleKnowledgePort(
                client=_FakeMilvusClient(collections=["policy_rules_v2"])
            ),
        )
        milvus_port.reset_rule_knowledge_port_cache()
        assert milvus_port.get_rule_knowledge_port() is not None
        milvus_port.reset_rule_knowledge_port_cache()

    def test_factory_fail_closed_on_connection_error(self, monkeypatch):
        def _explode(**kwargs):
            raise ConnectionError("milvus unreachable")

        monkeypatch.setattr(milvus_port, "MilvusRuleKnowledgePort", _explode)
        milvus_port.reset_rule_knowledge_port_cache()
        assert milvus_port.get_rule_knowledge_port() is None
        milvus_port.reset_rule_knowledge_port_cache()
