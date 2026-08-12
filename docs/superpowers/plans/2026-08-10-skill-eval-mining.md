# Skill 真实问答挖掘与分型回归 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Policy QA 中用户指出或评测者发现的所有回答错误统一沉淀到 Skill 案例池，并按路由、计算、政策内容、引用、答案质量、安全维度转成可追溯、可执行、可防止同类错误复发的回归资产。

**Architecture:** 服务端为每轮 Policy QA 生成稳定 `qa_turn_id` 并持久化脱敏来源。反馈与历史选取只提交 ID，应用服务执行所有权、租户、脱敏和去重检查后写入案例池。AI 通过 ModelGateway 生成严格类型化 proposal，人工确认后将 routing 投影到现有 `SkillEvalCase`，其余维度写入独立 `SkillRegressionCase`。评测器按类型执行，未实现的类型明确标记 `blocked_by_evaluator`，不得伪造通过结果。

**Tech Stack:** Python 3.12、Pydantic v2 discriminated unions、FastAPI、ModelGateway、PostgreSQL JSONB、Next.js 16、React 19、TypeScript、pytest、Vitest、Playwright。

---

## 范围、依赖与完成标准

- 覆盖 PRD 意见 3 的 P1、P2、P3。
- PRD 的 IA 前置方案 A 已在当前 Portal 落地；本计划把案例池挂载到顶层 `/skills/evaluations`，不会把评测或发布重新塞回 Skill 详情工作区。
- “回答有误”首先统一认定为 Skill 案例：路由、计算、政策内容、引用、答案质量、安全都可入池；`other` 仅表示尚未完成分型，不得绕过人工分诊直接形成可执行用例。
- routing 继续写入现有 `SkillEvalCase`，不修改 `top1_accuracy`、必测路由用例和发布门禁语义。
- calculation、policy_content、citation、answer_quality、safety 写入新的 `SkillRegressionCase`，使用严格判别联合，不保存自然语言裸 expected。
- 反馈接口不接受 question、answer 或 selected_skill_id；这些数据只由服务端通过 `qa_turn_id` 读取。
- 原始患者标识不得进入案例池、模型输入、日志、指标或审计事件。未确认案例默认保留 90 天，确认后只保留匿名回归模板和来源哈希。
- 依赖 `2026-08-10-skill-ai-authoring.md` Task 8 的候选隔离执行端口；在该依赖完成前，非路由用例可以确认但必须是 `blocked_by_evaluator`。
- 验证严格按 T1 单元测试 → T2a API 测试 → T2b Flow 测试执行；前端再执行 Vitest、ESLint、build、Playwright。

## 计划依赖图

```text
Task 1 qa_turn_id 后端链路 ─> Task 2 前端消息链路
Task 1 ─> Task 3 案例池领域模型 ─> Task 4 存储
Task 2 + Task 4 ─> Task 5 安全入池服务 ─> Task 6 反馈/历史 API 与 UI
Task 4 + Task 5 ─> Task 7 AI 分型转换 ─> Task 8 人工确认与资产投影
Task 8 + 候选隔离端口 ─> Task 9 分型评测器与门禁
Task 6 + Task 7 + Task 8 + Task 9 ─> Task 10 Flow/E2E/指标
```

### Task 1: 建立服务端 qa_turn_id 全链路

**Files:**
- Modify: `src/runtime/policy_qa/persistence.py`
- Modify: `src/runtime/policy_qa/history_service.py`
- Modify: `src/runtime/policy_qa/public_contract.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/tests/unit/runtime/policy_qa/test_policy_qa.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`

- [ ] **Step 1: 写失败测试锁定 ID 一致性和内部字段边界**

```python
def test_record_qa_task_uses_server_qa_turn_id() -> None:
    qa_turn_id = "qat_01JTEST000000000000000001"
    saved = record_qa_task(
        qa_turn_id=qa_turn_id,
        workflow_id="wf-1",
        session_id="session-1",
        user_id="user-1",
        tenant_id="tenant-1",
        question="起付线怎么计算",
        output={"answer_excerpt": "按年度累计计算", "selected_skill_id": "deductible"},
    )
    assert saved == qa_turn_id
    assert get_task(qa_turn_id)["output"]["selected_skill_id"] == "deductible"


def test_stream_result_and_done_share_qa_turn_id(client: TestClient) -> None:
    events = collect_sse_events(client, question="起付线怎么计算")
    result_id = next(event["data"]["qa_turn_id"] for event in events if event["event"] == "result")
    done_id = next(event["data"]["qa_turn_id"] for event in events if event["event"] == "done")
    assert result_id == done_id
```

