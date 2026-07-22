"""Tests for Semantic Registry CRUD service — in-memory backend."""
import pytest
from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, ObjectRelation, Metric,
    ValueDomain, ValueDomainMapping,
)
from src.semantic_layer.registry import SemanticRegistry, InMemoryRegistryStore


@pytest.fixture
def registry():
    """Create a registry with seed data for Settlement domain."""
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)

    store.save_domain(BusinessDomain(domain_code="settlement", name="医保结算"))
    store.save_object(BusinessObject(
        object_code="Settlement", domain_code="settlement", name="医保结算",
        identifier="settlement_id",
        source_object="InsuranceTransaction",
        source_adapter_port="InsuranceInterfacePort",
    ))
    store.save_metric(Metric(
        metric_code="Settlement.deductible", object_code="Settlement",
        name="起付线", definition="医保开始报销前需先由个人承担的固定金额",
        metric_type="Atomic", semantic_type="Amount", unit="元",
        required=True,
        source_object="InsuranceTransaction", source_field="deductible",
        source_adapter_port="InsuranceInterfacePort",
        importance="core",
    ))
    store.save_metric(Metric(
        metric_code="Settlement.fund_pay", object_code="Settlement",
        name="基金支付", metric_type="Atomic", semantic_type="Amount", unit="元",
        source_object="InsuranceTransaction", source_field="fund_pay",
        source_adapter_port="InsuranceInterfacePort",
        importance="core",
    ))
    store.save_metric(Metric(
        metric_code="Settlement.hospital_level", object_code="Settlement",
        name="医院等级", metric_type="Atomic", semantic_type="Enum",
        value_domain="HOSPITAL_LEVEL",
        source_object="InsuranceTransaction", source_field="hospital_level",
        importance="core",
    ))
    store.save_value_domain(ValueDomain(domain_code="HOSPITAL_LEVEL", name="医院等级"))
    store.save_value_mapping(ValueDomainMapping(
        domain_code="HOSPITAL_LEVEL", source_value="三级", standard_value="LEVEL_3",
    ))
    store.save_value_mapping(ValueDomainMapping(
        domain_code="HOSPITAL_LEVEL", source_value="3", standard_value="LEVEL_3",
    ))
    return reg


class TestRegistryQuery:
    def test_get_object(self, registry):
        obj = registry.get_object("Settlement")
        assert obj is not None
        assert obj.name == "医保结算"
        assert obj.source_object == "InsuranceTransaction"

    def test_get_nonexistent_object_returns_none(self, registry):
        assert registry.get_object("Nonexistent") is None

    def test_get_metrics_by_object(self, registry):
        metrics = registry.get_metrics_by_object("Settlement")
        assert len(metrics) == 3
        metric_codes = {m.metric_code for m in metrics}
        assert "Settlement.deductible" in metric_codes
        assert "Settlement.fund_pay" in metric_codes

    def test_get_metric(self, registry):
        metric = registry.get_metric("Settlement.deductible")
        assert metric is not None
        assert metric.source_field == "deductible"
        assert metric.importance == "core"


class TestValueDomainResolution:
    def test_resolve_value_domain(self, registry):
        result = registry.resolve_value("HOSPITAL_LEVEL", "三级")
        assert result == "LEVEL_3"

    def test_resolve_numeric_value(self, registry):
        result = registry.resolve_value("HOSPITAL_LEVEL", "3")
        assert result == "LEVEL_3"

    def test_resolve_unknown_value_returns_original(self, registry):
        result = registry.resolve_value("HOSPITAL_LEVEL", "未知等级")
        assert result == "未知等级"

    def test_resolve_no_value_domain_returns_original(self, registry):
        result = registry.resolve_value("NONEXISTENT", "anything")
        assert result == "anything"


class TestGetMetricsForBuilder:
    def test_build_mapping_for_object(self, registry):
        mapping = registry.get_metric_mapping("Settlement", ["deductible", "fund_pay"])
        assert len(mapping) == 2
        assert mapping[0].metric_code == "Settlement.deductible"

    def test_build_mapping_skips_missing_metrics(self, registry):
        mapping = registry.get_metric_mapping("Settlement", ["deductible", "nonexistent"])
        assert len(mapping) == 1

    def test_build_mapping_empty_metrics(self, registry):
        mapping = registry.get_metric_mapping("Settlement", [])
        assert mapping == []

    def test_build_mapping_short_codes(self, registry):
        """Short metric codes (without Object prefix) should be expanded to Object.Metric."""
        mapping = registry.get_metric_mapping("Settlement", ["deductible"])
        assert len(mapping) == 1
        assert mapping[0].metric_code == "Settlement.deductible"
