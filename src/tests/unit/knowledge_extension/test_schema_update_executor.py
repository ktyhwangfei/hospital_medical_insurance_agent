"""P5.1 三策略执行器纯函数测试 — schema 演化的字段级合并逻辑。

不依赖 LLM / Milvus，纯 dict → dict 变换，验证三策略对字段级溯源对象
（FieldTrace）的合并行为是否符合设计文档 §6.2。

[依据: docs/steering/政策知识管线设计.md §6.2；开发计划 P5.1]
"""
from src.knowledge_extension.rule_explanation.schema_update_executor import (
    SchemaUpdateExecutor,
    apply_full,
    apply_incremental,
    apply_soft_delete,
    update_rules,
)


def _sample_entity() -> dict:
    """一条 policy_rules_v2 entity：核心维度顶层标量 + 详情字段为 FieldTrace dict。"""
    return {
        "rule_id": "r1", "fact_id": "f1", "doc_id": "d1",
        "rule_type": "报销比例", "insu_type": "城镇职工",
        "schema_version": 1, "vector": [0.1] * 768,
        "payment_ratio": {"value": "85%", "extracted_at": "2026-01-01T00:00:00Z",
                          "schema_version": 1, "confidence": 0.9},
        "deductible_amount": {"value": "1300", "extracted_at": "2026-01-01T00:00:00Z",
                              "schema_version": 1, "confidence": 1.0},  # 人工锁定（冻结）
        "cap_amount": {"value": "50万", "extracted_at": "2026-01-01T00:00:00Z",
                       "schema_version": 1, "confidence": 0.9},
    }


# ── incremental：加字段，冻结保护 ──────────────────────────

def test_incremental_overwrites_non_frozen_field():
    entity = _sample_entity()
    result = apply_incremental(
        entity, extracted_fields={"payment_ratio": "90%"},
        frozen_field_codes={"deductible_amount"},
        extracted_at="2026-07-24T00:00:00Z", schema_version=2, confidence=0.8,
    )
    assert result["payment_ratio"]["value"] == "90%"
    assert result["payment_ratio"]["schema_version"] == 2
    assert result["payment_ratio"]["extracted_at"] == "2026-07-24T00:00:00Z"


def test_incremental_preserves_frozen_field():
    """冻结字段（已审核）不被重提取覆盖，保留旧 FieldTrace。"""
    entity = _sample_entity()
    result = apply_incremental(
        entity, extracted_fields={"deductible_amount": "1500"},
        frozen_field_codes={"deductible_amount"},
        extracted_at="2026-07-24T00:00:00Z", schema_version=2, confidence=0.8,
    )
    assert result["deductible_amount"]["value"] == "1300"  # 旧值保留
    assert result["deductible_amount"]["schema_version"] == 1  # 旧版本保留


def test_incremental_updates_core_dimension():
    """核心维度（如 rule_type）直接覆盖为标量。"""
    entity = _sample_entity()
    result = apply_incremental(
        entity, extracted_fields={"rule_type": "封顶线"},
        frozen_field_codes=set(),
        extracted_at="2026-07-24T00:00:00Z", schema_version=2, confidence=0.8,
    )
    assert result["rule_type"] == "封顶线"


def test_incremental_bumps_entity_schema_version():
    entity = _sample_entity()
    result = apply_incremental(
        entity, extracted_fields={}, frozen_field_codes=set(),
        extracted_at="2026-07-24T00:00:00Z", schema_version=3, confidence=0.8,
    )
    assert result["schema_version"] == 3


# ── full：改字段语义，整条重提取 ────────────────────────────

def test_full_overwrites_all_details():
    entity = _sample_entity()
    result = apply_full(
        entity, new_rule={"payment_ratio": "88%", "cap_amount": "60万"},
        extracted_at="2026-07-24T00:00:00Z", schema_version=2, confidence=0.85,
    )
    assert result["payment_ratio"]["value"] == "88%"
    assert result["cap_amount"]["value"] == "60万"
    assert result["payment_ratio"]["schema_version"] == 2


