# 门诊部分项目预退费分析 Implementation Plan

> **状态更正（2026-08-31）**：原计划错误地绕过草稿治理直接接入正式运行时，后续实施已撤回。当前只保留 `skill_drafts/` 候选包、适配器契约和隔离核心流程；真实预结算接入、候选评测、人工审批与物化发布须另行执行。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 `/policy-qa/stream` 入口中增加门诊部分项目预退费分析：只接受费用明细唯一标识和拟退数量，只信任院端预结算结果，输出可追溯的退款/补缴分析，并在任何实际退费意图出现时转人工确认。

**Architecture:** 新 Skill 负责确定性校验和解释；`BillingPort` 增加只读预结算能力，默认内存适配器明确返回“未配置”；运行时在现有结算解释流程前分流预退费请求。复用现有 SSE、公开结果、任务闭环、风险控制和 Skill 路由，不新增业务入口、数据库表、前端页面或本地医保待遇重算。

**Tech Stack:** Python 3.12、Pydantic、FastAPI、pytest、现有 SkillLoader/SkillRouter、现有 adapters ports、现有 Policy QA SSE。

---

## 约束与成功标准

- 仅支持门诊原交易的部分项目预退费分析。
- 请求只接收 `fee_detail_id` 与 `refund_quantity`；项目名称、单价、金额均由院端预结算返回。
- 所有金额使用 `Decimal`；不得自行重算医保待遇。
- 官方预结算接受或拒绝都可形成可追溯结果；未配置、瞬时故障和关联校验失败不能伪造答案。
- “立即执行/确认退费/冲正”等写操作意图必须在调用适配器前转为 `waiting_human_confirmation`，并证明适配器调用次数为 0。
- 瞬时故障最多恢复一次；未配置和数据不一致不重试。
- 公开结果继续使用 `PolicyQAPublicResult`，不得扩展任意裸字典字段。
- 完成后严格按单元测试 → API 测试 → Flow 测试验证。

## 文件映射

| 文件 | 操作 | 职责 |
|---|---|---|
| `src/adapters/billing/models.py` | 新建 | 预退费适配器的输入、项目、金额快照、结果和失败类型 |
| `src/adapters/ports/billing.py` | 修改 | 为 `BillingPort` 增加只读 `preview_partial_refund` |
| `src/adapters/billing/in_memory.py` | 修改 | 默认实现明确返回“预结算未配置”，不生成假金额 |
| `skills/outpatient_pre_refund_analysis_skill/*` | 新建 | Skill 清单、说明、schema、确定性 assembler 及测试 |
| `src/runtime/policy_qa/models.py` | 修改 | 增加结构化拟退项目请求模型 |
| `src/runtime/policy_qa/pre_refund_flow.py` | 新建 | 高风险拦截、适配器调用、一次恢复、Skill 组装 |
| `src/runtime/api/policy_qa_routes.py` | 修改 | 依赖注入、请求校验、SSE 分流、公开结果构建 |
| `src/tests/unit/runtime/policy_qa/test_pre_refund_flow.py` | 新建 | 核心流程单元测试 |
| `src/tests/integration/api/test_policy_qa_routes.py` | 修改 | 请求契约、公开结果、高风险分支 API 测试 |
| `src/tests/integration/flow/test_policy_qa_pre_refund_flow.py` | 新建 | 成功、拒绝、降级、恢复、零调用端到端测试 |
| `src/domain/AGENTS.md` | 修改 | 增加统一领域术语 |
| `skills/AGENTS.md` | 修改 | 登记新 Skill |
| `docs/steering/接口设计文档.md` | 修改 | 更新 `/policy-qa/stream` 的可选结构化请求字段 |

## Task 1：建立只读预结算适配器契约

**Files:**

- Create: `src/adapters/billing/models.py`
- Modify: `src/adapters/ports/billing.py`
- Modify: `src/adapters/billing/in_memory.py`
- Test: `src/tests/unit/adapters/test_ports.py`
- Test: `src/tests/unit/adapters/test_adapter_contracts.py`

