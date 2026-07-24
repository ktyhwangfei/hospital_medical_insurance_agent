# 政策管线 P2：policy_rules 新 schema（核心维度 + 字段级溯源）Implementation Plan

**对整个目标的价值**（见路线图 §0 价值地图；P2 属 **M1 地基就绪** 的最后一块）:
- 建立「知识模型可配置」的物质基础：核心维度进固定 schema（可标量索引、高频过滤），详情进 dynamic field（**加字段不改 schema、不改代码**）——这正是「加维度不改代码」这一终极价值的落地点。
- 建立「字段级可溯源」的载体：`FieldTrace({value, extracted_at, schema_version, confidence})` 是后续「每个值知道从哪来」的统一结构（P3 入库填它、P4 门禁校验它、前端展示它）。
- 是 P3（自动入库）、P4（质量门禁）、P6（检索）的**共同前置**：新数据模型不建好，这三个阶段无处落地。
- 风险：R3（碰 Milvus schema），但用独立 collection `policy_rules_v2` + P0 回归基线兜底 → 零生产影响。
- **诚实提示**：完成后新 collection 为空（数据在 P3/P8 才进），属「地基型投入」；真正的「看得见」要等 M2（P3 端到端 demo）。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立符合设计文档 §3.3 的 `policy_rules` 新版 collection（核心检索维度进固定 schema + 标量索引，详情字段以字段级溯源对象落 dynamic field），并验证其存取能力。全程用**新 collection 名 `policy_rules_v2`**，不碰旧 `policy_rules`（政策问答生产路径）。

**Architecture:** 新增 `policy_rules_schema_v2.py`：定义字段级溯源模型 `FieldTrace`（`{value, extracted_at, schema_version, confidence}`）、新版 collection 创建函数（固定 schema + 标量索引 + `enable_dynamic_field`）、实体构造助手 `rule_to_entity`。设计依赖已验证的 Milvus 能力：dynamic field 原生存嵌套 dict、标量索引过滤。

**Tech Stack:** Python 3.13 · pymilvus（Collection/CollectionSchema API）· Pydantic v2 · pytest（连真 Milvus，不可用则 skip）

**依据:** `docs/steering/政策知识管线设计文档.md` §3.3（数据模型）、§4.1（向量复用）、§1.1（单向只读/解耦）。对应高层路线图 `docs/steering/政策知识管线开发计划.md` 的 **Phase 2**。

**已验证的技术前提（smoke 测试确认）:**
- Milvus @ 127.0.0.1:19530，`enable_dynamic_field=True` 后插入嵌套 dict，读回仍是 dict（无需 JSON 序列化）。
- `col.create_index(field_name, {})` 可为 VARCHAR 标量字段建索引，`col.query(expr='field == "x"')` 过滤命中。

**范围边界（重要）:**
- 本计划只做 **schema 定义 + 创建函数 + 存取 smoke 验证**。
- **不写入真实政策数据**（那是 P3 事实拆分入库）。
- **不实现"向量复用"的实际逻辑**（从 fact 取向量）：P2 的 `rule_to_entity` 接受 `vector` 参数（调用方提供），测试用占位向量；真正"rules.vector = facts.vector"在 P3（此时 policy_facts 才有数据）。
- **不迁移、不切换读入口**（P8/P10）：新 collection 用独立名 `policy_rules_v2`，与旧 `policy_rules` 完全隔离。
- **不触碰**旧 `policy_rules` collection（P0 回归基线保护的政策问答生产路径）。

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py` | 字段级溯源模型 `FieldTrace` + 新版 collection schema/创建函数 + `rule_to_entity` 实体构造 | 新建 |
| `src/tests/integration/flow/test_policy_rules_v2_schema.py` | 新 schema 创建 + 存取 smoke（连真 Milvus，不可用 skip） | 新建 |

**依赖方向:** 独立模块，仅依赖 pymilvus + pydantic。不反向耦合语义层或政策问答运行路径。

---

## Task 1: FieldTrace 模型 + 新 collection schema + 创建函数

**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py`
- Test: `src/tests/integration/flow/test_policy_rules_v2_schema.py`

