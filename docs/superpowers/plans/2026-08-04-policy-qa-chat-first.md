# Policy QA Chat-first Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** 将 Portal `/policy-qa` 重构为单列、连续追问的 Chat-first 产品，并把公开结果契约从患者/院端双视角收敛为一个可追溯的院端答案。

**Architecture:** 保留现有政策检索、结算核对、会话锚点和完整 SSE 帧解析；在 Skill、Runtime、API、前端映射四层统一使用 `answer`。内部 SQL/表字段/trace 继续写审计，不进入公开 SSE result。前端以单一阅读轴组合答案、查证摘要、计算折叠区、政策来源 Dialog 和 Composer，不展示常驻步骤链或推理链。

**Tech Stack:** Python 3.12、FastAPI、Pydantic、pytest、Next.js 16、React 19、TypeScript、Tailwind CSS 4、Vitest、Testing Library、Playwright、Locust。

---

## 开始前约束

- 工作目录固定为 `D:\project\hospital_medical_insurance_agent\.worktrees\policy-qa-chat-first`。
- 风险等级为 R4：设计稿已人工通过；前后端必须同批发布，不保留 `patient_view`、`office_view`、`settlement_evidence` 兼容字段。
- 不修改政策检索算法、费用计算规则、模型路由、权限和风控。
- 每次遇到实现缺陷，先补失败测试再修复。
- 最终验证严格按 T1 单元 → T2a API → T2b Flow；三层通过后才执行 T3 性能与 T4 E2E。
- `.codegraph/` 不在 worktree 中；实现时如需再次定位代码，先确认是否已生成 worktree 本地索引，否则按仓库规则回退到 `rg`。

## 目标公开契约

```json
{
  "answer": "本次统筹自付为 4,962.67 元……",
  "answer_status": "complete",
  "case_context": {
    "deductible": 650.0,
    "basic_pooling_payment": 91759.51,
    "basic_pooling_self_pay": 4962.67,
    "large_amount_payment": 53631.71,
    "large_amount_self_pay": 13407.93,
    "personal_total_pay": 43694.67
  },
  "calculation_steps": [],
  "definition": null,
  "warnings": [],
  "policy_evidence": [],
  "citations": [],
  "uncertainties": [],
  "verification_summary": {
    "settlement_checked": true,
    "calculation_checked": true,
    "policy_count": 0,
    "message": "已核对当前结算单；费用总览未使用单项政策规则。"
  }
}
```

禁止字段：`patient_view`、`office_view`、`settlement_evidence`、`query_trace`、`trace_events`、`reasoning_steps`、数据库表名、数据库字段名和 SQL profile。

## Task 1: 把费用解释 Skill 收敛为单答案

**Files:**

- Modify: `skills/settlement_explain_skill/tests/test_strategies.py`
- Modify: `skills/settlement_explain_skill/strategies/base.py`
- Modify: `skills/settlement_explain_skill/assembler.py`
- Modify: `skills/settlement_explain_skill/strategies/{pooling_self_pay,deductible,large_amount_self_pay,pooling_payment,personal_total_pay,out_of_scope}/strategy.py`
- Rename: 六个策略目录下的 `patient_template.yaml` → `answer_template.yaml`
- Modify: `skills/settlement_explain_skill/scripts/validate_skill_result.py`
- Modify: `skills/settlement_explain_skill/validators.yaml`
- Modify: `skills/settlement_explain_skill/schemas/output.schema.json`
- Delete: `skills/settlement_explain_skill/templates/office_view.md`
- Rename: `skills/settlement_explain_skill/templates/patient_view.md` → `answer.md`
- Delete: `skills/settlement_explain_skill/explanation_templates.yaml`
- Modify: `skills/settlement_explain_skill/SKILL.md`
- Modify: `skills/settlement_explain_skill/README.md`
- Modify: `skills/settlement_explain_skill/references/answer_quality_standard.md`
- Modify: `skills/AGENTS.md`
- Modify: `src/skill_infra/AGENTS.md`

### Step 1: 写失败的单答案测试

在 `test_strategies.py` 中把七方法契约改为六方法契约，并对所有策略固定新输出：

```python
def test_all_strategies_have_single_answer_contract():
    required_methods = [
        "build_definition",
        "build_policy_queries",
        "build_answer",
        "build_calculation_trace",
        "build_warnings",
        "build_completeness",
    ]
    for name in list_strategies():
        strategy = get_strategy(name)
        for method in required_methods:
            assert callable(getattr(strategy, method))
        assert not hasattr(strategy, "build_patient_answer")
        assert not hasattr(strategy, "build_office_answer")


def test_all_strategies_execute_with_one_answer(settlement_context, mock_evidence):
    for name in list_strategies():
        result = get_strategy(name).execute(
            settlement_context,
            mock_evidence,
            "full_policy_matched",
        )
        assert result.answer
        assert not hasattr(result, "patient_answer")
        assert not hasattr(result, "office_answer")
```

