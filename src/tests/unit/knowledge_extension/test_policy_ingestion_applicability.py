"""policy_ingestion 适用性字段预填充测试（Issue #25）。"""
from __future__ import annotations

from typing import Any

import pytest

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_ingestion import (
    build_ingest_records,
)


class _FakeEmbeddingProvider:
    """固定维度向量，避免加载真实模型。"""

    dim = 768

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dim for _ in texts]


@pytest.fixture
def provider() -> _FakeEmbeddingProvider:
    return _FakeEmbeddingProvider()


def test_build_ingest_records_prefills_applicability_from_doc_metadata(provider: _FakeEmbeddingProvider) -> None:
    facts = [
        {
            "fact_text": "测试事实",
            "rules": [
                {
                    "rule_type": "支付比例",
                    "insu_type": "城镇职工基本医疗保险",
                    "source_text": "测试规则",
                }
            ],
        }
    ]
    doc_metadata = {
        "policy_region": "北京",
        "effective_date": "2024-01-01",
        "abolition_date": "2025-12-31",
        "validity": "valid",
    }
    fact_records, rule_entities = build_ingest_records(
        facts,
        doc_id="doc_001",
        provider=provider,
        extracted_at="2024-09-01T00:00:00",
        doc_metadata=doc_metadata,
    )

    assert len(fact_records) == 1
    assert len(rule_entities) == 1
    entity = rule_entities[0]
    assert entity["region"] == "北京"
    assert entity["effective_date"] == "2024-01-01"
    assert entity["expiry_date"] == "2025-12-31"
    assert entity["publish_status"] == "published"
    assert entity["doc_id"] == "doc_001"


def test_build_ingest_records_rule_value_takes_precedence_over_metadata(provider: _FakeEmbeddingProvider) -> None:
    facts = [
        {
            "fact_text": "测试事实",
            "rules": [
                {
                    "rule_type": "支付比例",
                    "region": "上海",
                    "effective_date": "2023-06-01",
                    "source_text": "测试规则",
                }
            ],
        }
    ]
    doc_metadata = {
        "policy_region": "北京",
        "effective_date": "2024-01-01",
        "abolition_date": "2025-12-31",
        "validity": "valid",
    }
    _, rule_entities = build_ingest_records(
        facts,
        doc_id="doc_001",
        provider=provider,
        doc_metadata=doc_metadata,
    )

    entity = rule_entities[0]
    # rule 自身值优先于文档元数据
    assert entity["region"] == "上海"
    assert entity["effective_date"] == "2023-06-01"


def test_build_ingest_records_uses_defaults_without_metadata(provider: _FakeEmbeddingProvider) -> None:
    facts = [
        {
            "fact_text": "测试事实",
            "rules": [{"rule_type": "支付比例", "source_text": "测试规则"}],
        }
    ]
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        _DEFAULT_EFFECTIVE_DATE,
        _DEFAULT_EXPIRY_DATE,
        _DEFAULT_PUBLISH_STATUS,
        _DEFAULT_REGION,
    )

    _, rule_entities = build_ingest_records(
        facts,
        doc_id="doc_001",
        provider=provider,
    )

    entity = rule_entities[0]
    assert entity["region"] == _DEFAULT_REGION
    assert entity["effective_date"] == _DEFAULT_EFFECTIVE_DATE
    assert entity["expiry_date"] == _DEFAULT_EXPIRY_DATE
    assert entity["publish_status"] == _DEFAULT_PUBLISH_STATUS
