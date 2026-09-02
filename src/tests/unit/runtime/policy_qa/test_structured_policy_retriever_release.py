from __future__ import annotations

from types import SimpleNamespace


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

    monkeypatch.setattr(
        module,
        "_get_release_store",
        lambda: SimpleNamespace(
            get_active_release=lambda: SimpleNamespace(
                rules_collection="policy_rules_REL_complete"
            )
        ),
        raising=False,
    )
    monkeypatch.setattr(
        module, "_is_complete_release_collection", lambda *_args: True, raising=False
    )
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

    monkeypatch.setattr(
        module,
        "_get_release_store",
        lambda: SimpleNamespace(
            get_active_release=lambda: SimpleNamespace(
                rules_collection="policy_rules_REL_incomplete"
            )
        ),
    )
    monkeypatch.setattr(
        module, "_is_complete_release_collection", lambda *_args: False, raising=False
    )

    assert module.resolve_rules_collection() == module.COLLECTION_NAME


def test_active_release_lookup_failure_falls_back_to_global_collection(monkeypatch) -> None:
    from src.runtime.policy_qa import structured_policy_retriever as module

    class UnavailableStore:
        def get_active_release(self):
            raise RuntimeError("postgres unavailable")

    monkeypatch.setattr(module, "_get_release_store", lambda: UnavailableStore(), raising=False)

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
