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


class TestKeywordExtraction:
    def test_extract_keywords_removes_stop_words(self):
        keywords = BroadPolicyRetriever._extract_keywords("请问北京职工医保住院怎么报销")
        assert "北京" in keywords
        assert "职工" in keywords
        assert "医保" in keywords
        assert "住院" in keywords
        assert "怎么" not in keywords
        assert "请问" not in keywords


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
