# 政策管线 P3：事实拆分 + 结构化入库（新通路）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**对整个目标的价值**（见路线图 §0 价值地图；P3 属 **M2 数据通路打通**，是**第一个"看得见"的阶段**）:

- 建立「政策自动变结构化知识」的入库通路：LLM 提取的 facts/rules → `policy_facts`（向量化）+ `policy_rules_v2`（字段级溯源 + 向量复用）。这正是 M2 的核心交付——**完成后可在新 collection 上跑端到端 demo**（上传→提取→入库→查），不必等 P10 切换。
- 解决痛点「政策更新要手工重灌」：提取结果自动结构化入库（含向量化 + 字段级溯源），而非手工脚本灌扁平表。
- 是 **P4（质量门禁）、P6（混合检索）的硬前置**：没有入库的数据，门禁没东西校验、检索没东西查。
- **3.1（schema-driven prompt）推迟**：契约现在返回空 fields（种子指标全 draft，P4 质量门禁前无 published），prompt builder 接入无意义。P3 用现有 prompt 提取（不改 `run_extraction`），不影响入库通路。3.1 移到 P4 后（契约有数据时）作为独立小阶段。
- 风险：R2（LLM + Milvus 写入），但**全程写新 collection**（`policy_facts` / `policy_rules_v2`，不改 `publish_extraction` 写旧 `policy_rules` 的逻辑）+ mock LLM 测试 + P0 回归基线兜底 → 生产路径零影响。

---

## Goal

把 `PipelineOrchestrator` 的 LLM 提取结果（已存 PG `extractions`）**发布到新 collection**：写 `policy_facts`（fact_text 向量化）+ `policy_rules_v2`（rule_to_entity + 复用 fact 向量 + 字段级溯源）。新增发布函数 `publish_to_new_collections` 与 API 端点，**不改**现有 `publish_extraction`（写旧 collection，隔离）。

## Architecture

三层分工：
1. **schema 层写入辅助**（Task 1/2）：`policy_facts_schema.upsert_facts`、`policy_rules_schema_v2.upsert_rules` —— 纯 Milvus 批量写入（薄封装）。
2. **ingestion 编排**（Task 3 核心）：新模块 `policy_ingestion.build_ingest_records(facts, doc_id, provider) → (fact_records, rule_entities)` —— 纯函数：fact_text 向量化 + rule_to_entity（字段级溯源）+ fact_id 关联 + **向量复用**（rule 用所属 fact 的 vector，§4.1）。
3. **发布链路 + API**（Task 3）：`PipelineOrchestrator.publish_to_new_collections` 编排（build_ingest_records → upsert_facts → upsert_rules → lineage）+ `POST /extractions/{id}/publish-v2` 端点。

**Tech Stack:** Python 3.13 · pymilvus · Pydantic v2 · SentenceTransformerEmbeddingProvider（P0-b 已修）· pytest

**依据:** `docs/steering/政策知识管线设计文档.md` §3.2（policy_facts）/ §3.3（policy_rules）/ §4.1（向量复用）/ §2（数据流）。对应路线图 Phase 3（3.2/3.3/3.4；3.1 推迟）。

## 关键设计决策

1. **隔离**：新增 `publish_to_new_collections` + `publish-v2` 端点，**不改** `publish_extraction`（写旧 `policy_rules`）。新旧发布路径并存，P10 才切换。
2. **3.1 推迟**：契约空（P4 前），prompt builder 接入无意义。P3 不碰 `run_extraction` 的 prompt，消费其现有产出（19 字段 facts/rules）。rule_to_entity 已能消费 19 字段（核心维度进固定 schema，详情字段包成 FieldTrace）。
3. **测试策略**：Task 1/2 连真 Milvus（临时 collection + 占位 vector，skip 兜底）；Task 3 的 `build_ingest_records` 是**纯函数**，用 FakeProvider 单测（不连 Milvus、不加载模型，快且确定）。LLM 本身不在测试内（`run_extraction` 的 LLM 调用是既有行为，P3 不改）。
4. **向量复用**（§4.1）：同 fact 的多条 rules 共享该 fact 的向量。`build_ingest_records` 保证 `rule_entity["vector"] == fact_record["vector"]`。

## 范围边界

