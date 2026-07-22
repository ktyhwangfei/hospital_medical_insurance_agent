"""End-to-end integration test: Registry → Builder → Facts."""
import pytest
from unittest.mock import MagicMock
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_settlement_domain
from src.semantic_layer.builder import BusinessFactsBuilder
from src.semantic_layer.models import BusinessFactsRequest, ObjectMetricRequest


@pytest.fixture
def full_chain():
    store = InMemoryRegistryStore()
    seed_settlement_domain(store)
    registry = SemanticRegistry(store)
    adapter = MagicMock()
    adapter.query_transaction.return_value = type("Result", (), {
        "status": type("Status", (), {"value": "success"})(),
        "source_system": "insurance",
        "capability": "query_transaction",
        "data": {
            "deductible": 1300, "basic_pooling_payment": 28560,
            "basic_pooling_self_pay": 4520, "large_amount_payment": 5000,
            "large_amount_self_pay": 800, "personal_total_pay": 5820,
            "person_type": "退休人员", "insurance_type": "城镇职工",
            "service_type": "普通住院", "hospital_level": "三级",
            "medical_insurance_inner_amount": 35000,
        },
        "data_quality": type("Quality", (), {"value": "complete"})(),
    })()
    builder = BusinessFactsBuilder(registry, {"InsuranceInterfacePort": adapter})
    return registry, builder


class TestFullChain:
    def test_settlement_explain_skill_facts(self, full_chain):
        """Simulate settlement_explain_skill requesting its declared metrics."""
        registry, builder = full_chain
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(
                object_code="Settlement",
                metric_codes=[
                    "deductible", "basic_pooling_payment", "basic_pooling_self_pay",
                    "large_amount_payment", "large_amount_self_pay",
                    "personal_total_pay", "person_type", "insurance_type",
                    "service_type", "hospital_level",
                ],
            )],
            context={"patient_id": "P001", "encounter_id": "E001", "settlement_id": "1671213"},
        )
        result = builder.build(request)
        facts = result.facts["Settlement"]
        assert facts["deductible"] == 1300
        assert facts["basic_pooling_payment"] == 28560
        assert facts["basic_pooling_self_pay"] == 4520
        assert facts["personal_total_pay"] == 5820
        assert facts["hospital_level"] == "LEVEL_3"
        assert facts["person_type"] == "RETIRED"
        assert facts["insurance_type"] == "EMPLOYEE"
        assert result.meta.warnings == []

    def test_missing_core_metric_produces_warning(self, full_chain):
        """When adapter returns no data for a core metric, warning is generated."""
        registry, builder = full_chain
        adapter = builder._adapter_builders["InsuranceInterfacePort"]
        adapter.query_transaction.return_value.data = {"deductible": 1300}
        request = BusinessFactsRequest(
            objects=[ObjectMetricRequest(
                object_code="Settlement",
                metric_codes=["deductible", "basic_pooling_payment"],
            )],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert "deductible" in result.facts["Settlement"]
        assert len(result.meta.warnings) >= 1

    def test_multiple_objects_request(self, full_chain):
        """Builder should handle requests for multiple objects."""
        registry, builder = full_chain
        request = BusinessFactsRequest(
            objects=[
                ObjectMetricRequest(object_code="Settlement", metric_codes=["deductible", "basic_pooling_payment"]),
                ObjectMetricRequest(object_code="Settlement", metric_codes=["hospital_level"]),
            ],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        result = builder.build(request)
        assert "Settlement" in result.facts
        assert result.facts["Settlement"]["deductible"] == 1300
