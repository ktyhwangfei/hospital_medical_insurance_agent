# Rule-driven Policy Structure Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从异常规则和来源 release 生成可解释的机构类别/基金语义诊断，并在页面确认后保存不直接发布的治理变更草稿。

**Architecture:** 复用编译 lineage 作为政策权威来源、现有 `match_database_evidence` 作为 bjyb 证据匹配、现有 `SemanticProposal` JSONB 存储作为草稿队列。新增一个纯确定性诊断模块和两个语义对齐 API；Portal 在政策知识页面提供三步向导，现有提议队列保留为次级入口。

**Tech Stack:** FastAPI、Pydantic、PostgreSQL JSONB、Next.js 16、React 19、Vitest。

---

### Task 1: 确定性规则诊断与未发布草稿

**Files:**
- Create: `src/knowledge_extension/rule_explanation/rule_governance.py`
- Modify: `src/knowledge_extension/rule_explanation/semantic_alignment.py`
- Test: `src/tests/unit/knowledge_extension/test_rule_governance.py`

- [ ] **Step 1: 写失败测试**

测试用 `InMemoryCompilationTraceStore` 固化两类规则：社区/非社区规则应合并为“医疗机构类别”问题并推荐 `H_TYPE`、排除 `H_LEVEL`；大额互助规则与综合待遇比例规则必须拆为两个问题，且不能都标记为统筹基金。

- [ ] **Step 2: 运行测试确认 RED**

Run: `pytest -q src/tests/unit/knowledge_extension/test_rule_governance.py`

Expected: 因 `diagnose_rule_governance` 尚不存在而失败。

- [ ] **Step 3: 写最小实现**

在 `rule_governance.py` 实现：

```python
def diagnose_rule_governance(
    release_id: str,
    rule_ids: list[str],
    trace_store: CompilationTraceStore,
    database_fields: list[dict],
) -> RuleGovernanceDiagnosis:
    """按 lineage 读取 canonical rule，以确定性词汇和结构轴拆分治理问题。"""
```

在 `SemanticProposal` 增加 `RULE_GOVERNANCE`、`MANUAL_RULE_CORRECTION`、`revision` 和类型化 `governance_change_plan`；增加 `create_rule_governance_draft()`，同 fingerprint 返回现有草稿，并在 `publish_proposal()` 阻止规则治理草稿直接发布。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `pytest -q src/tests/unit/knowledge_extension/test_rule_governance.py`

Expected: 2 passed。

### Task 2: 诊断和创建草稿 API

**Files:**
- Modify: `src/runtime/api/semantic_alignment_routes.py`
- Modify: `src/tests/integration/api/test_semantic_alignment_api.py`

- [ ] **Step 1: 写失败 API 测试**

覆盖：`POST /rule-diagnoses` 返回来源 release、问题拆分和数据库证据；`POST /rule-governance-drafts` 返回 `proposal_type=rule_governance`、`status=proposed`，且不修改 registry。

- [ ] **Step 2: 运行测试确认 RED**

Run: `pytest -q src/tests/integration/api/test_semantic_alignment_api.py -k rule_governance`

Expected: 端点 404。

- [ ] **Step 3: 写最小路由**

新增可 override 的 `get_rule_governance_trace_store()`，并实现：

```text
POST /semantic/alignment/rule-diagnoses
POST /semantic/alignment/rule-governance-drafts
```

两端点复用 `SemanticReviewPrincipalDependency`；创建草稿时重新诊断并校验 issue ID，改选推荐时要求说明。

- [ ] **Step 4: 运行测试确认 GREEN**

Run: `pytest -q src/tests/integration/api/test_semantic_alignment_api.py -k rule_governance`

Expected: 1 passed。

### Task 3: 三步治理页面与规则追溯入口

**Files:**
- Create: `src/apps/portal/src/components/policy-knowledge/rule-governance-wizard.tsx`
- Modify: `src/apps/portal/app/policy-knowledge/knowledge/semantic-discovery/page.tsx`
- Modify: `src/apps/portal/src/components/policy-knowledge/rule-trace-drawer.tsx`
- Modify: `src/apps/portal/src/lib/policy-knowledge-api.ts`
- Modify: `src/apps/portal/app/semantic-layer/proposals/page.tsx`
- Test: `src/apps/portal/src/tests/policy-knowledge/rule-governance-wizard.test.tsx`

- [ ] **Step 1: 写失败 Portal 测试**

验证深链自动诊断、业务标题优先、`H_TYPE` 推荐/`H_LEVEL` 排除、基金问题拆分、确认后显示“未执行”，且页面没有直接发布按钮。

- [ ] **Step 2: 运行测试确认 RED**

Run: `npm test -- src/tests/policy-knowledge/rule-governance-wizard.test.tsx --run`

Workdir: `src/apps/portal`

Expected: 组件不存在。

- [ ] **Step 3: 写最小页面实现**

向导默认展示“规则诊断 → 数据库证据 → 建模决策”，技术 ID 折叠；无深链时展示说明和“高级方式”输入。将 `diagnosis_id`、release 和规则 ID 保留在 URL/sessionStorage。规则追溯抽屉增加携带 release/rule ID 的“发起结构治理”链接；统一队列对规则治理提议只允许批准计划，不调用 publish API。

- [ ] **Step 4: 聚焦验证**

Run: `npm test -- src/tests/policy-knowledge/rule-governance-wizard.test.tsx --run`

Workdir: `src/apps/portal`

Expected: 1 passed。

Run: `npx tsc --noEmit`

Workdir: `src/apps/portal`

Expected: exit 0。

### Task 4: 收口记录

**Files:**
- Modify: `PROGRESS.md`
- Modify: `docs/steering/政策知识治理-需求迭代记录.md`

- [ ] **Step 1: 按单元 → API → Portal 顺序复跑上述三条聚焦命令**

- [ ] **Step 2: 记录实际通过数、页面验证路径和未实现边界**

- [ ] **Step 3: 只提交本次直接相关文件，不带入工作区已有改动**