- ✅ 做：facts/rules 写入辅助、ingestion 编排（向量化 + 字段级溯源 + 向量复用）、新发布函数 + API 端点。
- ❌ 不做：schema-driven prompt（3.1，推迟 P4 后）、改 `run_extraction`、改 `publish_extraction`（旧路径）、质量门禁（P4）、混合检索（P6）、数据迁移（P8）。
- ❌ 不碰：旧 `policy_rules` collection（P0 基线保护的生产路径）。

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/knowledge_extension/rule_explanation/policy_retrieval/policy_facts_schema.py` | 加 `upsert_facts`（批量写入事实） | 改 |
| `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py` | 加 `upsert_rules`（批量写入规则实体） | 改 |
| `src/knowledge_extension/rule_explanation/policy_retrieval/policy_ingestion.py` | `build_ingest_records`（编排：向量化 + rule_to_entity + 向量复用 + fact_id 关联） | 新建 |
| `src/knowledge_extension/rule_explanation/pipeline_orchestrator.py` | 加 `publish_to_new_collections`（编排发布到新 collection） | 改 |
| `src/runtime/api/policy_pipeline_routes.py` | 加 `POST /extractions/{id}/publish-v2` 端点 | 改 |
| `src/tests/integration/flow/test_policy_facts_write.py` | facts 写入集成测试 | 新建 |
| `src/tests/integration/flow/test_policy_rules_v2_write.py` | rules 写入集成测试 | 新建 |
| `src/tests/unit/rule_explanation/test_policy_ingestion.py` | build_ingest_records 单测（FakeProvider） | 新建 |

**需新建目录:** `src/tests/unit/rule_explanation/`（含 `__init__.py`）。

---

## Task 1: facts 写入辅助（upsert_facts）

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/policy_retrieval/policy_facts_schema.py`
- Test: `src/tests/integration/flow/test_policy_facts_write.py`

- [ ] **Step 1: 写失败测试**

Create `src/tests/integration/flow/test_policy_facts_write.py`:

```python
"""policy_facts 写入集成测试（P3 Task 1）。依赖 Milvus，不可用则 skip。"""
import pytest

MILVUS_URI = "http://127.0.0.1:19530"


def _milvus_ready() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2); c.close(); return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _milvus_ready(), reason="Milvus 不可用")


def test_upsert_facts_writes_and_readable():
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
        create_policy_facts_collection, upsert_facts,
    )
    connections.connect(alias="default", host="127.0.0.1", port="19530")
    tmp = "_test_facts_write"
    try:
        col = create_policy_facts_collection(collection_name=tmp, drop_existing=True)
        records = [
            {"fact_id": "f_smoke_1", "doc_id": "d_smoke",
             "fact_text": "起付标准1300元", "vector": [0.1] * 768, "created_at": "2026-07-24"},
            {"fact_id": "f_smoke_2", "doc_id": "d_smoke",
             "fact_text": "统筹支付85%", "vector": [0.2] * 768, "created_at": "2026-07-24"},
        ]
        n = upsert_facts(col, records)
        assert n == 2
        col.load()
        res = col.query(expr='doc_id == "d_smoke"',
                        output_fields=["fact_text"], limit=10)
        texts = {r["fact_text"] for r in res}
        assert "起付标准1300元" in texts and "统筹支付85%" in texts
    finally:
        if utility.has_collection(tmp):
            utility.drop_collection(tmp)
```

**隔离策略**：测试用临时 collection 名（`_test_facts_write`），与 P2 一致，不污染正式 `policy_facts`。需先给 `create_policy_facts_collection` 加 `collection_name` 参数（Step 3）。

- [ ] **Step 2: 运行，确认失败（`upsert_facts` 不存在）**

```bash
python -m pytest src/tests/integration/flow/test_policy_facts_write.py -v
```

- [ ] **Step 3: 给 `create_policy_facts_collection` 加 `collection_name` 参数 + 实现 `upsert_facts`**

**(a) 加 `collection_name` 参数**（放最后，向后兼容，不 break 现有位置调用；测试用临时名隔离）。把函数体 3 处 `FACT_COLLECTION` 替换为 `collection_name`：

```python
def create_policy_facts_collection(
    dim: int = FACT_VECTOR_DIM, drop_existing: bool = False, alias: str = "default",
    collection_name: str = FACT_COLLECTION,
) -> Collection:
    """创建 policy_facts 集合。collection_name 可参数化（测试用临时名隔离）。"""
    if utility.has_collection(collection_name, using=alias):
        if drop_existing:
            utility.drop_collection(collection_name, using=alias)
        else:
            return Collection(collection_name, using=alias)
    fields = [...]  # 字段定义不变
    schema = CollectionSchema(fields, description="政策事实（语义单元 + 向量入口）",
                              enable_dynamic_field=True)
    col = Collection(collection_name, schema, using=alias)
    _create_indexes(col)
    return col
```

