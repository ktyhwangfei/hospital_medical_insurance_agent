# 政策管线 3.1：Schema 驱动的提示词（解锁"加维度不改代码"）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**对整个目标的价值**（实现整个管线重构最想证明的声明式能力）:

- **核心证明**："加维度不改代码"——提示词从硬编码 19 字段 → 由语义层 published 指标（ExtractionSchema）动态拼。以后加提取字段：语义层加 Metric + `publish_object` → 提示词自动包含，**不改任何提取代码**。
- **P4 的直接红利**：P4 修复了 publish_object 漏改 metric status，契约现在能返回 published 指标。3.1 让契约真正驱动提取，闭环"指标定义 → 契约 → 提示词 → LLM 提取"。
- **现状（要改的）**：`pipeline_orchestrator._build_fact_extraction_prompt` 硬编码 19 字段说明（insu_type/med_type/...）。加字段要改这个函数。3.1 把它替换为从 `ExtractionSchema` 动态拼。
- **字段无关性证明**：Task 1 单元测试用两个不同 schema（1 字段 / 2 字段+hint+值域）验证构建器都正确拼——这就是"加维度不改代码"的可执行证据。
- 风险：R2（改提取提示词）。但构建器是纯函数 + 单元测试覆盖；run_extraction 集成保留 LLM 提取的输出格式契约（fact_text + rules），不破坏入库（build_ingest_records 字段无关）。

**依据:** `docs/steering/政策知识管线设计文档.md` §3.1（extraction_hint"给 LLM 的提取说明，动态拼 prompt 用"）/ §5（publish 解锁契约）。P3 推迟 3.1 的唯一原因是契约空，P4 已修复。

---

## Goal

新建 `build_prompt_from_schema`（从 ExtractionSchema 动态拼提示词，字段无关），集成进 `run_extraction`（从 registry 读 zcgz published schema）。配合 re-seed + publish zcgz，端到端验证"加维度不改代码"。

## Architecture

- **构建器（纯函数）**：`build_prompt_from_schema(text, title, schema) -> str`。遍历 schema.fields/entities/relations 拼"字段说明 + 实体 + 关系 + 输出格式"。不读 PG，参数注入 schema（可单元测试）。
- **集成**：`run_extraction` 从 registry 读 `build_extraction_schema(registry, "zcgz")` → `build_prompt_from_schema`。替代硬编码 `_build_fact_extraction_prompt`。
- **数据准备**：re-seed PG（zcgz 19 字段指标进 PG）+ `publish_object("zcgz")`（draft→published）。

**Tech Stack:** ExtractionSchema/FieldContract（P1）· SemanticRegistry（P4 publish）· pytest

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `src/semantic_layer/extraction_contract.py` | 加 `build_prompt_from_schema`（契约→提示词） | 改 |
| `src/knowledge_extension/rule_explanation/pipeline_orchestrator.py` | `run_extraction` 用 schema 驱动提示词 | 改 |
| `src/tests/unit/semantic_layer/test_extraction_contract.py` | 构建器单元测试（字段无关证明） | 改 |

---

## Task 1: build_prompt_from_schema + 字段无关性单元测试

**Files:**
- Modify: `src/semantic_layer/extraction_contract.py`
- Test: `src/tests/unit/semantic_layer/test_extraction_contract.py`

- [ ] **Step 1: 写失败测试（字段无关性证明）**

在 `test_extraction_contract.py` **末尾追加**：

```python
def test_build_prompt_from_schema_is_field_agnostic():
    """构建器从 schema 动态拼提示词——加维度只改语义层，不改此函数（§3.1 核心证明）。"""
    from src.semantic_layer.extraction_contract import build_prompt_from_schema

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
```

- [ ] **Step 2: 运行，确认失败（`build_prompt_from_schema` 不存在）**

```bash
python -m pytest src/tests/unit/semantic_layer/test_extraction_contract.py::test_build_prompt_from_schema_is_field_agnostic -v
```

- [ ] **Step 3: 实现 `build_prompt_from_schema`**

在 `extraction_contract.py` 末尾追加（纯函数，字段无关）：

```python
def build_prompt_from_schema(text: str, title: str, schema: ExtractionSchema) -> str:
    """从提取契约动态拼 LLM 提示词（schema-driven，加维度不改此函数）。

    [来源: §3.1 extraction_hint 动态拼 prompt；§7.1 契约结构]
    """
    # 字段说明（核心检索维度 + 详情字段）
    if schema.fields:
        fields_desc = "\n".join(
            f"- {f.code}（{f.name}）"
            + (f"：{f.extraction_hint}" if f.extraction_hint else "")
            + (f" 值域：{', '.join(schema.dictionaries[f.value_domain])}"
               if f.value_domain and f.value_domain in schema.dictionaries else "")
            for f in schema.fields
        )
    else:
        fields_desc = "（无 published 字段——请先 publish_object）"

    # 实体说明
    entities_desc = "\n".join(
        f"- {e.code}（{e.name}）" + (f"：{e.extraction_hint}" if e.extraction_hint else "")
        for e in schema.entities
    ) or "（无）"

    # 关系说明（三元组）
    relations_desc = "\n".join(
        f"- {r.code}：({r.subject_hint}, {r.predicate_hint}, {r.object_hint})"
        for r in schema.relations
    ) or "（无）"

    field_codes = [f.code for f in schema.fields]
    return f"""你是一个医保政策分析专家。请从政策文本中提取所有"政策事实"，并从每个事实提取结构化规则。

## 提取字段（来自语义层 published 指标，schema_version={schema.schema_version}）
{fields_desc}

## 实体
{entities_desc}

## 关系
{relations_desc}

## 政策文件
{title}

## 原文
{text}

## 输出格式
返回 JSON 数组，每个事实含 fact_text + rules（rules 含上述字段 {field_codes}，原文未提及填空字符串""）：
[
  {{
    "fact_text": "完整事实描述",
    "rules": [{{"{"": ""}", }}
  }}
]
"""
```

