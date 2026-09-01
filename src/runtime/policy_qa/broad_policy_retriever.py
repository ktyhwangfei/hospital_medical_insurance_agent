"""
宽泛问题混合检索器（BroadPolicyRetriever）

针对没有结算单上下文的宽泛政策问题（如“北京职工医保住院报销比例是多少”），
走向量语义召回 + BM25 关键词召回 + 适用性字段精排，返回政策证据。

设计约束（Issue #25 阶段 2-3）：
- 不修改提取契约 / Milvus schema / 存量数据；只消费 policy_rules_v2 已有字段。
- 向量复用 policy_rules_v2.vector（bge-base-zh-v1.5，768 维），默认真实 bge 模型。
- 关键词召回使用 rank-bm25 + jieba 分词，在适用性过滤后的候选池上计算真实 BM25 分数。
- 适用性字段（region / effective_date / expiry_date / publish_status / is_remote）
  用于过滤与精排。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import grpc
import jieba
from pymilvus import MilvusClient
from rank_bm25 import BM25Okapi
from pymilvus.exceptions import (
    ConnectError,
    ConnectionNotExistException,
    ErrorCode,
    MilvusException,
    MilvusUnavailableException,
)

from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    get_embedding_provider,
)
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    POLICY_RULES_V2_VECTOR_DIM,
)
from src.runtime.policy_qa.policy_rules_search import COLLECTION_NAME, OUTPUT_FIELDS, unpack_detail
from src.runtime.policy_qa.structured_policy_retriever import (
    PolicyRetrievalUnavailableError,
    StructuredPolicyEvidence,
    _DEFAULT_REGION,
)

logger = logging.getLogger(__name__)

_TRANSIENT_MILVUS_ERROR_TYPES = (
    ConnectionError,
    TimeoutError,
    ConnectError,
    ConnectionNotExistException,
    MilvusUnavailableException,
)
_TRANSIENT_GRPC_CODES = {
    grpc.StatusCode.ABORTED,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.INTERNAL,
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.UNKNOWN,
}

_DEFAULT_EXPIRY_DATE = "9999-12-31"
_DEFAULT_REFERENCE_DATE = "2026-01-01"
_RRF_K = 60


def _is_transient_milvus_error(exc: Exception) -> bool:
    if isinstance(exc, _TRANSIENT_MILVUS_ERROR_TYPES):
        return True
    if isinstance(exc, grpc.RpcError):
        return exc.code() in _TRANSIENT_GRPC_CODES
    if isinstance(exc, MilvusException):
        return (
            exc.code in _TRANSIENT_GRPC_CODES
            or exc.code == ErrorCode.RATE_LIMIT
            or "Retry run out" in exc.message
            or "Retry timeout" in exc.message
        )
    return False


@dataclass
class InferredQueryContext:
    """从宽泛问题中推断出的适用性上下文。"""

    region: str = _DEFAULT_REGION
    reference_date: str = _DEFAULT_REFERENCE_DATE
    is_remote: bool | None = None  # None 表示未推断出，不做异地过滤
    insu_type: str = ""
    med_type: str = ""
    psn_type: str = ""
    hosp_lv: str = ""


@dataclass
class BroadRetrievalResult:
    """宽泛问题检索结果。"""

    selected_evidence: list[StructuredPolicyEvidence] = field(default_factory=list)
    missing_required_rules: list[str] = field(default_factory=list)
    query_trace: dict[str, Any] = field(default_factory=dict)


class BroadPolicyRetriever:
    """宽泛问题混合检索器：向量 + 关键词 + 适用性字段精排。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        collection_name: str | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_kind: str = "sentence_transformer",
    ):
        uri = f"http://{host}:{port}"
        try:
            self.client = MilvusClient(uri=uri)
        except Exception as e:
            if not _is_transient_milvus_error(e):
                raise
            raise PolicyRetrievalUnavailableError(str(e)) from e

        self.collection_name = collection_name or COLLECTION_NAME
        self.embedding_provider = embedding_provider or get_embedding_provider(embedding_kind)
        logger.info(
            "BroadPolicyRetriever initialized: %s (dim=%s)",
            uri,
            self.embedding_provider.dim,
        )

    def retrieve(
        self,
        question: str,
        top_k: int = 8,
        ctx: InferredQueryContext | None = None,
    ) -> BroadRetrievalResult:
        """主入口：宽召回 + 精排。

        Args:
            question: 用户原始问题。
            top_k: 返回证据条数。
            ctx: 推断的适用性上下文；None 时使用默认值。

        Returns:
            BroadRetrievalResult，其 selected_evidence 可直接被 policy_qa_routes 消费。
        """
        inferred = ctx or InferredQueryContext()
        reference_date = inferred.reference_date or _DEFAULT_REFERENCE_DATE

        # 1. 从问题推断并补全上下文
        question_inferred = self._infer_context_from_question(question)
        merged = self._merge_context(inferred, question_inferred)

        # 2. 构建硬过滤 expr（发布状态 + 地区 + 有效期 + 异地标识）
        expr = self._build_applicability_expr(merged, reference_date)

        # 3. 向量召回
        vector_hits = self._vector_search(question, expr, top_k=top_k * 3)

        # 4. 关键词召回（真实 BM25）
        keyword_hits = self._keyword_search(question, expr, top_k=top_k * 3)

        # 5. RRF 融合
        merged_hits = self._rrf_merge(vector_hits, keyword_hits, top_k=top_k * 3)

        # 6. 适用性字段精排
        ranked = self._applicability_rerank(merged_hits, merged, top_k=top_k)

        trace = {
            "question": question,
            "inferred_context": {
                "region": merged.region,
                "reference_date": reference_date,
                "is_remote": merged.is_remote,
                "insu_type": merged.insu_type,
                "med_type": merged.med_type,
                "psn_type": merged.psn_type,
                "hosp_lv": merged.hosp_lv,
            },
            "expr": expr,
            "vector_hits": len(vector_hits),
            "keyword_hits": len(keyword_hits),
            "final_hits": len(ranked),
        }
        logger.info("[BroadRetrieval] %s", trace)

        return BroadRetrievalResult(
            selected_evidence=[self._to_evidence(h) for h in ranked],
            query_trace=trace,
        )

    @staticmethod
    def _infer_context_from_question(question: str) -> InferredQueryContext:
        """从问题文本推断适用性上下文（轻量规则，不调用模型）。"""
        ctx = InferredQueryContext()
        q = question or ""

        # 地区推断
        region_map = {
            "北京": ["北京", "京"],
            "上海": ["上海", "沪"],
            "广州": ["广州", "穗"],
            "深圳": ["深圳"],
            "天津": ["天津", "津"],
            "杭州": ["杭州"],
        }
        for region, tokens in region_map.items():
            if any(t in q for t in tokens):
                ctx.region = region
                break

        # 异地 / 转诊推断
        if any(kw in q for kw in ("异地", "转诊", "备案", "跨省", "跨市")):
            ctx.is_remote = True

        # 险种推断
        if "城镇职工" in q or "职工医保" in q:
            ctx.insu_type = "城镇职工基本医疗保险"
        elif "城乡居民" in q or "居民医保" in q:
            ctx.insu_type = "城乡居民基本医疗保险"

        # 医疗类别推断
        if "住院" in q:
            ctx.med_type = "住院-普通住院"
        elif "门诊" in q:
            ctx.med_type = "门诊-普通门急诊"
        elif "门特" in q:
            ctx.med_type = "门诊-一般门特"

        # 人群推断
        if "退休" in q:
            ctx.psn_type = "退休人员"
        elif "在职" in q:
            ctx.psn_type = "在职人员"
        elif "学生" in q or "儿童" in q:
            ctx.psn_type = "学生儿童"

        # 医院等级推断
        if "三级" in q or "三甲医院" in q:
            ctx.hosp_lv = "三级医院"
        elif "二级" in q:
            ctx.hosp_lv = "二级医院"
        elif "一级" in q or "社区" in q:
            ctx.hosp_lv = "一级医院"

        return ctx

    @staticmethod
    def _merge_context(base: InferredQueryContext, inferred: InferredQueryContext) -> InferredQueryContext:
        """合并外部传入上下文与问题推断上下文；外部传入优先级更高。"""
        return InferredQueryContext(
            region=base.region or inferred.region,
            reference_date=base.reference_date or inferred.reference_date,
            is_remote=base.is_remote if base.is_remote is not None else inferred.is_remote,
            insu_type=base.insu_type or inferred.insu_type,
            med_type=base.med_type or inferred.med_type,
            psn_type=base.psn_type or inferred.psn_type,
            hosp_lv=base.hosp_lv or inferred.hosp_lv,
        )

    @staticmethod
    def _build_applicability_expr(
        ctx: InferredQueryContext, reference_date: str
    ) -> str:
        """构建适用性硬过滤表达式。"""
        parts = ['publish_status == "published"']

        if ctx.region:
            parts.append(f'region == "{ctx.region}"')

        if reference_date and reference_date != _DEFAULT_EXPIRY_DATE:
            parts.append(f'effective_date <= "{reference_date}"')
            parts.append(f'(expiry_date == "{_DEFAULT_EXPIRY_DATE}" or expiry_date >= "{reference_date}")')

        if ctx.is_remote is not None:
            parts.append(f'is_remote == {str(ctx.is_remote).lower()}')

        return " and ".join(parts)

    def _vector_search(
        self,
        question: str,
        expr: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """向量语义召回。"""
        try:
            vector = self.embedding_provider.encode([question])[0]
        except Exception as e:
            logger.warning("[BroadRetrieval] embedding failed: %s", e)
            return []

        try:
            results = self.client.search(
                collection_name=self.collection_name,
                data=[vector],
                anns_field="vector",
                filter=expr,
                limit=top_k,
                output_fields=OUTPUT_FIELDS,
                search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            )
        except Exception as e:
            if not _is_transient_milvus_error(e):
                raise
            raise PolicyRetrievalUnavailableError(str(e)) from e

        hits: list[dict[str, Any]] = []
        for batch in results:
            for item in batch:
                entity = item.get("entity", {})
                unpack_detail(entity)
                entity["score"] = float(item.get("distance", item.get("score", 0.0)))
                entity["_source"] = "vector"
                hits.append(entity)
        return hits

    def _keyword_search(
        self,
        question: str,
        expr: str,
        top_k: int,
        candidate_limit: int = 200,
    ) -> list[dict[str, Any]]:
        """BM25 关键词召回：在适用性过滤后的候选池上用 rank-bm25 + jieba 分词打分。"""
        if not question or not question.strip():
            return []

        try:
            results = self.client.query(
                collection_name=self.collection_name,
                filter=expr or 'rule_id != ""',
                output_fields=OUTPUT_FIELDS,
                limit=candidate_limit,
            )
        except Exception as e:
            if not _is_transient_milvus_error(e):
                raise
            raise PolicyRetrievalUnavailableError(str(e)) from e

        if not results:
            return []

        for entity in results:
            unpack_detail(entity)

        # jieba 分词构建语料与查询
        corpus = [list(jieba.cut(str(r.get("source_text", "") or ""))) for r in results]
        query_tokens = list(jieba.cut(question))

        try:
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(query_tokens)
        except Exception as e:
            logger.warning("[BroadRetrieval] BM25 scoring failed: %s", e)
            return []

        scored = sorted(
            zip(scores, results),
            key=lambda x: x[0],
            reverse=True,
        )[:top_k]

        hits: list[dict[str, Any]] = []
        for score, entity in scored:
            entity["score"] = float(score)
            entity["_source"] = "bm25"
            hits.append(entity)
        return hits

    @staticmethod
    def _rrf_merge(
        vector_hits: list[dict[str, Any]],
        keyword_hits: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Reciprocal Rank Fusion 融合向量与关键词结果。"""
        scores: dict[str, float] = {}
        entities: dict[str, dict[str, Any]] = {}

        def _rank_id(entity: dict[str, Any]) -> str:
            return str(entity.get("rule_id", "")) or str(id(entity))

        for rank, hit in enumerate(vector_hits, start=1):
            rid = _rank_id(hit)
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (_RRF_K + rank)
            if rid not in entities:
                entities[rid] = hit

        for rank, hit in enumerate(keyword_hits, start=1):
            rid = _rank_id(hit)
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (_RRF_K + rank)
            if rid not in entities:
                entities[rid] = hit

        sorted_ids = sorted(scores.keys(), key=lambda rid: scores[rid], reverse=True)
        merged = []
        for rid in sorted_ids[:top_k]:
            entities[rid]["_rrf_score"] = scores[rid]
            merged.append(entities[rid])
        return merged

    def _applicability_rerank(
        self,
        hits: list[dict[str, Any]],
        ctx: InferredQueryContext,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """基于推断上下文对结果做适用性精排。"""
        scored: list[tuple[float, dict[str, Any]]] = []
        for hit in hits:
            score = float(hit.get("_rrf_score", hit.get("score", 0.0)))
            # 适用性字段匹配加分（与 RRF 分数同量级，避免过度挤压语义/关键词信号）
            boost = 0.005
            if ctx.insu_type and str(hit.get("insu_type", "")) in (ctx.insu_type, ""):
                score += boost
            if ctx.med_type and str(hit.get("med_type", "")) in (ctx.med_type, ""):
                score += boost
            if ctx.psn_type and str(hit.get("psn_type", "")) in (ctx.psn_type, ""):
                score += boost
            if ctx.hosp_lv and str(hit.get("hosp_lv", "")) in (ctx.hosp_lv, ""):
                score += boost
            scored.append((score, hit))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in scored[:top_k]]

    def _to_evidence(self, entity: dict[str, Any]) -> StructuredPolicyEvidence:
        """将 Milvus 实体转换为 StructuredPolicyEvidence。"""

        def _bool_val(key: str) -> bool:
            v = entity.get(key)
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes", "是")
            return False

        source_text = str(entity.get("source_text", "") or "")
        return StructuredPolicyEvidence(
            evidence_id=str(entity.get("rule_id", "") or ""),
            source="broad_policy_retriever",
            query_name=str(entity.get("_source", "") or "broad"),
            policy_id=str(entity.get("doc_id", "") or ""),
            clause_id=str(entity.get("clause_id", "") or ""),
            rule_type=str(entity.get("rule_type", "") or ""),
            insu_type=str(entity.get("insu_type", "") or ""),
            med_type=str(entity.get("med_type", "") or ""),
            hosp_lv=str(entity.get("hosp_lv", "") or ""),
            psn_type=str(entity.get("psn_type", "") or ""),
            region=str(entity.get("region", "") or _DEFAULT_REGION),
            effective_date=str(entity.get("effective_date", "") or ""),
            expiry_date=str(entity.get("expiry_date", "") or ""),
            publish_status=str(entity.get("publish_status", "") or ""),
            policy_version=str(entity.get("policy_version", "") or ""),
            is_remote=_bool_val("is_remote"),
            source_text=source_text,
            rule_value=str(entity.get("rule_value", "") or ""),
            payment_ratio=str(entity.get("payment_ratio", "") or ""),
            amount_band=str(entity.get("amount_band", "") or ""),
            rule_id=str(entity.get("rule_id", "") or ""),
            applied_reason=f"宽泛问题混合召回：{entity.get('_source', 'unknown')} 命中",
            score=float(entity.get("_rrf_score", entity.get("score", 0.0))),
        )


def retrieve_broad_policy_evidence(
    question: str,
    host: str = "127.0.0.1",
    port: str = "19530",
    region: str = _DEFAULT_REGION,
    reference_date: str | None = None,
    top_k: int = 8,
    embedding_kind: str = "sentence_transformer",
) -> BroadRetrievalResult:
    """便捷函数：从问题直接检索宽泛政策证据。

    Args:
        question: 用户问题。
        host: Milvus host。
        port: Milvus port。
        region: 默认地区；问题中若含地区词会被覆盖。
        reference_date: 参考日期，默认当天。
        top_k: 返回条数。
        embedding_kind: embedding provider 类型（sentence_transformer / hash）；
            hash 仅用于无 embedding 模型时的流程测试，维度强制对齐 policy_rules_v2（768）。

    Returns:
        BroadRetrievalResult。
    """
    if reference_date is None:
        reference_date = date.today().isoformat()
    ctx = InferredQueryContext(region=region, reference_date=reference_date)
    if embedding_kind == "hash":
        embedding_provider = HashEmbeddingProvider(dim=POLICY_RULES_V2_VECTOR_DIM)
    else:
        embedding_provider = get_embedding_provider(embedding_kind)
    retriever = BroadPolicyRetriever(
        host=host,
        port=port,
        embedding_provider=embedding_provider,
    )
    return retriever.retrieve(question, top_k=top_k, ctx=ctx)
