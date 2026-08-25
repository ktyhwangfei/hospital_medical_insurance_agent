# Policy QA 唯一业务面退役收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除结算异常导办、出院前联合质控及旧 Chat 的全部现行影响，使 `/policy-qa` 成为唯一业务入口，同时保留真实结算单与 `settlement_explain_skill`。

**Architecture:** 先用文件边界和 API 404 测试固定退役契约，再删除无生产调用者的旧运行时、Portal 和测试资产。共享结算数据、政策知识、Skill 治理与 Runtime Memory 保留；包级 `__init__` 改为只导出现行 Policy QA 需要的类型，阻断旧模块启动导入。

**Tech Stack:** Python 3、FastAPI、pytest、Next.js 16、TypeScript、Vitest、Playwright

---

### Task 1: 用失败测试固定唯一业务面

**Files:**
- Create: `src/tests/unit/runtime/test_policy_qa_only_surface.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
- Create: `src/apps/portal/src/tests/routing/policy-qa-only-entry.test.ts`

- [ ] **Step 1: 新增后端旧模块不存在测试**

```python
from pathlib import Path

from src.runtime.intent.planner import ContextPlanner


SRC_ROOT = Path(__file__).resolve().parents[3]
LEGACY_PATHS = (
    "business_scenarios",
    "runtime/scenario_executor.py",
    "runtime/orchestrator.py",
    "runtime/langgraph",
    "runtime/orchestration",
    "runtime/planning",
    "runtime/scheduling",
    "runtime/capability_nodes",
    "runtime/dependencies.py",
    "runtime/skill_registry",
    "runtime/policy_qa/orchestrator.py",
    "data_platform/storage/skill/seed.py",
)


def test_retired_business_modules_are_absent() -> None:
    existing = [path for path in LEGACY_PATHS if (SRC_ROOT / path).exists()]
    assert existing == []


def test_context_planner_contains_no_retired_business_intents() -> None:
    assert "settlement_exception_guidance" not in ContextPlanner.INTENT_OBJECT_MAP
    assert "pre_discharge_quality_control" not in ContextPlanner.INTENT_OBJECT_MAP
```

- [ ] **Step 2: 运行单元测试并确认红灯**

Run: `python -m pytest src/tests/unit/runtime/test_policy_qa_only_surface.py -q`

Expected: FAIL，列出当前仍存在的旧运行时路径和两个旧 intent。

- [ ] **Step 3: 固定旧 API 为 404**

在 `test_policy_qa_routes.py` 增加：

```python
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/medical-insurance-ai-agent/chat"),
        ("post", "/api/v1/medical-insurance-ai-agent/chat/stream"),
        ("get", "/api/v1/medical-insurance-ai-agent/workflows"),
        ("post", "/api/v1/medical-insurance-ai-agent/tasks/confirm"),
    ],
)
def test_retired_business_api_is_not_registered(client, method: str, path: str) -> None:
    response = client.post(path, json={}) if method == "post" else client.get(path)
    assert response.status_code == 404
```

- [ ] **Step 4: 固定 Portal 旧页面文件不存在**

```typescript
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('Policy QA is the only business page', () => {
  it.each(['settlement', 'qc', 'dashboard'])('removes /%s', (route) => {
    expect(existsSync(resolve(process.cwd(), 'app', route, 'page.tsx'))).toBe(false)
  })

  it('keeps /policy-qa', () => {
    expect(existsSync(resolve(process.cwd(), 'app/policy-qa/page.tsx'))).toBe(true)
  })
})
```

- [ ] **Step 5: 运行 Portal 测试并确认红灯**

Run: `cd src/apps/portal; npm test -- src/tests/routing/policy-qa-only-entry.test.ts`

Expected: FAIL，`settlement`、`qc`、`dashboard` 页面仍存在。

- [ ] **Step 6: 保留红灯改动并进入实现**

此时不提交失败测试；Task 2–5 完成并让后端与 Portal 聚焦测试全部转绿后，作为一个可回滚提交一起提交。

### Task 2: 删除旧后端执行链

**Files:**
- Delete: `src/business_scenarios/`
- Delete: `src/runtime/scenario_executor.py`
- Delete: `src/runtime/orchestrator.py`
- Delete: `src/runtime/langgraph/`
- Delete: `src/runtime/orchestration/`
- Delete: `src/runtime/planning/`
- Delete: `src/runtime/scheduling/`
- Delete: `src/runtime/capability_nodes/`
- Delete: `src/runtime/dependencies.py`
- Delete: `src/runtime/skill_registry/`
- Delete: `src/data_platform/storage/skill/seed.py`
- Delete: `src/knowledge_extension/knowledge_stub.py`
- Modify: `src/runtime/context/__init__.py`
- Delete: `src/runtime/context/service.py`
- Modify: `src/runtime/intent/__init__.py`
- Modify: `src/runtime/intent/planner.py`
- Delete: `src/runtime/intent/knowledge.py`
- Delete: `src/runtime/intent/parser.py`
- Delete: `src/runtime/intent/registry.py`
- Delete: `src/runtime/intent/service.py`
- Delete: `src/runtime/intent/skill_matcher.py`
- Delete: `src/runtime/intent/prompts.py`
- Delete: `src/runtime/intent/graph/`

- [ ] **Step 1: 删除只被旧 scenario executor 调用的模块**

删除清单中的目录和文件；保留 `runtime/context/models.py`、`runtime/intent/models.py`、`runtime/intent/planner.py`、Memory、Reasoning 和 Task Closure。

- [ ] **Step 2: 收窄包级导出，避免导入旧实现**

`src/runtime/context/__init__.py`：

```python
from src.runtime.context.models import RuntimeContext

