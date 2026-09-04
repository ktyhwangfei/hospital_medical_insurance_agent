from __future__ import annotations

from types import SimpleNamespace


def _patch_resolver(
    monkeypatch,
    *,
    rules_collection: str = "policy_rules_REL_complete",
    existing: tuple[str, ...] = ("policy_rules_REL_complete",),
    row_count: int = 418,
) -> None:
    """把统一 release resolver 的两个外部依赖（PG 指针 + Milvus 探测）替换为假实现。"""
    from src.knowledge_extension.rule_explanation import release_resolver

    monkeypatch.setattr(
        release_resolver,
        "_get_store",
        lambda: SimpleNamespace(
            get_active_release=lambda: SimpleNamespace(
                rules_collection=rules_collection,
                facts_collection="policy_facts_REL_complete",
            )
        ),
    )

    class FakeMilvusClient:
        def __init__(self, uri=None, **_kwargs) -> None:
            pass

        def list_collections(self):
            return list(existing)

        def get_collection_stats(self, _name):
            return {"row_count": row_count}

    monkeypatch.setattr(release_resolver, "MilvusClient", FakeMilvusClient)


def test_retrieve_uses_active_release_collection_and_normalizes_hospital_level(
    monkeypatch,
) -> None:
    from src.runtime.policy_qa import structured_policy_retriever as module

    captured: dict[str, object] = {}

    class FakeRetriever:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

        def retrieve(self, context, *, target_field, custom_queries):
            captured["context"] = context
            return SimpleNamespace(selected_evidence=[], missing_required_rules=[])

    _patch_resolver(monkeypatch)
    monkeypatch.setattr(module, "StructuredPolicyRuleRetriever", FakeRetriever)

    module.retrieve_policy_evidence(
        {
            "insu_type": "城镇职工基本医疗保险",
            "med_type": "住院-普通住院",
            "hosp_lv": "三级医院",
            "psn_type": "退休人员",
        }
    )

    assert captured["collection_name"] == "policy_rules_REL_complete"
    assert captured["context"].hosp_lv == "三级"  # type: ignore[union-attr]


def test_incomplete_active_release_falls_back_to_global_collection(monkeypatch) -> None:
    from src.runtime.policy_qa import structured_policy_retriever as module

    # active release 的集合不存在（未构建/已删除）→ 回退主集合
    _patch_resolver(monkeypatch, existing=())

    assert module.resolve_rules_collection() == module.COLLECTION_NAME


def test_empty_active_release_falls_back_to_global_collection(monkeypatch) -> None:
    from src.runtime.policy_qa import structured_policy_retriever as module

    # 集合存在但为空（row_count=0）→ 同样视为不完整，回退主集合
    _patch_resolver(monkeypatch, row_count=0)

    assert module.resolve_rules_collection() == module.COLLECTION_NAME