- [ ] **Step 1: 写失败测试（schema 创建 + 字段 + 标量索引 + dynamic）**

Create `src/tests/integration/flow/test_policy_rules_v2_schema.py`:

```python
"""policy_rules 新版 collection schema 验证（P2）。

验证设计文档 §3.3：核心检索维度进固定 schema + 标量索引，
详情字段走 dynamic field（字段级溯源对象）。

依赖 Milvus @ 127.0.0.1:19530；不可用则 skip。测试用独立临时 collection 名，不碰生产。
"""
import pytest

MILVUS_URI = "http://127.0.0.1:19530"


def _milvus_ready() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2)
        c.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _milvus_ready(), reason="Milvus 不可用（需 127.0.0.1:19530）")


def test_create_v2_collection_has_core_dims_and_dynamic():
    """新 collection 固定 schema 含核心维度，标量索引齐全，dynamic field 启用。"""
    from pymilvus import connections, utility, Collection
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection,
        POLICY_RULES_V2_COLLECTION,
        CORE_DIM_FIELDS,
    )

    connections.connect(alias="default", host="127.0.0.1", port="19530")
    tmp_name = "_test_pr_v2_schema"
    try:
        col = create_policy_rules_v2_collection(collection_name=tmp_name, drop_existing=True)
        # 固定 schema 含全部核心维度
        field_names = {f.name for f in col.schema.fields}
        for dim in CORE_DIM_FIELDS:
            assert dim in field_names, f"核心维度 {dim} 应在固定 schema 中"
        # rule_id 是主键
        pk = next(f for f in col.schema.fields if f.name == "rule_id")
        assert pk.is_primary is True
        # vector 字段存在（768 维）
        vec = next(f for f in col.schema.fields if f.name == "vector")
        assert vec.dtype.name == "FLOAT_VECTOR"
        # dynamic field 启用
        assert col.schema.enable_dynamic_field is True
        # 核心维度已建标量索引（rule_id 除外，vector 走向量索引）
        indexed = {idx.field_name for idx in col.indexes}
        for dim in ("insu_type", "med_type", "hosp_lv", "psn_type", "setl_type", "fact_id", "doc_id"):
            assert dim in indexed, f"{dim} 应建标量索引，实际 indexed={indexed}"
    finally:
        if utility.has_collection(tmp_name):
            utility.drop_collection(tmp_name)
```

- [ ] **Step 2: 运行测试，确认失败（模块不存在）**

Run:
```bash
cd D:/project/hospital_medical_insurance_agent
python -m pytest src/tests/integration/flow/test_policy_rules_v2_schema.py::test_create_v2_collection_has_core_dims_and_dynamic -v
```
Expected: `ModuleNotFoundError: No module named 'src...policy_rules_schema_v2'`。

- [ ] **Step 3: 实现 FieldTrace + schema + 创建函数**

Create `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py`:

```python
"""policy_rules 新版 collection（设计文档 §3.3）。

与旧 policy_rules_schema.py（21 字段扁平）的区别：
- 核心检索维度进固定 schema + 标量索引（高频过滤性能）。
- 详情字段走 dynamic field，值是字段级溯源对象 FieldTrace（{value, extracted_at, schema_version, confidence}）。
- 向量字段名统一为 vector（复用 policy_facts 的事实向量，见 §4.1；实际复用逻辑在 P3）。

[来源: docs/steering/政策知识管线设计文档.md §3.3 / §4.1]
"""
from __future__ import annotations

from typing import Any, Optional

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
from pydantic import BaseModel, Field

POLICY_RULES_V2_COLLECTION = "policy_rules_v2"
POLICY_RULES_V2_VECTOR_DIM = 768  # bge-base-zh-v1.5，与 policy_facts 一致

# 核心检索维度（进固定 schema + 标量索引）。设计文档 §3.3 固定 schema。
CORE_DIM_FIELDS = (
    "rule_id",      # PK
    "fact_id",      # 关联 policy_facts
    "doc_id",       # 关联 policy_documents
    "rule_type",    # 规则业务类别（起付线/报销比例/封顶线…）
    "insu_type",    # 险种
    "med_type",     # 医疗类别
    "hosp_lv",      # 医院等级
    "psn_type",     # 人群标签
    "setl_type",    # 结算方式
    "schema_version",
    "vector",
)


# ── 字段级溯源对象（设计文档 §3.3 D3）──────────────────────────

class FieldTrace(BaseModel):
    """字段级溯源：每个详情字段值携带提取元信息，而非裸值。

    落 Milvus dynamic field 时序列化为 dict（Milvus 原生支持嵌套 dict）。
    """
    value: Any = Field(description="字段值（可能是 str/float/list[dict] 等）")
    extracted_at: str = Field(description="提取时间 ISO 字符串")
    schema_version: int = Field(default=1, description="提取时所用 schema 版本")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="提取置信度")


def _connect(alias: str = "default", host: str = "127.0.0.1", port: str = "19530") -> None:
    connections.connect(alias=alias, host=host, port=port)


def create_policy_rules_v2_collection(
    collection_name: str = POLICY_RULES_V2_COLLECTION,
    dim: int = POLICY_RULES_V2_VECTOR_DIM,
    drop_existing: bool = False,
    alias: str = "default",
) -> Collection:
    """创建新版 policy_rules collection（核心维度固定 schema + 标量索引 + dynamic field）。

    已存在则返回（除非 drop_existing）。
    """
    if utility.has_collection(collection_name, using=alias):
        if drop_existing:
            utility.drop_collection(collection_name, using=alias)
        else:
            return Collection(collection_name, using=alias)

    fields = [
        FieldSchema("rule_id", DataType.VARCHAR, is_primary=True, max_length=64,
                    description="规则ID（PK）"),
        FieldSchema("fact_id", DataType.VARCHAR, max_length=64,
                    description="关联 policy_facts.fact_id"),
        FieldSchema("doc_id", DataType.VARCHAR, max_length=64,
                    description="关联 policy_documents.doc_id"),
        FieldSchema("rule_type", DataType.VARCHAR, max_length=64, description="规则业务类别"),
        FieldSchema("insu_type", DataType.VARCHAR, max_length=64, description="险种"),
        FieldSchema("med_type", DataType.VARCHAR, max_length=64, description="医疗类别"),
        FieldSchema("hosp_lv", DataType.VARCHAR, max_length=64, description="医疗机构等级"),
        FieldSchema("psn_type", DataType.VARCHAR, max_length=64, description="人群标签"),
        FieldSchema("setl_type", DataType.VARCHAR, max_length=64, description="结算方式"),
        FieldSchema("schema_version", DataType.INT64, description="提取时 schema 版本"),
        FieldSchema("vector", DataType.FLOAT_VECTOR, dim=dim,
                    description="复用对应 fact 的事实向量（§4.1）"),
    ]
    schema = CollectionSchema(
        fields,
        description="政策结构化规则（核心维度固定 schema + 详情 dynamic field + 字段级溯源）",
        enable_dynamic_field=True,
    )
    col = Collection(collection_name, schema, using=alias)
    _create_indexes(col)
    return col


def _create_indexes(col: Collection) -> None:
    # 向量索引：HNSW + COSINE（与 policy_facts 一致）
    col.create_index(
        field_name="vector",
        index_params={
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "params": {"M": 16, "efConstruction": 200},
        },
    )
    # 核心维度标量索引（高频过滤）
    for dim in ("fact_id", "doc_id", "rule_type", "insu_type",
                "med_type", "hosp_lv", "psn_type", "setl_type"):
        col.create_index(field_name=dim, index_params={})


def drop_policy_rules_v2_collection(
    collection_name: str = POLICY_RULES_V2_COLLECTION, alias: str = "default"
) -> None:
    if utility.has_collection(collection_name, using=alias):
        utility.drop_collection(collection_name, using=alias)
```