- [ ] **Step 2: 运行测试并确认当前事件无 qa_turn_id**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/policy_qa/test_policy_qa.py src/tests/integration/api/test_policy_qa_routes.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 在请求开始时生成一次 qa_turn_id**

路由进入流式处理后立即生成不可预测的 ULID/UUID 风格 ID，贯穿 persistence、result、done 和异常 done。`record_qa_task` 接受该 ID，不再根据问题正文计算 task ID。

```python
qa_turn_id = f"qat_{uuid.uuid4().hex}"

yield sse_event(
    "result",
    {
        "qa_turn_id": qa_turn_id,
        "result": public_result.model_dump(mode="json"),
    },
)
yield sse_event(
    "done",
    {
        "qa_turn_id": qa_turn_id,
        "answer_status": public_result.answer_status,
        "success": True,
    },
)
```

持久化 output 增加内部 `selected_skill_id`、脱敏 `question_excerpt` 和 `answer_excerpt`；公开 SSE 继续经过 `public_contract`，不得泄露 `selected_skill_id`。

- [ ] **Step 4: 用显式 DTO 返回历史记录**

新增 `PolicyQAHistoryItem`，对普通用户只返回本人可见记录和公开字段；评测权限视图可返回 `selected_skill_id`，但问题与答案仍为脱敏摘要。删除当前“未传 user_id 返回全部”的公开行为，用户身份必须来自认证上下文而非查询参数。

- [ ] **Step 5: 执行 T1 → T2a**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/policy_qa/test_policy_qa.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_policy_qa_routes.py -q --tb=short`

Expected: PASS；result、done、history、task 主键一致。

Commit: `feat: add stable policy qa turn ids`

### Task 2: 将 qa_turn_id 保存到前端 assistant 消息

**Files:**
- Modify: `src/apps/portal/src/lib/policy-qa-session.ts`
- Modify: `src/apps/portal/src/lib/policy-qa-stream.ts`
- Modify: `src/apps/portal/src/lib/use-policy-qa-stream.ts`
- Modify: `src/apps/portal/src/tests/lib/policy-qa-session.test.ts`
- Modify: `src/apps/portal/src/tests/lib/use-policy-qa-stream.test.tsx`

- [ ] **Step 1: 写失败测试锁定 result/done 合并行为**

```tsx
it("keeps the server qa_turn_id on the assistant message", async () => {
  stream.emit("result", { qa_turn_id: "qat-1", result: validPolicyResult });
  stream.emit("done", { qa_turn_id: "qat-1", answer_status: "answered", success: true });
  expect(result.current.messages.at(-1)).toMatchObject({
    role: "assistant",
    qaTurnId: "qat-1",
  });
});
```

- [ ] **Step 2: 运行 Vitest 并确认字段丢失**

Run: `npm exec vitest run src/tests/lib/policy-qa-session.test.ts src/tests/lib/use-policy-qa-stream.test.tsx`（workdir: `src/apps/portal`）

Expected: FAIL。

- [ ] **Step 3: 扩展类型和 reducer，不放开内部字段**

`PolicyQAChatMessage` 新增 `qaTurnId?: string`、`selectedSkillId?: string` 和反馈状态。SSE parser 允许 `qa_turn_id`，但继续将 `selected_skill_id` 列入 forbidden keys；`selectedSkillId` 只允许由具备评测权限的 history DTO 映射。result 与 done 若返回不同 ID，标记流契约错误，不覆盖消息。

- [ ] **Step 4: 运行前端测试**

Run: `npm exec vitest run src/tests/lib/policy-qa-session.test.ts src/tests/lib/use-policy-qa-stream.test.tsx`（workdir: `src/apps/portal`）

Expected: PASS。

Commit: `feat: retain policy qa turn ids in chat`

### Task 3: 定义统一案例池与分型回归领域模型

**Files:**
- Create: `src/domain/skill/regression_models.py`
- Modify: `src/domain/skill/__init__.py`
- Modify: `src/domain/AGENTS.md`
- Create: `src/tests/unit/domain/skill/test_skill_regression_models.py`

- [ ] **Step 1: 写失败测试覆盖全部 Skill 错误维度**

```python
@pytest.mark.parametrize(
    "dimension",
    ["routing", "calculation", "policy_content", "citation", "answer_quality", "safety", "other"],
)
def test_case_pool_accepts_every_skill_error_dimension(dimension: str) -> None:
    item = valid_pool_item(error_dimension=dimension)
    assert item.error_dimension.value == dimension


