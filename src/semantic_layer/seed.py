"""Seed data migration: load settlement domain metrics from skill YAML into Registry.

Source: skills/settlement_explain_skill/field_mapping.yaml + skill_manifest.yaml
"""
from src.semantic_layer.models import (
    BusinessDomain, BusinessObject, ObjectRelation,
    Metric, ValueDomain, ValueDomainMapping,
)
from src.semantic_layer.registry import RegistryStore


def seed_settlement_domain(store: RegistryStore) -> None:
    """Seed the Settlement domain, its Business Object, and all 11 core metrics."""
    store.save_domain(BusinessDomain(
        domain_code="settlement", name="医保结算",
        description="结算、费用、退费", sort_order=1,
    ))
    store.save_object(BusinessObject(
        object_code="Settlement", domain_code="settlement", name="医保结算",
        definition="一次医保结算交易的完整记录",
        identifier="settlement_id",
        source_object="InsuranceTransaction",
        source_adapter_port="InsuranceInterfacePort",
        version="1.0", status="published",
        relations=[ObjectRelation(target="Patient", type="belongs_to", cardinality="N:1")],
    ))
    _seed_value_domain_hospital_level(store)
    _seed_value_domain_person_type(store)
    _seed_value_domain_insurance_type(store)
    _seed_settlement_metrics(store)


def _seed_value_domain_hospital_level(store: RegistryStore) -> None:
    store.save_value_domain(ValueDomain(domain_code="HOSPITAL_LEVEL", name="医院等级", description="医疗机构等级编码"))
    for sv in ["三级", "3", "03", "三级甲等", "三甲"]:
        store.save_value_mapping(ValueDomainMapping(domain_code="HOSPITAL_LEVEL", source_value=sv, standard_value="LEVEL_3"))
    for sv in ["二级", "2", "02", "二级甲等", "二甲"]:
        store.save_value_mapping(ValueDomainMapping(domain_code="HOSPITAL_LEVEL", source_value=sv, standard_value="LEVEL_2"))
    for sv in ["一级", "1", "01"]:
        store.save_value_mapping(ValueDomainMapping(domain_code="HOSPITAL_LEVEL", source_value=sv, standard_value="LEVEL_1"))


def _seed_value_domain_person_type(store: RegistryStore) -> None:
    store.save_value_domain(ValueDomain(domain_code="PERSON_TYPE", name="人员类别"))
    store.save_value_mapping(ValueDomainMapping(domain_code="PERSON_TYPE", source_value="退休人员", standard_value="RETIRED"))
    store.save_value_mapping(ValueDomainMapping(domain_code="PERSON_TYPE", source_value="在职人员", standard_value="EMPLOYED"))
    store.save_value_mapping(ValueDomainMapping(domain_code="PERSON_TYPE", source_value="退休", standard_value="RETIRED"))
    store.save_value_mapping(ValueDomainMapping(domain_code="PERSON_TYPE", source_value="在职", standard_value="EMPLOYED"))


def _seed_value_domain_insurance_type(store: RegistryStore) -> None:
    store.save_value_domain(ValueDomain(domain_code="INSURANCE_TYPE", name="险种类型"))
    store.save_value_mapping(ValueDomainMapping(domain_code="INSURANCE_TYPE", source_value="城镇职工", standard_value="EMPLOYEE"))
    store.save_value_mapping(ValueDomainMapping(domain_code="INSURANCE_TYPE", source_value="职工", standard_value="EMPLOYEE"))
    store.save_value_mapping(ValueDomainMapping(domain_code="INSURANCE_TYPE", source_value="01", standard_value="EMPLOYEE"))
    store.save_value_mapping(ValueDomainMapping(domain_code="INSURANCE_TYPE", source_value="城乡居民", standard_value="RESIDENT"))
    store.save_value_mapping(ValueDomainMapping(domain_code="INSURANCE_TYPE", source_value="居民", standard_value="RESIDENT"))


