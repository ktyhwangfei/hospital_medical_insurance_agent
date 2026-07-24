# 政策管线 P1：语义层提取契约 (Extraction Contract) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为政策知识管线提供一个只读的"提取契约" API，从语义层 `zcgz`（政策规则）对象的已发布指标动态生成结构化提取 schema，供后续 P3 schema-driven prompt 消费。

**Architecture:** 新增一个纯函数 `build_extraction_schema(registry, object_code)`，从语义层注册表只读读取 `status="published"` 的指标，按 `metric_kind` 分组为 fields/entities/relations，并解析值域字典。该函数不修改语义层状态（单向只读依赖，设计文档 §1.1 铁律）。API 层只是一个薄封装。语义层指标模型（`Metric`）已具备 `metric_kind`/`indexed`/`extraction_hint`/`schema_version`/`status` 字段，无需改模型。

**Tech Stack:** Python 3.13 · FastAPI · Pydantic v2 · pytest · 内存注册表 (`InMemoryRegistryStore`) 用于测试

**依据:** `docs/steering/政策知识管线设计文档.md` §7.1（接口契约）、§3.1（指标扩展）、§1.1（单向只读依赖）。对应高层路线图 `docs/steering/政策知识管线开发计划.md` 的 **Phase 1**。

**范围边界（重要）:**
- 本计划**只做"读契约"**。把 zcgz 指标从 `draft` 翻为 `published` 的质量门禁属于 **P4**，不在本计划内。因此本计划交付后，真实种子数据下契约的 `fields` 仍为空（全部 draft）——这是符合设计的正确状态，由 P4 发布后填充。
- 本计划**不触碰** `policy_rules` Milvus collection（政策问答 1.1–1.5 的生产路径），零生产风险。

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/semantic_layer/extraction_contract.py` | 契约 Pydantic 模型 + 纯构建函数 `build_extraction_schema` | 新建 |
| `src/tests/unit/semantic_layer/test_extraction_contract.py` | 契约构建函数单测（内存注册表） | 新建 |
| `src/runtime/api/semantic_routes.py` | 新增 `GET /semantic/objects/{object_code}/extraction-schema` 端点 | 修改（加 1 行 import + 1 个函数） |
| `src/tests/integration/api/test_semantic_extraction_schema.py` | 端点 API 测试（TestClient） | 新建 |
| `src/semantic_layer/seed.py` | 扩展 `_m()` 助手 + 标注 zcgz 核心维度指标 `indexed`/`extraction_hint` | 修改 |
| `src/tests/unit/semantic_layer/test_seed.py` | 断言 zcgz 种子核心维度已标注 | 修改（追加 1 个测试函数） |

**依赖方向:** `runtime/api → semantic_layer.extraction_contract → semantic_layer.registry/store`。语义层不知道政策管线存在。

---

## Task 1: 契约构建函数与模型（TDD 单测）

**Files:**
- Create: `src/semantic_layer/extraction_contract.py`
- Test: `src/tests/unit/semantic_layer/test_extraction_contract.py`

- [ ] **Step 1: 写失败测试（空契约 + 短码 + 字典 + 关系 + 实体分流）**

Create `src/tests/unit/semantic_layer/test_extraction_contract.py`:

```python
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
```

- [ ] **Step 2: 运行测试，确认失败（模块不存在）**

Run:
```bash
cd D:/project/hospital_medical_insurance_agent
python -m pytest src/tests/unit/semantic_layer/test_extraction_contract.py -v
```
Expected: collection error / `ModuleNotFoundError: No module named 'src.semantic_layer.extraction_contract'`.

- [ ] **Step 3: 实现契约模型 + 构建函数**

Create `src/semantic_layer/extraction_contract.py`:

```python
"""政策管线提取契约：从语义层只读构建结构化提取 schema。

设计要点（[来源: docs/steering/政策知识管线设计文档.md §7.1 / §1.1]）：
- 单向只读依赖语义层；本模块不修改语义层状态。
- 只返回 status=published 的指标（draft 不进入契约）。
- 按 metric_kind 分流：field → fields / entity → entities / relation → relations。
- 值域字典（value_domain）解析为标准值列表，供政策提取与数据取数统一口径（语义拉齐）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.semantic_layer.registry import SemanticRegistry


# ── 契约模型（对应设计文档 §7.1 返回结构）──────────────────────

class FieldContract(BaseModel):
    """字段型指标契约：核心检索维度(indexed) 或详情字段。"""
    code: str
    name: str
    kind: Literal["field"] = "field"
    indexed: bool = False
    extraction_hint: Optional[str] = None
    value_domain: Optional[str] = None
    semantic_type: Optional[str] = None


class EntityContract(BaseModel):
    """实体型指标契约（metric_kind=entity，设计文档 D1：实体也是指标）。"""
    code: str
    name: str
    kind: Literal["entity"] = "entity"
    extraction_hint: Optional[str] = None
    value_domain: Optional[str] = None


class RelationContract(BaseModel):
    """关系型指标契约（metric_kind=relation）。三元组提示从 transformation 取。"""
    code: str
    name: str
    kind: Literal["relation"] = "relation"
    subject_hint: Optional[str] = None
    predicate_hint: Optional[str] = None
    object_hint: Optional[str] = None


class ExtractionSchema(BaseModel):
    """提取契约整体（§7.1 顶层结构）。"""
    schema_version: int = 1
    fields: list[FieldContract] = Field(default_factory=list)
    entities: list[EntityContract] = Field(default_factory=list)
    relations: list[RelationContract] = Field(default_factory=list)
    dictionaries: dict[str, list[str]] = Field(default_factory=dict)


# ── 契约构建 ──────────────────────────────────────────────────

def _short_code(metric_code: str) -> str:
    """zcgz.insu_type → insu_type（契约字段短码，与 Milvus dynamic field 名对齐）。"""
    return metric_code.split(".", 1)[1] if "." in metric_code else metric_code


def build_extraction_schema(
    registry: "SemanticRegistry", object_code: str = "zcgz"
) -> ExtractionSchema:
    """从语义层只读构建提取契约。

    只含 status=published 的指标；按 metric_kind 分组；解析值域字典。
    不修改语义层状态（单向只读依赖）。
    """
    store = registry._store
    published = [
        m for m in store.list_metrics(object_code=object_code) if m.status == "published"
    ]

    fields: list[FieldContract] = []
    entities: list[EntityContract] = []
    relations: list[RelationContract] = []

    for m in published:
        code = _short_code(m.metric_code)
        if m.metric_kind == "entity":
            entities.append(EntityContract(
                code=code, name=m.name,
                extraction_hint=m.extraction_hint, value_domain=m.value_domain,
            ))
        elif m.metric_kind == "relation":
            t = m.transformation or {}
            relations.append(RelationContract(
                code=code, name=m.name,
                subject_hint=t.get("subject_hint"),
                predicate_hint=t.get("predicate_hint"),
                object_hint=t.get("object_hint"),
            ))
        else:  # field（默认）
            fields.append(FieldContract(
                code=code, name=m.name, indexed=m.indexed,
                extraction_hint=m.extraction_hint, value_domain=m.value_domain,
                semantic_type=m.semantic_type,
            ))

    # 值域字典：published 指标引用的 value_domain → 标准值列表
    domain_codes = sorted({m.value_domain for m in published if m.value_domain})
    dictionaries: dict[str, list[str]] = {}
    for dc in domain_codes:
        vd = store.get_value_domain(dc)
        dictionaries[dc] = list(vd.standard_values) if vd else []

    schema_version = max((m.schema_version for m in published), default=1)
    return ExtractionSchema(
        schema_version=schema_version, fields=fields, entities=entities,
        relations=relations, dictionaries=dictionaries,
    )
```

- [ ] **Step 4: 运行测试，确认全部通过**

Run:
```bash
python -m pytest src/tests/unit/semantic_layer/test_extraction_contract.py -v
```
Expected: `5 passed`.

- [ ] **Step 5: 提交**

```bash
cd D:/project/hospital_medical_insurance_agent
git add src/semantic_layer/extraction_contract.py src/tests/unit/semantic_layer/test_extraction_contract.py
git commit -m "feat: add policy extraction contract builder (zcgz, §7.1)"
```

---

## Task 2: API 端点（TDD via TestClient）

**Files:**
- Modify: `src/runtime/api/semantic_routes.py`
- Test: `src/tests/integration/api/test_semantic_extraction_schema.py`

- [ ] **Step 1: 写失败测试**

Create `src/tests/integration/api/test_semantic_extraction_schema.py`:

```python
"""提取契约端点 API 测试。

