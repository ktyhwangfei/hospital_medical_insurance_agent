"""提取契约构建器单测 — 内存注册表，零外部依赖。

[依据: docs/steering/政策知识管线设计文档.md §7.1 / §3.1]
"""
from src.semantic_layer.extraction_contract import build_extraction_schema
from src.semantic_layer.models import BusinessDomain, BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry


def _make_registry():
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_domain(BusinessDomain(domain_code="ybzc", name="医保政策"))
    store.save_object(BusinessObject(object_code="zcgz", domain_code="ybzc", name="政策规则"))
    return reg, store


def test_empty_when_all_draft():
    """draft 指标不应进入契约（设计文档 §7.1：只返回 status=published）。"""
    reg, store = _make_registry()
    store.save_metric(Metric(
        metric_code="zcgz.payment_ratio", object_code="zcgz", name="支付比例",
        status="draft",
    ))
    schema = build_extraction_schema(reg, "zcgz")
    assert schema.fields == []
    assert schema.entities == []
    assert schema.relations == []
    assert schema.dictionaries == {}
    assert schema.schema_version == 1


def test_published_field_has_short_code_and_attrs():
    """已发布 field 指标：短码 + indexed + value_domain + extraction_hint 透传。"""
    reg, store = _make_registry()
    store.save_metric(Metric(
        metric_code="zcgz.insu_type", object_code="zcgz", name="险种类别",
        semantic_type="Enum", value_domain="insu_type",
        metric_kind="field", indexed=True,
        extraction_hint="城镇职工/城乡居民/超转人员/生育保险",
        status="published", schema_version=3,
    ))
    schema = build_extraction_schema(reg, "zcgz")
    assert len(schema.fields) == 1
    f = schema.fields[0]
    assert f.code == "insu_type"          # 短码：去掉 zcgz. 前缀
    assert f.indexed is True
    assert f.value_domain == "insu_type"
    assert f.extraction_hint.startswith("城镇职工")
    assert schema.schema_version == 3      # 取已发布指标的 max schema_version


def test_dictionary_resolved_from_value_domain():
    """value_domain 引用的字典，其 standard_values 应解析进 dictionaries。"""
    reg, store = _make_registry()
    store.save_metric(Metric(
        metric_code="zcgz.hosp_lv", object_code="zcgz", name="医院等级",
        value_domain="hosp_lv", status="published",
    ))
    store.save_value_domain(ValueDomain(
        domain_code="hosp_lv", name="医院等级",
        standard_values=["一级", "二级", "三级"],
    ))
    schema = build_extraction_schema(reg, "zcgz")
    assert schema.dictionaries["hosp_lv"] == ["一级", "二级", "三级"]


def test_relation_uses_transformation_hints():
    """metric_kind=relation 的指标：subject/predicate/object hint 从 transformation 取。"""
    reg, store = _make_registry()
    store.save_metric(Metric(
        metric_code="zcgz.contains_item", object_code="zcgz", name="包含项目",
        metric_kind="relation", status="published",
        transformation={"subject_hint": "规则", "predicate_hint": "包含", "object_hint": "药品"},
    ))
    schema = build_extraction_schema(reg, "zcgz")
    assert len(schema.relations) == 1
    r = schema.relations[0]
    assert r.code == "contains_item"
    assert r.subject_hint == "规则"
    assert r.predicate_hint == "包含"
    assert r.object_hint == "药品"
    assert schema.fields == []             # relation 不进 fields


def test_entity_kind_routed_to_entities():
    """metric_kind=entity 的指标进 entities，不进 fields。"""
    reg, store = _make_registry()
    store.save_metric(Metric(
        metric_code="zcgz.hospital", object_code="zcgz", name="医院",
        metric_kind="entity", value_domain="hosp_lv", status="published",
    ))
    schema = build_extraction_schema(reg, "zcgz")
    assert len(schema.entities) == 1
    assert schema.entities[0].code == "hospital"
    assert schema.fields == []


def test_publish_object_unlocks_extraction_schema():
    """publish_object 发布后，build_extraction_schema 应返回该对象指标（解锁 §3.1）。

    发布前契约空（draft 不进），发布后有数据。这是 P3 推迟 3.1 的根因验证。
    """
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_object(BusinessObject(object_code="t_unlock", domain_code="d", name="解锁测试"))
    store.save_metric(Metric(
        metric_code="t_unlock.f1", object_code="t_unlock", name="字段1",
        metric_kind="field", semantic_type="Amount",
    ))
    # 发布前：draft 不进契约
    schema_before = build_extraction_schema(reg, "t_unlock")
    assert len(schema_before.fields) == 0, "draft 指标不应进契约"
    # 发布后：published 进契约
    reg.publish_object("t_unlock")
    schema_after = build_extraction_schema(reg, "t_unlock")
    assert len(schema_after.fields) == 1, "发布后契约应有 1 个字段"
    assert schema_after.fields[0].code == "f1"


def test_build_prompt_from_schema_is_field_agnostic():
    """构建器从 schema 动态拼提示词——加维度只改语义层，不改此函数（§3.1 核心证明）。"""
    from src.semantic_layer.extraction_contract import (
        build_prompt_from_schema, ExtractionSchema, FieldContract,
    )
    # schema A：1 个字段
    schema_a = ExtractionSchema(fields=[FieldContract(code="f1", name="字段1")])
    prompt_a = build_prompt_from_schema("原文A", "标题A", schema_a)
    assert "f1" in prompt_a and "字段1" in prompt_a
    assert "原文A" in prompt_a and "标题A" in prompt_a

    # schema B：2 个字段 + extraction_hint + value_domain（证明 hint/值域也动态拼）
    schema_b = ExtractionSchema(
        fields=[
            FieldContract(code="f1", name="字段1"),
            FieldContract(code="f2", name="字段2", extraction_hint="必须提取此金额",
                          value_domain="vd"),
        ],
        dictionaries={"vd": ["高", "低"]},
    )
    prompt_b = build_prompt_from_schema("原文B", "标题B", schema_b)
    assert "f2" in prompt_b, "新字段应自动进提示词"
    assert "必须提取此金额" in prompt_b, "extraction_hint 应进提示词"
    assert "高" in prompt_b, "value_domain 字典值应进提示词"
    # 关键：构建器代码没变，schema 不同 → 提示词不同（字段无关）
    assert prompt_a != prompt_b
