from types import SimpleNamespace

import pyodbc
import pytest
import grpc
from pymilvus.exceptions import MilvusException
from pymilvus.exceptions import ParamError

from src.runtime.policy_qa.settlement_data_provider import (
    RealDbSettlementDataProvider,
    SettlementDataUnavailableError,
    SettlementNotFoundError,
)
from src.runtime.policy_qa.structured_policy_retriever import (
    PolicyRetrievalUnavailableError,
    StructuredPolicyQuery,
    StructuredPolicyRuleRetriever,
)


def test_policy_retriever_classifies_transient_connection_failure(monkeypatch) -> None:
    from src.runtime.policy_qa import structured_policy_retriever

    monkeypatch.setattr(
        structured_policy_retriever,
        "MilvusClient",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
    )

    with pytest.raises(PolicyRetrievalUnavailableError):
        StructuredPolicyRuleRetriever()


@pytest.mark.asyncio
async def test_settlement_provider_classifies_transient_source_failure() -> None:
    provider = RealDbSettlementDataProvider.__new__(RealDbSettlementDataProvider)
    provider.client = SimpleNamespace(
        get_case_context_raw=lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout"))
    )

    with pytest.raises(SettlementDataUnavailableError):
        await provider.get_settlement_context("S-1")


@pytest.mark.asyncio
async def test_settlement_provider_classifies_missing_record_without_retry_signal() -> None:
    provider = RealDbSettlementDataProvider.__new__(RealDbSettlementDataProvider)
    provider.client = SimpleNamespace(
        get_case_context_raw=lambda **_kwargs: (_ for _ in ()).throw(
            ValueError("未查询到结算记录 djh=S-404")
        )
    )

    with pytest.raises(SettlementNotFoundError):
        await provider.get_settlement_context("S-404")


@pytest.mark.asyncio
async def test_settlement_provider_does_not_retry_invalid_sql() -> None:
    provider = RealDbSettlementDataProvider.__new__(RealDbSettlementDataProvider)
    provider.client = SimpleNamespace(
        get_case_context_raw=lambda **_kwargs: (_ for _ in ()).throw(
            pyodbc.ProgrammingError("42000", "invalid SQL")
        )
    )

    with pytest.raises(pyodbc.ProgrammingError):
        await provider.get_settlement_context("S-1")


def test_policy_retriever_exposes_transient_source_failure() -> None:
    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.collection_name = "policy_rules_v2"
    retriever.client = SimpleNamespace(
        query=lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout"))
    )

    with pytest.raises(PolicyRetrievalUnavailableError):
        retriever.execute_query(
            StructuredPolicyQuery(query_name="required", filters={}, required=True)
        )


def test_policy_retriever_classifies_sdk_unavailable_failure() -> None:
    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.collection_name = "policy_rules_v2"
    retriever.client = SimpleNamespace(
        query=lambda **_kwargs: (_ for _ in ()).throw(
            MilvusException(
                code=grpc.StatusCode.UNAVAILABLE,
                message="Retry run out of 0 retry times",
            )
        )
    )

    with pytest.raises(PolicyRetrievalUnavailableError):
        retriever.execute_query(
            StructuredPolicyQuery(query_name="required", filters={}, required=True)
        )


def test_policy_retriever_does_not_retry_invalid_query() -> None:
    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.collection_name = "policy_rules_v2"
    retriever.client = SimpleNamespace(
        query=lambda **_kwargs: (_ for _ in ()).throw(ParamError(message="invalid"))
    )

    with pytest.raises(ParamError):
        retriever.execute_query(
            StructuredPolicyQuery(query_name="required", filters={}, required=True)
        )


def test_policy_retriever_exposes_transient_like_fallback_failure() -> None:
    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.collection_name = "policy_rules_v2"
    calls = 0

    def query(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        raise TimeoutError("timeout")

    retriever.client = SimpleNamespace(query=query)

    with pytest.raises(PolicyRetrievalUnavailableError):
        retriever.execute_query(
            StructuredPolicyQuery(
                query_name="required",
                filters={},
                required=True,
                text_must_include_any=["起付线"],
            )
        )


def test_policy_retriever_disables_sdk_internal_retries() -> None:
    retriever = StructuredPolicyRuleRetriever.__new__(StructuredPolicyRuleRetriever)
    retriever.collection_name = "policy_rules_v2"
    calls = []

    def query(**kwargs):
        calls.append(kwargs)
        return []

    retriever.client = SimpleNamespace(query=query)
    retriever.execute_query(
        StructuredPolicyQuery(
            query_name="required",
            filters={},
            required=True,
            text_must_include_any=["起付线"],
        )
    )

    assert len(calls) == 2
    assert all(call["retry_times"] == 0 for call in calls)