def test_calculation_case_rejects_natural_language_expected() -> None:
    with pytest.raises(ValidationError):
        SkillRegressionCase.model_validate(
            {
                "case_id": "case-1",
                "target_skill_id": "deductible",
                "case_type": "calculation",
                "input_template": {"amount": 1000},
                "expected_assertions": "结果应该差不多正确",
            }
        )
```

- [ ] **Step 2: 运行测试并确认模型不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/domain/skill/test_skill_regression_models.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现状态机、错误维度和严格判别联合**

```python
class SkillErrorDimension(StrEnum):
    ROUTING = "routing"
    CALCULATION = "calculation"
    POLICY_CONTENT = "policy_content"
    CITATION = "citation"
    ANSWER_QUALITY = "answer_quality"
    SAFETY = "safety"
    OTHER = "other"


SkillRegressionAssertions = Annotated[
    CalculationAssertions
    | PolicyContentAssertions
    | CitationAssertions
    | AnswerQualityAssertions
    | SafetyAssertions,
    Field(discriminator="case_type"),
]
```

定义 `SkillEvalCasePoolItem`、`SkillEvalCasePoolStatus`、`SkillFeedbackReasonCode`、五类 proposal/assertions、`SkillRegressionCase`、`SkillRegressionEvaluatorStatus`。所有证据和已确认资产使用 frozen 模型；`other` 不属于 `SkillRegressionAssertions`。

- [ ] **Step 4: 同步通用语言字典并运行测试**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/domain/skill/test_skill_regression_models.py src/tests/unit/domain/skill/test_skill_governance_models.py -q --tb=short`

Expected: PASS；现有路由模型未改变。

Commit: `feat: model skill regression case mining`

### Task 4: 实现案例池与回归资产存储端口

**Files:**
- Create: `src/data_platform/storage/skill/regression_ports.py`
- Create: `src/data_platform/storage/skill/regression_in_memory.py`
- Create: `src/data_platform/storage/skill/regression_postgres.py`
- Create: `src/data_platform/storage/skill/regression_factory.py`
- Modify: `src/data_platform/storage/skill/__init__.py`
- Create: `src/tests/unit/data_platform/test_skill_regression_storage.py`

- [ ] **Step 1: 写存储契约失败测试**

```python
def test_pool_deduplicates_by_tenant_and_qa_turn() -> None:
    storage = InMemorySkillRegressionStorage()
    first = storage.create_pool_item(valid_pool_item(pool_id="pool-1"))
    second = storage.create_pool_item(valid_pool_item(pool_id="pool-2"))
    assert second.pool_id == first.pool_id


def test_confirm_is_idempotent_and_revision_checked() -> None:
    storage = seeded_storage()
    first = storage.confirm_pool_item("pool-1", "regression", "case-1", expected_revision=2)
    second = storage.confirm_pool_item("pool-1", "regression", "case-1", expected_revision=first.revision)
    assert second.eval_case_id == first.eval_case_id
    assert storage.count_regression_cases() == 1
```

- [ ] **Step 2: 运行测试并确认适配器不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/data_platform/test_skill_regression_storage.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现 ports、深拷贝内存适配器和 PostgreSQL 事务**

