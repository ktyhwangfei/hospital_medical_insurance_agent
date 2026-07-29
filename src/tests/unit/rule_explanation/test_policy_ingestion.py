"""build_ingest_records 单测（P3 Task 3 核心：向量化 + rule_to_entity + 向量复用 + fact_id 关联）。

不连 Milvus、不加载模型（用 FakeProvider），快且确定。
"""
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_ingestion import (
    build_ingest_records,
)


class FakeProvider:
    """固定向量 provider，便于断言向量复用。"""

    def encode(self, texts):
        return [[0.5] * 768 for _ in texts]

    @property
    def dim(self):
        return 768


def test_build_ingest_records_vector_reuse_and_lineage():
    facts = [
        {
            "fact_text": "起付标准1300元，统筹支付85%",
            "rules": [
                {"rule_type": "起付线", "insu_type": "城镇职工基本医疗保险",
                 "deductible_amount": "1300元", "confidence": 0.9},
                {"rule_type": "支付比例", "insu_type": "城镇职工基本医疗保险",
                 "payment_ratio": "85%", "confidence": 0.92},
            ],
        }
    ]
    provider = FakeProvider()
    fact_records, rule_entities = build_ingest_records(
        facts, doc_id="d1", provider=provider, extracted_at="2026-07-24T00:00:00"
    )

    # facts：向量化 + doc_id
    assert len(fact_records) == 1
    assert fact_records[0]["fact_text"] == "起付标准1300元，统筹支付85%"
    assert fact_records[0]["doc_id"] == "d1"
    assert len(fact_records[0]["vector"]) == 768
    assert fact_records[0]["created_at"] == "2026-07-24T00:00:00"

    # rules：2 条，都复用所属 fact 的向量 + 关联 fact_id
    assert len(rule_entities) == 2
    fact_vector = fact_records[0]["vector"]
    fact_id = fact_records[0]["fact_id"]
    for e in rule_entities:
        assert e["vector"] == fact_vector, "rule 应复用所属 fact 的向量（§4.1）"
        assert e["fact_id"] == fact_id, "rule 应关联所属 fact_id"
        assert e["doc_id"] == "d1", "rule 应携带所属文档 doc_id（LLM 不产 doc_id，由编排填）"

    # 核心维度进固定 schema
    types = {e["rule_type"] for e in rule_entities}
    assert types == {"起付线", "支付比例"}

    # 详情字段是字段级溯源对象（FieldTrace）
    da = next(e["deductible_amount"] for e in rule_entities if e["rule_type"] == "起付线")
    assert isinstance(da, dict) and da["value"] == "1300元"
    assert da["extracted_at"] == "2026-07-24T00:00:00" and da["confidence"] == 0.9
    pr = next(e["payment_ratio"] for e in rule_entities if e["rule_type"] == "支付比例")
    assert pr["value"] == "85%" and pr["confidence"] == 0.92


def test_build_ingest_records_empty_fact_text_uses_zero_vector():
    """fact_text 为空时用零向量（不崩），rule 仍关联。"""
    facts = [{"fact_text": "", "rules": [{"rule_type": "通用规则"}]}]
    fact_records, rule_entities = build_ingest_records(
        facts, doc_id="d2", provider=FakeProvider(), extracted_at="t"
    )
    assert fact_records[0]["vector"] == [0.0] * 768
    assert rule_entities[0]["vector"] == fact_records[0]["vector"]


def test_build_ingest_records_generates_unique_rule_id():
    """每个 rule_entity 必须有唯一非空 rule_id。

    LLM 提取的 rule 不含 rule_id（系统字段），build_ingest_records 必须生成，
    否则 Milvus 空 PK 去重导致 publish 数据丢失（P8.4 实测：publish 120 条只存活 1 条）。
    """
    facts = [{"fact_text": "测试", "rules": [
        {"rule_type": "起付线", "insu_type": "城镇职工"},
        {"rule_type": "支付比例", "insu_type": "城镇职工"},
    ]}]
    _, rule_entities = build_ingest_records(
        facts, doc_id="d3", provider=FakeProvider(), extracted_at="t"
    )
    ids = [e["rule_id"] for e in rule_entities]
    assert all(ids), "rule_id 不能为空（Milvus 空 PK 去重会丢数据）"
    assert len(set(ids)) == len(ids), "rule_id 必须唯一"
    assert all(rid.startswith("rule_") for rid in ids), "生成的 rule_id 应有 rule_ 前缀"
