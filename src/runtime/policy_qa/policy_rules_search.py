"""
医保政策问答 RAG - policy_rules_v2 搜索引擎

搜索 Milvus policy_rules_v2 集合（schema-driven 提取的结构化政策规则，
向量复用 policy_facts）。返回的 detail 字段已解包为裸值，下游消费者无感。
"""

from __future__ import annotations

import logging
from typing import Any

from pymilvus import MilvusClient

logger = logging.getLogger(__name__)

# policy_rules_v2 collection（schema-driven 提取）
COLLECTION_NAME = "policy_rules_v2"
# 向量字段名（复用 policy_facts 的向量）
VECTOR_FIELD = "vector"

# 核心维度字段（固定列，裸值）
CORE_FIELDS = (
    "rule_id", "fact_id", "doc_id",
    "rule_type", "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
)

# 详情字段（落 dynamic field，值是 FieldTrace dict，需解包 .value）
DETAIL_FIELDS = (
    "payment_ratio", "deductible_amount", "cap_amount", "amount_band",
    "time_period", "admission_order", "priority", "rule_value", "source_text",
)

# 检索输出字段
OUTPUT_FIELDS = list(CORE_FIELDS) + list(DETAIL_FIELDS)


def unpack_detail(entity: dict[str, Any]) -> dict[str, Any]:
    """detail 字段落 dynamic field，值是 FieldTrace dict，解包为裸 value。

    并将 doc_id 复制到 policy_id，兼容下游依赖 policy_id 的消费者。
    """
    for f in DETAIL_FIELDS:
        v = entity.get(f)
        if isinstance(v, dict) and "value" in v:
            entity[f] = v["value"]
    if "policy_id" not in entity:
        entity["policy_id"] = entity.get("doc_id", "")
    return entity


class PolicyRulesSearchEngine:
    """policy_rules_v2 搜索引擎（MilvusClient API）。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        embedding_kind: str = "sentence_transformer",
        collection_name: str = COLLECTION_NAME,
    ):
        self.client = MilvusClient(uri=f"http://{host}:{port}")
        self.collection_name = collection_name
        self._init_embedding(embedding_kind)
        logger.info(f"Initialized PolicyRulesSearchEngine: {self.collection_name}")

    def _init_embedding(self, kind: str) -> None:
        """初始化嵌入提供者。"""
        if kind == "hash":
            from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import HashEmbeddingProvider
            # 384 维匹配历史 policy_rules 维度（仅测试用）
            self.embedding_provider = HashEmbeddingProvider(dim=384)
        else:
            from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import SentenceTransformerEmbeddingProvider
            self.embedding_provider = SentenceTransformerEmbeddingProvider()

    def search(
        self,
        question: str,
        top_k: int = 10,
        expr: str | None = None,
    ) -> list[dict[str, Any]]:
        """向量检索 policy_rules_v2，返回匹配的政策规则（detail 已解包为裸值）。"""
        try:
            vector = self.embedding_provider.encode([question])[0]
            results = self.client.search(
                collection_name=self.collection_name,
                data=[vector],
                anns_field=VECTOR_FIELD,
                search_params={"metric_type": "COSINE", "params": {"ef": 64}},
                limit=top_k,
                filter=expr,
                output_fields=OUTPUT_FIELDS,
            )
            # MilvusClient.search() 返回 list[list[dict]]，外层对应查询向量
            rules = []
            for query_hits in results:
                for hit in query_hits:
                    entity = {f: hit["entity"].get(f) for f in OUTPUT_FIELDS}
                    entity = unpack_detail(entity)
                    entity["score"] = (
                        float(hit["distance"])
                        if hit.get("distance") is not None
                        else 0.0
                    )
                    rules.append(entity)
            logger.info(
                f"Searched {self.collection_name}: question='{question[:50]}...', found {len(rules)} rules"
            )
            return rules
        except Exception:
            logger.exception("Failed to search policy_rules_v2")
            return []

    def search_with_context(
        self,
        question: str,
        insu_type: str | None = None,
        med_type: str | None = None,
        psn_type: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """带上下文的检索 — 优先纯标量过滤（query），回退向量搜索。"""
        parts = []
        if insu_type:
            parts.append(f'insu_type like "%{insu_type}%"')
        if med_type:
            parts.append(f'med_type like "%{med_type}%"')
        if psn_type:
            # 人员类型可能是"退休/在职"组合值，用 like 模糊匹配
            parts.append(f'psn_type like "%{psn_type}%"')

        expr = " and ".join(parts) if parts else None

        if expr:
            # 优先纯标量查询（不依赖向量相似度）
            try:
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter=expr,
                    output_fields=OUTPUT_FIELDS,
                    limit=top_k,
                )
                if results:
                    for r in results:
                        unpack_detail(r)
                        r["score"] = 1.0  # 标量匹配默认满分
                    return results
            except Exception:
                pass

        # 回退：标量过滤 + 向量搜索
        return self.search(question, top_k=top_k, expr=expr)