- [ ] **Step 1：先写失败的端口测试**

在 `test_ports.py` 中增加断言，要求 `BillingPort` 暴露同步只读方法：

```python
def preview_partial_refund(
    self,
    original_trade_no: str,
    items: tuple[PartialRefundItemRequest, ...],
) -> AdapterCallResult: ...
```

测试还应构造 `PartialRefundItemRequest(fee_detail_id="F001", refund_quantity=Decimal("1"))`，证明数量为 `Decimal` 而非浮点数。

- [ ] **Step 2：运行测试并确认失败**

```powershell
uv run python -m pytest src/tests/unit/adapters/test_ports.py -q
```

Expected: FAIL，原因是模型或端口方法尚不存在。

- [ ] **Step 3：实现最小类型模型**

在 `src/adapters/billing/models.py` 中定义冻结 dataclass：

```python
class PreSettlementErrorType(str, Enum):
    NOT_CONFIGURED = "pre_settlement_not_configured"
    UNAVAILABLE = "pre_settlement_unavailable"

@dataclass(frozen=True)
class PartialRefundItemRequest:
    fee_detail_id: str
    refund_quantity: Decimal

@dataclass(frozen=True)
class SettlementAmountSnapshot:
    total_amount: Decimal
    fund_amount: Decimal
    personal_amount: Decimal

@dataclass(frozen=True)
class PreviewedRefundItem:
    fee_detail_id: str
    refund_quantity: Decimal
    refundable_quantity: Decimal
    refund_amount: Decimal

@dataclass(frozen=True)
class PartialRefundPreview:
    accepted: bool
    original_trade_no: str
    response_code: str
    response_message: str
    preview_id: str | None
    source_system: str
    source_reference: str
    items: tuple[PreviewedRefundItem, ...]
    before: SettlementAmountSnapshot | None
    after: SettlementAmountSnapshot | None
```

不引入基类、工厂或配置层；当前只有一个明确契约。

- [ ] **Step 4：扩展端口和默认适配器**

在 `BillingPort` 增加上述方法，返回现有 `AdapterCallResult`。在 `InMemoryBillingAdapter` 中通过 `failed_result` 实现为失败结果：

```python
return failed_result(
    context=context,
    source_system="billing",
    capability="preview_partial_refund",
    error_type=PreSettlementErrorType.NOT_CONFIGURED.value,
    message="院端门诊部分退费预结算接口未配置",
)
```

不得返回演示金额或根据原结算单推算结果。

- [ ] **Step 5：补默认行为契约测试并跑绿**

在 `test_adapter_contracts.py` 断言默认适配器返回 `AdapterCallStatus.FAILED`、`PreSettlementErrorType.NOT_CONFIGURED`，且仍满足 `AdapterCallResult` 契约。

```powershell
uv run python -m pytest src/tests/unit/adapters/test_ports.py src/tests/unit/adapters/test_adapter_contracts.py -q
```

Expected: PASS。

- [ ] **Step 6：提交原子变更**

```powershell
git add src/adapters/billing/models.py src/adapters/ports/billing.py src/adapters/billing/in_memory.py src/tests/unit/adapters/test_ports.py src/tests/unit/adapters/test_adapter_contracts.py
git commit -m "feat: 增加门诊部分退费预结算端口"
```

## Task 2：创建确定性的预退费分析 Skill

**Files:**

- Create: `skills/outpatient_pre_refund_analysis_skill/__init__.py`
- Create: `skills/outpatient_pre_refund_analysis_skill/SKILL.md`
- Create: `skills/outpatient_pre_refund_analysis_skill/skill_manifest.yaml`
- Create: `skills/outpatient_pre_refund_analysis_skill/assembler.py`
- Create: `skills/outpatient_pre_refund_analysis_skill/schemas/input.schema.json`
- Create: `skills/outpatient_pre_refund_analysis_skill/schemas/output.schema.json`
- Create: `skills/outpatient_pre_refund_analysis_skill/templates/analysis.yaml`
- Create: `skills/outpatient_pre_refund_analysis_skill/tests/__init__.py`
- Create: `skills/outpatient_pre_refund_analysis_skill/tests/test_assembler.py`
- Modify: `src/tests/unit/skill_infra/test_skill_loader.py`
- Modify: `src/tests/unit/skill_infra/test_skill_router.py`

