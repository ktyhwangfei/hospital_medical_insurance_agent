"""Tests for Business Facts Builder."""
import pytest
from unittest.mock import MagicMock
from src.semantic_layer.models import (
    BusinessFactsRequest, ObjectMetricRequest, BusinessFactsResponse,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_settlement_domain
from src.semantic_layer.builder import BusinessFactsBuilder


@pytest.fixture
def registry():
    store = InMemoryRegistryStore()
    seed_settlement_domain(store)
    return SemanticRegistry(store)


@pytest.fixture
def mock_insurance_adapter():
    adapter = MagicMock()
    adapter.query_transaction.return_value = type("Result", (), {
        "status": type("Status", (), {"value": "success"})(),
        "source_system": "insurance",
        "capability": "query_transaction",
        "data": {
            "deductible": 1300,
            "basic_pooling_payment": 28560,
            "basic_pooling_self_pay": 4520,
            "large_amount_payment": 0,
            "large_amount_self_pay": 0,
            "personal_total_pay": 5820,
            "person_type": "退休人员",
            "insurance_type": "城镇职工",
            "service_type": "普通住院",
            "hospital_level": "三级",
            "medical_insurance_inner_amount": 35000,
        },
        "data_quality": type("Quality", (), {"value": "complete"})(),
    })()
    return adapter


class TestBuilderBasic:
    def test_build_single_object_facts(self, registry, mock_insurance_adapter):
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(object_code="Settlement", metric_codes=["deductible", "basic_pooling_payment", "basic_pooling_self_pay"])],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert isinstance(result, BusinessFactsResponse)
        assert "Settlement" in result.facts
        assert result.facts["Settlement"]["deductible"] == 1300
        assert result.facts["Settlement"]["basic_pooling_payment"] == 28560

    def test_build_applies_value_domain(self, registry, mock_insurance_adapter):
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(object_code="Settlement", metric_codes=["hospital_level", "person_type", "insurance_type"])],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert result.facts["Settlement"]["hospital_level"] == "LEVEL_3"
        assert result.facts["Settlement"]["person_type"] == "RETIRED"
        assert result.facts["Settlement"]["insurance_type"] == "EMPLOYEE"

    def test_build_missing_optional_metric_does_not_block(self, registry, mock_insurance_adapter):
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(object_code="Settlement", metric_codes=["deductible", "nonexistent_field"])],
            context={"patient_id": "P001"},
        )
        result = builder.build(request)
        assert result.facts["Settlement"]["deductible"] == 1300

    def test_adapters_called_with_context(self, registry, mock_insurance_adapter):
        builders = {"InsuranceInterfacePort": mock_insurance_adapter}
        builder = BusinessFactsBuilder(registry, builders)
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(object_code="Settlement", metric_codes=["deductible"])],
            context={"patient_id": "P001", "encounter_id": "E001", "settlement_id": "1671213"},
        )
        builder.build(request)
        mock_insurance_adapter.query_transaction.assert_called_once()
        call_args = mock_insurance_adapter.query_transaction.call_args
        assert call_args.kwargs.get("patient_id") == "P001"
        assert call_args.kwargs.get("encounter_id") == "E001"