def _seed_settlement_metrics(store: RegistryStore) -> None:
    """Seed all 11 settlement metrics from field_mapping.yaml."""
    metrics = [
        Metric(metric_code="Settlement.deductible", object_code="Settlement", name="起付线", definition="医保开始报销前需先由个人承担的固定金额", metric_type="Atomic", semantic_type="Amount", unit="元", required=True, source_object="InsuranceTransaction", source_field="deductible", source_adapter_port="InsuranceInterfacePort", importance="core"),
        Metric(metric_code="Settlement.medical_insurance_inner_amount", object_code="Settlement", name="医保内费用", definition="本次结算纳入医保报销范围的费用总额", metric_type="Atomic", semantic_type="Amount", unit="元", source_object="InsuranceTransaction", source_field="medical_insurance_inner_amount", source_adapter_port="InsuranceInterfacePort", importance="core"),
        Metric(metric_code="Settlement.basic_pooling_payment", object_code="Settlement", name="统筹支付", definition="基本医保统筹基金已经支付的部分", metric_type="Atomic", semantic_type="Amount", unit="元", required=True, source_object="InsuranceTransaction", source_field="basic_pooling_payment", source_adapter_port="InsuranceInterfacePort", importance="core"),
        Metric(metric_code="Settlement.basic_pooling_self_pay", object_code="Settlement", name="统筹自付", definition="基本医保统筹段内按政策比例由个人承担的金额", metric_type="Atomic", semantic_type="Amount", unit="元", required=True, source_object="InsuranceTransaction", source_field="basic_pooling_self_pay", source_adapter_port="InsuranceInterfacePort", importance="core"),
        Metric(metric_code="Settlement.large_amount_payment", object_code="Settlement", name="大额支付", definition="大额医疗费用补助基金支付的部分", metric_type="Atomic", semantic_type="Amount", unit="元", source_object="InsuranceTransaction", source_field="large_amount_payment", source_adapter_port="InsuranceInterfacePort", importance="core"),
        Metric(metric_code="Settlement.large_amount_self_pay", object_code="Settlement", name="大额自付", definition="进入大额保障段后个人承担的部分", metric_type="Atomic", semantic_type="Amount", unit="元", source_object="InsuranceTransaction", source_field="large_amount_self_pay", source_adapter_port="InsuranceInterfacePort", importance="core"),
        Metric(metric_code="Settlement.personal_total_pay", object_code="Settlement", name="个人总支付", definition="包含多类个人负担，不等于统筹自付", metric_type="Atomic", semantic_type="Amount", unit="元", required=True, source_object="InsuranceTransaction", source_field="personal_total_pay", source_adapter_port="InsuranceInterfacePort", importance="core"),
        Metric(metric_code="Settlement.person_type", object_code="Settlement", name="人员类别", definition="参保人员类别（在职/退休等）", metric_type="Atomic", semantic_type="Enum", source_object="InsuranceTransaction", source_field="person_type", source_adapter_port="InsuranceInterfacePort", value_domain="PERSON_TYPE", importance="core"),
        Metric(metric_code="Settlement.insurance_type", object_code="Settlement", name="险种类型", definition="基本医保险种类型", metric_type="Atomic", semantic_type="Enum", source_object="InsuranceTransaction", source_field="insurance_type", source_adapter_port="InsuranceInterfacePort", value_domain="INSURANCE_TYPE", importance="core"),
        Metric(metric_code="Settlement.service_type", object_code="Settlement", name="医疗类别", definition="本次医疗服务的业务类别", metric_type="Atomic", semantic_type="Enum", source_object="InsuranceTransaction", source_field="service_type", source_adapter_port="InsuranceInterfacePort", importance="optional"),
        Metric(metric_code="Settlement.hospital_level", object_code="Settlement", name="医院等级", definition="医疗机构等级", metric_type="Atomic", semantic_type="Enum", source_object="InsuranceTransaction", source_field="hospital_level", source_adapter_port="InsuranceInterfacePort", value_domain="HOSPITAL_LEVEL", importance="core"),
    ]
    for m in metrics:
        store.save_metric(m)