def test_active_release_lookup_failure_falls_back_to_global_collection(monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation import release_resolver
    from src.runtime.policy_qa import structured_policy_retriever as module

    class UnavailableStore:
        def get_active_release(self):
            raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(release_resolver, "_get_store", lambda: UnavailableStore())

    assert module.resolve_rules_collection() == module.COLLECTION_NAME


def test_structured_query_includes_generic_dimension_rules() -> None:
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
    retriever.execute_query(StructuredPolicyQuery(
        query_name="outpatient",
        filters={
            "insu_type": "城镇职工基本医疗保险",
            "med_type": "门诊-普通门急诊",
            "hosp_lv": "三级",
            "psn_type": "退休人员",
            "rule_type": "支付比例",
        },
    ))

    expression = captured["filter"]
    assert '(med_type == "门诊-普通门急诊" or med_type == "")' in expression
    assert '(hosp_lv == "三级" or hosp_lv == "")' in expression
    assert '(psn_type == "退休人员" or psn_type == "")' in expression
    assert 'rule_type == "支付比例"' in expression


def test_amount_range_filter_skips_unparseable_zero_band() -> None:
    """Issue #33：(0,0) 视为无法解析，不参与金额段范围过滤（保留召回，不漏规则）。"""
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
    retriever._collection_fields = {"rule_type", "amount_band_min", "amount_band_max"}
    retriever.execute_query(StructuredPolicyQuery(
        query_name="amount-band",
        filters={"rule_type": "支付比例"},
        amount_range=(20000.0, 30000.0),
    ))

    expression = captured["filter"]
    assert "(amount_band_min == 0 and amount_band_max == 0)" in expression
    assert "amount_band_min <= 20000.0" in expression
    assert "(amount_band_max >= 20000.0 or amount_band_max == -1)" in expression


def _plan(target_med_type: str, target_amount: float = 25000.0):
    from src.runtime.policy_qa.structured_policy_retriever import (
        NormalizedPolicyContext,
        StructuredPolicyRuleRetriever,
    )

    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    ctx = NormalizedPolicyContext(
        insu_type="城镇职工基本医疗保险",
        med_type=target_med_type,
        hosp_lv="三级",
        psn_type="退休人员",
        target_amount=target_amount,
    )
    return retriever.plan_queries(ctx, target_field="统筹自付")


def test_outpatient_query_plan_uses_amount_band_not_inpatient_keywords() -> None:
    """Issue #33：门诊分段文本在 amount_band 字段而非 source_text，
    门诊查询计划不再使用住院特化关键词，分段选择交给金额段数值过滤。"""
    q1, q2 = _plan("门诊-普通门急诊")

    assert q1.query_name == "employee_outpatient_segment_ratio"
    assert not q1.text_must_include_any
    assert q1.amount_range == (25000, 25000)
    # query2 去掉万金油 "60%"（负例 FAR 来源），保留"个人支付"
    assert q2.text_must_include_any == ["个人支付"]


def test_inpatient_query_plan_unchanged() -> None:
    """住院查询计划保持既有住院分段关键词。"""
    q1, q2 = _plan("住院-普通住院")

    assert q1.query_name == "employee_inpatient_tertiary_segment_ratio"
    assert q1.text_must_include_any == ["起付标准至3万元", "超过3万元至4万元", "超过4万元"]
    assert q2.text_must_include_any == ["个人支付"]


def test_keyword_filter_fetches_enough_candidates_before_truncation() -> None:
    """Issue #33：带关键词过滤时标量查询先取足候选（>=200），避免 limit 截断期望规则。"""
    from src.runtime.policy_qa.structured_policy_retriever import (
        StructuredPolicyQuery,
        StructuredPolicyRuleRetriever,
    )

    captured: dict[str, list[int]] = {"limits": []}

    class FakeClient:
        def query(self, *, limit, **_kwargs):
            captured["limits"].append(limit)
            return []

    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.client = FakeClient()
    retriever.collection_name = "policy_rules_v2"
    retriever.execute_query(StructuredPolicyQuery(
        query_name="kw",
        filters={"rule_type": "支付比例"},
        text_must_include_any=["起付标准至3万元"],
    ))

    # 首次标量查询放大候选到 200；后续 LIKE 兜底仍按 top_k（20）
    assert captured["limits"][0] == 200


def test_relevance_query_rejects_generic_rules_and_uses_dense_bm25_fallback(
    monkeypatch,
) -> None:
    from src.runtime.policy_qa import structured_policy_retriever as module
    from src.runtime.policy_qa.structured_policy_retriever import (
        StructuredPolicyQuery,
        StructuredPolicyRuleRetriever,
    )

    class FakeClient:
        def __init__(self) -> None:
            self.query_calls = 0
            self.search_calls = 0

        def query(self, **_kwargs):
            self.query_calls += 1
            if self.query_calls > 1:
                return []
            return [{
                "rule_id": "generic",
                "rule_type": "支付比例",
                "insu_type": "",
                "med_type": "",
                "source_text": "个人负担按支付比例计算。",
            }]

        def search(self, **_kwargs):
            self.search_calls += 1
            return [[
                {
                    "distance": 0.8,
                    "entity": {
                        "rule_id": "less-relevant",
                        "rule_type": "支付比例",
                        "insu_type": "公疗医照",
                        "med_type": "门诊-普通门急诊",
                        "source_text": "门诊个人负担适用支付比例。",
                    },
                },
                {
                    "distance": 0.8,
                    "entity": {
                        "rule_id": "self-pay-rule",
                        "rule_type": "支付比例",
                        "insu_type": "公疗医照",
                        "med_type": "门诊-普通门急诊",
                        "source_text": "门诊个人自付一和自付二组成个人负担。",
                    },
                },
            ]]

    monkeypatch.setattr(
        module,
        "get_embedding_provider",
        lambda: SimpleNamespace(encode=lambda _texts: [[0.1, 0.2]]),
        raising=False,
    )
    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.client = FakeClient()
    retriever.collection_name = "policy_rules_v2"
    query = StructuredPolicyQuery(
        query_name="personal-liability",
        filters={
            "rule_type": "支付比例",
            "insu_type": "公疗医照",
            "med_type": "门诊-普通门急诊",
        },
        text_must_include_any=["个人负担", "自付一", "自付二"],
    )
    query.search_text = "门诊个人负担 自付一 自付二 支付比例"
    query.exact_match_fields = ["insu_type", "med_type"]

    results = retriever.execute_query(query)

    assert retriever.client.search_calls == 1
    assert [item["rule_id"] for item in results] == [
        "self-pay-rule", "less-relevant",
    ]


def test_empty_context_plan_queries_refuses() -> None:
    """Issue #33 加固：空上下文（无险种/医疗类别/人群/医院等级/结算单号）拒绝规划查询。

    空上下文时所有维度过滤退化为"空值保留"，泛化规则会被当作确定答案召回
    （真实语料基线 6 条 BROAD_* 负例全部误召同 3 条门诊规则）。
    """
    from src.runtime.policy_qa.structured_policy_retriever import (
        NormalizedPolicyContext,
        StructuredPolicyRuleRetriever,
    )

    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    ctx = NormalizedPolicyContext()

    assert retriever.plan_queries(ctx, target_field="统筹自付") == []


def test_partial_context_still_plans_queries() -> None:
    """只有部分维度（如仅医疗类别）不算空上下文，查询计划照常生成。"""
    from src.runtime.policy_qa.structured_policy_retriever import (
        NormalizedPolicyContext,
        StructuredPolicyRuleRetriever,
    )

    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    ctx = NormalizedPolicyContext(med_type="门诊-普通门急诊")

    queries = retriever.plan_queries(ctx, target_field="统筹自付")

    assert len(queries) == 2
    assert queries[0].filters["med_type"] == "门诊-普通门急诊"


def test_empty_context_retrieve_returns_refusal_result() -> None:
    """空上下文 retrieve 直接返回空证据并标记 refusal_reason，不触碰 Milvus。"""
    from src.runtime.policy_qa.structured_policy_retriever import (
        NormalizedPolicyContext,
        StructuredPolicyRuleRetriever,
    )

    class ExplodingClient:
        def query(self, **_kwargs):
            raise AssertionError("空上下文不应执行任何 Milvus 查询")

    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.client = ExplodingClient()
    retriever.collection_name = "policy_rules_v2"

    result = retriever.retrieve(NormalizedPolicyContext(), target_field="统筹自付")

    assert result.selected_evidence == []
    assert result.refusal_reason == "empty_context"
    assert "缺少可依据的政策上下文" in result.refusal_message
    assert result.planned_queries == []


def test_broad_empty_ctx_negatives_refuse_through_structured() -> None:
    """真实语料基线 6 条 BROAD_* 空 ctx 负例（BROAD_DEDUCTIBLE / BROAD_RETIREE_RATIO /
    BROAD_REMOTE / BROAD_SHANGHAI / BROAD_AMOUNT_BAND / BROAD_VERSION）走 structured
    的行为断言：ctx 均为全空 → 必须诚实拒答，不得召回泛化规则兜底。"""
    from src.runtime.policy_qa.structured_policy_retriever import (
        NormalizedPolicyContext,
        StructuredPolicyRuleRetriever,
    )

    class ExplodingClient:
        def query(self, **_kwargs):
            raise AssertionError("空上下文不应执行任何 Milvus 查询")

    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.client = ExplodingClient()
    retriever.collection_name = "policy_rules_v2"

    result = retriever.retrieve(NormalizedPolicyContext(), target_field="统筹自付")

    assert result.selected_evidence == []
    assert result.refusal_reason == "empty_context"
    assert result.refusal_message


def test_empty_context_retrieve_honors_explicit_custom_queries() -> None:
    """外部显式传入 custom_queries 时不受空上下文拒答限制（调用方自负规划责任）。"""
    from src.runtime.policy_qa.structured_policy_retriever import (
        NormalizedPolicyContext,
        StructuredPolicyQuery,
        StructuredPolicyRuleRetriever,
    )

    calls: list[str] = []

    class FakeClient:
        def query(self, *, filter, **_kwargs):
            calls.append(filter)
            return []

    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.client = FakeClient()
    retriever.collection_name = "policy_rules_v2"

    result = retriever.retrieve(
        NormalizedPolicyContext(),
        target_field="统筹自付",
        custom_queries=[StructuredPolicyQuery(query_name="explicit", filters={"rule_type": "支付比例"})],
    )

    assert len(calls) == 1
    assert result.refusal_reason == ""
