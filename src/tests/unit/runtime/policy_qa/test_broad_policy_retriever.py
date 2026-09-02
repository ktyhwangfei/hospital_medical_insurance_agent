"""
BroadPolicyRetriever 单元测试

不依赖真实 Milvus / embedding 模型，通过 monkeypatch 验证：
- 问题上下文推断
- 适用性过滤表达式
- 向量 + 关键词 RRF 融合
- 结果到 StructuredPolicyEvidence 的转换
"""

import pytest

from src.runtime.policy_qa.broad_policy_retriever import (
    BroadPolicyRetriever,
    BroadRetrievalResult,
    InferredQueryContext,
    retrieve_broad_policy_evidence,
)
from src.runtime.policy_qa.structured_policy_retriever import StructuredPolicyEvidence


class FakeMilvusClient:
    """模拟 MilvusClient，返回固定规则记录。"""

    def __init__(self, records):
        self.records = records

    def search(self, **kwargs):
        return [[{"entity": dict(r), "distance": 0.85} for r in self.records]]

    def query(self, **kwargs):
        return [dict(r) for r in self.records]


@pytest.fixture
def fake_records():
    return [
        {
            "rule_id": "r1",
            "doc_id": "d1",
            "rule_type": "支付比例",
            "insu_type": "城镇职工基本医疗保险",
            "med_type": "住院-普通住院",
            "hosp_lv": "三级医院",
            "psn_type": "退休人员",
            "region": "北京",
            "effective_date": "2024-01-01",
            "expiry_date": "9999-12-31",
            "publish_status": "published",
            "policy_version": "1.0",
            "is_remote": False,
            "source_text": "退休人员三级医院住院个人支付比例为10%。",
            "rule_value": "10%",
        },
        {
            "rule_id": "r2",
            "doc_id": "d1",
            "rule_type": "起付线",
            "insu_type": "城镇职工基本医疗保险",
            "med_type": "住院-普通住院",
            "hosp_lv": "三级医院",
            "psn_type": "",
            "region": "北京",
            "effective_date": "2024-01-01",
            "expiry_date": "9999-12-31",
            "publish_status": "published",
            "policy_version": "1.0",
            "is_remote": False,
            "source_text": "三级医院住院起付线为1300元。",
            "rule_value": "1300",
        },
    ]


class TestInferredQueryContext:
    def test_infer_region_from_question(self):
        ctx = BroadPolicyRetriever._infer_context_from_question("上海职工医保门诊报销比例")
        assert ctx.region == "上海"

    def test_infer_insurance_med_type_psn_type(self):
        ctx = BroadPolicyRetriever._infer_context_from_question("北京城乡居民住院报销")
        assert ctx.region == "北京"
        assert ctx.insu_type == "城乡居民基本医疗保险"
        assert ctx.med_type == "住院-普通住院"

    def test_infer_remote_from_question(self):
        ctx = BroadPolicyRetriever._infer_context_from_question("异地就医怎么备案")
        assert ctx.is_remote is True


class TestApplicabilityExpr:
    def test_expr_includes_publish_status_and_region(self):
        ctx = InferredQueryContext(region="北京", reference_date="2025-06-01")
        expr = BroadPolicyRetriever._build_applicability_expr(ctx, "2025-06-01")
        assert 'publish_status == "published"' in expr
        assert 'region == "北京"' in expr
        assert 'effective_date <= "2025-06-01"' in expr
        assert 'expiry_date == "9999-12-31" or expiry_date >= "2025-06-01"' in expr


class TestBm25Search:
    def test_bm25_ranks_relevant_higher(self, fake_records):
        retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
        retriever.client = FakeMilvusClient(fake_records)
        hits = retriever._keyword_search("退休人员住院个人支付比例", expr="", top_k=2)
        # 第一条记录明确提到“退休人员”“个人支付比例”，应排在首位
        assert hits[0]["rule_id"] == "r1"

    def test_bm25_empty_corpus_returns_empty(self):
        retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
        retriever.client = FakeMilvusClient([])
        hits = retriever._keyword_search("住院报销", expr="", top_k=3)
        assert hits == []


class TestRrfMerge:
    def test_rrf_merge_boosts_co_occurrence(self):
        vector_hits = [{"rule_id": "r1", "score": 0.9}, {"rule_id": "r2", "score": 0.8}]
        keyword_hits = [{"rule_id": "r2", "score": 1.0}, {"rule_id": "r3", "score": 1.0}]
        merged = BroadPolicyRetriever._rrf_merge(vector_hits, keyword_hits, top_k=10)
        ids = [h["rule_id"] for h in merged]
        assert "r2" in ids  # 同时出现在向量与关键词结果中