- [ ] **Step 4: 运行通过 → 提交**

```bash
python -m pytest src/tests/unit/semantic_layer/test_extraction_contract.py -v
git add src/semantic_layer/extraction_contract.py src/tests/unit/semantic_layer/test_extraction_contract.py
git commit -m "feat: build_prompt_from_schema schema-driven prompt 构建器 (3.1, §3.1)"
```

---

## Task 2: run_extraction 集成 + re-seed/publish zcgz + 端到端

**Files:**
- Modify: `src/knowledge_extension/rule_explanation/pipeline_orchestrator.py`

- [ ] **Step 1: re-seed PG（zcgz 19 字段进 PG）+ publish zcgz**

```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.semantic_layer.registry import create_registry
from src.semantic_layer.seed import seed_semantic_layer
reg = create_registry()
seed_semantic_layer(reg._store)  # re-seed（含 zcgz）
reg.publish_object('zcgz')       # draft→published
schema_check = reg._store.list_metrics(object_code='zcgz')
print('zcgz published 指标数:', sum(1 for m in schema_check if m.status=='published'))
"
```
> 预期输出：zcgz published 指标数 ≈ 19（seed 的 19 字段）。

- [ ] **Step 2: 改 `run_extraction` 用 schema 驱动提示词**

在 `pipeline_orchestrator.py`：
- 改 `_build_fact_extraction_prompt` 调用为从 registry 读 schema + `build_prompt_from_schema`：

```python
    def _build_fact_extraction_prompt(self, text: str, title: str) -> str:
        """构建事实提取 prompt（schema-driven，§3.1）。

        从语义层读 zcgz 对象的 published 指标契约，动态拼提示词。
        回退：registry 不可用时用硬编码兜底（保证提取不中断）。
        """
        from src.semantic_layer.registry import create_registry
        from src.semantic_layer.extraction_contract import (
            build_extraction_schema, build_prompt_from_schema,
        )
        try:
            reg = create_registry()
            schema = build_extraction_schema(reg, "zcgz")
            if schema.fields or schema.entities or schema.relations:
                return build_prompt_from_schema(text, title, schema)
        except Exception:
            pass
        # 回退：registry 不可用 → 用原硬编码 prompt（保留为 _legacy_prompt）
        return self._legacy_fact_extraction_prompt(text, title)
```

- 把**原 `_build_fact_extraction_prompt` 的硬编码实现**改名为 `_legacy_fact_extraction_prompt`（作为回退）。

- [ ] **Step 3: import smoke + 回归 + 端到端验证 → 提交**

```bash
# import smoke
python -c "from src.knowledge_extension.rule_explanation.pipeline_orchestrator import PipelineOrchestrator; print('OK')"
# 回归（契约 + 构建 + 入库单元）
python -m pytest src/tests/unit/semantic_layer/test_extraction_contract.py src/tests/unit/rule_explanation/ -q
# 端到端：验证 run_extraction 拿到 schema-driven prompt（不跑 LLM，只看 prompt 含 zcgz 字段）
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import PipelineOrchestrator
orch = PipelineOrchestrator()
prompt = orch._build_fact_extraction_prompt('测试原文', '测试标题')
print('含 insu_type:', 'insu_type' in prompt or '险种' in prompt)
print('prompt 前 200 字:', prompt[:200])
"
git add src/knowledge_extension/rule_explanation/pipeline_orchestrator.py
git commit -m "feat: run_extraction 用 schema-driven prompt + legacy 回退 (3.1 集成)"
```

---

## 收口标准

- [ ] `build_prompt_from_schema` 从 ExtractionSchema 动态拼提示词（字段无关，单元测试证明）。
- [ ] `run_extraction` 用 schema 驱动提示词（registry 不可用时回退 legacy）。
- [ ] re-seed + publish zcgz 后，端到端 prompt 含 zcgz 的 published 字段。
- [ ] 现有契约 + 入库单元测试全绿（无回归）。

## 本计划交付后的事实

- **"加维度不改代码"成为现实**：语义层加 Metric（extraction_hint）+ publish_object → 提示词自动包含新字段，不改 extraction_contract / pipeline_orchestrator 任何代码。
- **声明式提取闭环打通**：指标定义（语义层）→ 契约（build_extraction_schema）→ 提示词（build_prompt_from_schema）→ LLM 提取 → 入库（build_ingest_records，字段无关）。
- **legacy 回退保留**：registry 不可用时用硬编码 prompt，保证提取管线不中断（渐进迁移）。
- 完整端到端（真 LLM 提取新字段）可作为后续 demo 验证（依赖 MODEL_API_KEY + re-seed 后的 zcgz）。