在同文件增加 schema 断言：

```python
def test_output_schema_requires_answer_only():
    import json
    from pathlib import Path

    schema_path = Path(__file__).parents[1] / "schemas" / "output.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = set(schema["required"])
    properties = set(schema["properties"])
    assert "answer" in required
    assert "patient_answer" not in required | properties
    assert "office_answer" not in required | properties
```

Run: `python -m pytest skills/settlement_explain_skill/tests/test_strategies.py -q`

Expected: FAIL，旧策略仍暴露双答案。

### Step 2: 修改 Skill 核心契约

目标结构：

```python
@dataclass
class StrategyResult:
    definition: dict
    answer: str
    calculation_trace: dict
    policy_queries: list[Any]
    warnings: list[str]
    completeness: dict
    target_fee_item: str = "pooling_self_pay"
    target_field: str = "basic_pooling_self_pay"


@dataclass
class SkillResult:
    answer: str
    calculation_trace: dict
    ratio_explanation: dict = None
    explanation_completeness: dict = None
    warnings: list[str] = None
    definition: dict = None
    policy_status: str = "no_policy_matched"
    policy_status_message: str = ""
    target_fee_item: str = "pooling_self_pay"
    target_field: str = "basic_pooling_self_pay"
    llm_readable_context: str = ""
```

在 `BaseFeeStrategy` 中只保留 `build_answer()`，`execute()` 只调用一次。六个策略将现有患者版正文原样迁入 `build_answer()`；删除所有 `build_office_answer()`，不得把表名、字段名拼回单答案。所有 YAML 加载改为 `answer_template.yaml`。

`validate_skill_result.py` 将 `validate_patient_answer()` 重命名为 `validate_answer()`，只校验 `result["answer"]`；删除“双答案金额一致性”规则。`validators.yaml` 的键改为 `required_answer_contains` 和 `required_answer_contains_when_complete`。

`output.schema.json` 的关键部分改为：

```json
{
  "required": [
    "skill_id",
    "target_fee_item",
    "data_source",
    "mock_used",
    "can_answer",
    "answer",
    "trace_events"
  ],
  "properties": {
    "answer": {
      "type": "string",
      "description": "面向当前院端经办角色的单一自然语言解释"
    }
  }
}
```

同步 Skill 文档和两份 Skill 架构说明，全文不得再把患者版/医保办版描述为输出能力。

### Step 3: 运行 Skill 单元测试

Run: `python -m pytest skills/settlement_explain_skill/tests -q`

Expected: PASS。

### Step 4: 提交

```powershell
git add skills src/skill_infra/AGENTS.md
git commit -m "refactor: 收敛费用解释 skill 为单答案"
```

## Task 2: 移除 Runtime 双视角模型与生成链

**Files:**

- Modify: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`
- Modify: `src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py`
- Modify: `src/runtime/policy_qa/models.py`
- Modify: `src/runtime/policy_qa/explanation_generator.py`
- Modify: `src/runtime/policy_qa/orchestrator.py`
- Modify: `src/runtime/policy_qa/runtime_bridge.py`
- Modify: `src/runtime/policy_qa/persistence.py`
- Modify: `src/runtime/policy_qa/history_service.py`
- Modify: `src/runtime/scenario_executor.py`
- Modify: `skills/settlement_explain_skill/scripts/build_trace_event.py`

### Step 1: 写失败的 Runtime 测试

在 `test_policy_qa.py` 增加：

```python
@pytest.mark.asyncio
async def test_explanation_generator_returns_one_answer():
    from src.runtime.policy_qa.models import ExplanationContext

    generator = ExplanationGenerator(model_gateway=None)
    answer = await generator.generate_answer(ExplanationContext())
    assert isinstance(answer, str)
    assert answer
    assert not hasattr(generator, "generate_dual_views")


def test_policy_qa_response_has_single_answer():
    response = PolicyQAResponse(
        step="generate_explanation",
        status="done",
        answer="已完成解释",
        answer_status="complete",
    )
    assert response.answer == "已完成解释"
    assert response.answer_status == "complete"
    assert not hasattr(response, "patient_view")
    assert not hasattr(response, "office_view")