**(b) 末尾追加 `upsert_facts`**:

```python
def upsert_facts(col: Collection, fact_records: list[dict]) -> int:
    """批量写入事实到 policy_facts。

    Args:
        col: policy_facts Collection（已创建）。
        fact_records: 每条 {fact_id, doc_id, fact_text, vector, created_at}。
    Returns: 写入条数。
    """
    if not fact_records:
        return 0
    col.insert(fact_records)
    col.flush()
    return len(fact_records)
```

- [ ] **Step 4: 运行，确认通过 → 提交**

```bash
python -m pytest src/tests/integration/flow/test_policy_facts_write.py -v
git add src/knowledge_extension/rule_explanation/policy_retrieval/policy_facts_schema.py src/tests/integration/flow/test_policy_facts_write.py
git commit -m "feat: add upsert_facts for policy_facts batch write (P3, §3.2)"
```

---

## Task 2: rules 写入辅助（upsert_rules）

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py`
- Test: `src/tests/integration/flow/test_policy_rules_v2_write.py`

- [ ] **Step 1: 写失败测试**

Create `src/tests/integration/flow/test_policy_rules_v2_write.py`:

```python
"""policy_rules_v2 写入集成测试（P3 Task 2）。依赖 Milvus，不可用则 skip。"""
import pytest

MILVUS_URI = "http://127.0.0.1:19530"


def _milvus_ready() -> bool:
    try:
        from pymilvus import MilvusClient
        c = MilvusClient(uri=MILVUS_URI, timeout=2); c.close(); return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _milvus_ready(), reason="Milvus 不可用")


def test_upsert_rules_writes_entities():
    from pymilvus import connections, utility
    from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
        create_policy_rules_v2_collection, rule_to_entity, upsert_rules,
    )
    connections.connect(alias="default", host="127.0.0.1", port="19530")
    tmp = "_test_rules_v2_write"
    try:
        col = create_policy_rules_v2_collection(collection_name=tmp, drop_existing=True)
        rule = {
            "rule_id": "r_smoke_p3", "rule_type": "起付线",
            "insu_type": "城镇职工基本医疗保险", "hosp_lv": "三级医院",
            "deductible_amount": "1300元",
        }
        entity = rule_to_entity(rule, vector=[0.1] * 768,
                                extracted_at="2026-07-24", confidence=0.9)
        n = upsert_rules(col, [entity])
        assert n == 1
        col.load()
        res = col.query(expr='insu_type == "城镇职工基本医疗保险"',
                        output_fields=["rule_type", "deductible_amount"], limit=5)
        assert len(res) == 1
        assert res[0]["rule_type"] == "起付线"
        da = res[0]["deductible_amount"]
        assert isinstance(da, dict) and da["value"] == "1300元" and da["confidence"] == 0.9
    finally:
        if utility.has_collection(tmp):
            utility.drop_collection(tmp)
```

- [ ] **Step 2: 运行，确认失败（`upsert_rules` 不存在）**

- [ ] **Step 3: 实现 `upsert_rules`**

在 `policy_rules_schema_v2.py` **末尾追加**:

```python
def upsert_rules(col: Collection, entities: list[dict[str, Any]]) -> int:
    """批量写入规则实体（rule_to_entity 产出）到 policy_rules_v2。

    Args:
        col: policy_rules_v2 Collection（已创建）。
        entities: 每条为 rule_to_entity 返回的 dict。
    Returns: 写入条数。
    """
    if not entities:
        return 0
    col.insert(entities)
    col.flush()
    return len(entities)
