# 政策管线 P4：质量门禁与指标发布 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**对整个目标的价值**（解锁 §3.1 schema-driven prompt，打通"契约→提取"闭环）:

- **根因定位**：`publish_object` 发布对象时只改 `obj.status` + 存版本快照，**漏改 `metric.status`**（没 `save_metric`）。而 `build_extraction_schema` / `extraction_contract` 只读 `m.status == "published"`——所以即使对象 published，metric 仍 draft，**契约永远空**。这就是 P3 时 3.1（schema-driven prompt）推迟的根因。
- **证据**：现有契约测试（test_extraction_contract.py:41,58 / test_semantic_extraction_schema.py:48）都**手动设 `status="published"`** 绕过 publish_object，所以这个 bug 从未被测试捕获。
- **小修复、大解锁**：publish_object 加几行（同步 metric status + 门禁），契约就有数据 → 3.1（"加维度不改代码"的动态 prompt）立即可行。
- **质量门禁（§5）首版简化**：完整质量分（填充率/值域合规率/标注一致性）需黄金样本集 + 已提取数据，是独立大块。P4 实现 §5 的硬约束——"空指标不能发布"（对象无 metric 不能发布），完整质量分推迟。
- 风险：R1（改 registry.publish_object 逻辑）。但现有测试（test_builder / test_integration）调 publish_object **不断言 metric status**，所以同步 status 不破坏现有；纯单元测试，快。

**依据:** `docs/steering/政策知识管线设计文档.md` §5（质量门禁：空指标不能发布）/ §3.1（契约驱动提取）。根因：`src/semantic_layer/registry.py:225 publish_object` 漏改 metric status。

---

## Goal

修复 `publish_object` 发布对象时同步 metric.status（draft→published）+ 加门禁（对象无 metric 不能发布），并端到端验证契约解锁（发布后 `build_extraction_schema` 返回该指标）。

## Architecture

- `publish_object` 增加：① 门禁检查（metrics 非空，否则 raise）；② 同步 metric.status="published" + save_metric（在快照生成后、obj 状态更新时一起做）。
- 契约端到端：`build_extraction_schema(registry, object_code)` 依赖 metric.status=="published"，修复后发布即返回。

**Tech Stack:** SemanticRegistry + InMemoryRegistryStore（纯单元，不需 PG/Milvus，快）· pytest

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/semantic_layer/registry.py` | `publish_object` 加门禁 + 同步 metric status | 改 |
| `src/tests/unit/semantic_layer/test_builder.py` | 加 publish 门禁 + status 同步测试 | 改 |
| `src/tests/unit/semantic_layer/test_extraction_contract.py` | 加契约端到端解锁测试 | 改 |

---

## Task 1: publish_object 同步 metric status + 门禁

**Files:**
- Modify: `src/semantic_layer/registry.py`
- Test: `src/tests/unit/semantic_layer/test_builder.py`

- [ ] **Step 1: 写失败测试（发布后 metric status published + 空对象拒绝）**

在 `test_builder.py` **末尾追加**（独立函数，自包含 InMemoryRegistryStore）：

```python
def test_publish_object_promotes_metric_status():
    """publish_object 发布对象时，metric.status 应同步 draft→published（契约读取的前置）。"""
    from src.semantic_layer.models import BusinessObject, Metric
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_object(BusinessObject(object_code="t_pub", domain_code="d", name="测试"))
    store.save_metric(Metric(metric_code="t_pub.f1", object_code="t_pub", name="字段1"))
    assert store.list_metrics("t_pub")[0].status == "draft"  # 发布前 draft
    reg.publish_object("t_pub")
    assert store.list_metrics("t_pub")[0].status == "published"  # 发布后 published


def test_publish_object_rejects_empty_object():
    """空对象（无 metric）不能发布（§5：空指标不能发布）。"""
    from src.semantic_layer.models import BusinessObject
    store = InMemoryRegistryStore()
    reg = SemanticRegistry(store)
    store.save_object(BusinessObject(object_code="t_empty", domain_code="d", name="空对象"))
    import pytest
    with pytest.raises(ValueError, match="无.*指标|metric|空"):
        reg.publish_object("t_empty")
