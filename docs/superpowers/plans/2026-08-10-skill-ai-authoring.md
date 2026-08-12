# Skill AI 编写与候选隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Skill 开发者可通过自然语言和已发布指标生成或优化 Skill 草稿，同时保证 AI 产物在严格 DTO、静态安全门禁、隔离候选评测和人工确认前绝不进入运行时目录。

**Architecture:** 在现有 `SkillDraft`、`SkillPackageGenerator`、`SkillInputService` 和 `ModelGateway` 上增加 AI 编写应用服务。模型只返回结构化 proposal；服务端完成指标快照、代码扫描、哈希和草稿持久化。候选包写入临时隔离目录，由无网络、只读、限时限资源的独立执行适配器评测；只有已有人工物化接口可写入 `skills/`。

**Tech Stack:** Python 3.12、Pydantic v2、FastAPI、ModelGateway、PostgreSQL JSONB、Next.js 16、React 19、TypeScript、pytest、Vitest、Playwright、Docker sandbox adapter。

---

## 范围、依赖与完成标准

- 覆盖 PRD 意见 2 的 P1、P2，以及 P3 中与生成质量度量直接相关的部分。
- PRD 的 IA 前置“详情页仅保留概览/版本/开发详情，评测与发布归顶层页”已由当前 `skill-workspace.tsx`、`app/skills/evaluations/page.tsx` 和 `app/skills/releases/page.tsx` 落地；本计划只做回归保护，不重复改造信息架构。
- 依赖现有草稿 CRUD、校验、包生成、输入指标和版本治理能力；不重写这些模块。
- AI 生成与优化都只产出 proposal 或 `source_type=ai_generated` 的草稿。
- `SkillLoader`、`SkillRouter` 和线上编排不得扫描候选隔离目录。
- AI 代码未通过静态门禁时不得保存为可接受 proposal；隔离执行器不可用时行为评测必须返回 `blocked_by_evaluator`，不得回退到宿主进程执行。
- 所有写操作要求明确权限；接受优化要求 `expected_revision`；生成、优化和接受均记录模型、prompt、输入指标和内容哈希。
- 验证严格按 T1 单元测试 → T2a API 测试 → T2b Flow 测试执行；前端再执行 Vitest、ESLint、build、Playwright。

## 计划依赖图

```text
Task 1 领域与 DTO
  ├─> Task 2 静态安全门禁
  ├─> Task 3 AI 生成服务 ─> Task 4 生成/接受 API ─> Task 5 创建页
  └─> Task 6 AI 优化与 revision ─> Task 7 编辑页 diff
Task 2 + Task 3 ─> Task 8 候选隔离评测
Task 4 + Task 5 + Task 6 + Task 7 + Task 8 ─> Task 9 Flow/E2E/指标
```

### Task 1: 冻结 AI 编写领域契约与跨层 DTO

**Files:**
- Modify: `src/domain/skill/draft_models.py`
- Modify: `src/domain/skill/__init__.py`
- Modify: `src/domain/AGENTS.md`
- Create: `src/runtime/skill_management/ai_authoring/__init__.py`
- Create: `src/runtime/skill_management/ai_authoring/schemas.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/apps/portal/src/lib/types.ts`
- Create: `src/tests/unit/runtime/skill_management/test_ai_authoring_schemas.py`

- [ ] **Step 1: 写失败测试，锁定来源类型、严格字段和不可变溯源信息**

```python
def test_ai_proposal_rejects_unknown_fields_and_freezes_provenance() -> None:
    with pytest.raises(ValidationError):
        SkillAIGenerationResponse.model_validate(
            {
                "generation_id": "gen-1",
                "proposal_hash": "a" * 64,
                "structured_config": valid_structured_config(),
                "raw_files": {"assembler.py": "def load():\n    return None\n"},
                "validation_preview": valid_validation_preview(),
                "provenance": valid_provenance(),
                "citations": [],
                "uncertainties": ["需人工确认政策适用范围"],
                "untrusted_extra": True,
            }
        )

    proposal = valid_ai_response()
    with pytest.raises(ValidationError):
        proposal.provenance.prompt_version = "changed"


def test_skill_draft_accepts_ai_generated_source_type() -> None:
    draft = valid_draft(source_type=SkillDraftSourceType.AI_GENERATED)
    assert draft.source_type.value == "ai_generated"
```

