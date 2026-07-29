"""政策入库编排：从 LLM 提取的 facts 构建 (fact_records, rule_entities)。

核心逻辑（设计文档 §4.1 向量复用、§3.3 字段级溯源）：
- fact_text 向量化（provider）。
- 每条 rule 用所属 fact 的 vector（同 fact 多 rules 共享，节省存储 + 语义一致）。
- rule 详情字段包成 FieldTrace（rule_to_entity）。
- rule 关联所属 fact_id。

[来源: docs/steering/政策知识管线设计文档.md §2 数据流 / §3.3 / §4.1]
"""
from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    rule_to_entity,
)

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import EmbeddingProvider


def build_ingest_records(
    facts: list[dict[str, Any]],
    doc_id: str,
    provider: "EmbeddingProvider",
    extracted_at: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从 LLM 提取的 facts 构建 (fact_records, rule_entities)。

    Args:
        facts: LLM 产出，每条 {fact_text, rules: [...]}。
        doc_id: 所属政策文档 ID。
        provider: 向量化 provider（fact_text → vector）。
        extracted_at: 本次提取时间（ISO），写入字段级溯源。
    Returns:
        fact_records: 每条 {fact_id, doc_id, fact_text, vector, created_at}。
        rule_entities: 每条为 rule_to_entity 产出 + fact_id。
    """
    fact_records: list[dict[str, Any]] = []
    rule_entities: list[dict[str, Any]] = []

    for fact in facts:
        fact_text = fact.get("fact_text", "") or ""
        # 向量化；空文本用零向量避免 provider 对空串报错
        if fact_text:
            vector = provider.encode([fact_text])[0]
        else:
            vector = [0.0] * provider.dim

        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        fact_records.append({
            "fact_id": fact_id,
            "doc_id": doc_id,
            "fact_text": fact_text,
            "vector": vector,
            "created_at": extracted_at,
        })

        for rule in fact.get("rules", []):
            # rule_id 是系统字段（LLM 不产），必须生成唯一值，
            # 否则 Milvus 空 PK 去重导致 publish 数据丢失
            rule_id = rule.get("rule_id") or f"rule_{uuid.uuid4().hex[:12]}"
            entity = rule_to_entity(
                {**rule, "rule_id": rule_id},
                vector=vector,            # 复用所属 fact 向量（§4.1）
                extracted_at=extracted_at,
                confidence=rule.get("confidence", 0.7),
            )
            entity["fact_id"] = fact_id   # 关联回所属 fact
            entity["doc_id"] = doc_id     # LLM 不产 doc_id，由编排填
            rule_entities.append(entity)

    return fact_records, rule_entities