```

- [ ] **Step 4: 运行通过 + 回归（P2 测试不破坏）→ 提交**

```bash
python -m pytest src/tests/integration/flow/test_policy_rules_v2_write.py src/tests/integration/flow/test_policy_rules_v2_schema.py -v
git add src/knowledge_extension/rule_explanation/policy_retrieval/policy_rules_schema_v2.py src/tests/integration/flow/test_policy_rules_v2_write.py
git commit -m "feat: add upsert_rules for policy_rules_v2 batch write (P3, §3.3)"
```

---

## Task 3: ingestion 编排（build_ingest_records）+ 发布链路 + API

**Files:**
- Create: `src/knowledge_extension/rule_explanation/policy_retrieval/policy_ingestion.py`
- Modify: `src/knowledge_extension/rule_explanation/pipeline_orchestrator.py`
- Modify: `src/runtime/api/policy_pipeline_routes.py`
- Test: `src/tests/unit/rule_explanation/test_policy_ingestion.py`

- [ ] **Step 1: 写失败测试（build_ingest_records 纯函数，FakeProvider）**

Create `src/tests/unit/rule_explanation/__init__.py`（空）+ `src/tests/unit/rule_explanation/test_policy_ingestion.py`:

```python
"""build_ingest_records 单测（P3 Task 3 核心：向量化 + rule_to_entity + 向量复用 + fact_id 关联）。

不连 Milvus、不加载模型（用 FakeProvider），快且确定。
"""
from src.knowledge_extension.rule_explanation.policy_retrieval.policy_ingestion import (
    build_ingest_records,
)


class FakeProvider:
    """固定向量 provider，便于断言向量复用。"""
    def encode(self, texts):
        return [[0.5] * 768 for _ in texts]

    @property
    def dim(self):
        return 768


def test_build_ingest_records_vector_reuse_and_lineage():
    facts = [
        {
            "fact_text": "起付标准1300元，统筹支付85%",
            "rules": [
                {"rule_type": "起付线", "insu_type": "城镇职工基本医疗保险",
                 "deductible_amount": "1300元", "confidence": 0.9},
                {"rule_type": "支付比例", "insu_type": "城镇职工基本医疗保险",
                 "payment_ratio": "85%", "confidence": 0.92},
            ],
        }
    ]
    provider = FakeProvider()
    fact_records, rule_entities = build_ingest_records(
        facts, doc_id="d1", provider=provider, extracted_at="2026-07-24T00:00:00"
    )

    # facts：向量化 + doc_id
    assert len(fact_records) == 1
    assert fact_records[0]["fact_text"] == "起付标准1300元，统筹支付85%"
    assert fact_records[0]["doc_id"] == "d1"
    assert len(fact_records[0]["vector"]) == 768
    assert fact_records[0]["created_at"] == "2026-07-24T00:00:00"

    # rules：2 条，都复用所属 fact 的向量 + 关联 fact_id
    assert len(rule_entities) == 2
    fact_vector = fact_records[0]["vector"]
    fact_id = fact_records[0]["fact_id"]
    for e in rule_entities:
        assert e["vector"] == fact_vector, "rule 应复用所属 fact 的向量（§4.1）"
        assert e["fact_id"] == fact_id, "rule 应关联所属 fact_id"

    # 核心维度进固定 schema
    types = {e["rule_type"] for e in rule_entities}
    assert types == {"起付线", "支付比例"}

    # 详情字段是字段级溯源对象（FieldTrace）
    da = next(e["deductible_amount"] for e in rule_entities if e["rule_type"] == "起付线")
    assert isinstance(da, dict) and da["value"] == "1300元"
    assert da["extracted_at"] == "2026-07-24T00:00:00" and da["confidence"] == 0.9
    pr = next(e["payment_ratio"] for e in rule_entities if e["rule_type"] == "支付比例")
    assert pr["value"] == "85%" and pr["confidence"] == 0.92


def test_build_ingest_records_empty_fact_text_uses_zero_vector():
    """fact_text 为空时用零向量（不崩），rule 仍关联。"""
    facts = [{"fact_text": "", "rules": [{"rule_type": "通用规则"}]}]
    fact_records, rule_entities = build_ingest_records(
        facts, doc_id="d2", provider=FakeProvider(), extracted_at="t"
    )
    assert fact_records[0]["vector"] == [0.0] * 768
    assert rule_entities[0]["vector"] == fact_records[0]["vector"]
```

- [ ] **Step 2: 运行，确认失败（模块不存在）**

```bash
python -m pytest src/tests/unit/rule_explanation/test_policy_ingestion.py -v
```

- [ ] **Step 3: 实现 `build_ingest_records`**

Create `src/knowledge_extension/rule_explanation/policy_retrieval/policy_ingestion.py`:

```python
"""政策入库编排：从 LLM 提取的 facts 构建 (fact_records, rule_entities)。

核心逻辑（设计文档 §4.1 向量复用、§3.3 字段级溯源）：
- fact_text 向量化（provider）。
- 每条 rule 用所属 fact 的 vector（同 fact 多 rules 共享，节省存储 + 语义一致）。
- rule 详情字段包成 FieldTrace（rule_to_entity）。
- rule 关联所属 fact_id。

[来源: docs/steering/政策知识管线设计文档.md §2 数据流 / §3.3 / §4.1]
"""
from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
    rule_to_entity,
)

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import EmbeddingProvider


