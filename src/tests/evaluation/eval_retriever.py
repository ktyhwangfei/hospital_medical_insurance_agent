"""
评估专用检索器 — 直接查询 policy_rules_v2 + policy_facts。

与产品 milvus_retriever.py 分离的原因：
- milvus_retriever 连 policy_nodes（已不存在）+ policy_facts（无维度字段）
- 评估需要 policy_rules_v2 的维度字段（insu_type/hosp_lv/psn_type/rule_type）
- 支持向量检索和 BM25 检索两种模式（纯 Python BM25，不依赖 Milvus 稀疏向量）

BM25 实现：
- Okapi BM25（rank_bm25），默认 k1=1.2, b=0.75
- jieba 精确模式中文分词，加载自定义医保术语词典
- 语料来自 policy_rules_v2 关联的 policy_facts.fact_text

[来源: docs/research/知识召回质量评估方案.md §3]
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from pymilvus import Collection, connections

# 确保项目根在 path 中
_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
    get_embedding_provider,
    EmbeddingProvider,
)

RULES_COLLECTION = "policy_rules_v2"
FACTS_COLLECTION = "policy_facts"

RULES_OUTPUT_FIELDS = [
    "rule_id",
    "fact_id",
    "doc_id",
    "rule_type",
    "insu_type",
    "med_type",
    "hosp_lv",
    "psn_type",
    "setl_type",
    "schema_version",
]

FACTS_OUTPUT_FIELDS = [
    "fact_id",
    "doc_id",
    "fact_text",
    "created_at",
]


class EvalHit:
    """评估用检索命中，比 SearchHit 更轻量。"""

    def __init__(
        self,
        id: str,
        score: float | None,
        entity: dict[str, Any],
        fact_text: str = "",
    ):
        self.id = id
        self.score = score
        self.entity = entity
        self.fact_text = fact_text

    def __repr__(self) -> str:
        return f"EvalHit(id={self.id}, score={self.score})"


class EvalRetriever:
    """评估专用检索器。

    支持两种模式：
    - vector: bge-base-zh-v1.5 向量 ANN（HNSW+COSINE）
    - bm25:  纯 Python BM25（rank_bm25），离线计算不依赖 Milvus 稀疏向量
    """

    # ── 医保领域自定义词典（避免 jieba 分错关键术语）──
    _MEDICAL_TERMS: list[str] = [
        # 保险类型
        "城乡居民基本医疗保险", "城镇职工基本医疗保险", "大病保险",
        # 规则类型
        "起付线", "起付标准", "封顶线", "支付比例", "报销比例",
        "排除规则", "适用范围", "通用规则",
        # 医疗类型
        "普通门急诊", "门诊慢特病", "急诊留观", "普通住院",
        "住院普通住院", "一般门特",
        # 结算方式
        "按项目付费", "按床日付费", "按病种付费", "按人头付费",
        # 人群
        "在职职工", "退休人员", "城乡居民", "学生儿童",
        "困难人群", "灵活就业", "离休人员", "参保个人",
        # 医院等级
        "三级医院", "二级医院", "一级医院",
        # 金额/比例相关
        "最高支付限额", "统筹自付", "个人自付", "二次住院",
        "报销政策", "报销标准",
        # 其他
        "医疗救助", "异地就医", "转院治疗", "生育医疗",
        "不予支付", "参保范围", "缴费年限",
    ]

    @classmethod
    def _init_jieba_dict(cls) -> None:
        """向 jieba 添加医保领域自定义词典（类级别，仅加载一次）。"""
        if getattr(cls, "_jieba_dict_loaded", False):
            return
        try:
            import jieba
            for term in cls._MEDICAL_TERMS:
                jieba.add_word(term, freq=100, tag="nz")
            cls._jieba_dict_loaded = True
        except ImportError:
            pass

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: str = "19530",
        mode: str = "vector",
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self.host = host
        self.port = port
        self.mode = mode

        connections.connect(host=host, port=port, timeout=10)

        self.rules_col = Collection(RULES_COLLECTION)
        self.facts_col = Collection(FACTS_COLLECTION)
        self.rules_col.load()
        self.facts_col.load()

        self.embedding_provider = embedding_provider or get_embedding_provider("sentence_transformer")

        self.search_params = {
            "metric_type": "COSINE",
            "params": {"ef": 64},
        }

        # BM25 延迟初始化（首次使用时加载语料）
        self._bm25_model = None
        self._bm25_corpus: list[str] = []           # 原始 fact_text（用于展示）
        self._bm25_tokenized: list[list[str]] = []  # 分词后语料（用于 BM25）
        self._bm25_rids: list[str] = []
        self._bm25_k1: float = 1.2   # 词频饱和度参数
        self._bm25_b: float = 0.75   # 文档长度归一化参数

    # ── 公共检索接口 ──────────────────────────────────

    def search(self, query: str, top_k: int = 10) -> list[EvalHit]:
        """统一检索入口，根据 mode 分发。"""
        if self.mode == "bm25":
            return self._bm25_search(query, top_k)
        else:
            return self._vector_search(query, top_k)

    def _vector_search(self, query: str, top_k: int = 10) -> list[EvalHit]:
        """向量 ANN 检索 policy_rules_v2，并回填 fact_text。"""
        vector = self.embedding_provider.encode([query])[0]

        result = self.rules_col.search(
            data=[vector],
            anns_field="vector",
            param=self.search_params,
            limit=top_k,
            output_fields=RULES_OUTPUT_FIELDS,
        )

        hits: list[EvalHit] = []
        for batch in result:
            for h in batch:
                entity = {}
                for fld in RULES_OUTPUT_FIELDS:
                    try:
                        entity[fld] = h.entity.get(fld)
                    except Exception:
                        entity[fld] = None

                fact_text = self._get_fact_text(entity.get("fact_id"))

                hits.append(EvalHit(
                    id=entity.get("rule_id") or str(h.id),
                    score=float(h.score) if h.score is not None else None,
                    entity=entity,
                    fact_text=fact_text,
                ))

        return hits

    # ── BM25 检索 ─────────────────────────────────────

    def _ensure_bm25(self) -> None:
        """加载 BM25 语料（从 policy_rules_v2 关联的 fact_text）。

        构建三个数据结构：
        - _bm25_corpus: 原始 fact_text 列表（用于结果展示）
        - _bm25_tokenized: jieba 分词后语料（用于 BM25Okapi 计分）
        - _bm25_model: BM25Okapi 实例（k1=1.2, b=0.75）
        """
        if self._bm25_model is not None:
            return

        from rank_bm25 import BM25Okapi

        all_rules = self.rules_col.query(
            expr='rule_id != ""',
            limit=2000,
            output_fields=["rule_id", "fact_id"],
        )

        corpus_raw: list[str] = []
        corpus_tok: list[list[str]] = []
        rids: list[str] = []

        for rule in all_rules:
            fact_text = self._get_fact_text(rule.get("fact_id"))
            if fact_text:
                tokenized = self._tokenize(fact_text)
                corpus_raw.append(fact_text)
                corpus_tok.append(tokenized)
                rids.append(rule["rule_id"])

        self._bm25_corpus = corpus_raw
        self._bm25_tokenized = corpus_tok
        self._bm25_rids = rids
        self._bm25_model = BM25Okapi(
            corpus_tok,
            k1=self._bm25_k1,
            b=self._bm25_b,
        )

    def _tokenize(self, text: str) -> list[str]:
        """中文分词：jieba 精确模式（医保术语词典）+ 字符 bigram 回退。

        策略：
        - jieba 精确模式 + HMM，加载自定义医保词典确保关键术语不被切碎
        - 无 jieba 时回退到字符 bigram（2-gram 窗口），比单字保留更多上下文
        """
        try:
            import jieba
            self._init_jieba_dict()
            tokens = list(jieba.cut(text, HMM=True))
            return [t.strip() for t in tokens if t.strip()]
        except ImportError:
            clean = text.replace(" ", "").replace("\n", "")
            if len(clean) <= 1:
                return [clean] if clean else []
            bigrams = [clean[i:i+2] for i in range(len(clean)-1)]
            return bigrams if bigrams else [clean]

    def _bm25_search(self, query: str, top_k: int = 10) -> list[EvalHit]:
        """BM25 检索。

        分词 query → BM25 计分 → 取 top_k → 回填 rule entity + fact_text。
        """
        self._ensure_bm25()

        if self._bm25_model is None:
            return []

        tokenized = self._tokenize(query)
        scores = self._bm25_model.get_scores(tokenized)

        indexed = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        hits: list[EvalHit] = []
        for idx, score in indexed:
            rule_id = self._bm25_rids[idx]
            entity = self._get_rule_entity(rule_id)
            fact_text = self._bm25_corpus[idx]
            hits.append(EvalHit(
                id=rule_id,
                score=float(score),
                entity=entity,
                fact_text=fact_text,
            ))

        return hits

    # ── 辅助方法 ──────────────────────────────────────

    def _get_fact_text(self, fact_id: str | None) -> str:
        """从 policy_facts 获取 fact_text（带模块级缓存）。"""
        if not fact_id:
            return ""
        if fact_id in _fact_text_cache:
            return _fact_text_cache[fact_id]
        try:
            rows = self.facts_col.query(
                expr=f'fact_id == "{fact_id}"',
                limit=1,
                output_fields=["fact_text"],
            )
            text = rows[0].get("fact_text", "") if rows else ""
        except Exception:
            text = ""
        _fact_text_cache[fact_id] = text
        return text

    def _get_rule_entity(self, rule_id: str) -> dict[str, Any]:
        """获取单条规则的完整实体。"""
        try:
            rows = self.rules_col.query(
                expr=f'rule_id == "{rule_id}"',
                limit=1,
                output_fields=RULES_OUTPUT_FIELDS,
            )
            if rows:
                return dict(rows[0])
        except Exception:
            pass
        return {}


# 简单的内存缓存，避免重复查询
_fact_text_cache: dict[str, str] = {}