- [ ] **Step 1：先写 Skill 发现和路由失败测试**

增加以下期望：

- SkillLoader 可加载 `outpatient_pre_refund_analysis_skill`。
- `business_action == "evaluate"`。
- `business_object == "settlement"`。
- “部分项目预退费分析”“退费试算”路由到新 Skill。
- 现有结算解释问题仍路由到 `settlement_explain_skill`。

```powershell
uv run python -m pytest src/tests/unit/skill_infra/test_skill_loader.py src/tests/unit/skill_infra/test_skill_router.py -q
```

Expected: FAIL，新 Skill 尚不存在。

- [ ] **Step 2：写最小 Skill 包元数据**

`skill_manifest.yaml` 使用已有清单格式，关键字段：

```yaml
id: outpatient_pre_refund_analysis_skill
name: 门诊部分项目预退费分析技能
business_action: evaluate
business_object: settlement
keywords:
  - 预退费
  - 部分项目退费
  - 退费分析
  - 退费试算
required_mcp_servers:
  - billing-pre-settlement
```

`SKILL.md` 明确：只分析官方预结算结果，不执行退费，不做待遇重算；无官方结果时必须说明不可用。

- [ ] **Step 3：运行发现/路由测试并确认通过**

```powershell
uv run python -m pytest src/tests/unit/skill_infra/test_skill_loader.py src/tests/unit/skill_infra/test_skill_router.py -q
```

Expected: PASS。

- [ ] **Step 4：先写 assembler 失败测试**

`test_assembler.py` 覆盖五条核心规则：

1. 官方接受且个人金额减少，输出“预计退还”。
2. 官方接受且个人金额增加，输出“预计补缴”。
3. 官方拒绝仍为可回答结果，包含 `response_code`、原因和官方来源。
4. 返回的交易号、项目 ID 或数量与请求不一致时不可回答。
5. 金额恒等式不成立时不可回答：

```text
before.total - after.total
  == sum(item.refund_amount)
  == (before.fund - after.fund) + (before.personal - after.personal)
```

另加 `refund_quantity > refundable_quantity` 的拒绝测试。

```powershell
uv run python -m pytest skills/outpatient_pre_refund_analysis_skill/tests/test_assembler.py -q
```

Expected: FAIL，assembler 尚不存在。

- [ ] **Step 5：实现最小 assembler**

定义 Pydantic 结果模型 `PreRefundSkillResult`，只包含现有公开结果构建所需的数据：

```python
class PreRefundSkillResult(BaseModel):
    answer: str
    calculation_trace: list[dict[str, object]]
    warnings: list[str]
    definition: str
    source_citations: list[dict[str, str]]
    case_context: PolicyQACaseContext | None
    can_answer: bool
    partial_answer: bool
    verified_external_result: bool
    policy_status: str = "no_policy"
```

单一入口：

```python
def assemble_pre_refund_analysis(
    original_trade_no: str,
    requested_items: tuple[PartialRefundItemRequest, ...],
    preview: PartialRefundPreview,
) -> PreRefundSkillResult:
    ...
```

实现顺序：先校验原交易号和项目集合，再校验数量，再校验金额快照与恒等式，最后从 `templates/analysis.yaml` 读取并格式化中文解释、计算步骤和来源。不得调用模型或外部 IO，解释文案不得硬编码在 Python 中。

官方拒绝分支不要求 `before/after`，但必须有 `response_code`、`response_message` 和来源引用；官方接受分支必须有完整快照。

- [ ] **Step 6：补 JSON Schema 并跑绿**

输入 schema 只允许：