def build_ingest_records(
    facts: list[dict[str, Any]],
    doc_id: str,
    provider: "EmbeddingProvider",
    extracted_at: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从 LLM 提取的 facts 构建 (fact_records, rule_entities)。

    Args:
        facts: LLM 产出，每条 {fact_text, rules: [...]}。
        doc_id: 所属政策文档 ID。
        provider: 向量化 provider（fact_text → vector）。
        extracted_at: 本次提取时间（ISO），写入字段级溯源。
    Returns:
        fact_records: 每条 {fact_id, doc_id, fact_text, vector, created_at}。
        rule_entities: 每条为 rule_to_entity 产出 + fact_id。
    """
    fact_records: list[dict[str, Any]] = []
    rule_entities: list[dict[str, Any]] = []

    for fact in facts:
        fact_text = fact.get("fact_text", "") or ""
        # 向量化；空文本用零向量避免 provider 对空串报错
        if fact_text:
            vector = provider.encode([fact_text])[0]
        else:
            vector = [0.0] * provider.dim

        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
        fact_records.append({
            "fact_id": fact_id,
            "doc_id": doc_id,
            "fact_text": fact_text,
            "vector": vector,
            "created_at": extracted_at,
        })

        for rule in fact.get("rules", []):
            entity = rule_to_entity(
                rule,
                vector=vector,            # 复用所属 fact 向量（§4.1）
                extracted_at=extracted_at,
                confidence=rule.get("confidence", 0.7),
            )
            entity["fact_id"] = fact_id   # 关联回所属 fact
            rule_entities.append(entity)

    return fact_records, rule_entities
```

- [ ] **Step 4: 运行单测，确认通过**

```bash
python -m pytest src/tests/unit/rule_explanation/test_policy_ingestion.py -v
```

- [ ] **Step 5: 实现 `publish_to_new_collections` + API 端点**

在 `pipeline_orchestrator.py` 的 `PipelineOrchestrator` 类**末尾追加**:

```python
    def publish_to_new_collections(self, extraction_id: str) -> dict[str, Any]:
        """将审核通过的提取结果发布到新 collection（policy_facts + policy_rules_v2）。

        与 publish_extraction（写旧 policy_rules）并存，互不影响（隔离，P10 才切换）。
        """
        ext = self._store.get_extraction(extraction_id)
        if not ext:
            return {"success": False, "error": "提取记录不存在"}
        if ext["status"] != "reviewed":
            return {"success": False, "error": "只有已审核的提取记录才能入库"}

        fields = ext["extracted_fields"]
        if isinstance(fields, str):
            fields = json.loads(fields)
        fact_text = fields.get("fact_text", "") or ext.get("source_text", "")
        rules = fields.get("rules", [])
        doc_id = ext["doc_id"]
        extracted_at = _now_iso()

        try:
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_facts_schema import (
                create_policy_facts_collection, upsert_facts,
            )
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_rules_schema_v2 import (
                create_policy_rules_v2_collection, upsert_rules,
            )
            from src.knowledge_extension.rule_explanation.policy_retrieval.policy_ingestion import (
                build_ingest_records,
            )
            from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
                get_embedding_provider,
            )
        except ImportError as e:
            return {"success": False, "error": f"依赖缺失: {e}"}

        try:
            provider = get_embedding_provider()
            facts_col = create_policy_facts_collection()
            rules_col = create_policy_rules_v2_collection()

            fact_records, rule_entities = build_ingest_records(
                [{"fact_text": fact_text, "rules": rules}],
                doc_id=doc_id, provider=provider, extracted_at=extracted_at,
            )
            upsert_facts(facts_col, fact_records)
            upsert_rules(rules_col, rule_entities)

            rule_ids = [e["rule_id"] for e in rule_entities]
            for rid in rule_ids:
                self._store.create_lineage(rid, extraction_id, doc_id)
            self._store.update_extraction(extraction_id, {"status": "published"})

            return {
                "success": True,
                "extraction_id": extraction_id,
                "fact_id": fact_records[0]["fact_id"] if fact_records else "",
                "rule_ids": rule_ids,
                "published_count": len(rule_ids),
                "target": "policy_facts + policy_rules_v2",
            }
        except Exception as e:
            logger.error("发布到新 collection 失败 ext=%s: %s", extraction_id, e)
            return {"success": False, "error": str(e), "extraction_id": extraction_id}
```

在 `pipeline_orchestrator.py` **模块级**加（若 datetime 未导入）:

```python
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

在 `policy_pipeline_routes.py` 的 publish 端点**附近追加**:

```python
@router.post("/extractions/{extraction_id}/publish-v2")
def publish_extraction_v2(extraction_id: str):
    """发布到新 collection（policy_facts + policy_rules_v2，P3 新通路）。

    与 /publish（写旧 policy_rules）并存；P10 切换后此端点成为主入口。
    """
    result = _get_orchestrator().publish_to_new_collections(extraction_id)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=error_detail(
            "PUBLISH_FAILED", result.get("error", ""), {"extraction_id": extraction_id}))
    return result
```

- [ ] **Step 6: 全量回归（P0/P1/P2 基线 + 新 P3 测试）→ 提交**

```bash
python -m pytest src/tests/unit/rule_explanation/ src/tests/unit/semantic_layer/ src/tests/integration/flow/test_policy_facts_write.py src/tests/integration/flow/test_policy_rules_v2_write.py src/tests/integration/flow/test_policy_rules_v2_schema.py src/tests/integration/flow/test_policy_qa_scalar_retrieval_baseline.py src/tests/integration/flow/test_policy_qa_vector_retrieval_baseline.py -q
git add src/knowledge_extension/rule_explanation/policy_retrieval/policy_ingestion.py src/knowledge_extension/rule_explanation/pipeline_orchestrator.py src/runtime/api/policy_pipeline_routes.py src/tests/unit/rule_explanation/
git commit -m "feat: publish_to_new_collections writes facts+rules_v2 with vector reuse (P3, §3.2/3.3/3.4)"
```

---

## 收口标准

- [ ] `upsert_facts` / `upsert_rules` 能批量写入对应 collection（集成测试绿）。
- [ ] `build_ingest_records` 实现向量复用（rule 复用 fact 向量）+ fact_id 关联 + 字段级溯源（单测绿）。
- [ ] `publish_to_new_collections` 编排端到端（提取记录 → facts + rules_v2 + lineage）。
- [ ] `POST /extractions/{id}/publish-v2` 端点可用。
- [ ] **未触碰** `publish_extraction`（旧路径）、旧 `policy_rules` collection。
- [ ] P0 回归基线（标量 + 向量）+ P2 schema 测试无回归。

## M2 demo 验证（收口后人工执行，非自动化）

P3 完成后，可在新 collection 上验证端到端（需 LLM 可用 + Milvus）：
1. 上传一篇政策原文（`POST /documents` 或 Excel）。
2. 触发提取（`POST /documents/{id}/extract`）→ 审核 extraction（`PUT /extractions/{id}` status=reviewed）。
3. 发布到新通路（`POST /extractions/{id}/publish-v2`）。
4. 直连 Milvus 查 `policy_facts`（有 fact_text+vector）+ `policy_rules_v2`（有核心维度 + 字段级溯源对象）。
5. 这是**第一个能"看见"的产出**——政策原文变成了结构化、可溯源、向量化的知识。

## 本计划交付后的事实 + 3.1 去向

- 新 collection `policy_facts` + `policy_rules_v2` 可被管线填充（端到端通路打通）。
- 生产政策问答**仍读旧 `policy_rules`**（`publish-v2` 是新通路，未切换）。
- **3.1（schema-driven prompt）移到 P4 后**：等 P4 让指标 draft→published、契约返回真实 fields 后，再做 `extraction_prompt_builder` 并接入 `run_extraction`。届时提取字段将跟随契约（加维度不改代码），无需改入库代码（build_ingest_records 已字段无关）。

## 后续计划（不在本计划内）

- **P4**: 质量门禁 + 指标 draft→published（让契约有数据，3.1 才有意义）。
- **P6**: 混合检索（基于 policy_rules_v2 新 schema + policy_facts 向量召回）。
- **P8**: 数据迁移（旧 policy_extractions 93 条 → 拆 facts + rules_v2）。
- **3.1**（独立小阶段，P4 后）：schema-driven prompt builder + 接入 run_extraction。