```

把 Flow 末尾契约改为：

```python
assert explanation_done.answer
assert explanation_done.answer_status == "complete"
assert not hasattr(explanation_done, "patient_view")
assert not hasattr(explanation_done, "office_view")
```

Run: `python -m pytest src/tests/unit/runtime/policy_qa/test_policy_qa.py -q -k "single_answer or returns_one_answer"`

Expected: FAIL。

### Step 2: 实现单答案 Runtime

`PolicyQAResponse` 改为：

```python
@dataclass
class PolicyQAResponse:
    step: str = ""
    status: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    public_detail: dict[str, Any] = field(default_factory=dict)
    chunk: str = ""
    error: str = ""
    public_message: str = ""
    answer: str = ""
    answer_status: str = "unavailable"
    policy_cards: list[dict[str, Any]] = field(default_factory=list)
    trace_event: dict[str, Any] | None = None
```

`ExplanationGenerator.generate_answer()` 复用当前价值门控、患者版模板和模型降级逻辑，只返回一个字符串；删除 `dual` prompt、`_parse_dual_response()` 和院端来源拼接。`PolicyQAOrchestrator` 全部变量统一为 `answer`，输出校验只检查单答案、政策引用/不确定性和禁止内容。

步骤名统一为 `answer_generation`；`runtime_bridge.py`、`persistence.py`、`build_trace_event.py` 同步更新映射。`history_service.py` 不再把双视角字段列为历史详情字段。`scenario_executor.py` 从 `response.answer` 累积结果。

### Step 3: 运行 Runtime 单元测试

Run: `python -m pytest src/tests/unit/runtime/policy_qa -q`

Expected: PASS。Flow 测试此时只修改不执行，留到 Task 3 完成 API 后按强制顺序执行。

### Step 4: 提交

```powershell
git add src/runtime src/tests/unit/runtime/policy_qa src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py skills/settlement_explain_skill/scripts/build_trace_event.py
git commit -m "refactor: 移除 policy qa 双视角运行时"
```

## Task 3: 建立安全的 Policy QA 公开结果契约

**Files:**

- Create: `src/runtime/policy_qa/public_contract.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
- Modify: `src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py`

### Step 1: 写失败的 API 契约测试

在 API 测试中添加 SSE 解析帮助函数和断言：

```python
def _sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event_name = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if event_name and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


def test_stream_result_uses_single_safe_answer_contract(client):
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "统筹自付为什么这么多？", "settlement_id": "1671213"},
    )
    assert response.status_code == 200
    result_event = next(data for event, data in _sse_events(response.text) if event == "result")
    result = result_event["result"]
    assert result["answer"]
    assert result["answer_status"] in {"complete", "partial", "unavailable"}
    assert set(result).isdisjoint(
        {"patient_view", "office_view", "settlement_evidence", "query_trace", "trace_events", "reasoning_steps"}
    )
    assert result["citations"] or result["uncertainties"]
```

Run: `python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q -k "single_safe_answer_contract"`

Expected: FAIL。

### Step 2: 定义 Pydantic 公开模型

`public_contract.py` 定义：

```python
from typing import Literal

from pydantic import BaseModel, Field


class PolicyCitation(BaseModel):
    title: str
    excerpt: str


class VerificationSummary(BaseModel):
    settlement_checked: bool
    calculation_checked: bool
    policy_count: int = Field(ge=0)
    message: str


class PolicyQAPublicResult(BaseModel):
    answer: str
    answer_status: Literal["complete", "partial", "unavailable"]
    case_context: dict[str, str | int | float | bool | None] | None = None
    calculation_steps: list[dict[str, str]] = Field(default_factory=list)
    definition: dict[str, str | list[str]] | None = None
    warnings: list[str] = Field(default_factory=list)
    policy_evidence: list[dict[str, str | float | None]] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    verification_summary: VerificationSummary
```

路由层用一个私有 builder 将 Skill/overview 结果转换为该模型。状态规则固定为：可回答且政策完整为 `complete`；有真实金额但政策不完整为 `partial`；不能可靠回答为 `unavailable`。政策证据转换为 `citations`；没有引用时必须把原因放入 `uncertainties`。

### Step 3: 清理 stream 与 REST 公开输出

`_policy_qa_stream()` 只发送：

```python
public_result = _build_public_result(
    answer=result_answer,
    can_answer=trace_can_answer,
    partial_answer=trace_partial_answer,
    policy_status=policy_status,
    policy_evidence=result_policy_evidence,
    calculation_steps=_calc_steps,
    definition=_definition,
    warnings=_warnings,
    case_context=_case_context,
)
yield _sse_event("result", {"result": public_result.model_dump(mode="json")})
```

