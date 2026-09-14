"""宽泛问题事实单元检索器（Issue #37/#38 政策问答改造）。

基于结算单的问答走 `policy_rules_*` 结构化字段；
宽泛政策问答走 `policy_facts_*` 的语义单元（fact_text）向量搜索 + BM25 重排。
"""

from __future__ import annotations

from typing import Any

from pymilvus import MilvusClient

from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
    get_embedding_provider,
)
from src.knowledge_extension.rule_explanation.release_resolver import (
    resolve_facts_collection,
)
from src.runtime.policy_qa.structured_policy_retriever import _bm25_scores

# 向量 / BM25 融合权重：事实单元场景以稠密向量为主，BM25 压制同主题噪声
_DENSE_WEIGHT = 0.6
_BM25_WEIGHT = 0.4


def retrieve_broad_fact_units(
    question: str,
    *,
    host: str = "127.0.0.1",
    port: str = "19530",
    top_k: int = 20,
    final_top_n: int = 5,
    collection_name: str | None = None,
) -> list[dict[str, Any]]:
    """在 policy_facts_* 集合上做向量召回 + BM25 重排，返回事实单元列表。

    返回项包含：
    - fact_text: 事实单元全文
    - doc_id: 来源文档 ID
    - score: 融合后的综合分
    - dense_score: 向量余弦分
    - bm25_score: 词面重合分
    """
    if not question or not question.strip():
        return []

    collection = collection_name or resolve_facts_collection(host, port)
    client = MilvusClient(uri=f"http://{host}:{port}")
    vector = get_embedding_provider().encode([question])[0]

    raw = client.search(
        collection_name=collection,
        data=[vector],
        anns_field="vector",
        limit=top_k,
        output_fields=["doc_id", "fact_text", "unit_id", "unit_source_text"],
    )

    hits: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    for batch in raw:
        for h in batch:
            text = str(h["entity"].get("fact_text") or "").strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            hits.append({
                "fact_text": text,
                "doc_id": str(h["entity"].get("doc_id") or ""),
                "unit_id": str(h["entity"].get("unit_id") or ""),
                "unit_source_text": str(h["entity"].get("unit_source_text") or ""),
                "dense_score": float(h["distance"]) if h.get("distance") is not None else 0.0,
            })

    if not hits:
        return []

    bm25_scores = _bm25_scores(question, [h["fact_text"] for h in hits])
    for h, bm25 in zip(hits, bm25_scores):
        h["bm25_score"] = bm25
        h["score"] = _DENSE_WEIGHT * h["dense_score"] + _BM25_WEIGHT * bm25

    hits.sort(key=lambda x: x["score"], reverse=True)
    return hits[:final_top_n]