class TestBroadPolicyRetriever:
    def test_retrieve_returns_structured_evidence(self, fake_records):
        retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
        retriever.client = FakeMilvusClient(fake_records)
        result = retriever.retrieve("北京职工医保住院报销比例", top_k=5)

        assert isinstance(result, BroadRetrievalResult)
        assert len(result.selected_evidence) > 0
        assert all(isinstance(ev, StructuredPolicyEvidence) for ev in result.selected_evidence)

    def test_retrieve_passes_applicability_filter_to_search(self, fake_records):
        """验证 retrieve 将适用性过滤表达式传给 Milvus search。"""
        captured = {}

        class CapturingClient(FakeMilvusClient):
            def search(self, **kwargs):
                captured["filter"] = kwargs.get("filter")
                return super().search(**kwargs)

        retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
        retriever.client = CapturingClient(fake_records)
        retriever.retrieve("北京职工医保住院报销比例", top_k=5, ctx=InferredQueryContext(reference_date="2025-06-01"))

        expr = captured.get("filter", "")
        assert 'publish_status == "published"' in expr
        assert 'region == "北京"' in expr
        assert 'effective_date <= "2025-06-01"' in expr


class _FakeEmbeddingProvider:
    """固定维度向量，避免加载真实模型。"""

    dim = 768

    def encode(self, texts):
        return [[0.1] * self.dim for _ in texts]


def test_retrieve_broad_policy_evidence_with_hash_provider():
    """便捷函数在 hash 模式下应使用 768 维向量，避免维度不匹配。"""
    retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
    retriever.client = FakeMilvusClient([])
    result = retriever.retrieve("北京医保政策", top_k=3)
    assert isinstance(result, BroadRetrievalResult)


class TestHonestRefusalGate:
    """Issue #33 P1-5：向量低分 + BM25 零命中 → 诚实拒答（空证据 + refusal_reason）。"""

    def test_below_threshold_and_zero_bm25_refuses(self, fake_records):
        # FakeMilvusClient 向量 distance 固定 0.85 < 阈值 0.9；
        # 问题与语料零词面重叠 → BM25 全 0
        retriever = BroadPolicyRetriever(
            embedding_provider=_FakeEmbeddingProvider(), min_vector_score=0.9
        )
        retriever.client = FakeMilvusClient(fake_records)
        result = retriever.retrieve("zxqwv asdf", top_k=5)

        assert result.selected_evidence == []
        assert "below_threshold" in result.query_trace.get("refusal_reason", "")

    def test_above_threshold_keeps_results(self, fake_records):
        retriever = BroadPolicyRetriever(
            embedding_provider=_FakeEmbeddingProvider(), min_vector_score=0.5
        )
        retriever.client = FakeMilvusClient(fake_records)
        result = retriever.retrieve("退休人员住院个人支付比例", top_k=5)

        assert len(result.selected_evidence) > 0
        assert "refusal_reason" not in result.query_trace

    def test_default_threshold_disabled(self):
        retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
        assert retriever.min_vector_score == 0.0


class TestDimensionConflictExclusion:
    """Issue #33：显式维度硬冲突排除（诚实拒答的主要信号）。"""

    def test_conflict_detected(self):
        from src.runtime.policy_qa.broad_policy_retriever import _dimension_conflict

        ctx = InferredQueryContext(insu_type="城乡居民基本医疗保险", med_type="门诊-普通门急诊")
        # 候选险种冲突 → 排除
        assert _dimension_conflict({"insu_type": "城镇职工基本医疗保险", "med_type": "门诊-普通门急诊"}, ctx)
        # 候选维度为空（通用）→ 保留
        assert not _dimension_conflict({"insu_type": "", "med_type": "门诊-普通门急诊"}, ctx)
        # 双向子串兼容（"退休" vs "70岁以上退休人员"）→ 保留
        ctx2 = InferredQueryContext(psn_type="退休人员")
        assert not _dimension_conflict({"psn_type": "70岁以上退休人员"}, ctx2)
        # 未给出显式维度 → 不排除
        assert not _dimension_conflict({"insu_type": "城镇职工基本医疗保险"}, InferredQueryContext())

    def test_retrieve_excludes_conflicting_candidates(self, fake_records):
        # fake_records 全部为 职工+住院；问题显式问居民+门诊 → 全部冲突排除 → 空证据
        retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
        retriever.client = FakeMilvusClient(fake_records)
        result = retriever.retrieve("北京城乡居民医保门诊报销比例", top_k=5)
        assert result.selected_evidence == []