```

- [ ] **Step 2: 运行，确认失败（metric status 未同步 / 空对象未拒绝）**

```bash
python -m pytest src/tests/unit/semantic_layer/test_builder.py::test_publish_object_promotes_metric_status src/tests/unit/semantic_layer/test_builder.py::test_publish_object_rejects_empty_object -v
```

- [ ] **Step 3: 修复 `publish_object`（加门禁 + 同步 status）**

在 `registry.py` 的 `publish_object`，在 `metrics = self._store.list_metrics(...)` **之后**插入门禁，并在快照生成后**同步 metric status**：

```python
        metrics = self._store.list_metrics(object_code=object_code)
        if not metrics:
            raise ValueError(
                f"对象 '{object_code}' 无指标，不能发布（§5：空指标不能发布）"
            )
```

然后在 `obj.status = "published"` **之前/之后**同步 metric status：

```python
        obj.current_version = next_version
        obj.status = "published"
        self._store.save_object(obj)
        # 同步 metric.status → published（解锁 build_extraction_schema / 契约）
        for m in metrics:
            m.status = "published"
            self._store.save_metric(m)
        return snapshot
```

- [ ] **Step 4: 运行通过 + 回归（test_builder 全部 + test_extraction_contract）→ 提交**

```bash
python -m pytest src/tests/unit/semantic_layer/test_builder.py src/tests/unit/semantic_layer/test_extraction_contract.py src/tests/unit/semantic_layer/test_integration.py -v
git add src/semantic_layer/registry.py src/tests/unit/semantic_layer/test_builder.py
git commit -m "fix: publish_object 同步 metric.status draft→published + 空对象门禁 (P4, §5)"
```

---

## Task 2: 契约端到端解锁（发布即进契约）

**Files:**
- Test: `src/tests/unit/semantic_layer/test_extraction_contract.py`（不改代码，验证修复后联动）

- [ ] **Step 1: 写测试（发布前契约空，发布后契约有数据）**

在 `test_extraction_contract.py` **末尾追加**：

```python
def test_publish_object_unlocks_extraction_schema():
    """publish_object 发布后，build_extraction_schema 应返回该对象指标（解锁 §3.1）。

    这是 P3 推迟 3.1 的根因验证：发布前契约空（draft 不进），发布后有数据。
    """
    from src.semantic_layer.models import BusinessObject, Metric
    from src.semantic_layer.registry import SemanticRegistry
    from src.data_platform.storage.in_memory.semantic_registry_store import InMemoryRegistryStore
    from src.semantic_layer.extraction_contract import build_extraction_schema
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
```

> **注意**：确认 `InMemoryRegistryStore` 的 import 路径（test_builder 里用的路径）；若不同，用 test_builder 一致的 import。

- [ ] **Step 2: 运行通过（依赖 Task 1 修复）→ 提交**

```bash
python -m pytest src/tests/unit/semantic_layer/test_extraction_contract.py -v
git add src/tests/unit/semantic_layer/test_extraction_contract.py
git commit -m "test: publish_object→extraction_schema 端到端解锁 (P4 验证 §3.1 前置)"
```

---

## 收口标准

- [ ] `publish_object` 后该对象所有 metric.status == "published"（单元测试绿）。
- [ ] 空对象（无 metric）发布被拒，raise ValueError（§5 门禁）。
- [ ] 发布后 `build_extraction_schema` 返回该对象指标（契约解锁，3.1 前置达成）。
- [ ] 现有 test_builder / test_integration / test_extraction_contract 全绿（无回归）。

## 本计划交付后的事实 + 后续去向

- **3.1（schema-driven prompt）解锁**：契约现在有 published 指标，可以构建动态提取 prompt（加维度只改语义层 + 发布，不改代码）。3.1 可作为独立小阶段执行。
- **完整质量门禁推迟**：§5.3 质量分（填充率/值域合规率/标注一致性）+ §5.2 黄金样本集 + §6 schema_update_task（批量增量更新）都是独立大块，需提取数据 + 人工标注，后续单独阶段。
- **P4 是"小修复、大解锁"**：几行修复了 publish_object 漏改 status 的根因，打通契约闭环——这是政策管线从"手动设 status 绕过"到"发布即生效"的关键一步。