删除公开 `settlement_evidence`、`answer_mode`、`run_id`、`selected_skill_id`、`trace_events` 和 `reasoning_steps`。任务持久化改为 `answer_excerpt`、`answer_status`、证据数量和内部 run id；SQL/表字段仍只留在已有内部 trace/audit 记录。

`runtime_bridge.record_step()` 仍可在服务端维护推理状态，但 route 不再向 SSE 转发 `reasoning_step`；只允许 `context_need`、`memory_update`、`step`、`result`、`error`、`done` 等公开事件。实现时在 yield 边界显式过滤：

```python
for event_type, payload in runtime_bridge.record_step(
    session_id=session_id,
    step="answer_assembly",
    detail={},
):
    if event_type == "reasoning_step":
        continue
    yield _sse_event(event_type, _sanitize(payload))
```

`/settlement-explanation` 暂时保留路径以控制本次变更范围，但改为返回同一个 `PolicyQAPublicResult`，不返回 `query_trace`、表名或双答案。它不再被 Portal 调用，并在接口文档中标注为兼容入口。

overview builder 只生成 `answer`，删除含 `yb_zyfdxx` / `yb_dyxxzy` 的院端文本。

### Step 4: 按顺序验证 API 与 Flow

Run: `python -m pytest src/tests/unit/runtime/policy_qa skills/settlement_explain_skill/tests -q`

Expected: PASS。

Run: `python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q`

Expected: PASS。

Run: `python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py -q`

Expected: PASS。

### Step 5: 提交

```powershell
git add src/runtime/api/policy_qa_routes.py src/runtime/policy_qa/public_contract.py src/tests/integration
git commit -m "refactor: 统一 policy qa 公开回答契约"
```

## Task 4: 前端只消费安全单答案结果

**Files:**

- Create: `src/apps/portal/src/lib/policy-qa-stream.ts`
- Modify: `src/apps/portal/src/lib/policy-qa-session.ts`
- Modify: `src/apps/portal/src/lib/use-policy-qa-stream.ts`
- Modify: `src/apps/portal/src/tests/lib/policy-qa-session.test.ts`
- Modify: `src/apps/portal/src/tests/lib/use-policy-qa-stream.test.tsx`

### Step 1: 写失败的解析与映射测试

在 `policy-qa-session.test.ts` 固定现有正确的完整帧行为，并新增防泄漏测试：

```typescript
it('parses a complete multiline SSE frame', () => {
  const event = parseSseBlock('event: result\ndata: {"result":\ndata: {"answer":"已核对"}}')
  expect(event).toEqual({ event: 'result', data: { result: { answer: '已核对' } } })
})

it('recursively removes non-public fields', () => {
  expect(sanitizePublicPayload({
    answer: '安全答案',
    patient_view: '旧字段',
    nested: { query_trace: { tables: ['yb_zyfdxx'] }, title: '政策依据' },
  })).toEqual({ answer: '安全答案', nested: { title: '政策依据' } })
})
```

在 hook 测试把 result fixture 改成 `answer`，并断言消息不再有 `officeView`/`reasoning`：

```typescript
['result', {
  result: {
    answer: '本次住院统筹自付 4962.67 元。',
    answer_status: 'complete',
    citations: [{ title: '住院支付政策', excerpt: '退休人员按规定比例支付。' }],
    uncertainties: [],
    verification_summary: {
      settlement_checked: true,
      calculation_checked: true,
      policy_count: 1,
      message: '已核对当前结算单与 1 条政策依据。',
    },
  },
}]
```

Run: `npm test -- src/tests/lib/policy-qa-session.test.ts src/tests/lib/use-policy-qa-stream.test.tsx`

Expected: FAIL。

### Step 2: 拆出纯 SSE 契约模块

`policy-qa-stream.ts` 包含：完整帧 parser、递归过滤、snake_case 映射和前端类型。禁止字段集合固定为：

```typescript
const FORBIDDEN_PUBLIC_KEYS = new Set([
  'patient_view',
  'office_view',
  'settlement_evidence',
  'query_trace',
  'trace_events',
  'reasoning_steps',
  'sql_profile',
  'tables',
])
```

公开前端结果类型：

```typescript
export interface PolicyQAResult {
  answer: string
  answerStatus: 'complete' | 'partial' | 'unavailable'
  caseContext?: PolicyQACaseContext
  calculationSteps: Array<{ stepName: string; description: string }>
  definition?: { name: string; plainText: string; excludes: string[] }
  warnings: string[]
  citations: Array<{ title: string; excerpt: string }>
  uncertainties: string[]
  verificationSummary: {
    settlementChecked: boolean
    calculationChecked: boolean
    policyCount: number
    message: string
  }
}
```