```json
{
  "original_trade_no": "string",
  "items": [
    {"fee_detail_id": "string", "refund_quantity": "decimal-string"}
  ]
}
```

输出 schema 对齐 `PreRefundSkillResult`，不加入未来字段。

```powershell
uv run python -m pytest skills/outpatient_pre_refund_analysis_skill/tests/test_assembler.py src/tests/unit/skill_infra/test_skill_loader.py src/tests/unit/skill_infra/test_skill_router.py -q
```

Expected: PASS。

- [ ] **Step 7：提交原子变更**

```powershell
git add skills/outpatient_pre_refund_analysis_skill src/tests/unit/skill_infra/test_skill_loader.py src/tests/unit/skill_infra/test_skill_router.py
git commit -m "feat: 创建门诊部分项目预退费分析技能"
```

## Task 3：实现核心预退费流程

**Files:**

- Modify: `src/runtime/policy_qa/models.py`
- Create: `src/runtime/policy_qa/pre_refund_flow.py`
- Create: `src/tests/unit/runtime/policy_qa/test_pre_refund_flow.py`

- [ ] **Step 1：先写请求模型和核心流程失败测试**

新增 Pydantic 输入模型：

```python
class PreRefundItemInput(BaseModel):
    fee_detail_id: str = Field(min_length=1)
    refund_quantity: Decimal = Field(gt=0)
```

`PolicyQARequest` 增加：

```python
pre_refund_items: list[PreRefundItemInput] | None = None
```

测试至少覆盖：

- 零数、负数和空明细 ID 校验失败。
- 重复 `fee_detail_id` 被流程拒绝。
- 明确分析意图调用适配器一次。
- `error_type=pre_settlement_not_configured` 不重试并返回 unavailable。
- `error_type=pre_settlement_unavailable` 只重试一次。
- 返回关联不一致不重试。
- “立即执行退费/确认退费/冲正”先转人工确认，适配器调用次数为 0。
- “预退费分析/退费试算”不误判为写操作。

```powershell
uv run python -m pytest src/tests/unit/runtime/policy_qa/test_pre_refund_flow.py -q
```

Expected: FAIL，核心流程尚不存在。

- [ ] **Step 2：实现写操作意图的最小判定**

在 `pre_refund_flow.py` 中复用 `detect_blocked_actions`，只增加新场景必要的前置消歧：

```python
PREVIEW_TERMS = ("预退费", "退费分析", "退费试算", "分析退费")
EXECUTION_TERMS = ("立即执行", "确认退费", "执行退费", "办理退费", "冲正")
```

显式执行词优先；只有预览词时视为只读；其余裸“退费”交给现有高风险检测。不要修改全局风险词表，避免影响其他入口。

- [ ] **Step 3：实现核心流程状态和调用顺序**

定义最小结果：

```python
@dataclass(frozen=True)
class PreRefundFlowOutcome:
    state: Literal["completed", "unavailable", "waiting_human_confirmation"]
    skill_result: PreRefundSkillResult | None
    confirmation: AgentResponse | None
    attempt_count: int
    recovery_count: int
    halt_reason: str
```

`run_pre_refund_flow` 按以下顺序执行：

1. 检查执行意图；命中则调用 `build_human_confirmation_response` 并立即返回。
2. 校验非空项目和重复 ID。
3. 转换为 adapter request。
4. 用 `asyncio.to_thread` 调用同步适配器。
5. 适配器失败且 `error_type=pre_settlement_not_configured` 时直接 unavailable。
6. 适配器失败且 `error_type=pre_settlement_unavailable` 时最多再试一次。
7. 调用 Skill assembler；校验失败直接 unavailable。

不得捕获所有异常后继续；未知异常应交给现有 SSE 错误边界。

- [ ] **Step 4：运行核心流程测试并跑绿**

```powershell
uv run python -m pytest src/tests/unit/runtime/policy_qa/test_pre_refund_flow.py -q
```

Expected: PASS。

- [ ] **Step 5：提交原子变更**