PostgreSQL 新增 `skill_eval_case_pool` 与 `skill_regression_cases`。使用显式列映射、JSONB 严格反序列化、tenant 条件和软删除。工厂遵循 `USE_MEMORY_STORAGE`。

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_eval_pool_turn
ON skill_eval_case_pool(tenant_id, source_qa_turn_id)
WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_regression_source
ON skill_regression_cases(source_type, source_ref, case_type)
WHERE enabled = TRUE;
```

`transform`、`confirm`、`reject` 使用 `WHERE pool_id = :pool_id AND tenant_id = :tenant_id AND revision = :expected_revision`；受影响行数为零时返回统一冲突异常。

- [ ] **Step 4: 运行存储测试**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/data_platform/test_skill_regression_storage.py src/tests/unit/data_platform/test_skill_governance_storage.py -q --tb=short`

Expected: PASS。

Commit: `feat: persist skill regression case mining`

### Task 5: 构建所有权校验、脱敏、去重的安全入池服务

**Files:**
- Create: `src/runtime/skill_management/regression_mining_service.py`
- Modify: `src/security/desensitization/service.py`
- Create: `src/tests/unit/runtime/skill_management/test_regression_mining_service.py`
- Create: `src/tests/unit/security/test_regression_desensitization.py`

- [ ] **Step 1: 写失败测试覆盖伪造、跨租户和敏感信息**

```python
def test_feedback_reads_source_by_id_and_ignores_no_client_content() -> None:
    service = build_service(source=qa_source(question="起付线怎么计算", selected_skill_id="deductible"))
    item = service.collect_feedback(
        principal=principal("user-1", "tenant-1"),
        qa_turn_id="qat-1",
        reason_code=SkillFeedbackReasonCode.WRONG_CALCULATION,
        comment="计算口径不对",
        idempotency_key="feedback-1",
    )
    assert item.source_selected_skill_id == "deductible"
    assert item.error_dimension == SkillErrorDimension.CALCULATION


def test_feedback_rejects_cross_tenant_without_disclosing_existence() -> None:
    service = build_service(source=qa_source(tenant_id="tenant-2"))
    with pytest.raises(QATurnNotAccessibleError):
        service.collect_feedback(
            principal=principal("user-1", "tenant-1"),
            qa_turn_id="qat-1",
            reason_code=SkillFeedbackReasonCode.WRONG_POLICY_CONTENT,
            comment=None,
            idempotency_key="feedback-2",
        )
```

- [ ] **Step 2: 运行测试并确认服务不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_mining_service.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现先授权、再脱敏、再持久化的固定流水线**

```text
load qa_turn by server ID
  -> compare principal.user_id + principal.tenant_id
  -> map reason_code to initial SkillErrorDimension
  -> sanitize question/answer excerpt/comment
  -> scan sanitized snapshot again
  -> compute source_hash
  -> create-or-return pool item by tenant_id + qa_turn_id
  -> emit audit event without source text
```

新增结构化 `sanitize_regression_snapshot`，姓名、身份证、手机号、结算号、住院号、病案号等使用占位符；二次扫描仍命中时阻断入池并记录安全审计。不得把原文传给存储层。

- [ ] **Step 4: 实现历史批量入池的逐项结果**

评测者批量选取要求 `skill:evaluate`。每个 qa_turn 独立返回 `created | duplicate | forbidden | rejected_sensitive`，单项失败不回滚其他合法项；批量上限固定为 100。

- [ ] **Step 5: 运行服务与安全测试**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_mining_service.py src/tests/unit/security/test_regression_desensitization.py -q --tb=short`

Expected: PASS；fake ModelGateway 尚未收到任何原始敏感信息。

Commit: `feat: collect safe skill error cases`

### Task 6: 暴露反馈、历史选取和案例池查询，并接入前端

**Files:**
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/policy_qa_routes.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/tests/integration/api/test_policy_qa_routes.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`
- Modify: `src/apps/portal/src/components/policy-qa/policy-agent-answer.tsx`
- Modify: `src/apps/portal/app/qa-history/page.tsx`
- Modify: `src/apps/portal/src/lib/types.ts`
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Modify: `src/apps/portal/src/tests/components/policy-agent-answer.test.tsx`
- Create: `src/apps/portal/src/tests/qa-history-mining.test.tsx`

- [ ] **Step 1: 写 API 失败测试，证明客户端不能伪造来源**

反馈请求模型仅允许以下字段：

```python
class PolicyQAFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qa_turn_id: str = Field(min_length=1, max_length=80)
    reason_code: SkillFeedbackReasonCode
    comment: str | None = Field(default=None, max_length=500)
```