__all__ = ["RuntimeContext"]
```

`src/runtime/intent/__init__.py`：

```python
from src.runtime.intent.models import IntentCandidate, IntentResult

__all__ = ["IntentCandidate", "IntentResult"]
```

- [ ] **Step 3: 从 Context Planner 删除旧业务映射**

```python
INTENT_OBJECT_MAP: dict[str, list[MemoryType]] = {
    "policy_qa_fee_decomposition": [
        MemoryType.SETTLEMENT,
        MemoryType.POLICY,
        MemoryType.RULE,
    ],
    "skill_execution": [],
}
```

- [ ] **Step 4: 运行唯一业务面单元测试**

Run: `python -m pytest src/tests/unit/runtime/test_policy_qa_only_surface.py -q`

Expected: PASS。

- [ ] **Step 5: 保持改动未提交**

继续执行 Task 3；此时仍有旧测试引用待删除模块，不形成中间提交。

### Task 3: 删除退役 Policy QA 编排器并收窄治理资产

**Files:**
- Delete: `src/runtime/policy_qa/orchestrator.py`
- Delete: `src/runtime/policy_qa/dictionary_normalizer.py`
- Delete: `src/runtime/policy_qa/explanation_generator.py`
- Delete: `src/runtime/policy_qa/fee_decomposition_skill.py`
- Delete: `src/runtime/policy_qa/fee_item_detector.py`
- Delete: `src/runtime/policy_qa/intent_detector.py`
- Delete: `src/runtime/policy_qa/question_rewriter.py`
- Delete: `src/runtime/policy_qa/sql_data_fetcher.py`
- Delete: `src/runtime/policy_qa/tool_adapters.py`
- Modify: `src/runtime/policy_qa/models.py`
- Modify: `src/runtime/policy_qa/policy_rules_search.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/model_service/governance.py`
- Modify: `src/model_service/governance_import.py`
- Modify: `src/config/model_routing.py`
- Modify: `src/config/security_policy/rules.py`
- Modify: `src/observability/metrics/definitions.py`

- [ ] **Step 1: 删除旧编排器专属 Policy QA 模块**

保留：`explanation_mode.py`、`history_service.py`、`models.py`、`persistence.py`、`policy_rules_search.py`、`public_contract.py`、`runtime_bridge.py`、`settlement_data_provider.py`、`structured_policy_retriever.py`。

- [ ] **Step 2: 将 `models.py` 收窄为现行请求 DTO**

```python
from dataclasses import dataclass


@dataclass
class PolicyQARequest:
    question: str
    settlement_id: str
    session_id: str | None = None
    user_id: str = ""
    role: str = ""