```powershell
git add src/runtime/policy_qa/models.py src/runtime/policy_qa/pre_refund_flow.py src/tests/unit/runtime/policy_qa/test_pre_refund_flow.py
git commit -m "feat: 实现门诊预退费分析核心流程"
```

## Task 4：接入 Policy QA SSE 和公开结果

**Files:**

- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`

- [ ] **Step 1：先写 API 失败测试**

使用 FastAPI dependency override 注入记录调用次数的 `BillingPort` 假实现。测试：

- 带 `pre_refund_items` 的请求进入新 Skill。
- 数量不是正数返回标准 422。
- 重复明细 ID 返回标准业务错误，不调用适配器。
- 官方结果的公开字段仍严格等于 `PolicyQAPublicResult` 字段集合。
- 官方结果引用出现在 `citations`，且内部 SQL/原始敏感内容不会透传。
- 明确执行意图返回 `done.status == "waiting_human_confirmation"`，适配器调用次数为 0。
- 无 `pre_refund_items` 的既有请求行为不变。

```powershell
uv run python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q
```

Expected: FAIL，新依赖和分流尚不存在。

- [ ] **Step 2：增加最小依赖注入点**

在路由模块增加：

```python
def get_pre_refund_billing_adapter() -> BillingPort:
    return InMemoryBillingAdapter()
