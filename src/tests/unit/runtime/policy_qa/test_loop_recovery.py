from types import SimpleNamespace

import pytest

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