```

不新增 `tenant_id` 或旧编排器字段；租户继续由现有 `_resolve_tenant_id()` 安全回退。

- [ ] **Step 3: 将 `policy_rules_search.py` 收窄为 v2 字段契约**

保留 `COLLECTION_NAME`、`CORE_FIELDS`、`DETAIL_FIELDS`、`OUTPUT_FIELDS` 和 `unpack_detail()`；删除无生产调用者的 `PolicyRulesSearchEngine` 和 embedding 初始化。

- [ ] **Step 4: 删除治理中的退役提示词与模型路由**

从 `governance.py` 和 `governance_import.py` 删除以下资产：

```python
{"intent.classify", "intent.discriminate", "policy_qa.intent_detect", "policy_qa.patient_explain"}
```

从 `config/model_routing.py` 删除 `("intent_recognition", "llm")`；从安全场景和指标定义删除两个旧业务 ID 与 `settlement_exception_duration`。保留 `skill_routing`、`policy_qa`、政策抽取和 Skill 创作治理资产。

- [ ] **Step 5: 清理路由中的退役导入与注释**

删除未使用的 `PolicyQAResponse` import，以及关于 `PolicyRulesSearchEngine` 和旧编排器的启动注释；不改变现行 SSE 契约。

- [ ] **Step 6: 运行模型治理与 Policy QA 聚焦单元测试**

Run: `python -m pytest src/tests/unit/model_service/test_governance.py src/tests/unit/model_service/test_governance_import.py src/tests/unit/runtime/policy_qa/test_policy_qa.py -q`

Expected: 初次运行因旧资产断言失败；在 Task 5 更新对应测试后全部 PASS。

- [ ] **Step 7: 保持改动未提交**

继续执行 Portal 和测试收口；不提交会造成测试收集失败的中间状态。

### Task 4: 删除 Portal 旧业务页面与组件

**Files:**
- Delete: `src/apps/portal/app/settlement/page.tsx`
- Delete: `src/apps/portal/app/qc/page.tsx`
- Delete: `src/apps/portal/app/dashboard/page.tsx`
- Delete: `src/apps/portal/src/components/settlement-chat.tsx`
- Delete: `src/apps/portal/src/components/settlement-exception-list.tsx`
- Delete: `src/apps/portal/src/components/discharge-qc.tsx`
- Delete: `src/apps/portal/src/components/dashboard.tsx`
- Delete: `src/apps/portal/src/components/intent-trace-card.tsx`
- Delete: `src/apps/portal/src/components/thinking-chain.tsx`
- Delete: `src/apps/portal/src/components/chat/`
- Delete: `src/apps/portal/src/lib/sse-hooks.ts`
- Modify: `src/apps/portal/src/lib/policy-qa-session.ts`
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Modify: `src/apps/portal/src/lib/mock-data.ts`
- Modify: `src/apps/portal/src/lib/types.ts`
- Delete: `src/apps/portal/src/tests/components/chat-input.test.tsx`
- Delete: `src/apps/portal/src/tests/components/message-list.test.tsx`
- Delete: `src/apps/portal/src/tests/components/streaming-bubble.test.tsx`

- [ ] **Step 1: 把 Policy QA 消息类型移回 Policy QA 模块**

在 `policy-qa-session.ts` 删除对旧 `chat/helpers` 的 import，并定义：

```typescript
export interface PolicyQAChatMessage {
  role: 'user' | 'assistant'
  content: string
  fallback?: boolean
  kind?: 'normal' | 'clarification' | 'confirmation'
  contextNeed?: ContextNeedSnapshot
  answerStatus?: PolicyQAResult['answerStatus']
  citations?: PolicyQAResult['citations']
  uncertainties?: string[]
  verificationSummary?: PolicyQAVerificationSummary
  calculationSteps?: PolicyQAResult['calculationSteps']
  definition?: PolicyQAResult['definition']
  warnings?: string[]
  caseContext?: PolicyQACaseContext
  qaTurnId?: string
  selectedSkillId?: string
  feedbackState?: 'idle' | 'submitted' | 'error'
}
```

- [ ] **Step 2: 删除旧页面、组件、hook 和专属组件测试**

删除清单中的文件。保留根 `/` 到 `/policy-qa` 的默认重定向，以及所有政策知识、语义层、模型治理、Skill 治理和问答历史页面。

- [ ] **Step 3: 清理旧 API client 和 mock**

从 `api-client.ts` 删除 `sendChatStream`、patient-context、task confirm、workflow、error-code dashboard API 及其专属 fallback；从 `mock-data.ts` 删除结算异常、质控、旧 Chat、旧运营看板数据，只保留仍被模型/MCP 管理实际引用的导出；从 `types.ts` 删除只被这些旧函数使用的 DTO。

- [ ] **Step 4: 运行唯一页面测试**

Run: `cd src/apps/portal; npm test -- src/tests/routing/policy-qa-only-entry.test.ts`

Expected: PASS。

- [ ] **Step 5: 保持改动未提交**

继续执行 Task 5，等后端与前端聚焦测试同时转绿后统一提交。

### Task 5: 删除失效测试资产并保留现行覆盖

**Files:**
- Delete: `src/tests/unit/runtime/langgraph/`
- Delete: `src/tests/unit/runtime/test_capability_nodes.py`
- Delete: `src/tests/unit/runtime/test_dependencies.py`
- Delete: `src/tests/unit/runtime/test_scenario_executor_policy_qa.py`
- Delete: `src/tests/unit/runtime/context/test_runtime_context_and_planning.py`
- Delete: `src/tests/unit/runtime/intent/test_intent_parser.py`
- Delete: `src/tests/unit/runtime/intent/test_intent_registry.py`
- Delete: `src/tests/unit/runtime/intent/test_intent_service_compat.py`
- Delete: `src/tests/unit/runtime/intent/test_intent_discrimination.py`
- Delete: `src/tests/unit/runtime/intent/test_intent_prompts.py`
- Delete: `src/tests/integration/api/test_skill_routes_api.py`
- Delete: `src/tests/integration/api/test_skill_routes.py`
- Delete: `src/tests/integration/flow/test_audit_and_degradation.py`
- Delete: `src/tests/integration/flow/test_full_mvp_contract.py`
- Delete: `src/tests/integration/flow/test_high_risk_and_permission.py`
- Delete: `src/tests/integration/flow/test_intent_routing.py`
- Delete: `src/tests/integration/flow/test_knowledge_extension_runtime.py`
- Delete: `src/tests/integration/flow/test_langgraph_e2e_flow.py`
- Delete: `src/tests/integration/flow/test_pre_discharge_qc_flow.py`
- Delete: `src/tests/integration/flow/test_runtime_execution_loop.py`
- Delete: `src/tests/integration/flow/test_security_boundaries.py`
- Delete: `src/tests/integration/flow/test_settlement_exception_flow.py`
- Delete: `src/tests/integration/flow/test_skill_intent_matching.py`
- Delete: `src/tests/integration/flow/test_skill_mention.py`
- Delete: `src/tests/performance/scenarios/business_api.py`
- Modify: `src/tests/performance/locustfile.py`
- Modify: `src/tests/unit/runtime/intent/test_context_planner.py`
- Modify: `src/tests/unit/runtime/intent/test_intent_models.py`
- Modify: `src/tests/unit/runtime/memory/test_memory_manager.py`
- Modify: `src/tests/unit/runtime/reasoning/test_reasoning_manager.py`
- Modify: `src/tests/unit/model_service/test_gateway.py`
- Modify: `src/tests/unit/model_service/test_router.py`
- Modify: `src/tests/unit/model_service/test_governance.py`
- Modify: `src/tests/unit/model_service/test_governance_import.py`
- Modify: `src/tests/unit/model_service/test_governance_service.py`
- Modify: `src/tests/integration/api/test_model_governance_api.py`
- Modify: `src/tests/integration/flow/test_model_governance_management_flow.py`
- Modify: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
- Modify: `src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py`

- [ ] **Step 1: 删除只验证退役模块和 404 旧入口的测试**

删除清单中的完整测试文件，不把它们迁移为新的 Policy QA 行为。

- [ ] **Step 2: 更新仍有效测试中的样例与断言**

- Context Planner 只使用 `policy_qa_fee_decomposition`。
- Memory/Reasoning 的示例 intent 改为 `policy_qa_fee_decomposition`。
- ModelGateway/Router 的示例 scene 改为 `policy_qa`。
- 模型治理断言删除四个退役 prompt asset。
- 三个 Policy QA 测试文件删除 `PolicyQAOrchestrator` 专属测试块，保留公开契约、真实结算、结构化检索和 Skill 测试。

- [ ] **Step 3: 从 Locust 入口删除旧 BusinessAPIUser**

```python
from scenarios.policy_qa_api import PolicyQAAPIUser