测试额外发送 `question`、`answer`、`selected_skill_id` 时返回 422；跨用户/租户统一返回不可枚举的 404；重复 idempotency key 返回同一 pool ID；案例池端点无 `skill:evaluate` 返回 403。

- [ ] **Step 2: 运行 API 测试并确认端点不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_policy_qa_routes.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现显式 DTO、依赖注入和端点**

```text
POST /policy-qa/feedback
GET  /infra-skills/eval-case-pool
POST /infra-skills/eval-case-pool/from-history
```

普通反馈 principal 来自认证上下文；评测接口复用 `SkillEvaluationPrincipalDependency`。所有错误通过 `error_detail()` 返回 `{error_code, message, audit_event}`。查询支持 status、error_dimension、target_skill_id、limit、offset，且始终附加 tenant 条件。

- [ ] **Step 4: 写前端失败测试**

覆盖：仅有 qaTurnId 的 assistant 回答显示“回答有误”；reason 必选；提交成功后禁用重复提交；无 qaTurnId 不显示反馈入口；qa-history 评测者可勾选多条并看到 created/duplicate/forbidden 的逐项结果。

- [ ] **Step 5: 实现反馈组件与历史批量选取**

`policy-agent-answer.tsx` 只提交 `qa_turn_id + reason_code + comment`。`qa-history/page.tsx` 不展示完整患者上下文；批量按钮最多提交 100 个 ID；普通用户不渲染评测控件。API client 统一附带 Idempotency-Key。

- [ ] **Step 6: 按后端 T1 → T2a，再执行前端验证**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_mining_service.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_policy_qa_routes.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Run 3: `npm exec vitest run src/tests/components/policy-agent-answer.test.tsx src/tests/qa-history-mining.test.tsx`（workdir: `src/apps/portal`）

Expected: PASS。

Commit: `feat: collect policy qa errors for skill evaluation`

### Task 7: 用 ModelGateway 生成类型化错误归因与回归 proposal

**Files:**
- Create: `src/runtime/skill_management/regression_transform_service.py`
- Create: `src/runtime/skill_management/regression_transform_prompts.py`
- Modify: `src/config/model_routing.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Create: `src/tests/unit/runtime/skill_management/test_regression_transform_service.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`

- [ ] **Step 1: 写失败测试覆盖六种可执行 proposal 和 other 降级**

```python
@pytest.mark.parametrize(
    "dimension, expected_type",
    [
        ("routing", RoutingCaseProposal),
        ("calculation", CalculationCaseProposal),
        ("policy_content", PolicyContentCaseProposal),
        ("citation", CitationCaseProposal),
        ("answer_quality", AnswerQualityCaseProposal),
        ("safety", SafetyCaseProposal),
    ],
)
def test_transform_returns_typed_proposal(dimension: str, expected_type: type[BaseModel]) -> None:
    result = build_transform_service(model_output=valid_output(dimension)).transform("pool-1", expected_revision=1)
    assert isinstance(result.case_proposal, expected_type)


def test_transform_does_not_invent_expected_without_evidence() -> None:
    result = build_transform_service(model_output=unsupported_policy_output()).transform("pool-1", expected_revision=1)
    assert result.error_dimension == SkillErrorDimension.OTHER
    assert result.case_proposal is None
    assert result.uncertainties
```

- [ ] **Step 2: 运行测试并确认服务不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_transform_service.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现严格转换服务**

只向 `ModelGateway.generate(scene="skill_eval_transform")` 发送案例池中的脱敏摘要、当时 selected skill、可用 Skill manifest 摘要和可追溯政策证据。模型输出包含 error_dimension、root_cause、target_skill_id、case_proposal、citations、uncertainties。最多一次结构修复；证据不足时强制 `other + case_proposal=None`。

```python
if output.error_dimension is SkillErrorDimension.OTHER:
    if output.case_proposal is not None:
        raise SkillRegressionTransformInvalidError("other cannot carry executable proposal")
elif output.case_proposal is None:
    raise SkillRegressionTransformInvalidError("executable dimension requires proposal")