def test_full_overrides_frozen_field():
    """full 策略无视冻结保护（语义已变，旧值必须失效）。"""
    entity = _sample_entity()
    result = apply_full(
        entity, new_rule={"deductible_amount": "2000"},
        extracted_at="2026-07-24T00:00:00Z", schema_version=2, confidence=0.85,
    )
    assert result["deductible_amount"]["value"] == "2000"


def test_full_preserves_rule_id_and_vector():
    entity = _sample_entity()
    result = apply_full(
        entity, new_rule={"payment_ratio": "88%"},
        extracted_at="2026-07-24T00:00:00Z", schema_version=2, confidence=0.85,
    )
    assert result["rule_id"] == "r1"  # PK 保留
    assert result["fact_id"] == "f1"
    assert result["vector"] == [0.1] * 768  # 向量不动


# ── soft_delete：删字段，数据保留 ────────────────────────────

def test_soft_delete_preserves_field_data():
    """soft_delete 不删字段数据（历史溯源不丢），仅由查询端按 schema_version 忽略。"""
    entity = _sample_entity()
    result = apply_soft_delete(
        entity, deleted_field_codes={"payment_ratio"}, schema_version=2,
    )
    assert result["payment_ratio"]["value"] == "85%"  # 数据保留
    assert result["deductible_amount"]["value"] == "1300"  # 其他字段不变


def test_soft_delete_bumps_entity_schema_version():
    entity = _sample_entity()
    result = apply_soft_delete(entity, deleted_field_codes={"payment_ratio"}, schema_version=2)
    assert result["schema_version"] == 2  # 标记已应用 schema 变更


# ── update_rules 批量编排（P5.2）────────────────────────────

def test_update_rules_batch_incremental():
    entities = [_sample_entity(), _sample_entity()]
    entities[0]["rule_id"] = "r1"
    entities[1]["rule_id"] = "r2"
    result = update_rules(
        entities, "incremental", new_values={"payment_ratio": "90%"},
        frozen_field_codes=set(), extracted_at="t", schema_version=2, confidence=0.8,
    )
    assert all(e["payment_ratio"]["value"] == "90%" for e in result)
    assert all(e["schema_version"] == 2 for e in result)


def test_update_rules_unknown_strategy_no_change():
    """未知策略不修改数据（安全降级）。"""
    entities = [_sample_entity()]
    result = update_rules(entities, "weird", schema_version=2)
    assert result[0]["payment_ratio"]["value"] == "85%"
    assert result[0]["schema_version"] == 1  # 未 bump


# ── SchemaUpdateExecutor read-modify-write 编排（P5.2）──────

def test_executor_evolve_reads_modifies_writes():
    """evolve: reader → update_rules → writer 完整编排（注入 mock）。"""
    read_entities = [_sample_entity(), _sample_entity()]
    read_entities[1]["rule_id"] = "r2"
    written: list = []
    ex = SchemaUpdateExecutor(
        reader=lambda doc_id: read_entities,
        writer=lambda ents: (written.extend(ents), len(ents))[1],
    )
    out = ex.evolve(
        "d1", "incremental", new_values={"payment_ratio": "95%"},
        frozen_field_codes=set(), extracted_at="t", schema_version=2, confidence=0.8,
    )
    assert out["total"] == 2
    assert out["processed"] == 2
    assert len(written) == 2
    assert all(e["payment_ratio"]["value"] == "95%" for e in written)


def test_executor_evolve_soft_delete_no_writer_needed():
    """soft_delete：writer 仍被调用（bump schema_version 需 upsert 整条）。"""
    read_entities = [_sample_entity()]
    written: list = []
    ex = SchemaUpdateExecutor(
        reader=lambda d: read_entities,
        writer=lambda e: (written.extend(e), len(e))[1],
    )
    out = ex.evolve("d1", "soft_delete", deleted_field_codes={"cap_amount"}, schema_version=3)
    assert out["processed"] == 1
    assert written[0]["schema_version"] == 3
    assert written[0]["cap_amount"]["value"] == "50万"  # 数据保留