- [ ] **Step 2: 运行测试并确认因模型或枚举不存在而失败**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_schemas.py -q --tb=short`

Expected: FAIL，缺少 `SkillAIGenerationProposal` 或 `AI_GENERATED`。

- [ ] **Step 3: 实现最小严格模型**

在 `draft_models.py` 增加 `AI_GENERATED`；在 `ai_authoring/schemas.py` 定义模型输出和生成响应的严格契约；`skill_schemas.py` 只定义 API 请求/响应包装 DTO。核心结构如下：

```python
class SkillAIGenerationProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_type: str = Field(min_length=1, max_length=120)
    scene: Literal["skill_authoring"]
    prompt_version: str = Field(min_length=1, max_length=64)
    metric_versions: tuple[SkillMetricVersionRef, ...]
    generated_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SkillAIGenerationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_id: str = Field(min_length=1, max_length=80)
    proposal_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    structured_config: SkillStructuredConfig
    raw_files: dict[str, str]
    validation_preview: SkillValidationReportResponse
    provenance: SkillAIGenerationProvenance
    citations: tuple[Citation, ...]
    uncertainties: tuple[str, ...]
```

生成请求 DTO 只允许 `description`、`metric_codes`；优化请求增加 `expected_revision`；创建草稿请求逐项允许 `generation_id`、`proposal_hash`、`skill_id`、`skill_name`、`structured_config`、`raw_files`。禁止用裸 `dict` 作为路由返回类型。

- [ ] **Step 4: 同步前端判别联合与领域字典**

前端 `SkillDraftSourceType` 增加 `ai_generated`；新增 `SkillAIGenerationProposal`、`SkillAIGenerateRequest`、`SkillAIAcceptRequest`，字段与后端 snake_case DTO 一一对应。`src/domain/AGENTS.md` 增加 AI 草稿、AI proposal、候选制品的统一定义。

- [ ] **Step 5: 运行领域测试**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_schemas.py src/tests/unit/runtime/skill_management/test_draft_service.py -q --tb=short`

Expected: PASS。

Commit: `feat: define skill ai authoring contracts`

### Task 2: 建立生成文件、AST、敏感信息和大小门禁

**Files:**
- Create: `src/runtime/skill_management/ai_authoring/security.py`
- Modify: `src/runtime/skill_management/draft_validator.py`
- Create: `src/tests/unit/runtime/skill_management/test_ai_authoring_security.py`
- Modify: `src/tests/unit/runtime/skill_management/test_draft_validator_and_package.py`

- [ ] **Step 1: 写失败测试覆盖危险代码与安全代码**

```python
@pytest.mark.parametrize(
    "path, content, expected_code",
    [
        ("../escape.py", "value = 1", "AI_FILE_PATH_FORBIDDEN"),
        ("assembler.py", "import socket", "AI_IMPORT_FORBIDDEN"),
        ("assembler.py", "open('secret.txt').read()", "AI_CALL_FORBIDDEN"),
        ("assembler.py", "__import__('os').system('whoami')", "AI_CALL_FORBIDDEN"),
        ("payload.bin", "not-python", "AI_FILE_PATH_FORBIDDEN"),
    ],
)
def test_scan_ai_files_rejects_unsafe_content(
    path: str,
    content: str,
    expected_code: str,
) -> None:
    result = scan_ai_generated_files({path: content})
    assert expected_code in {issue.code for issue in result.issues}


def test_scan_ai_files_accepts_minimal_assembler_and_prompt() -> None:
    result = scan_ai_generated_files(
        {
            "assembler.py": "def load(config):\n    return config\n",
            "prompt_template.yaml": "system: explain with citations\n",
        }
    )
    assert result.passed is True
```