用内存注册表 + 重置语义层单例，确保 zcgz 种子数据存在且可隔离。
[依据: docs/steering/政策知识管线设计文档.md §7.1]
"""
import pytest

import src.semantic_layer.registry as reg_mod

BASE = "/api/v1/medical-insurance-ai-agent/semantic"


@pytest.fixture
def client(monkeypatch):
    """内存后端 + 重置单例，保证每次测试从干净种子开始。"""
    monkeypatch.setenv("USE_MEMORY_STORAGE", "1")
    reg_mod._semantic_registry_instance = None
    from fastapi.testclient import TestClient
    from src.runtime.api.app import create_app
    client = TestClient(create_app())
    yield client
    reg_mod._semantic_registry_instance = None


def test_unknown_object_returns_404(client):
    r = client.get(f"{BASE}/objects/no_such_object/extraction-schema")
    assert r.status_code == 404


def test_zcgz_contract_structure_when_all_draft(client):
    """种子 zcgz 19 指标均为 draft，契约 fields 应为空（发布流程在 P4 质量门禁）。"""
    r = client.get(f"{BASE}/objects/zcgz/extraction-schema")
    assert r.status_code == 200
    data = r.json()
    assert data["fields"] == []
    assert data["entities"] == []
    assert data["relations"] == []
    assert "schema_version" in data
    assert "dictionaries" in data


def test_zcgz_contract_returns_published_field(client):
    """手动把一条 zcgz 指标置为 published，验证契约返回它。"""
    reg = reg_mod.get_semantic_registry()
    store = reg._store
    m = store.get_metric("zcgz.insu_type")
    assert m is not None
    m.status = "published"
    m.indexed = True
    m.extraction_hint = "城镇职工/城乡居民"
    store.save_metric(m)

    r = client.get(f"{BASE}/objects/zcgz/extraction-schema")
    assert r.status_code == 200
    codes = [f["code"] for f in r.json()["fields"]]
    assert "insu_type" in codes
```

- [ ] **Step 2: 运行测试，确认失败（404 路由不存在 → 当前会命中 /objects/{object_code} 或 422/405）**

Run:
```bash
python -m pytest src/tests/integration/api/test_semantic_extraction_schema.py -v
```
Expected: `test_unknown_object_returns_404` 可能通过（恰好 404），但 `test_zcgz_contract_structure_when_all_draft` / `test_zcgz_contract_returns_published_field` 失败（路由未实现，返回的不是契约结构）。

- [ ] **Step 3: 在 semantic_routes 加 import 与端点**

Modify `src/runtime/api/semantic_routes.py`：

在文件顶部 import 区（其它 `from src....` 附近）加一行：

```python
from src.semantic_layer.extraction_contract import ExtractionSchema, build_extraction_schema
```

在语义层对象相关端点附近（例如 `get_object` / `list_object_versions` 附近）新增端点：

```python
@router.get("/objects/{object_code}/extraction-schema", response_model=ExtractionSchema)
def get_extraction_schema(object_code: str):
    """提取契约（政策管线只读消费）：返回该对象 status=published 指标的提取 schema。

    [来源: docs/steering/政策知识管线设计文档.md §7.1]
    政策管线据此动态生成 LLM 提取 prompt；本端点不修改语义层状态。
    """
    reg = get_registry()
    if reg.get_object(object_code) is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "OBJECT_NOT_FOUND",
                "message": f"对象 '{object_code}' 不存在",
                "audit_event": {"object_code": object_code},
            },
        )
    return build_extraction_schema(reg, object_code)
```

> 注意路由顺序：`/objects/{object_code}/extraction-schema` 比 `/objects/{object_code}` 更具体，FastAPI 会正确匹配。放在 `@router.get("/objects/{object_code}")` 定义之后即可。

- [ ] **Step 4: 运行测试，确认全部通过**

Run:
```bash
python -m pytest src/tests/integration/api/test_semantic_extraction_schema.py -v
```
Expected: `3 passed`.

- [ ] **Step 5: 回归现有语义层测试，确保未破坏**

Run:
```bash
python -m pytest src/tests/unit/semantic_layer/ -v
```
Expected: 全绿（新端点与契约模型不影响既有逻辑）。

- [ ] **Step 6: 提交**

```bash
git add src/runtime/api/semantic_routes.py src/tests/integration/api/test_semantic_extraction_schema.py
git commit -m "feat: add GET /semantic/objects/{code}/extraction-schema endpoint"
```

---

## Task 3: 种子标注 zcgz 核心维度（indexed / extraction_hint）

> 目的：让契约在 P4 发布 zcgz 指标后，能返回正确的 `indexed`（决定哪些进 Milvus 固定 schema）与 `extraction_hint`（拼 prompt 用）。本任务只填字段值，不改变 `status`（仍为 draft）。

**Files:**
- Modify: `src/semantic_layer/seed.py`
- Test: `src/tests/unit/semantic_layer/test_seed.py`

- [ ] **Step 1: 写失败测试**

在 `src/tests/unit/semantic_layer/test_seed.py` **末尾追加**一个测试函数：

```python
def test_zcgz_seed_marks_core_dimensions_indexed():
    """zcgz 核心检索维度应标注 indexed=True + extraction_hint；详情字段 indexed=False。

    [依据: docs/steering/政策知识管线设计文档.md §3.1 / §3.3（核心维度进固定 schema）]
    """
    from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
    from src.semantic_layer.seed import seed_semantic_layer

    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    reg = SemanticRegistry(store)

    # 核心检索维度：indexed=True，且有 extraction_hint
    for code in ("zcgz.rule_type", "zcgz.insu_type", "zcgz.med_type",
                 "zcgz.hosp_lv", "zcgz.psn_type", "zcgz.setl_type"):
        m = reg.get_metric(code)
        assert m is not None, f"种子缺失 {code}"
        assert m.indexed is True, f"{code} 应为核心检索维度 (indexed=True)"
        assert m.extraction_hint, f"{code} 缺少 extraction_hint"

    # 详情字段：indexed=False（走 Milvus dynamic field）
    payment = reg.get_metric("zcgz.payment_ratio")
    assert payment is not None
    assert payment.indexed is False

    # 仍为 draft（发布流程在 P4 质量门禁）
    assert reg.get_metric("zcgz.insu_type").status == "draft"
```

- [ ] **Step 2: 运行测试，确认失败**

Run:
```bash
python -m pytest src/tests/unit/semantic_layer/test_seed.py::test_zcgz_seed_marks_core_dimensions_indexed -v
```
Expected: FAIL — `assert m.indexed is True`（当前种子未标注，indexed 默认 False）。

- [ ] **Step 3: 扩展 `_m()` 助手，支持新字段**

Modify `src/semantic_layer/seed.py`，把 `_m` 函数替换为（增加 4 个关键字参数并透传）：

```python
def _m(metric_code, object_code, name, definition, semantic_type, *,
       unit=None, required=False, source_object=None, source_field=None,
       source_adapter_port=None, value_domain=None, importance="optional",
       default_value=None, metric_kind="field", indexed=False,
       extraction_hint=None, schema_version=1):
    """指标构造助手，减少重复参数。"""
    return Metric(
        metric_code=metric_code, object_code=object_code, name=name,
        definition=definition, metric_type="Atomic", semantic_type=semantic_type,
        unit=unit, required=required, source_object=source_object,
        source_field=source_field, source_adapter_port=source_adapter_port,
        value_domain=value_domain, importance=importance,
        default_value=default_value,
        metric_kind=metric_kind, indexed=indexed,
        extraction_hint=extraction_hint, schema_version=schema_version,
        version="1.0", status="draft",
    )
```

- [ ] **Step 4: 标注 zcgz 核心维度指标**

在 `src/semantic_layer/seed.py` 的 zcgz 区块，给 6 个核心维度指标加 `indexed=True` 与 `extraction_hint`。用以下精确替换（每条只在其末尾 kwargs 追加两个参数）：

替换 1（`zcgz.rule_type`）：
```python
        _m("zcgz.rule_type", "zcgz", "规则类型", "动态规则类型（嵌套字段）", "String",
           source_field="zcgz.rule_type", source_object="policy_extractions"),
```
为：
```python
        _m("zcgz.rule_type", "zcgz", "规则类型", "动态规则类型（嵌套字段）", "String",
           source_field="zcgz.rule_type", source_object="policy_extractions",
           indexed=True, extraction_hint="规则的业务类别，如 起付线/报销比例/封顶线/分段比例"),
```

替换 2（`zcgz.insu_type`）：
```python
        _m("zcgz.insu_type", "zcgz", "险种类别", "城镇职工、城乡居民、超转人员、生育保险", "Enum",
           source_field="zcgz.insu_type", source_object="policy_extractions", value_domain="insu_type"),
```
为：
```python
        _m("zcgz.insu_type", "zcgz", "险种类别", "城镇职工、城乡居民、超转人员、生育保险", "Enum",
           source_field="zcgz.insu_type", source_object="policy_extractions", value_domain="insu_type",
           indexed=True, extraction_hint="参保险种，取值见 insu_type 字典：城镇职工/城乡居民/超转人员/生育保险"),
```

替换 3（`zcgz.med_type`）：
```python
        _m("zcgz.med_type", "zcgz", "医疗类别", "住院-普通住院、门诊-一般门特", "Enum",
           source_field="zcgz.med_type", source_object="policy_extractions", value_domain="med_type"),
```
为：
```python
        _m("zcgz.med_type", "zcgz", "医疗类别", "住院-普通住院、门诊-一般门特", "Enum",
           source_field="zcgz.med_type", source_object="policy_extractions", value_domain="med_type",
           indexed=True, extraction_hint="医疗服务类别，取值见 med_type 字典：住院/门诊/门诊特殊病等"),
```

替换 4（`zcgz.hosp_lv`）：
```python
        _m("zcgz.hosp_lv", "zcgz", "医疗机构等级", "一级医院、二级医院、三级医院、社区", "Enum",
           source_field="zcgz.hosp_lv", source_object="policy_extractions", value_domain="hosp_lv"),
```
为：
```python
        _m("zcgz.hosp_lv", "zcgz", "医疗机构等级", "一级医院、二级医院、三级医院、社区", "Enum",
           source_field="zcgz.hosp_lv", source_object="policy_extractions", value_domain="hosp_lv",
           indexed=True, extraction_hint="定点医疗机构等级，取值见 hosp_lv 字典：一级/二级/三级/社区"),
```

替换 5（`zcgz.psn_type`）：
```python
        _m("zcgz.psn_type", "zcgz", "人群标签", "退休、在职、70岁以上、学生儿童（嵌套字段）", "Enum",
           source_field="zcgz.psn_type", source_object="policy_extractions", value_domain="psn_type"),
```
为：
```python
        _m("zcgz.psn_type", "zcgz", "人群标签", "退休、在职、70岁以上、学生儿童（嵌套字段）", "Enum",
           source_field="zcgz.psn_type", source_object="policy_extractions", value_domain="psn_type",
           indexed=True, extraction_hint="适用人群标签，取值见 psn_type 字典：在职/退休/学生儿童等"),
```

替换 6（`zcgz.setl_type`）：
```python
        _m("zcgz.setl_type", "zcgz", "结算方式", "按项目付费、DRG、单病种、床日定额", "Enum",
           source_field="zcgz.setl_type", source_object="policy_extractions", value_domain="setl_type"),
```
为：
```python
        _m("zcgz.setl_type", "zcgz", "结算方式", "按项目付费、DRG、单病种、床日定额", "Enum",
           source_field="zcgz.setl_type", source_object="policy_extractions", value_domain="setl_type",
           indexed=True, extraction_hint="付费/结算方式，取值见 setl_type 字典：按项目/DRG/单病种/床日定额"),
```

- [ ] **Step 5: 运行测试，确认通过**

Run:
```bash
python -m pytest src/tests/unit/semantic_layer/test_seed.py::test_zcgz_seed_marks_core_dimensions_indexed -v
```
Expected: PASS.

- [ ] **Step 6: 全量回归语义层 + 契约 + 端点**

Run:
```bash
python -m pytest src/tests/unit/semantic_layer/ src/tests/integration/api/test_semantic_extraction_schema.py -v
```
Expected: 全绿。

- [ ] **Step 7: 提交**

```bash
git add src/semantic_layer/seed.py src/tests/unit/semantic_layer/test_seed.py
git commit -m "feat: mark zcgz core dimensions as indexed with extraction hints (§3.1/§3.3)"
```

---

## 收口标准

- [ ] `build_extraction_schema` 单测全绿（5 例）。
- [ ] 提取契约端点 API 测试全绿（3 例）。
- [ ] zcgz 种子核心维度标注测试全绿。
- [ ] 既有语义层测试无回归。
- [ ] 端点 `GET /api/v1/medical-insurance-ai-agent/semantic/objects/zcgz/extraction-schema` 可访问，返回 `ExtractionSchema` 结构。
- [ ] **未触碰** `policy_rules` Milvus collection（政策问答生产路径零影响）。

## 本计划交付后的事实

- 真实种子下，契约 `fields` 为空（zcgz 全 draft）。这是**符合设计的正确状态**——填充它需要 P4（质量门禁 → 把指标翻为 published）。
- 契约的读取链路、字段语义、值域字典解析已就绪；P4 发布指标后契约自动返回正确数据，无需再改本计划代码。

## 后续计划（不在本计划内）

依据 `docs/steering/政策知识管线开发计划.md`：
- **P2**: `policy_rules` 新 schema（核心维度固定 + 详情 dynamic + 字段级溯源）+ 向量复用。
- **P3**: 事实拆分 + schema-driven 入库（消费本契约拼 prompt）。
- **P4**: 质量门禁 + 指标 draft→published（让本契约返回真实数据）。