__all__ = [
    "KnowledgeAPIUser",
    "McpAPIUser",
    "ModelAPIUser",
    "PolicyQAAPIUser",
    "SemanticAlignmentAPIUser",
    "SkillAPIUser",
]
```

- [ ] **Step 4: 运行后端聚焦回归**

Run: `python -m pytest src/tests/unit/runtime src/tests/unit/model_service src/tests/integration/api/test_policy_qa_routes.py src/tests/integration/api/test_model_governance_api.py src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py src/tests/integration/flow/test_model_governance_management_flow.py -q`

Expected: PASS；不存在因已删除模块导致的收集错误。

- [ ] **Step 5: 提交完整旧场景退役单元**

```bash
git add -A src
git commit -m "refactor: 退役旧业务场景"
```

### Task 6: 收口 E2E 与现行文档，包括 PROGRESS

**Files:**
- Delete: `src/tests/e2e/flows/portal/chat-streaming.flow.ts`
- Delete: `src/tests/e2e/flows/portal/chat-ux.flow.ts`
- Delete: `src/tests/e2e/flows/portal/pre-discharge-qc.flow.ts`
- Delete: `src/tests/e2e/flows/portal/settlement-guide.flow.ts`
- Delete: `src/tests/e2e/pages/portal/chat.page.ts`
- Delete: `src/tests/e2e/pages/portal/dashboard.page.ts`
- Delete: `src/tests/e2e/pages/portal/qc.page.ts`
- Delete: `src/tests/e2e/pages/portal/settlement.page.ts`
- Modify: `src/tests/e2e/smoke/portal-smoke.spec.ts`
- Modify: `AGENTS.md`
- Modify: `src/runtime/AGENTS.md`
- Modify: `src/tests/AGENTS.md`
- Modify: `src/apps/portal/AGENTS.md`
- Modify: `docs/steering/架构设计.md`
- Modify: `docs/steering/接口设计文档.md`
- Modify: `docs/steering/原型设计文档.md`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 删除旧 E2E 页面对象和流程**

重写 `portal-smoke.spec.ts`，只检查根路径重定向、`/policy-qa` 可用，以及旧业务 URL 返回 404：

```typescript
test('旧业务路由返回 404', async ({ request }) => {
  for (const path of ['/settlement', '/qc', '/dashboard']) {
    const response = await request.get(path)
    expect(response.status()).toBe(404)
  }
})
```

- [ ] **Step 2: 更新现行说明文档**

所有当前态文档统一写明：

```text
Portal business entry: /policy-qa
Runtime: policy_qa_routes → real settlement provider → settlement_explain_skill
Retired: /chat, settlement exception guidance, pre-discharge QC, scenario_executor, legacy LangGraph
```

历史规格和历史落地记录不批量改写。

- [ ] **Step 3: 更新 `PROGRESS.md` 当前状态**

必须完成以下修改：

- §0 当前焦点改为 Issue #21 Policy QA 唯一入口与 Loop。
- §1 删除“结算异常导办”“出院前质控”“运营看板”领域行和详情，重算总数。
- Policy QA 1.1–1.3 改为现行 `policy_qa_routes → settlement_data_provider → structured_policy_retriever → settlement_explain_skill`。
- Skill 7.2 删除 `skill_registry/engine.py`，改为 Skill assembler。
- §3 删除 `scenario_executor` 架构定位，改为 `runtime_bridge` 横切现行 Policy QA。
- §5 删除“端点迁移 404”债务，因为失效测试已随旧产品退役。
- §6 增加 2026-08-25 旧场景硬退役记录；Loop 完成状态由第二份计划补充。

- [ ] **Step 4: 运行静态残留搜索**

Run: `rg -n "settlement_exception_guidance|pre_discharge_quality_control|pre_discharge_qc|/chat" src AGENTS.md PROGRESS.md docs/steering/架构设计.md docs/steering/接口设计文档.md docs/steering/原型设计文档.md`

Expected: 仅允许历史文档、明确的“已退役”说明及与政策内容本身有关的自然语言；现行源代码、测试和当前态表格无旧业务引用。

- [ ] **Step 5: 提交文档和 E2E 收口**

```bash
git add -A AGENTS.md PROGRESS.md src/runtime/AGENTS.md src/tests/AGENTS.md src/apps/portal/AGENTS.md docs/steering src/tests/e2e
git commit -m "docs: 收口 policy-qa 唯一业务入口"
```

### Task 7: 按仓库顺序验证退役结果

**Files:**
- Modify: `PROGRESS.md`

- [ ] **Step 1: T1 单元测试**

Run: `python -m pytest src/tests/unit -q`

Expected: PASS；如有环境性预存失败，记录精确用例和与本变更无关的证据，不跳过聚焦测试。

- [ ] **Step 2: T2a API 测试**

Run: `python -m pytest src/tests/integration/api -q`

Expected: PASS；旧 API 404 契约通过。

- [ ] **Step 3: T2b Flow 测试**

Run: `python -m pytest src/tests/integration/flow -q`

Expected: PASS；仅保留现行 Policy QA、治理和知识链路。

- [ ] **Step 4: Portal 测试和构建**

```bash
cd src/apps/portal
npm test
npx tsc --noEmit
npm run lint
npm run build
```

Expected: 全部退出码 0，构建产物不包含 `/settlement`、`/qc`、`/dashboard`。

- [ ] **Step 5: 将真实验证数量写回 `PROGRESS.md`**

逐条抄录 Step 1–4 的 pytest/Vitest 通过数和四个前端命令退出状态；不得用预计数字或省略号。记录中必须同时写明旧 API 与 `/settlement`、`/qc`、`/dashboard` 的 404 结果。

- [ ] **Step 6: 提交验证证据**

```bash
git add PROGRESS.md
git commit -m "docs: 记录旧场景退役验证证据"
```