```

- [ ] **Step 4: 新增 transform API 与 revision 保护**

```text
POST /infra-skills/eval-case-pool/{pool_id}/transform
```

要求 `skill:evaluate`，body 只含 `expected_revision`。模型失败时不改变状态和 revision；成功时原子保存 transformed payload、provenance、operator、revision。响应为显式 DTO。

- [ ] **Step 5: 按 T1 → T2a 验证**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_transform_service.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Expected: PASS。

Commit: `feat: transform skill errors into typed cases`

### Task 8: 人工确认并投影到正确的评测资产

**Files:**
- Modify: `src/runtime/skill_management/regression_mining_service.py`
- Modify: `src/runtime/skill_management/governance_service.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/tests/unit/runtime/skill_management/test_regression_mining_service.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`

- [ ] **Step 1: 写分流与幂等失败测试**

```python
def test_confirm_routing_projects_to_existing_route_case() -> None:
    result = service.confirm("pool-routing", routing_confirmation(), expected_revision=2)
    assert result.eval_case_ref.case_type == "route"
    assert governance_storage.get_case(result.eval_case_ref.case_id).source_ref == "qat-1"


def test_confirm_calculation_creates_regression_case() -> None:
    result = service.confirm("pool-calc", calculation_confirmation(), expected_revision=2)
    case = regression_storage.get_case(result.eval_case_ref.case_id)
    assert case.case_type == SkillErrorDimension.CALCULATION
    assert case.evaluator_status == SkillRegressionEvaluatorStatus.AVAILABLE


def test_confirm_other_is_rejected() -> None:
    with pytest.raises(SkillRegressionCaseNotExecutableError):
        service.confirm("pool-other", other_confirmation(), expected_revision=2)
```

- [ ] **Step 2: 运行测试并确认尚无分流实现**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_mining_service.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现按维度的唯一分流**

```python
if confirmation.error_dimension is SkillErrorDimension.ROUTING:
    eval_ref = self._governance.create_case(to_route_case(pool, confirmation))
elif confirmation.error_dimension is SkillErrorDimension.OTHER:
    raise SkillRegressionCaseNotExecutableError(pool.pool_id)
else:
    eval_ref = self._regression_storage.create_case(to_regression_case(pool, confirmation))
return self._storage.confirm_pool_item(
    pool.pool_id,
    eval_ref.case_type,
    eval_ref.case_id,
    expected_revision=expected_revision,
)
```

routing 的 `source_type=policy_qa_feedback`、`source_ref=qa_turn_id`；非路由资产冻结人工修改后的类型化 assertions、source hash 和确认人。confirm 使用 pool ID 作为业务幂等键，重复请求返回同一资产。

- [ ] **Step 4: 实现 confirm/reject API**

```text
POST /infra-skills/eval-case-pool/{pool_id}/confirm
POST /infra-skills/eval-case-pool/{pool_id}/reject
```

confirm body 携带 expected_revision、最终 error_dimension、target_skill_id、严格 case_proposal；reject 携带 expected_revision 和限长 rejection_reason。stale revision 返回 409。

- [ ] **Step 5: 运行 T1 → T2a**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_mining_service.py src/tests/unit/runtime/skill_management/test_governance_service.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Expected: PASS；路由指标语义未变化。

Commit: `feat: confirm mined skill regression assets`

### Task 9: 实现分型编辑 UI 与五类评测器

**Files:**
- Create: `src/apps/portal/src/components/skills/eval-case-pool-list.tsx`
- Create: `src/apps/portal/src/components/skills/eval-case-editor.tsx`
- Create: `src/apps/portal/app/skills/eval-mining/page.tsx`
- Modify: `src/apps/portal/app/skills/layout.tsx`
- Modify: `src/apps/portal/src/lib/types.ts`
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Create: `src/apps/portal/src/tests/skill-eval-case-pool.test.tsx`
- Create: `src/runtime/skill_management/regression_evaluators.py`
- Modify: `src/domain/skill/governance_models.py`
- Modify: `src/runtime/skill_management/governance_service.py`
- Modify: `src/data_platform/storage/skill/governance_ports.py`
- Modify: `src/data_platform/storage/skill/governance_in_memory.py`
- Modify: `src/data_platform/storage/skill/governance_postgres.py`
- Create: `src/tests/unit/runtime/skill_management/test_regression_evaluators.py`
- Modify: `src/tests/unit/domain/skill/test_skill_governance_models.py`
- Modify: `src/tests/unit/data_platform/test_skill_governance_storage.py`

- [ ] **Step 1: 写前端判别联合编辑测试**

验证每个 error_dimension 只显示对应字段：计算展示 expected_value/tolerance/rounding；政策展示 applicability/must_include/forbidden/policy_version；引用展示 source IDs/support requirement；质量展示 answerability/must_include/must_not_include/rubric；安全展示 sensitive fields/blocked actions/expected state。`other` 只允许重新分型或拒绝。

- [ ] **Step 2: 实现案例池列表、转换和人工编辑确认**

在 Skill 顶层导航新增“案例挖掘”，并把 `eval-mining` 加入保留路由段，避免被识别为 skillId。列表显示来源、初始 reason、AI 维度、人工最终维度、目标 Skill、状态、revision、最近评测状态。组件使用服务端返回的 discriminated union，不用任意 JSON 编辑器。409 时保留未提交修改并要求重新加载。

- [ ] **Step 3: 写评测器失败测试**

```python
def test_calculation_evaluator_checks_value_tolerance_and_rounding() -> None:
    result = evaluators.evaluate(calculation_case(expected=100.0, tolerance=0.01), output={"amount": 100.02})
    assert result.passed is False
    assert result.failures[0].code == "CALCULATION_TOLERANCE_EXCEEDED"