```

让 `/policy-qa/stream` 端点通过 `Depends` 接收该适配器，并传给 `_policy_qa_stream`。不增加工厂模块；现有默认适配器足够。

- [ ] **Step 3：在现有结算数据查询前分流**

当满足任一条件时进入新流程：

- `pre_refund_items` 非空；
- SkillRouter 选择 `outpatient_pre_refund_analysis_skill`；
- 问题包含明确退费执行意图。

该分支必须放在 `create_settlement_data_provider` 之前，保证高风险请求和未配置请求不会先查询无关结算数据。

分支复用现有 SSE 事件名称：`intent`、`skill_routing`、必要时 `recovery`、`result`、`done`，完成后立即 `return`；原结算解释流程保持原样。

- [ ] **Step 4：扩展现有公开结果构建器**

只增加内部可选参数：

```python
source_citations: list[dict[str, str]] | None = None
verified_external_result: bool = False
```

要求：

- 来源引用使用现有 citation 清洗逻辑。
- 官方预结算引用不计入政策证据数量。
- `verified_external_result=True` 且有有效官方来源时，可在无政策证据的情况下形成 complete。
- 此分支不附加“缺少政策依据”的误导性 uncertainty。
- 未验证、未配置或关联不一致仍为 unavailable。

不要修改 `PolicyQAPublicResult` 字段。

- [ ] **Step 5：映射人工确认结果**

`waiting_human_confirmation` 分支输出安全的 `PolicyQAPublicResult(status="unavailable")`，并在 `done` 事件增加：

```json
{
  "status": "waiting_human_confirmation",
  "halt_reason": "high_risk_action_requires_human_confirmation"
}
```

任务创建仍由现有 `build_human_confirmation_response` 完成，不重复建任务。

- [ ] **Step 6：运行 API 测试并跑绿**

```powershell
uv run python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q
```

Expected: PASS。

- [ ] **Step 7：提交原子变更**

```powershell
git add src/runtime/api/policy_qa_routes.py src/tests/integration/api/test_policy_qa_routes.py
git commit -m "feat: 接入门诊预退费分析流式入口"
```

## Task 5：补齐完整 Flow 验证

**Files:**

- Create: `src/tests/integration/flow/test_policy_qa_pre_refund_flow.py`
- Verify: `src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py`

- [ ] **Step 1：写成功 Flow 测试**

注入确定性的官方预结算假实现，发送：

```json
{
  "question": "分析部分项目预退费",
  "settlement_id": "OP-001",
  "pre_refund_items": [
    {"fee_detail_id": "F001", "refund_quantity": "1"}
  ]
}
```

断言事件顺序完整，最终 `result.status == "complete"`，包含退款或补缴方向、金额计算步骤和官方来源，`done.attempt_count == 1`。

- [ ] **Step 2：写降级和恢复 Flow 测试**

覆盖：

- 默认内存适配器：unavailable，无假金额，尝试 1 次。
- 首次瞬时失败、第二次成功：complete，尝试 2 次，恢复 1 次。
- 连续瞬时失败：unavailable，恰好 2 次。
- 官方拒绝：complete，展示拒绝码、原因和来源。
- 官方结果关联不一致：unavailable，不重试。
- 明确执行请求：waiting_human_confirmation，适配器调用 0 次。

- [ ] **Step 3：按硬性顺序运行全套相关测试**

Unit：

```powershell
uv run python -m pytest skills/outpatient_pre_refund_analysis_skill/tests src/tests/unit/adapters src/tests/unit/skill_infra/test_skill_loader.py src/tests/unit/skill_infra/test_skill_router.py src/tests/unit/runtime/policy_qa/test_pre_refund_flow.py -q
```

Expected: PASS。

API：

```powershell
uv run python -m pytest src/tests/integration/api/test_policy_qa_routes.py -q
```

Expected: PASS。

Flow：

```powershell
uv run python -m pytest src/tests/integration/flow/test_policy_qa_pre_refund_flow.py src/tests/integration/flow/test_policy_qa_pooling_self_pay_flow.py -q
```

Expected: PASS，且既有大额自付解释流程无回归。

- [ ] **Step 4：提交 Flow 测试**

```powershell
git add src/tests/integration/flow/test_policy_qa_pre_refund_flow.py
git commit -m "test: 覆盖门诊预退费分析完整流程"
```

## Task 6：同步领域语言和接口文档

**Files:**

- Modify: `src/domain/AGENTS.md`
- Modify: `skills/AGENTS.md`
- Modify: `docs/steering/接口设计文档.md`

- [ ] **Step 1：更新统一语言字典**

只增加本需求已经落地的三个术语：

| 中文术语 | 英文代码名 | 含义 |
|---|---|---|
| 门诊部分项目预退费分析 | `OutpatientPartialPreRefundAnalysis` | 基于院端官方预结算结果，对拟退明细进行只读分析 |
| 拟退项目 | `PartialRefundItemRequest` | 费用明细唯一标识与拟退数量 |
| 预结算结果 | `PartialRefundPreview` | 院端返回的接受/拒绝、项目金额及结算前后快照 |

- [ ] **Step 2：登记 Skill 与接口字段**

在 `skills/AGENTS.md` 登记新 Skill 的 action/object、输入和“不执行退费”的边界。

在接口设计的 `/policy-qa/stream` 请求中登记可选字段：

```json
"pre_refund_items": [
  {"fee_detail_id": "F001", "refund_quantity": "1"}
]
```

注明：仅门诊、与 `settlement_id` 共同使用、金额必须来自院端预结算、实际退费需人工确认。

- [ ] **Step 3：运行最终静态和回归检查**

```powershell
uv run python -m compileall src skills/outpatient_pre_refund_analysis_skill
git diff --check
git status --short
```

Expected: compileall 成功，`git diff --check` 无输出，仅出现本计划内文件。

- [ ] **Step 4：提交文档**

```powershell
git add src/domain/AGENTS.md skills/AGENTS.md docs/steering/接口设计文档.md
git commit -m "docs: 补充门诊预退费分析领域与接口说明"
```

## 不在本次实现范围

- 不新增数据库表、存储过程或本地预结算数据持久化。
- 不新增正式退费/冲正接口，不自动执行高风险动作。
- 不新增前端页面；现有 Policy QA 输入可直接调用结构化 API。
- 不用 LLM 匹配费用项目，不接受项目名称代替唯一明细 ID。
- 不实现医保待遇规则重算，不在院端预结算不可用时估算金额。
- 不为尚不存在的真实院端厂商接口建立多层工厂或配置框架；合同确定后只需实现现有 `BillingPort`。
