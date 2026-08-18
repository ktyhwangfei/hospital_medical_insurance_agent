"""提取契约构建器单测 — 内存注册表，零外部依赖。

[依据: docs/steering/政策知识管线设计文档.md §7.1 / §3.1]
"""
from src.semantic_layer.extraction_contract import build_extraction_schema
from src.semantic_layer.models import BusinessDomain, BusinessObject, Metric, ValueDomain
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import (
    ensure_policy_dictionaries, publish_seed_policy_object, seed_semantic_layer,
)


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


def test_contract_reads_latest_object_version_instead_of_partial_live_status():
    reg, store = _make_registry()
    for code in ("rule_type", "rule_value", "cap_amount"):
        store.save_metric(Metric(
            metric_code=f"zcgz.{code}", object_code="zcgz", name=code,
        ))
    reg.publish_object("zcgz")

    for metric in store.list_metrics("zcgz"):
        store.save_metric(metric.model_copy(update={"status": "draft"}))
    store.save_metric(Metric(
        metric_code="jjgs", object_code="zcgz", name="基金归属", status="published",
    ))

    schema = build_extraction_schema(reg, "zcgz")

    assert {field.code for field in schema.fields} == {
        "rule_type", "rule_value", "cap_amount",
    }


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


def test_seed_includes_reextract_quality_metrics_and_publish_exposes_them():
    """迭代19 修改5：seed 后 zcgz 含新指标（相对比例系数/跨单元引用）；发布后进契约。"""
    from src.semantic_layer.registry import InMemoryRegistryStore as SeedRegistryStore

    store = SeedRegistryStore()
    reg = SemanticRegistry(store)
    seed_semantic_layer(store)

    metrics = {m.metric_code: m for m in store.list_metrics("zcgz")}
    coeff = metrics.get("zcgz.personal_payment_coefficient")
    ref = metrics.get("zcgz.referenced_clause")
    assert coeff is not None, "seed 应包含个人支付比例系数指标"
    assert coeff.status == "draft"
    assert "60%" in (coeff.extraction_hint or ""), "系数指标应带相对比例提取提示"
    assert ref is not None, "seed 应包含跨单元引用条款指标"

    # 发布 zcgz → 新指标进提取契约（解锁 schema 模式）
    reg.publish_object("zcgz")
    schema = build_extraction_schema(reg, "zcgz")
    codes = {f.code for f in schema.fields}
    assert "personal_payment_coefficient" in codes
    assert "referenced_clause" in codes
    assert "payment_ratio" in codes


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


def test_build_prompt_from_schema_requires_all_field_keys():
    """LLM 常省略字段键——提示词必须硬性要求全部字段逐键输出（实测只回 4 字段）。"""
    from src.semantic_layer.extraction_contract import (
        build_prompt_from_schema, ExtractionSchema, FieldContract,
    )
    schema = ExtractionSchema(fields=[
        FieldContract(code="f1", name="字段1"),
        FieldContract(code="f2", name="字段2"),
    ])
    prompt = build_prompt_from_schema("原文", "标题", schema)
    assert "全部 2 个字段" in prompt, "应标注字段总数"
    assert "禁止省略" in prompt, "应禁止省略字段键"
    assert "键数量必须等于 2" in prompt, "应要求自检键数量"


def test_build_prompt_from_schema_requires_entities_array():
    """schema prompt 输出格式必须含 entities 字段要求（S5 冲突分区靠实体短语分区）。

    实测 schema 模式 LLM 从不输出 entities → S5 分区判定无候选值，永远产不出维度候选。
    """
    from src.semantic_layer.extraction_contract import (
        build_prompt_from_schema, ExtractionSchema, FieldContract,
    )
    schema = ExtractionSchema(fields=[FieldContract(code="f1", name="字段1")])
    prompt = build_prompt_from_schema("原文", "标题", schema)
    assert '"entities"' in prompt, "输出格式示例必须含 entities 数组"
    assert '"entity_type"' in prompt, "实体项必须含类型键"
    assert '"RATIO"' in prompt, "必须给出比例实体类型示例（S5 分区短语来源）"
    assert "entities 不计入" in prompt, "字段键数自检必须排除 entities"
    assert "统筹基金支付比例" in prompt, "比例实体必须带归属主体（不得只写支付比例）"


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


# ── P8.3：种子发布后契约含全部字段 + 5 政策字典（收口标准）─────────


def test_seed_publish_unlocks_full_zcgz_contract():
    """P8.3 收口：seed + publish_seed_policy_object 后，契约含全部 19 字段 + 5 字典。

    [来源: docs/steering/政策知识管线开发计划.md Phase 8.3 — zcgz 指标 published + value_domain]
    """
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    seed_semantic_layer(store)
    # 发布前契约空（draft 不进）
    assert build_extraction_schema(reg, "zcgz").fields == []
    publish_seed_policy_object(reg)
    schema = build_extraction_schema(reg, "zcgz")
    # 22 字段全部进契约（19 原始 + 迭代19 修改5 新增 2：个人支付比例系数/跨单元引用
    # + U2 新增 1：个人支付比例 personal_payment_ratio）
    assert len(schema.fields) == 22, f"期望 22 字段，实际 {len(schema.fields)}"
    codes = {f.code for f in schema.fields}
    assert codes == {
        "rule_id", "fact_id", "policy_id", "clause_id", "source_text",
        "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
        "admission_order", "payment_ratio", "personal_payment_ratio",
        "deductible_amount", "cap_amount",
        "amount_band", "time_period", "priority", "rule_type", "rule_value",
        "personal_payment_coefficient", "referenced_clause",
    }
    # 核心检索维度 indexed + value_domain
    insu = next(f for f in schema.fields if f.code == "insu_type")
    assert insu.indexed is True and insu.value_domain == "insu_type"
    # 5 政策字典全部解析
    assert set(schema.dictionaries) == {
        "insu_type", "med_type", "hosp_lv", "psn_type", "setl_type",
    }
    assert "三级" in schema.dictionaries["hosp_lv"]
    assert "城镇职工基本医疗保险" in schema.dictionaries["insu_type"]


def test_publish_seed_policy_object_idempotent():
    """publish_seed_policy_object 幂等：重复调用不产生新版本。"""
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    seed_semantic_layer(store)
    publish_seed_policy_object(reg)
    v1 = reg.list_object_versions("zcgz")
    assert len(v1) == 1
    publish_seed_policy_object(reg)  # 再调用不应新增版本
    assert reg.list_object_versions("zcgz") == v1


def test_ensure_policy_dictionaries_seeds_five_domains():
    """ensure_policy_dictionaries 灌入 5 个政策值域（standard_values）。"""
    store = InMemoryRegistryStore()
    ensure_policy_dictionaries(store)
    for code in ("insu_type", "med_type", "hosp_lv", "psn_type", "setl_type"):
        vd = store.get_value_domain(code)
        assert vd is not None, f"缺少值域 {code}"
        assert vd.standard_values, f"{code} standard_values 为空"
    assert "三级" in store.get_value_domain("hosp_lv").standard_values
