"""Tests for semantic layer Pydantic models."""
import pytest
from pydantic import ValidationError
from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, ObjectRelation, Metric,
    ValueDomain, ValueDomainMapping,
    BusinessFactsRequest, ObjectMetricRequest,
    BusinessFactsResponse, FactsMeta,
)


class TestBusinessDomain:
    def test_create_valid_domain(self):
        domain = BusinessDomain(domain_code="settlement", name="医保结算", description="结算、费用、退费", sort_order=1)
        assert domain.domain_code == "settlement"
        assert domain.name == "医保结算"

    def test_domain_code_required(self):
        with pytest.raises(ValidationError):
            BusinessDomain(name="test")


class TestBusinessObject:
    def test_create_with_relations(self):
        obj = BusinessObject(
            object_code="Settlement", domain_code="settlement", name="医保结算",
            definition="一次医保结算交易的完整记录", identifier="settlement_id",
            source_object="InsuranceTransaction", source_adapter_port="InsuranceInterfacePort",
            relations=[ObjectRelation(target="Patient", type="belongs_to", cardinality="N:1")],
        )
        assert len(obj.relations) == 1
        assert obj.relations[0].target == "Patient"

    def test_default_relations_empty_list(self):
        obj = BusinessObject(object_code="Test", domain_code="test", name="测试")
        assert obj.relations == []

    def test_default_status_draft(self):
        obj = BusinessObject(object_code="Test", domain_code="test", name="测试")
        assert obj.status == "draft"


class TestMetric:
    def test_composite_metric_code(self):
        metric = Metric(
            metric_code="Settlement.deductible", object_code="Settlement", name="起付线",
            definition="医保开始报销前需先由个人承担的固定金额",
            metric_type="Atomic", semantic_type="Amount", unit="元",
            required=True, source_object="InsuranceTransaction", source_field="deductible",
            source_adapter_port="InsuranceInterfacePort", importance="core",
        )
        assert metric.metric_code == "Settlement.deductible"
        assert metric.importance == "core"

    def test_derived_metric_has_transformation(self):
        metric = Metric(
            metric_code="Settlement.reimbursement_ratio", object_code="Settlement", name="报销比例",
            definition="基金支付占总费用的比例", metric_type="Derived", semantic_type="Ratio", unit="%",
            transformation={"formula": "fund_pay / total_fee * 100"},
        )
        assert metric.transformation is not None

    def test_default_importance_optional(self):
        metric = Metric(metric_code="Test.field", object_code="Test", name="test")
        assert metric.importance == "optional"

    def test_enum_metric_has_value_domain(self):
        metric = Metric(
            metric_code="Settlement.hospital_level", object_code="Settlement", name="医院等级",
            metric_type="Atomic", semantic_type="Enum", value_domain="HOSPITAL_LEVEL",
        )
        assert metric.value_domain == "HOSPITAL_LEVEL"


class TestBusinessFactsRequest:
    def test_create_request(self):
        req = BusinessFactsRequest(
            objects=[
                ObjectMetricRequest(object_code="Settlement", metric_codes=["fund_pay", "deductible"]),
                ObjectMetricRequest(object_code="Institution", metric_codes=["level"]),
            ],
            context={"patient_id": "P001", "encounter_id": "E001"},
        )
        assert len(req.objects) == 2
        assert req.objects[0].object_code == "Settlement"
        assert req.context["patient_id"] == "P001"


class TestBusinessFactsResponse:
    def test_create_response(self):
        resp = BusinessFactsResponse(
            facts={"Settlement": {"fund_pay": 28560, "deductible": 1300}},
            meta=FactsMeta(version="1.0"),
        )
        assert resp.facts["Settlement"]["fund_pay"] == 28560
        assert resp.meta.version == "1.0"

    def test_meta_warnings_default_empty(self):
        resp = BusinessFactsResponse(facts={"Settlement": {"deductible": 1300}})
        assert resp.meta.warnings == []


class TestValueDomain:
    def test_create_value_domain(self):
        vd = ValueDomain(domain_code="HOSPITAL_LEVEL", name="医院等级", description="医疗机构等级编码")
        assert vd.domain_code == "HOSPITAL_LEVEL"
        assert vd.name == "医院等级"

    def test_value_domain_description_optional(self):
        vd = ValueDomain(domain_code="PERSON_TYPE", name="人员类别")
        assert vd.description is None


class TestValueDomainMapping:
    def test_create_mapping(self):
        vm = ValueDomainMapping(
            id=1, domain_code="HOSPITAL_LEVEL",
            source_value="三级", standard_value="LEVEL_3",
            description="三级医院",
        )
        assert vm.source_value == "三级"
        assert vm.standard_value == "LEVEL_3"

    def test_mapping_id_optional(self):
        vm = ValueDomainMapping(domain_code="PERSON_TYPE", source_value="退休", standard_value="RETIRED")
        assert vm.id is None
