from __future__ import annotations

import pytest

from src.runtime.policy_qa.settlement_data_provider import (
    SemanticSettlementDataProvider,
    SettlementNotFoundError,
)
from src.semantic_layer.query_planner import QueryEvidence, SemanticQueryResult
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import publish_seed_query_object, seed_semantic_layer


class _FakeQueryService:
    def __init__(self, result: SemanticQueryResult) -> None:
        self.result = result
        self.query = None

    def execute(self, query):
        self.query = query
        return self.result


def _registry() -> SemanticRegistry:
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    publish_seed_query_object(registry)
    return registry


def _result(*, quality_status: str = "complete", rows=None, anchor_count=1, segment_count=2, matched=2):
    return SemanticQueryResult(
        rows=rows or [],
        model_version="1",
        result_grain=["inpatient_admission"],
        query_scope="whole_admission",
        quality_status=quality_status,
        evidence=QueryEvidence(
            plan_hash="plan-1",
            datasets_used=["benefit_segments", "payment_segments"],
            anchor_count=anchor_count,
            segment_count=segment_count,
            matched_segment_count=matched,
            stay_start_date="2025-01-01",
            stay_end_date="2025-04-15",
        ),
    )


@pytest.mark.asyncio
async def test_provider_queries_whole_admission_and_maps_all_segments():
    service = _FakeQueryService(_result(rows=[{
        "total_amount": 3000,
        "medical_insurance_inner_amount": 2600,
        "deductible": 500,
        "basic_pooling_payment": 1800,
        "basic_pooling_self_pay": 300,
        "large_amount_payment": 100,
        "large_amount_self_pay": 50,
        "personal_total_pay": 1100,
        "yearly_cycle_count": 2,
        "person_type": "2",
        "insurance_type": "3",
        "service_type": "21",
    }]))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    context = await provider.get_settlement_context("1671213")

    assert service.query.scope.anchor.value == "1671213"
    assert service.query.scope.query_scope == "whole_admission"
    assert context.total_amount == 3000
    assert context.person_type == "退休人员"
    assert service.result.rows[0]["person_type"] == "退休人员"
    assert context.query_scope == "whole_admission"
    assert context.segment_count == 2
    assert context.matched_segment_count == 2
    assert context.stay_start_date == "2025-01-01"
    assert context.stay_end_date == "2025-04-15"
    assert context.amounts_reliable is True


@pytest.mark.asyncio
async def test_provider_withholds_amounts_when_segment_coverage_is_partial():
    service = _FakeQueryService(_result(
        quality_status="partial",
        rows=[{"total_amount": 3000}],
        segment_count=2,
        matched=1,
    ))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    context = await provider.get_settlement_context("1671213")

    assert context.coverage_status == "partial"
    assert context.amounts_reliable is False
    assert context.total_amount is None


@pytest.mark.asyncio
async def test_provider_reports_missing_admission():
    service = _FakeQueryService(_result(
        quality_status="unavailable",
        anchor_count=0,
        segment_count=0,
        matched=0,
    ))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    with pytest.raises(SettlementNotFoundError):
        await provider.get_settlement_context("missing")


@pytest.mark.asyncio
async def test_provider_preserves_null_and_explicit_zero_and_runs_capability_query():
    service = _FakeQueryService(_result(rows=[{
        "total_amount": None,
        "deductible": 0,
    }]))
    provider = SemanticSettlementDataProvider(service=service, registry=_registry())

    context = await provider.get_settlement_context("S-1")
    direct_result = await provider.run_semantic_query(service.query)

    assert context.total_amount is None
    assert context.deductible == 0.0
    assert direct_result.quality_status == "complete"