def test_safety_evaluator_requires_human_confirmation() -> None:
    result = evaluators.evaluate(safety_case(), output={"status": "completed", "answer": "已完成冲正"})
    assert result.passed is False
    assert {failure.code for failure in result.failures} >= {"HIGH_RISK_CONFIRMATION_MISSING"}
```

- [ ] **Step 4: 实现统一 evaluator registry**

```python
class SkillRegressionEvaluator(Protocol):
    case_type: SkillErrorDimension

    def evaluate(
        self,
        case: SkillRegressionCase,
        output: SkillCandidateBehaviorResult,
    ) -> SkillRegressionEvalResult:
        raise NotImplementedError
```

实现 calculation、policy_content、citation、answer_quality、safety 五个 evaluator。确定性断言优先；答案质量 rubric 需要模型时仍走 ModelGateway，并保存 rubric/prompt/model 版本。任何 evaluator 缺失返回 `blocked_by_evaluator`，不得生成 passed。

- [ ] **Step 5: 按风险逐步接入治理运行与发布门禁**

`SkillEvalRun` 保留现有路由 `results/metrics`，新增冻结的 `regression_results` 和独立 `regression_summary`；存储适配器显式序列化新字段。每条结果记录 case_id、candidate_version_id、case snapshot hash、evaluator version、passed/blocked、failure codes，案例详情由此反查失败版本、修复版本和最近结果。先将 safety、calculation 的 `required=true` 用例纳入 candidate gate；policy_content、citation 在证据版本冻结后纳入；answer_quality 仅在 rubric 稳定性达到门槛后纳入。禁止把非路由结果混入 top1 accuracy。

- [ ] **Step 6: 运行单元与前端验证**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_regression_evaluators.py src/tests/unit/runtime/skill_management/test_governance_service.py src/tests/unit/domain/skill/test_skill_governance_models.py src/tests/unit/data_platform/test_skill_governance_storage.py -q --tb=short`

Run 2: `npm exec vitest run src/tests/skill-eval-case-pool.test.tsx`（workdir: `src/apps/portal`）

Run 3: `npm exec eslint app/skills/layout.tsx app/skills/eval-mining/page.tsx src/components/skills/eval-case-pool-list.tsx src/components/skills/eval-case-editor.tsx src/lib/api-client.ts src/lib/types.ts src/tests/skill-eval-case-pool.test.tsx`（workdir: `src/apps/portal`）

Run 4: `npm run build`（workdir: `src/apps/portal`）

Expected: PASS。

Commit: `feat: evaluate typed skill regressions`

### Task 10: 完成 Flow、E2E、留存和可观测性验收

**Files:**
- Modify: `src/observability/metrics/definitions.py`
- Create: `src/tests/integration/flow/test_skill_error_mining_flow.py`
- Modify: `src/tests/e2e/pages/portal/policy-qa.page.ts`
- Modify: `src/tests/e2e/pages/portal/skill-catalog.page.ts`
- Create: `src/tests/e2e/flows/portal/skill-error-mining.flow.ts`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 写三条后端 Flow 主链和安全负向链**

