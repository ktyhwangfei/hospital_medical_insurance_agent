"""
医保政策问答RAG系统 - policy_rules 搜索引擎

搜索 Milvus policy_rules 集合（使用 MilvusClient API）
"""

from __future__ import annotations

import logging
import os
from typing import Any

from pymilvus import MilvusClient

logger = logging.getLogger(__name__)

# P0.3 灰度开关：政策问答读入口可切换 collection。
# 默认旧名 policy_rules，保证灰度切换（P10.1）前生产行为零变化。
# 设环境变量 POLICY_RULES_COLLECTION=policy_rules_v2 即切到新模型。
DEFAULT_POLICY_RULES_COLLECTION = "policy_rules"


def resolve_policy_rules_collection(explicit: str | None = None) -> str:
    """解析政策规则 collection 名（P0.3 灰度开关）。

    优先级：显式参数 > 环境变量 POLICY_RULES_COLLECTION > 默认旧名。
    """
    if explicit:
        return explicit
    return os.environ.get(
        "POLICY_RULES_COLLECTION", DEFAULT_POLICY_RULES_COLLECTION
    )


class PolicyRulesSearchEngine:
    """
    policy_rules 集合搜索引擎
    
    使用 MilvusClient API 搜索 policy_rules 集合，返回匹配的政策规则。
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        embedding_kind: str = "sentence_transformer",
        collection_name: str | None = None,
    ):
        uri = f"http://{host}:{port}"
        self.client = MilvusClient(uri=uri)
        # P0.3 灰度开关：默认旧名，经 POLICY_RULES_COLLECTION 可切新 collection
        self.collection_name = resolve_policy_rules_collection(collection_name)

        # 初始化嵌入提供者
        self._init_embedding(embedding_kind)

        logger.info(f"Initialized PolicyRulesSearchEngine: {uri}")

    def _init_embedding(self, kind: str) -> None:
        """初始化嵌入提供者"""
        if kind == "hash":
            from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import HashEmbeddingProvider
            # 使用 384 维以匹配 policy_rules 集合（实际维度）
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
        """
        搜索 policy_rules 集合
        
        Args:
            question: 用户问题
            top_k: 返回数量
            expr: 过滤表达式
            
        Returns:
            匹配的规则列表
        """
        try:
            # 生成向量
            vector = self.embedding_provider.encode([question])[0]
            
            # 搜索参数
            search_params = {
                "metric_type": "COSINE",
                "params": {"ef": 64},
            }
            
            # 输出字段
            output_fields = [
                "rule_id", "fact_id", "policy_id", "clause_id", "source_text",
                "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
                "payment_ratio", "deductible_amount", "cap_amount",
                "rule_type", "rule_value", "amount_band",
            ]
            
            # 执行搜索（MilvusClient API）
            results = self.client.search(
                collection_name=self.collection_name,
                data=[vector],
                anns_field="embedding",
                search_params=search_params,
                limit=top_k,
                filter=expr,
                output_fields=output_fields,
            )
            
            # 转换结果: MilvusClient.search() 返回 list[list[dict]]
            # 外层对应每个查询向量，内层是命中结果
            rules = []
            for query_hits in results:
                for hit in query_hits:
                    entity = {}
                    for field in output_fields:
                        try:
                            entity[field] = hit["entity"].get(field)
                        except Exception:
                            entity[field] = None
                    
                    entity["score"] = float(hit["distance"]) if hit.get("distance") is not None else 0.0
                    rules.append(entity)
            
            logger.info(f"Searched policy_rules: question='{question[:50]}...', found {len(rules)} rules")
            return rules
            
        except Exception as e:
            logger.exception("Failed to search policy_rules")
            return []

    def search_with_context(
        self,
        question: str,
        insu_type: str | None = None,
        med_type: str | None = None,
        psn_type: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        带上下文的搜索 — 优先使用纯标量过滤（query），回退到向量搜索

        纯标量过滤不依赖 embedding 质量，直接按字段值匹配。
        如果标量过滤 0 结果，回退到向量搜索 + LIKE 宽松匹配。
        """
        # 输出字段
        output_fields = [
            "rule_id", "fact_id", "policy_id", "clause_id", "source_text",
            "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
            "payment_ratio", "deductible_amount", "cap_amount",
            "rule_type", "rule_value", "amount_band",
        ]

        # 构建标量过滤表达式
        parts = []
        if insu_type:
            parts.append(f'insu_type like "%{insu_type}%"')
        if med_type:
            parts.append(f'med_type like "%{med_type}%"')
        if psn_type:
            # 人员类型可能是"退休/在职"这种组合值，用 like 模糊匹配
            parts.append(f'psn_type like "%{psn_type}%"')

        expr = " and ".join(parts) if parts else None

        if expr:
            # ★ 优先使用纯标量查询（不依赖向量相似度）
            try:
                results = self.client.query(
                    collection_name=self.collection_name,
                    filter=expr,
                    output_fields=output_fields,
                    limit=top_k,
                )
                if results:
                    for r in results:
                        r["score"] = 1.0  # 标量匹配默认满分
                    return results
            except Exception:
                pass

        # 回退：标量过滤 + 向量搜索
        return self.search(question, top_k=top_k, expr=expr)
