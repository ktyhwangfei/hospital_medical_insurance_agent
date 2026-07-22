"""Tests for seed data migration from YAML to Registry."""
import pytest
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_settlement_domain


@pytest.fixture
def registry():
    store = InMemoryRegistryStore()
    return SemanticRegistry(store)


class TestSeedSettlementDomain:
    def test_seed_creates_domain(self, registry):
        seed_settlement_domain(registry._store)
        domain = registry._store.get_domain("settlement")
        assert domain is not None
        assert domain.name == "医保结算"

    def test_seed_creates_object(self, registry):
        seed_settlement_domain(registry._store)
        obj = registry.get_object("Settlement")
        assert obj is not None
        assert obj.source_object == "InsuranceTransaction"
        assert obj.identifier == "settlement_id"

    def test_seed_creates_all_metrics(self, registry):
        seed_settlement_domain(registry._store)
        metrics = registry.get_metrics_by_object("Settlement")
        metric_codes = {m.metric_code for m in metrics}
        assert "Settlement.deductible" in metric_codes
        assert "Settlement.basic_pooling_payment" in metric_codes
        assert "Settlement.basic_pooling_self_pay" in metric_codes
        assert "Settlement.personal_total_pay" in metric_codes

    def test_seed_creates_value_domains(self, registry):
        seed_settlement_domain(registry._store)
        assert registry.has_value_domain("HOSPITAL_LEVEL")
        assert registry.has_value_domain("PERSON_TYPE")
        assert registry.has_value_domain("INSURANCE_TYPE")

    def test_seed_enum_metrics_have_value_domain(self, registry):
        seed_settlement_domain(registry._store)
        hospital_level = registry.get_metric("Settlement.hospital_level")
        assert hospital_level is not None
        assert hospital_level.value_domain == "HOSPITAL_LEVEL"

    def test_seed_core_metrics_marked_core(self, registry):
        seed_settlement_domain(registry._store)
        for metric in registry.get_metrics_by_object("Settlement"):
            if metric.metric_code in (
                "Settlement.deductible", "Settlement.basic_pooling_payment",
                "Settlement.basic_pooling_self_pay", "Settlement.personal_total_pay",
            ):
                assert metric.importance == "core", f"{metric.metric_code} should be core"