`PolicyQAChatMessage` 删除 `officeView` 和 `reasoning`，增加 `answerStatus`、`citations`、`uncertainties`、`verificationSummary`。`usePolicyQAStream` 在分发任何事件前先调用 `sanitizePublicPayload()`；result 分支只使用 `result.answer`，不得回退到旧字段。`reasoning_step` 事件忽略，不进入 React state；`step` 事件只保留最新 `public_message` 供执行中状态显示。

### Step 3: 运行前端逻辑测试

Run: `npm test -- src/tests/lib/policy-qa-session.test.ts src/tests/lib/use-policy-qa-stream.test.tsx`

Expected: PASS。

### Step 4: 提交

```powershell
git add src/apps/portal/src/lib src/apps/portal/src/tests/lib
git commit -m "refactor: 切换 portal 到单答案流契约"
```

## Task 5: 组件化 Chat-first 页面

**Files:**

- Create: `src/apps/portal/src/components/policy-qa/policy-qa-empty-state.tsx`
- Create: `src/apps/portal/src/components/policy-qa/policy-message-list.tsx`
- Create: `src/apps/portal/src/components/policy-qa/policy-agent-answer.tsx`
- Create: `src/apps/portal/src/components/policy-qa/verification-summary.tsx`
- Create: `src/apps/portal/src/components/policy-qa/calculation-disclosure.tsx`
- Create: `src/apps/portal/src/components/policy-qa/policy-sources-dialog.tsx`
- Create: `src/apps/portal/src/components/policy-qa/policy-composer.tsx`
- Create: `src/apps/portal/src/components/policy-qa/policy-conversation.tsx`
- Modify: `src/apps/portal/src/components/policy-qa/policy-qa-workspace.tsx`
- Modify: `src/apps/portal/app/policy-qa/page.tsx`
- Create: `src/apps/portal/src/tests/components/policy-agent-answer.test.tsx`
- Create: `src/apps/portal/src/tests/components/policy-composer.test.tsx`
- Create: `src/apps/portal/src/tests/components/policy-qa-workspace.test.tsx`

### Step 1: 写失败的组件测试

核心验收测试：

```typescript
it('renders one answer with progressive disclosure', async () => {
  render(<PolicyAgentAnswer message={completeMessage} />)
  expect(screen.getByText('本次统筹自付为 4,962.67 元。')).toBeInTheDocument()
  expect(screen.getByText('已核对当前结算单与 2 条政策依据。')).toBeInTheDocument()
  expect(screen.queryByText('本轮执行链路')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: '查看 2 条政策来源' })).toBeInTheDocument()
  expect(screen.getByText('计算依据')).toBeInTheDocument()
})


it('shows settlement context inside the composer', () => {
  render(<PolicyComposer settlementId="1671213" value="" onChange={vi.fn()} onSend={vi.fn()} />)
  expect(screen.getByText('结算单 1671213')).toBeInTheDocument()
  expect(screen.getByRole('textbox')).toHaveAttribute('placeholder', '继续追问当前结算单…')
})


it('uses a single centered reading column', () => {
  const { container } = render(<PolicyQAWorkspace />)
  expect(container.querySelector('[data-testid="policy-qa-reading-column"]')).toHaveClass('max-w-[840px]')
  expect(screen.queryByText('会话记忆')).not.toBeInTheDocument()
  expect(screen.queryByText('本轮执行链路')).not.toBeInTheDocument()
})
```

Run: `npm test -- src/tests/components/policy-agent-answer.test.tsx src/tests/components/policy-composer.test.tsx src/tests/components/policy-qa-workspace.test.tsx`

Expected: FAIL。

### Step 2: 实现单列页面结构

`page.tsx` 只保留深色全局导航之下的浅色内容区，删除网格、光斑和 dashboard 式大容器。阅读列：

```tsx
<main className="min-h-[calc(100vh-64px)] bg-slate-50/70">
  <div
    data-testid="policy-qa-reading-column"
    className="mx-auto flex w-full max-w-[840px] flex-col px-6 py-8"
  >
    <PolicyQAWorkspace />
  </div>
</main>
```

`PolicyConversation` 顺序固定为：轻量标题 → 空态或消息列表 → 当前公开状态 → Composer → 参考声明。执行中只显示最新 `publicMessage`：

```tsx
{isStreaming && currentPublicMessage ? (
  <div role="status" className="flex items-center gap-2 py-3 text-sm text-slate-500">
    <LoaderCircle className="size-4 animate-spin" aria-hidden />
    <span>{currentPublicMessage}</span>
  </div>
) : null}
```