- [ ] **Step 2: 运行测试并确认扫描器不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_security.py -q --tb=short`

Expected: FAIL，无法导入扫描器。

- [ ] **Step 3: 实现显式白名单和统一扫描结果**

允许的 AI 文件仅为 `assembler.py`、`prompt_template.yaml`；Schema 从结构化 DTO 生成，不接受模型自行指定路径。限制单文件和总大小。AST 只允许函数、赋值、字面量、容器、条件和受控调用；显式拒绝 import、属性反射、文件/网络/进程/动态执行调用。扫描完成后再次使用 `detect_sensitive_patterns` 检查生成文本。

```python
ALLOWED_AI_RAW_FILES = frozenset({"assembler.py", "prompt_template.yaml"})
FORBIDDEN_CALLS = frozenset(
    {
        "compile",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
        "__import__",
    }
)


class SkillAISecurityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    passed: bool
    issues: tuple[SkillAISecurityIssue, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
```

- [ ] **Step 4: 将同一门禁接入草稿校验器**

仅当 `draft.source_type == AI_GENERATED` 时追加 AI 安全规则，避免改变导入/手工草稿的既有契约。安全失败保持草稿可编辑，但校验状态不得变为 validated。

- [ ] **Step 5: 运行扫描器和原草稿校验测试**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_security.py src/tests/unit/runtime/skill_management/test_draft_validator_and_package.py -q --tb=short`

Expected: PASS，现有手工草稿行为不变。

Commit: `feat: gate ai generated skill content`

### Task 3: 通过 ModelGateway 生成可追溯 proposal

**Files:**
- Create: `src/runtime/skill_management/ai_authoring/service.py`
- Create: `src/runtime/skill_management/ai_authoring/prompts.py`
- Modify: `src/config/model_routing.py`
- Modify: `src/runtime/skill_management/__init__.py`
- Create: `src/tests/unit/runtime/skill_management/test_ai_authoring_service.py`

- [ ] **Step 1: 写失败测试覆盖指标冻结、单次修复重试和失败降级**

```python
def test_generate_freezes_only_published_metric_versions() -> None:
    gateway = FakeModelGateway([valid_model_json()])
    service = build_service(gateway=gateway, metrics=published_metric_registry())
    proposal = service.generate(valid_request())
    assert proposal.provenance.metric_versions[0].object_version == 3
    assert gateway.calls[0].scene == "skill_authoring"


def test_generate_repairs_invalid_json_once_then_stops() -> None:
    gateway = FakeModelGateway(["not-json", "still-not-json"])
    service = build_service(gateway=gateway, metrics=published_metric_registry())
    with pytest.raises(SkillAIOutputInvalidError):
        service.generate(valid_request())
    assert [call.scene for call in gateway.calls] == ["skill_authoring", "skill_authoring"]
```

- [ ] **Step 2: 运行测试并确认服务不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_service.py -q --tb=short`

Expected: FAIL，无法导入服务。

- [ ] **Step 3: 实现生成服务，不直接调用 Provider 或 HTTP**

流程必须固定为：校验描述长度 → 读取 published 指标及对象版本 → 组装无敏感信息 prompt → `ModelGateway.generate` → 严格解析 → 最多一次结构修复 → 安全扫描 → 计算输入/proposal 哈希 → 返回不可变 proposal。

```python
response = self._gateway.generate(
    messages=[Message(role="system", content=system_prompt), Message(role="user", content=user_prompt)],
    model_type="reasoning",
    scene="skill_authoring",
    max_tokens=self._max_tokens,
)
proposal_body = SkillAIModelOutput.model_validate_json(response.content)
security = scan_ai_generated_files(proposal_body.raw_files)
if not security.passed:
    raise SkillAISecurityRejectedError(security.issues)
return self._build_proposal(proposal_body, response, metric_snapshots)
```

模型路由新增 PRD 约定的 `skill_authoring` scene；生成、结构修复和优化通过审计字段 `operation` 区分，但都使用同一受控模型路由，不在服务内指定 URL 或密钥。

- [ ] **Step 4: 运行单元测试**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_service.py src/tests/unit/runtime/skill_management/test_skill_input_service.py -q --tb=short`

Expected: PASS。

Commit: `feat: generate traceable skill proposals`

### Task 4: 提供生成与原子接受 API

**Files:**
- Modify: `src/runtime/skill_management/draft_service.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/tests/integration/api/test_skill_draft_api.py`

- [ ] **Step 1: 写 API 失败测试**

覆盖：无 `skill:release:test` 返回 403；生成成功返回严格 proposal；危险代码返回 422 标准错误；接受后仅创建一个 AI 草稿；同一 idempotency key 返回同一 draft；模型异常不产生草稿；客户端篡改 provenance/proposal hash 返回 409。

```python
def test_accept_ai_proposal_creates_one_ai_draft(client: TestClient) -> None:
    generated = client.post("/api/v1/medical-insurance-ai-agent/infra-skills/ai-generate", json=valid_request()).json()
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/infra-skills/drafts/from-ai",
        headers={"Idempotency-Key": "generate-case-1"},
        json={
            "generation_id": generated["generation_id"],
            "proposal_hash": generated["proposal_hash"],
            "skill_id": "deductible_explain",
            "skill_name": "起付线解释",
            "structured_config": generated["structured_config"],
            "raw_files": generated["raw_files"],
        },
    )
    assert response.status_code == 201
    assert response.json()["source_type"] == "ai_generated"
    assert draft_storage.count() == 1
```

- [ ] **Step 2: 运行 API 测试并确认端点为 404**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_skill_draft_api.py -q --tb=short`

Expected: FAIL，新端点返回 404。

- [ ] **Step 3: 实现 DI、标准错误和原子接受**

新增 `get_skill_ai_authoring_service` 依赖，测试通过 `app.dependency_overrides` 注入 fake。端点声明顺序必须位于 `/{skill_id}` 动态路由之前：

```text
POST /infra-skills/ai-generate
POST /infra-skills/drafts/from-ai
```

生成服务把 `generation_id + proposal_hash + metric snapshots + provenance` 写入现有审计证据存储；接受逻辑先用 generation_id 读取服务端证据，再在 `draft_service.create_from_ai` 内重新计算 proposal hash、复验指标、重新扫描、保存 `AI_GENERATED` 草稿，并将 provenance 序列化到 `raw_files["__generation_meta__.json"]`。`SkillPackageGenerator` 必须继续忽略 `__` 前缀文件。幂等键复用现有 `_idempotent_release_mutation` 的缓存与冲突语义，不复制另一套不一致规则。

- [ ] **Step 4: 执行 T1 后再执行 API 测试**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_service.py src/tests/unit/runtime/skill_management/test_ai_authoring_security.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_skill_draft_api.py -q --tb=short`

Expected: 两阶段 PASS。

Commit: `feat: expose skill ai generation api`

### Task 5: 在新建向导接入 AI 生成与手工降级

**Files:**
- Modify: `src/apps/portal/src/lib/skill-draft-api.ts`
- Modify: `src/apps/portal/app/skills/new/page.tsx`
- Create: `src/apps/portal/src/components/skills/skill-draft-preview.tsx`
- Modify: `src/apps/portal/src/tests/skill-draft-api.test.ts`
- Modify: `src/apps/portal/src/tests/skill-new-wizard.test.tsx`
- Create: `src/apps/portal/src/tests/skill-draft-preview.test.tsx`

- [ ] **Step 1: 写前端失败测试**

锁定用户故事：选择 AI 创建 → 输入目标与指标 → 预览 proposal 的脚本/Schema/prompt/来源 → 接受后跳转草稿编辑页；生成失败保留输入并允许切回手工创建；按钮 loading 时不可重复提交。

```tsx
it("accepts an AI proposal and opens the created draft", async () => {
  render(<NewSkillPage />);
  await user.click(screen.getByRole("button", { name: "AI 创建" }));
  await user.type(screen.getByLabelText("能力说明"), "解释医保结算中的起付线计算");
  await user.click(screen.getByRole("button", { name: "生成候选" }));
  expect(await screen.findByText("生成来源与风险提示")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "接受为草稿" }));
  expect(mockPush).toHaveBeenCalledWith("/skills/draft-ai-1/edit");
});
```

- [ ] **Step 2: 运行 Vitest 并确认新交互不存在**

Run: `npm exec vitest run src/tests/skill-draft-api.test.ts src/tests/skill-new-wizard.test.tsx src/tests/skill-draft-preview.test.tsx`（workdir: `src/apps/portal`）

Expected: FAIL。

- [ ] **Step 3: 实现 API 客户端和向导状态**

API 客户端必须发送 `Idempotency-Key`，不得把服务端 provenance 在浏览器端重新计算。页面状态使用显式联合：`manual | ai_input | ai_generating | ai_preview | ai_error`。`SkillDraftPreview` 按白名单路径展示 assembler、Schema、prompt 和派生配置，清楚标注“尚未进入运行时”，并展示 validation preview、citations、uncertainties、安全扫描摘要和冻结指标版本。

- [ ] **Step 4: 运行 Vitest、目标 ESLint 和 build**

Run 1: `npm exec vitest run src/tests/skill-draft-api.test.ts src/tests/skill-new-wizard.test.tsx src/tests/skill-draft-preview.test.tsx`

Run 2: `npm exec eslint app/skills/new/page.tsx src/components/skills/skill-draft-preview.tsx src/lib/skill-draft-api.ts src/lib/types.ts src/tests/skill-draft-api.test.ts src/tests/skill-new-wizard.test.tsx src/tests/skill-draft-preview.test.tsx`

Run 3: `npm run build`

Workdir: `src/apps/portal`

Expected: PASS。

Commit: `feat: create skill drafts with ai`

### Task 6: 基于 revision 生成优化 diff

**Files:**
- Modify: `src/runtime/skill_management/ai_authoring/service.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/tests/unit/runtime/skill_management/test_ai_authoring_service.py`
- Modify: `src/tests/integration/api/test_skill_draft_api.py`

- [ ] **Step 1: 写 stale revision 和 diff 失败测试**

```python
def test_optimize_returns_structured_diff_without_mutating_draft() -> None:
    before = draft_storage.get("draft-1")
    proposal = service.optimize("draft-1", description="补充政策引用", expected_revision=before.revision)
    after = draft_storage.get("draft-1")
    assert after == before
    assert proposal.base_revision == before.revision
    assert {item.path for item in proposal.diff} >= {"prompt_template.yaml"}


def test_optimize_rejects_stale_revision(client: TestClient) -> None:
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/infra-skills/drafts/draft-1/ai-optimize",
        json={"description": "补充政策引用", "metric_codes": ["deductible_amount"], "expected_revision": 1},
    )
    assert response.status_code == 409
```

- [ ] **Step 2: 运行测试并确认缺少 optimize 行为**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_service.py src/tests/integration/api/test_skill_draft_api.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现只读优化和显式接受端点**

新增 `POST /infra-skills/drafts/{draft_id}/ai-optimize`。优化请求携带 `description + metric_codes + expected_revision`；服务端读取当前草稿、校验指标版本、调用 `scene=skill_authoring` 且记录 `operation=optimize`，返回带 `base_revision` 的文件级和字段级 diff，但不写存储。用户接受时复用现有 `PATCH /infra-skills/drafts/{draft_id}`，提交 proposal 内容和原 `expected_revision`；`save_draft` 原子更新并将状态恢复为 editing。冲突统一返回 409 和 `audit_event`。

- [ ] **Step 4: 运行 T1 与 T2a**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_service.py src/tests/unit/runtime/skill_management/test_draft_service.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_skill_draft_api.py -q --tb=short`

Expected: PASS。

Commit: `feat: optimize skill drafts with revision checks`

### Task 7: 在编辑页展示并接受优化 diff

**Files:**
- Modify: `src/apps/portal/src/lib/skill-draft-api.ts`
- Modify: `src/apps/portal/app/skills/[skillId]/edit/page.tsx`
- Create: `src/apps/portal/src/components/skills/skill-generation-diff.tsx`
- Modify: `src/apps/portal/src/tests/skill-draft-api.test.ts`
- Create: `src/apps/portal/src/tests/skill-generation-diff.test.tsx`

- [ ] **Step 1: 写前端失败测试**

覆盖：输入优化要求后展示 added/changed/removed；接受前草稿编辑器不变化；409 时保留 diff 并提示重新加载；模型失败不清空当前草稿；键盘可访问折叠 diff。

- [ ] **Step 2: 运行 Vitest 并确认失败**

Run: `npm exec vitest run src/tests/skill-draft-api.test.ts src/tests/skill-generation-diff.test.tsx`（workdir: `src/apps/portal`）

Expected: FAIL。

- [ ] **Step 3: 实现局部优化面板**

`SkillGenerationDiff` 仅接收已类型化 proposal、`onAccept` 和 `onDismiss`；不自行发请求。编辑页使用当前 revision 调用 optimize，接受成功后用现有 PATCH 返回的完整草稿替换本地状态，不在客户端手工合并文件。

- [ ] **Step 4: 运行前端验证**

Run 1: `npm exec vitest run src/tests/skill-draft-api.test.ts src/tests/skill-generation-diff.test.tsx src/tests/skill-new-wizard.test.tsx`

Run 2: `npm exec eslint 'app/skills/[skillId]/edit/page.tsx' src/components/skills/skill-generation-diff.tsx src/lib/skill-draft-api.ts src/tests/skill-generation-diff.test.tsx`

Run 3: `npm run build`

Workdir: `src/apps/portal`

Expected: PASS。

Commit: `feat: review skill ai optimization diffs`

### Task 8: 构建不导入运行时的候选制品与隔离评测

**Files:**
- Create: `src/runtime/skill_management/ai_authoring/candidate_evaluation.py`
- Create: `src/runtime/skill_management/ai_authoring/candidate_execution_ports.py`
- Create: `src/runtime/skill_management/ai_authoring/candidate_execution_docker.py`
- Create: `deploy/docker/skill-candidate-runner.Dockerfile`
- Modify: `src/config/production.py`
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Create: `src/tests/unit/runtime/skill_management/test_candidate_evaluation.py`
- Modify: `src/tests/integration/api/test_skill_draft_api.py`

- [ ] **Step 1: 写隔离边界失败测试**

```python
def test_route_evaluation_never_imports_candidate_assembler() -> None:
    service = build_candidate_service(loader=FailIfCalledSkillLoader())
    result = service.evaluate_routes(valid_ai_draft(), route_cases())
    assert result.status == "completed"
    assert result.artifact_hash


def test_behavior_evaluation_stays_blocked_without_sandbox() -> None:
    service = build_candidate_service(executor=DisabledCandidateExecutor())
    result = service.evaluate_behavior(valid_ai_draft(), behavior_cases())
    assert result.status == "blocked_by_evaluator"


def test_candidate_path_is_outside_runtime_skills_root(tmp_path: Path) -> None:
    service = build_candidate_service(candidate_root=tmp_path / "quarantine")
    artifact = service.build_artifact(valid_ai_draft())
    assert not artifact.path.is_relative_to(service.runtime_skills_root)
```

- [ ] **Step 2: 运行测试并确认模块不存在**

Run: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_candidate_evaluation.py -q --tb=short`

Expected: FAIL。

- [ ] **Step 3: 实现候选构建和无导入路由评测**

候选服务调用 `SkillPackageGenerator` 在受控临时目录生成包，校验解析后的绝对路径不位于 production skills root，计算 artifact hash。路由评测只读取生成后的 manifest/config 快照并调用现有 `evaluate_route_suite`，不得调用 `SkillLoader.discover`、动态 import 或 materializer。

- [ ] **Step 4: 实现 fail-closed 行为执行端口与 Docker adapter**

```python
class CandidateExecutionPort(Protocol):
    def execute(
        self,
        artifact: SkillCandidateArtifact,
        request: SkillCandidateBehaviorRequest,
    ) -> SkillCandidateBehaviorResult:
        raise NotImplementedError
```

Docker adapter 固定使用项目维护的 runner image，参数强制包含 `--network none`、`--read-only`、`--cap-drop ALL`、内存/CPU/PID 限制、临时 `tmpfs` 和超时；只挂载候选制品为只读。镜像或 Docker 不可用时返回 `blocked_by_evaluator`，禁止在 API 进程内执行 assembler。

- [ ] **Step 5: 新增候选评测 API 并验证权限**

```text
POST /infra-skills/drafts/{draft_id}/candidate-evaluations/routes
POST /infra-skills/drafts/{draft_id}/candidate-evaluations/behavior
```

两者要求 `skill:evaluate`，返回 artifact hash、case snapshot hash、状态、结果和阻塞原因；日志与 audit event 不记录生成脚本全文。

- [ ] **Step 6: 按 T1 → T2a 顺序验证**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_candidate_evaluation.py src/tests/unit/skill_infra/test_route_evaluator.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_skill_draft_api.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Expected: PASS；无 sandbox 时明确 blocked，绝不宿主执行。

Commit: `feat: evaluate skill candidates in isolation`

### Task 9: 完成端到端验收、可观测性和进度记录

**Files:**
- Modify: `src/observability/metrics/definitions.py`
- Create: `src/tests/integration/flow/test_skill_ai_authoring_flow.py`
- Modify: `src/tests/e2e/pages/portal/skill-catalog.page.ts`
- Create: `src/tests/e2e/flows/portal/skill-ai-authoring.flow.ts`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 写后端 Flow 测试**

完整故事：published 指标 → AI proposal → 接受为草稿 → 校验 → 路由候选评测 → 行为评测走 sandbox fake → 人工物化。另写负向链：危险代码拒绝、未接受 proposal 不产生草稿、不物化、stale revision 409、sandbox 不可用不执行。

- [ ] **Step 2: 增加生成质量与安全指标**

至少记录 `skill_ai_generation_total`、`skill_ai_generation_success_total`、`skill_ai_generation_rejected_total`、`skill_ai_output_parse_failure_total`、`skill_ai_unsafe_code_total`、`skill_ai_manual_accept_total`，标签只允许 scene/status/reason_code，不包含描述、脚本、患者信息或 skill 内容。

- [ ] **Step 3: 严格执行后端三阶段验证**

Run 1: `uv run --frozen python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_ai_authoring_security.py src/tests/unit/runtime/skill_management/test_ai_authoring_service.py src/tests/unit/runtime/skill_management/test_candidate_evaluation.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/api/test_skill_draft_api.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Run 3: `uv run --frozen python -m pytest -p no:asyncio src/tests/integration/flow/test_skill_ai_authoring_flow.py -q --tb=short`

Expected: 三阶段依次 PASS。

- [ ] **Step 4: 写并执行浏览器主链路**

先从工作区根目录运行 `..\ws.ps1 up skill`，再按 `..\ws.ps1 url all` 返回的当前工作区 URL 设置 Playwright base URL。浏览器验证 AI 创建、接受草稿、AI 优化、diff、候选评测状态和 390px 无横向溢出。

Run: `npx playwright test ../../tests/e2e/flows/portal/skill-ai-authoring.flow.ts`（workdir: `src/apps/portal`）

Expected: PASS。结束后从工作区根目录运行 `..\ws.ps1 down skill`。

- [ ] **Step 5: 更新进度与最终提交**

`PROGRESS.md` 记录已完成范围、验证命令、候选 sandbox 的部署前置条件和未纳入本计划的评测挖掘任务。

Commit: `feat: complete skill ai authoring flow`

## 最终回归清单

- [ ] AI 生成与优化仅通过 `ModelGateway`，无直接 Provider/HTTP 调用。
- [ ] proposal、API DTO、前端类型字段一致，无裸 `dict` 响应。
- [ ] 指标必须 published 且冻结对象版本。
- [ ] 未接受 proposal 不写草稿；未人工物化不写 `skills/`。
- [ ] 候选路由评测不 import assembler；行为评测无 sandbox 时 fail closed。
- [ ] 生成脚本、原始用户描述和敏感信息不进入日志、指标标签或 audit event。
- [ ] 权限、幂等、revision、来源哈希和模型 provenance 均有测试。
- [ ] 单元测试、API 测试、Flow、Vitest、ESLint、build、Playwright 均留有通过证据。