主链 A：Policy QA 路由错误 → 用户反馈 → 入池 → AI 转 routing → 人工确认 → 现有 `SkillEvalCase` → 路由回归失败 → 修复版本通过。

主链 B：计算/政策内容错误 → 用户反馈 → 入池 → 类型化 assertion → `SkillRegressionCase` → 对应 evaluator 失败 → 修复版本通过。

主链 C：评测者从 history 批量选取 → duplicate 合并 → 人工重新分型 → confirm → 可追溯到原 qa_turn。

安全链：跨用户/跨租户访问、客户端伪造正文、残留 PII、stale revision、重复 confirm、缺失 evaluator 全部按预期拒绝或 blocked。

- [ ] **Step 2: 实现 90 天留存和来源解绑**

提供应用服务清理入口：只软删除过期 `pending_triage/transformed/rejected`，不删除 confirmed 回归资产；用户依法删除来源时清空 source session/user 关联，保留匿名模板、source hash 和审计依据。清理任务不打印原始摘要。

- [ ] **Step 3: 增加无高基数、无敏感信息的指标**

记录 `skill_eval_pool_created_total`、`skill_eval_pool_duplicate_total`、`skill_eval_transform_total`、`skill_eval_confirm_total`、`skill_eval_blocked_total`、`skill_eval_dimension_total`。标签仅允许 status、reason_code、dimension、evaluator_status；不得使用 qa_turn_id、user_id、tenant_id、skill_id、问题内容。

- [ ] **Step 4: 严格执行后端三阶段验证**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/domain/skill/test_skill_regression_models.py src/tests/unit/data_platform/test_skill_regression_storage.py src/tests/unit/runtime/skill_management/test_regression_mining_service.py src/tests/unit/runtime/skill_management/test_regression_transform_service.py src/tests/unit/runtime/skill_management/test_regression_evaluators.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_policy_qa_routes.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Run 3: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/flow/test_skill_error_mining_flow.py -q --tb=short`

Expected: 三阶段依次 PASS。

- [ ] **Step 5: 执行浏览器主链路**

从工作区根目录运行 `..\ws.ps1 up skill`，再用 `..\ws.ps1 url all` 获取本工作区 URL。Playwright 验证用户反馈、history 批量入池、案例分型编辑、confirm、最近评测结果、390px 无横向溢出和键盘操作。

Run: `npx playwright test ../../tests/e2e/flows/portal/skill-error-mining.flow.ts`（workdir: `src/apps/portal`）

Expected: PASS。结束后从工作区根目录运行 `..\ws.ps1 down skill`。

- [ ] **Step 6: 更新进度与最终提交**

`PROGRESS.md` 记录各 evaluator 的 available/blocked 状态、已接入发布门禁的维度、测试证据和仍需人工审核的政策/rubric 风险。

Commit: `feat: complete skill error mining flow`

## 最终回归清单

- [ ] 每轮 Policy QA 的 result、done、assistant 消息、history、task 都使用同一服务端 qa_turn_id。
- [ ] 路由、计算、政策内容、引用、答案质量和安全错误都先进入统一 Skill 案例池。
- [ ] 反馈与历史批量接口不接受或信任客户端正文和 selected_skill_id。
- [ ] 所有权、租户隔离、脱敏、二次敏感扫描、去重、幂等、revision 均有正反测试。
- [ ] routing 只写现有 `SkillEvalCase`；其他五类只写 `SkillRegressionCase`；`other` 不生成可执行资产。
- [ ] 历史回答不直接成为 expected；expected 只来自确定计算、政策证据、结构化事实或人工确认。
- [ ] evaluator 缺失时状态为 `blocked_by_evaluator`，不会显示通过或放行发布。
- [ ] 非路由结果不会污染现有 top1 accuracy；发布门禁按风险逐维度启用。
- [ ] 存储、ModelGateway 输入、日志、指标和审计中均无原始敏感信息。
- [ ] 单元测试、API 测试、Flow、Vitest、ESLint、build、Playwright 均留有通过证据。
