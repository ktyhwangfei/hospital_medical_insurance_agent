"""政策规则混合检索服务（设计文档 §4.2）。

基于 policy_rules_v2（自带 vector 复用 + 核心维度）实现三模式检索，
按 fact_id 分组并 join policy_facts.fact_text。

三模式统一在 policy_rules_v2 上（无需跨 collection 召回，因 rules 复用 fact 向量）：
- precise: MilvusClient.query(filter=核心维度)
- semantic: MilvusClient.search(data=[query_vec])
- hybrid: MilvusClient.search(data=[query_vec], filter=核心维度)

[来源: docs/steering/政策知识管线设计文档.md §4.1（rules 复用 fact 向量） / §4.2（三种检索）]
"""
from __future__ import annotations

from typing import Any

from pymilvus import MilvusClient

# 核心维度（可做标量过滤）
CORE_DIMS = ("rule_type", "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type")

# rules 输出字段（核心维度 + 关键详情字段）
RULE_OUTPUT_FIELDS = [
    "rule_id", "fact_id", "doc_id", "rule_type", "insu_type", "med_type",
    "hosp_lv", "psn_type", "setl_type", "schema_version",
    "payment_ratio", "deductible_amount", "cap_amount", "amount_band",
    "rule_value", "source_text",
]


class RulesSearchService:
    """政策规则三模式检索 + 按 fact 分组。"""

    def __init__(
        self,
        uri: str = "http://127.0.0.1:19530",
        rules_col_name: str = "policy_rules_v2",
        facts_col_name: str = "policy_facts",
    ):
        self._client = MilvusClient(uri=uri, timeout=10)
        self._rules_col = rules_col_name
        self._facts_col = facts_col_name

    @staticmethod
    def _build_filter(filters: dict[str, str]) -> str:
        """核心维度 dict → Milvus filter 表达式。空 filters → 空串（不过滤）。"""
        parts = [f'{d} == "{filters[d]}"' for d in CORE_DIMS if filters.get(d)]
        return " and ".join(parts)

    def _ensure_loaded(self):
        """load rules + facts collection（Milvus 查询前必须 load）。幂等。"""
        self._client.load_collection(self._rules_col)
        self._client.load_collection(self._facts_col)

    def search_precise(self, filters: dict[str, str], top_k: int = 20) -> list[dict[str, Any]]:
        """精准标量检索：按核心维度过滤 policy_rules_v2。

        [来源: §4.2 精确模式]
        """
        self._ensure_loaded()
        flt = self._build_filter(filters)
        rules = self._client.query(
            collection_name=self._rules_col,
            filter=flt or "",
            output_fields=RULE_OUTPUT_FIELDS,
            limit=top_k,
        )
        return self._group_by_fact(rules)

    def search_semantic(self, query_text: str, top_k: int = 20) -> list[dict[str, Any]]:
        """语义检索：query 向量化 → policy_rules_v2 向量搜索（复用 fact 向量）。

        [来源: §4.2 语义模式]
        """
        from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
            get_embedding_provider,
        )
        self._ensure_loaded()
        vec = get_embedding_provider().encode([query_text])[0]
        results = self._client.search(
            collection_name=self._rules_col,
            data=[vec],
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            output_fields=RULE_OUTPUT_FIELDS,
        )
        return self._group_by_fact(self._parse_hits(results))

    def search_hybrid(
        self, query_text: str, filters: dict[str, str], top_k: int = 20
    ) -> list[dict[str, Any]]:
        """混合检索：向量召回 + 核心维度标量过滤。

        [来源: §4.2 混合模式]
        """
        from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
            get_embedding_provider,
        )
        self._ensure_loaded()
        vec = get_embedding_provider().encode([query_text])[0]
        flt = self._build_filter(filters)
        results = self._client.search(
            collection_name=self._rules_col,
            data=[vec],
            anns_field="vector",
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            filter=flt or "",
            limit=top_k,
            output_fields=RULE_OUTPUT_FIELDS,
        )
        return self._group_by_fact(self._parse_hits(results))

    @staticmethod
    def _parse_hits(results) -> list[dict[str, Any]]:
        """解析 MilvusClient.search 返回（list[list[hit]]）→ rules list（带 score）。"""
        rules = []
        for hit in results[0]:
            e = dict(hit["entity"])
            e["score"] = float(hit["distance"])
            rules.append(e)
        return rules

    def _group_by_fact(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按 fact_id 聚合 rules，join policy_facts.fact_text。"""
        by_fact: dict[str, list[dict]] = {}
        for r in rules:
            by_fact.setdefault(r.get("fact_id", ""), []).append(r)
        groups: list[dict[str, Any]] = []
        for fid, rs in by_fact.items():
            fact_text = ""
            if fid:
                fr = self._client.query(
                    collection_name=self._facts_col,
                    filter=f'fact_id == "{fid}"',
                    output_fields=["fact_text"], limit=1,
                )
                if fr:
                    fact_text = fr[0].get("fact_text", "")
            groups.append({"fact_id": fid, "fact_text": fact_text, "rules": rs})
        return groups
