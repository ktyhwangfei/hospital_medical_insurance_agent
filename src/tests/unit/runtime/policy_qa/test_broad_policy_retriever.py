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


class TestValidityHardFilter:
    """【加固②broad有效期/status硬过滤】有效期边界 + status 边界断言。

    与 structured 共用同一有效期判定 helper（policy_validity），避免两条读路径
    版本/有效期语义不一致。真实语料实测：全部 351 条规则 published/expiry=9999，
    本加固是防御性硬排除（过期/未发布段命中即丢弃），不指望其移动当前语料的 broad FAR。
    """

    def test_expiry_boundary_exact_day_kept_day_before_dropped(self):
        """expiry 精确当天保留（>=），前一天丢弃。"""
        from src.runtime.policy_qa.policy_validity import build_validity_date_expr

        expr = build_validity_date_expr("2025-06-01")
        assert any('expiry_date >= "2025-06-01"' in p for p in expr)

    def test_effective_boundary_exact_day_kept_day_after_dropped(self):
        """effective 精确当天保留（<=），后一天丢弃。"""
        from src.runtime.policy_qa.policy_validity import build_validity_date_expr

        expr = build_validity_date_expr("2025-06-01")
        assert any('effective_date <= "2025-06-01"' in p for p in expr)

    def test_validity_one_year_around_reference(self):
        """前后一年边界：expr 锚定参考日期字符串本身（比较由 Milvus 执行）。"""
        from src.runtime.policy_qa.policy_validity import build_validity_date_expr

        expr = build_validity_date_expr("2025-06-01")
        joined = " and ".join(expr)
        assert 'effective_date <= "2025-06-01"' in joined
        assert '(expiry_date == "9999-12-31" or expiry_date >= "2025-06-01")' in joined

    def test_publish_status_requires_published(self):
        from src.runtime.policy_qa.policy_validity import build_publish_status_expr

        assert build_publish_status_expr() == 'publish_status == "published"'
        # 字段缺失（旧 collection）→ 返回 None，由调用方跳过不误杀
        assert build_publish_status_expr({"rule_id", "vector"}) is None
        # dynamic field 集合字段齐全 → 照常硬过滤
        assert build_publish_status_expr({"publish_status"}) is not None

    def test_expr_skips_validity_parts_when_fields_absent(self):
        """旧 collection 缺有效期/发布状态字段 → 不拼该部分，避免查询报错/全空。"""
        ctx = InferredQueryContext(region="北京", reference_date="2025-06-01")
        expr = BroadPolicyRetriever._build_applicability_expr(
            ctx, "2025-06-01", available_fields={"rule_id", "vector"}
        )

        assert 'publish_status == "published"' not in expr
        assert "effective_date" not in expr
        assert "expiry_date" not in expr
        assert 'region == "北京"' in expr

    def test_expr_keeps_validity_parts_when_fields_present(self):
        ctx = InferredQueryContext(region="北京", reference_date="2025-06-01")
        expr = BroadPolicyRetriever._build_applicability_expr(
            ctx, "2025-06-01", available_fields={"publish_status", "effective_date", "expiry_date"}
        )

        assert 'publish_status == "published"' in expr
        assert 'effective_date <= "2025-06-01"' in expr
        assert 'expiry_date >= "2025-06-01"' in expr

    def test_retrieve_drops_expired_and_unpublished_records(self):
        """行为级断言：命中即丢弃——过期（expiry 前一天）与未发布记录不进入证据。"""

        class FilteringFakeClient(FakeMilvusClient):
            """按记录自身字段值模拟 Milvus expr 语义（publish_status + 有效期）。"""

            def search(self, **kwargs):
                records = [
                    r for r in self.records
                    if r.get("publish_status") == "published"
                    and r.get("effective_date", "") <= "2025-06-01"
                    and (r.get("expiry_date", "9999-12-31") >= "2025-06-01")
                ]
                return [[{"entity": dict(r), "distance": 0.85} for r in records]]

            def query(self, **kwargs):
                return [
                    dict(r) for r in self.records
                    if r.get("publish_status") == "published"
                    and r.get("effective_date", "") <= "2025-06-01"
                    and (r.get("expiry_date", "9999-12-31") >= "2025-06-01")
                ]

        records = [
            {  # 已过期（expiry 为参考日期前一天）
                "rule_id": "expired", "doc_id": "d1", "rule_type": "支付比例",
                "insu_type": "", "med_type": "", "hosp_lv": "", "psn_type": "",
                "region": "北京", "effective_date": "2020-01-01",
                "expiry_date": "2025-05-31", "publish_status": "published",
                "source_text": "已废止的支付比例规则。",
            },
            {  # 未发布（草案）
                "rule_id": "draft", "doc_id": "d1", "rule_type": "支付比例",
                "insu_type": "", "med_type": "", "hosp_lv": "", "psn_type": "",
                "region": "北京", "effective_date": "2020-01-01",
                "expiry_date": "9999-12-31", "publish_status": "draft",
                "source_text": "草案支付比例规则。",
            },
            {  # 现行有效（expiry 精确当天，长期有效哨兵）
                "rule_id": "current", "doc_id": "d1", "rule_type": "支付比例",
                "insu_type": "", "med_type": "", "hosp_lv": "", "psn_type": "",
                "region": "北京", "effective_date": "2020-01-01",
                "expiry_date": "9999-12-31", "publish_status": "published",
                "source_text": "现行支付比例规则。",
            },
        ]
        retriever = BroadPolicyRetriever(embedding_provider=_FakeEmbeddingProvider())
        retriever.client = FilteringFakeClient(records)
        result = retriever.retrieve("北京医保支付比例", top_k=5,
                                    ctx=InferredQueryContext(reference_date="2025-06-01"))

        ids = [ev.rule_id for ev in result.selected_evidence]
        assert "expired" not in ids
        assert "draft" not in ids
        assert "current" in ids


class TestStructuredValidityEquivalence:
    """加固②：structured 与 broad 走同一有效期 helper，expr 语义逐字一致。"""

    def test_structured_execute_query_uses_shared_validity_expr(self):
        from src.runtime.policy_qa.structured_policy_retriever import (
            StructuredPolicyQuery,
            StructuredPolicyRuleRetriever,
        )

        captured: dict[str, str] = {}

        class FakeClient:
            def query(self, *, filter, **_kwargs):
                captured["filter"] = filter
                return []

        retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
        retriever.client = FakeClient()
        retriever.collection_name = "policy_rules_v2"
        retriever._collection_fields = {"effective_date", "expiry_date"}
        retriever.execute_query(StructuredPolicyQuery(
            query_name="validity-check",
            filters={},
            settlement_date="2025-06-01",
        ))

        expression = captured["filter"]
        assert 'effective_date <= "2025-06-01"' in expression
        assert '(expiry_date == "9999-12-31" or expiry_date >= "2025-06-01")' in expression