`PolicyAgentAnswer` 先展示 `message.content`，其后按顺序组合 `VerificationSummary`、`CalculationDisclosure`、`PolicySourcesDialog`、`uncertainties` 和建议追问。不得渲染 reasoning、内部步骤、表名或结算来源卡。

`PolicySourcesDialog` 使用已有 `@/components/ui/dialog`，只展示政策标题和摘录。`CalculationDisclosure` 使用原生 `<details>`，默认收起。`PolicyComposer` 在输入框上方显示结算单 context chip，并保留 `@换结算`、`@新会话` 逻辑。

### Step 3: 运行组件与全量 Portal 单元测试

Run: `npm test -- src/tests/components/policy-agent-answer.test.tsx src/tests/components/policy-composer.test.tsx src/tests/components/policy-qa-workspace.test.tsx`

Expected: PASS。

Run: `npm test`

Expected: PASS。

### Step 4: 提交

```powershell
git add src/apps/portal/app/policy-qa src/apps/portal/src/components/policy-qa src/apps/portal/src/tests/components
git commit -m "feat: 重构 policy qa 为 chat-first 页面"
```

## Task 6: 删除旧展示路径和监控式组件

**Files:**

- Delete: `src/apps/portal/src/components/policy-qa-chat.tsx`
- Delete: `src/apps/portal/src/components/settlement-explanation-page.tsx`
- Delete: `src/apps/portal/src/lib/settlement-explanation-types.ts`
- Delete: `src/apps/portal/src/lib/settlement-explanation-mock.ts`
- Delete: `src/apps/portal/src/lib/dedup.ts`
- Delete: `src/apps/portal/src/tests/e2e/settlement-explanation.spec.ts`
- Delete: `src/apps/portal/src/components/policy-qa/chat-stream.tsx`
- Delete: `src/apps/portal/src/components/policy-qa/session-anchor-bar.tsx`
- Delete: `src/apps/portal/src/components/policy-qa/reasoning-chain-collapsible.tsx`
- Delete: `src/apps/portal/src/components/policy-qa/memory-panel.tsx`
- Delete: `src/apps/portal/src/tests/components/session-anchor-bar.test.tsx`
- Delete: `src/apps/portal/src/tests/components/reasoning-chain-collapsible.test.tsx`
- Delete: `src/apps/portal/src/tests/components/memory-panel.test.tsx`

### Step 1: 固定“无旧路径引用”检查

Run:

```powershell
rg -n "PolicyQAChat|SettlementExplanationPage|patient_view|office_view|settlement_evidence|ReasoningChainCollapsible|SessionAnchorBar|MemoryPanel" src/apps/portal
```

Expected: 当前有命中。

### Step 2: 删除文件并清理 import/comment

删除上述仅服务于旧双视角、结算来源大页和监控式 UI 的文件。不要删除通用 `thinking-chain.tsx`，它仍被 Portal 其他 Chat 页面使用。

### Step 3: 验证零引用、类型和构建

Run:

```powershell
rg -n "PolicyQAChat|SettlementExplanationPage|patient_view|office_view|settlement_evidence|ReasoningChainCollapsible|SessionAnchorBar|MemoryPanel" src/apps/portal
```

Expected: 无命中，`rg` 退出码为 1。

Run: `npm test`

Expected: PASS。

Run: `npm run lint`

Expected: PASS，无新增错误。

Run: `npm run build`

Expected: PASS。

### Step 4: 提交

```powershell
git add -A src/apps/portal
git commit -m "refactor: 删除 policy qa 旧双视角展示"
```

## Task 7: 同步接口、原型和进度文档

**Files:**

- Modify: `docs/steering/接口设计文档.md`
- Modify: `docs/steering/原型设计文档.md`
- Modify: `PROGRESS.md`
- Modify: `docs/superpowers/specs/2026-08-04-policy-qa-chat-first-design.md`

### Step 1: 更新文档契约

接口文档必须明确：

```text
result.answer              单一院端答案
result.answer_status       complete | partial | unavailable
result.citations           可展示的政策依据
result.uncertainties       无法形成可靠结论时的明确不确定性
result.verification_summary 结算、计算与政策核对摘要
```

标注 `patient_view`、`office_view`、`settlement_evidence` 已删除，前后端需同步发布；`/settlement-explanation` 是返回同一安全契约的兼容入口，不再供 Portal 页面调用。

原型文档更新为 1280–1920 桌面端、单列 840px、无左右栏、无常驻步骤链。`PROGRESS.md` 追加本次最小可验证单元、实际验证结果和变更日志。此任务不修改 `policy-knowledge/`，因此不触发政策知识治理需求迭代记录。