- [ ] **Step 4: 运行测试，确认通过**

Run:
```bash
python -m pytest src/tests/integration/flow/test_policy_rules_v2_schema.py::test_create_v2_collection_has_core_dims_and_dynamic -v
```
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py src/tests/integration/flow/test_policy_rules_v2_schema.py
git commit -m "feat: add policy_rules_v2 collection schema (core dims + field-level lineage, §3.3)"
```

---

## Task 2: 实体构造 + 字段级溯源存取 smoke

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py`（追加 `rule_to_entity`）
- Test: `src/tests/integration/flow/test_policy_rules_v2_schema.py`（追加测试）

- [ ] **Step 1: 写失败测试（写入 + 标量查询 + 字段级溯源读回）**

在 `src/tests/integration/flow/test_policy_rules_v2_schema.py` **末尾追加**：

```python
def test_upsert_and_query_with_field_trace():
    """写入一条规则（核心维度 + payment_ratio 字段级溯源 + 占位向量），
    标量查询命中，读回 payment_ratio 是含 value/confidence 的 dict。
    """
    from pymilvus import connections, utility, Collection
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection,
        rule_to_entity,
        FieldTrace,
    )

    connections.connect(alias="default", host="127.0.0.1", port="19530")
    tmp_name = "_test_pr_v2_write"
    try:
        col = create_policy_rules_v2_collection(collection_name=tmp_name, drop_existing=True)

        rule = {
            "rule_id": "r_smoke_1",
            "fact_id": "f_smoke_1",
            "doc_id": "d_smoke_1",
            "rule_type": "支付比例",
            "insu_type": "城镇职工基本医疗保险",
            "med_type": "住院-普通住院",
            "hosp_lv": "三级医院",
            "psn_type": "退休人员",
            "setl_type": "按项目付费",
            # 详情字段（裸值）—— rule_to_entity 会包成 FieldTrace
            "payment_ratio": "85%",
            "deductible_amount": "1300元",
        }
        placeholder_vector = [0.01] * 768  # P2 占位；P3 由 fact 向量复用
        entity = rule_to_entity(rule, vector=placeholder_vector)

        col.insert([entity])
        col.load()
        res = col.query(
            expr='insu_type == "城镇职工基本医疗保险" and hosp_lv == "三级医院"',
            output_fields=["rule_type", "payment_ratio", "deductible_amount"],
            limit=5,
        )
        assert len(res) == 1
        hit = res[0]
        assert hit["rule_type"] == "支付比例"
        # payment_ratio 是字段级溯源 dict（非裸值）
        pr = hit["payment_ratio"]
        assert isinstance(pr, dict)
        assert pr["value"] == "85%"
        assert "extracted_at" in pr and "schema_version" in pr and "confidence" in pr
    finally:
        if utility.has_collection(tmp_name):
            utility.drop_collection(tmp_name)
```

- [ ] **Step 2: 运行测试，确认失败（`rule_to_entity` 不存在）**

Run:
```bash
python -m pytest src/tests/integration/flow/test_policy_rules_v2_schema.py::test_upsert_and_query_with_field_trace -v
```
Expected: FAIL — `ImportError: cannot import name 'rule_to_entity'`。

- [ ] **Step 3: 实现 `rule_to_entity`**

在 `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py` **末尾追加**：