### Step 2: 文档一致性检查

Run:

```powershell
rg -n "patient_view|office_view|settlement_evidence|双视角" docs/steering/接口设计文档.md docs/steering/原型设计文档.md PROGRESS.md
```

Expected: 仅允许出现在“已删除/迁移说明”上下文。

### Step 3: 提交

```powershell
git add docs PROGRESS.md
git commit -m "docs: 同步 policy qa chat-first 契约"
```

## Task 8: 增加 R4 性能与 E2E 证据

**Files:**

- Create: `src/tests/performance/scenarios/policy_qa_api.py`
- Modify: `src/tests/performance/locustfile.py`
- Create: `src/tests/e2e/pages/portal/policy-qa.page.ts`
- Create: `src/tests/e2e/flows/portal/policy-qa.flow.ts`
- Modify: `src/tests/e2e/smoke/portal-smoke.spec.ts`
- Modify: `src/apps/portal/src/components/policy-qa/policy-composer.tsx`
- Modify: `src/apps/portal/src/components/policy-qa/policy-agent-answer.tsx`
- Modify: `src/apps/portal/src/components/policy-qa/policy-sources-dialog.tsx`

### Step 1: 添加稳定的 E2E 选择器

只在真实用户可感知的边界增加：

```tsx
data-testid="policy-qa-composer"
data-testid="policy-qa-answer"
data-testid="policy-qa-verification"
data-testid="policy-qa-sources"
data-testid="policy-qa-stream-done"
```

### Step 2: 新增 Page Object 与 Flow

`policy-qa.page.ts` 封装：访问 `/policy-qa`、输入问题、发送、等待 done、打开来源、读取答案。Flow 覆盖：空态与示例问题、结算 context chip、真实 SSE 单答案、政策来源 Dialog、计算折叠区、连续追问、partial/unavailable 提示。

Page Object 使用完整实现：

```typescript
import { type Locator, type Page } from '@playwright/test'

import { BasePage } from '../base.page'

export class PolicyQAPage extends BasePage {
  readonly composer: Locator
  readonly sendButton: Locator
  readonly answer: Locator
  readonly settlementChip: Locator
  readonly sourcesButton: Locator
  readonly sourcesDialog: Locator
  readonly doneIndicator: Locator

  constructor(page: Page) {
    super(page, 'http://127.0.0.1:3000')
    this.composer = page.locator('[data-testid="policy-qa-composer"] textarea')
    this.sendButton = page.getByRole('button', { name: '发送' })
    this.answer = page.locator('[data-testid="policy-qa-answer"]')
    this.settlementChip = page.getByText(/结算单 \d+/)
    this.sourcesButton = page.getByRole('button', { name: /查看 \d+ 条政策来源/ })
    this.sourcesDialog = page.locator('[data-testid="policy-qa-sources"]')
    this.doneIndicator = page.locator('[data-testid="policy-qa-stream-done"]')
  }

  async goto(): Promise<void> {
    await super.goto('/policy-qa')
  }

  async ask(question: string): Promise<void> {
    await this.composer.fill(question)
    await this.sendButton.click()
    await this.doneIndicator.waitFor({ state: 'visible', timeout: 60_000 })
  }

  async openSources(): Promise<void> {
    await this.sourcesButton.last().click()
  }
}
```

核心 Flow 断言：

```typescript
test('单列政策问答支持连续追问和政策来源', async ({ page }) => {
  const policyQA = new PolicyQAPage(page)
  await policyQA.goto()
  await policyQA.ask('查询住院费用，结算单 1671213')
  await expect(policyQA.answer).toBeVisible()
  await expect(policyQA.settlementChip).toContainText('1671213')
  await policyQA.ask('统筹自付为什么这么多？')
  await expect(policyQA.answer.last()).toContainText('统筹自付')
  await policyQA.openSources()
  await expect(policyQA.sourcesDialog).toBeVisible()
  await expect(page.getByText('本轮执行链路')).toHaveCount(0)
  await expect(page.getByText('结算数据来源')).toHaveCount(0)
})
```

### Step 3: 新增 Policy QA 性能场景

`policy_qa_api.py` 只打真实 `/policy-qa/stream`，完整消费流并确认 `done`：

```python
from locust import HttpUser, between, tag, task

from src.tests.performance.config import API_PREFIX


class PolicyQAAPIUser(HttpUser):
    wait_time = between(1, 2)

    @task
    @tag("policy-qa", "stream")
    def policy_qa_stream(self):
        with self.client.post(
            f"{API_PREFIX}/policy-qa/stream",
            json={
                "question": "查询住院费用构成",
                "settlement_id": "1671213",
            },
            catch_response=True,
            stream=True,
            name="/policy-qa/stream",
        ) as response:
            saw_done = any(line.startswith(b"event: done") for line in response.iter_lines())
            if response.status_code != 200 or not saw_done:
                response.failure("policy qa stream did not finish with done")
```

### Step 4: 提交测试资产

```powershell
git add src/tests src/apps/portal/src/components/policy-qa
git commit -m "test: 覆盖 policy qa chat-first 全链路"
```

## Task 9: 严格验证与交付证据

### Step 1: T1 单元测试

Run:

```powershell
python -m pytest skills/settlement_explain_skill/tests src/tests/unit/runtime/policy_qa -q
```

Expected: PASS。失败则停止，不执行 API。

Run:

```powershell
Set-Location src/apps/portal
npm test
npm run lint
npm run build
```

Expected: 全部 PASS；失败则停止。

### Step 2: T2a API 测试

Run:

```powershell
Set-Location D:\project\hospital_medical_insurance_agent\.worktrees\policy-qa-chat-first
python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q
```

Expected: PASS。失败则停止，不执行 Flow。

### Step 3: T2b Flow 测试

Run:

```powershell
python -m pytest src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py src/tests/integration/flow/test_policy_qa_scalar_retrieval_baseline.py src/tests/integration/flow/test_policy_qa_vector_retrieval_baseline.py -q
```

Expected: PASS。

### Step 4: 全仓禁止字段审计

Run:

```powershell
rg -n "patient_view|office_view|settlement_evidence|generate_dual_views|build_office_answer" src/runtime src/apps/portal skills/settlement_explain_skill src/tests
```

Expected: 无命中，`rg` 退出码为 1。

再检查公开回答没有数据库实现细节：

```powershell
rg -n "yb_zyfdxx|yb_dyxxzy|sql_profile|tables_queried" src/apps/portal src/runtime/api/policy_qa_routes.py
```

Expected: 路由内部查询上下文可有命中，但公开 result builder、前端组件和测试 fixture 中不得出现。

### Step 5: T3 性能测试

按仓库要求使用脚本启动服务：

```powershell
.\start-servers.ps1
python -m locust -f src/tests/performance/scenarios/policy_qa_api.py --host http://127.0.0.1:8000 --headless --users 10 --spawn-rate 2 --run-time 30s --tags policy-qa
```

Expected: 错误率 ≤ 5%，stream p95 ≤ 3000ms；环境缺少真实 SQL Server 时记录为外部环境阻塞，不伪造通过。

### Step 6: T4 E2E

Run:

```powershell
Set-Location src/tests/e2e
npx playwright test flows/portal/policy-qa.flow.ts smoke/portal-smoke.spec.ts --project=chromium
Set-Location D:\project\hospital_medical_insurance_agent\.worktrees\policy-qa-chat-first
.\stop-servers.ps1
```

Expected: PASS；失败时保留 `test-results/` screenshot/trace 作为证据。

### Step 7: 自查变更与最终提交

Run:

```powershell
git status --short
git diff --check
git log --oneline --decorate -10
```

确认无用户无关文件、无空白错误、无未提交实现。如果最终验证产生文档结果更新：

```powershell
git add PROGRESS.md docs
git commit -m "docs: 记录 policy qa r4 验证结果"
```

## 兼容性与回滚

- 兼容性：这是明确的破坏性契约升级。Portal 与后端同批发布；旧字段不保留。`/settlement-explanation` 路径暂留，但只返回新安全契约。
- 回滚：按提交逆序整体回滚 Task 8 → Task 1；不得只回滚前端或后端一侧。
- 数据：无数据库 schema 或业务数据迁移，回滚不涉及数据恢复。
- 安全：公开响应移除信息，内部审计字段不删除；如审计链出现缺口，停止交付并恢复 Task 3 前状态。

## 实施完成定义

- 页面在 1280–1920px 下保持单列 840px 阅读轴，无左右栏、无常驻步骤链、无数据来源大页。
- 用户可从 Composer 提交首问，结算单作为 context chip 保留，并可连续追问。
- 公开结果只有一个 `answer`，支持 complete/partial/unavailable。
- 政策结论有 citations；无可靠依据时有 uncertainties。
- UI 只展示政策来源，不展示结算表名、字段名或 SQL 路径。
- Skill、Runtime、API、Portal、测试和文档中不存在仍在使用的双视角契约。
- T1 → T2a → T2b 全通过，T3/T4 有实际执行证据或明确外部环境阻塞说明。