```python
# 详情字段集合：这些字段不进固定 schema，作为 FieldTrace 落 dynamic field。
# 核心维度（CORE_DIM_FIELDS）外的字段都视为详情字段。
DETAIL_FIELDS = (
    "payment_ratio", "deductible_amount", "cap_amount", "amount_band",
    "time_period", "admission_order", "priority", "rule_value", "source_text",
    "entities", "relations",
)


def rule_to_entity(
    rule: dict[str, Any],
    vector: list[float],
    extracted_at: str = "",
    schema_version: int = 1,
    confidence: float = 0.0,
) -> dict[str, Any]:
    """把一条规则 dict 转为 Milvus entity。

    - 核心维度 → 固定 schema 字段（顶层标量）。
    - 详情字段 → FieldTrace dict（落 dynamic field，字段级溯源）。
    - vector → 由调用方提供（P2 占位；P3 由 fact 向量复用，§4.1）。

    Args:
        rule: 规则 dict，含核心维度 + 详情字段（详情字段为裸值）。
        vector: 规则向量（复用 fact 的事实向量）。
        extracted_at: 本次提取时间（ISO），用于所有详情字段的溯源。
        schema_version: 本次提取所用 schema 版本。
        confidence: 本次提取置信度。
    """
    entity: dict[str, Any] = {"vector": vector, "schema_version": schema_version}

    # 核心维度（rule_id/fact_id/doc_id/rule_type/insu_type/med_type/hosp_lv/psn_type/setl_type）
    for dim in CORE_DIM_FIELDS:
        if dim in ("vector", "schema_version"):
            continue
        entity[dim] = str(rule.get(dim, ""))

    # 详情字段 → FieldTrace（裸值包成溯源对象）
    for detail in DETAIL_FIELDS:
        if detail in rule and rule[detail] is not None:
            trace = FieldTrace(
                value=rule[detail],
                extracted_at=extracted_at,
                schema_version=schema_version,
                confidence=confidence,
            )
            entity[detail] = trace.model_dump()

    return entity
```

- [ ] **Step 4: 运行测试，确认通过**

Run:
```bash
python -m pytest src/tests/integration/flow/test_policy_rules_v2_schema.py -v
```
Expected: `2 passed`。

- [ ] **Step 5: 全量回归（P0 基线 + 新 schema 测试，确保不破坏既有）**

Run:
```bash
python -m pytest src/tests/integration/flow/ src/tests/unit/semantic_layer/ -q
```
Expected: 全绿（P0-a/P0-b 基线、新 P2 测试、semantic_layer 单测）。

- [ ] **Step 6: 提交**

```bash
git add src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py src/tests/integration/flow/test_policy_rules_v2_schema.py
git commit -m "feat: add rule_to_entity with field-level lineage for policy_rules_v2 (§3.3 D3)"
```

---

## 收口标准

- [ ] `create_policy_rules_v2_collection` 能建出符合 §3.3 的 collection（核心维度固定 schema + 标量索引 + dynamic field 启用）。
- [ ] `FieldTrace` 模型定义字段级溯源对象（`{value, extracted_at, schema_version, confidence}`）。
- [ ] `rule_to_entity` 把核心维度落固定 schema、详情字段包成 FieldTrace 落 dynamic field。
- [ ] 写入 + 标量查询 + 字段级溯源读回 smoke 全绿。
- [ ] P0 回归基线（标量 + 向量）无回归。
- [ ] **未触碰**旧 `policy_rules` collection（生产路径零影响）。

## 本计划交付后的事实

- 新 collection `policy_rules_v2` 可用，schema 符合设计文档 §3.3，但**为空**（无真实数据）。
- 真实政策数据写入 + 向量复用（rules.vector = facts.vector）属于 **P3**（事实拆分入库）。
- `policy_rules_v2` 与旧 `policy_rules` 完全隔离；政策问答仍读旧的，P0 基线保护。

## 后续计划（不在本计划内）

依据 `docs/steering/政策知识管线开发计划.md`：
- **P3**: 事实拆分 + schema-driven 入库（消费 P1 提取契约拼 prompt → 写 policy_facts + policy_rules_v2，向量复用）。
- **P4**: 质量门禁 + 指标 draft→published（让 P1 契约返回真实数据）。
- **P6**: 混合检索（基于 policy_rules_v2 的新 schema）。
