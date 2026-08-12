# Skill Governance Daily Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Portal /skills 从资产详情入口调整为按“评测 → 定位问题 → 修改 → 复审 → 发布”推进的日常治理待办工作台，同时保持既有草稿、评测、审批与 Test Shadow 门禁不变。

**Architecture:** 扩展现有 SkillWorkbenchService 只读投影，从已存在的版本、评测、Release 和草稿事实派生待办阶段、优先级、等待时间和唯一下一步；不新增 Task 表或工作流状态机。Portal 复用现有 API client、URL 状态、草稿页、评测页、发布页和调试抽屉，只重组 /skills 为待办列、决策区和证据轨，并继续让所有写操作经过现有服务端门禁。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、Next.js 16、React 19、TypeScript、Tailwind CSS、Vitest、pytest、Playwright Chromium

---

## 0. 执行边界

- 设计依据：docs/superpowers/specs/2026-08-11-skill-governance-daily-workbench-design.md。
- 本计划是 2026-08-05 Skill Governance Workbench UI Redesign 的增量；已有版本、评测、审批、Test Shadow、草稿、AI 优化和候选隔离评测能力全部复用。
- 风险等级为 R4，验证严格按 T1 → T2a → T2b 执行；任一步失败即停止后续层级。
- 不修改 SkillLoader、SkillRouter、assembler、生产路由算法、治理存储 schema 或发布状态机。
- 不新增写接口、全局状态库、图表库、图标库、第二套品牌或可变治理任务表。
- 工作台降级只能退回现有 catalog；不得把聚合失败伪装成零待办。
- 页面只显示脱敏摘要；问题模板、患者标识、审批理由和完整 hash 不得进入 URL、localStorage、日志或埋点。

## 1. 文件职责

后端：

- Modify: src/runtime/skill_management/workbench_service.py — 派生待办阶段、优先级、等待时间、评测指标、关联草稿和下一步。
- Modify: src/runtime/api/infra_skill_routes.py — 将现有 SkillDraftService 注入工作台，不新增路由。
- Modify: src/tests/unit/runtime/skill_management/test_workbench_service.py — 待办矩阵、排序、草稿关联和安全摘要。
- Modify: src/tests/integration/api/test_infra_skill_workbench_api.py — 扩展 DTO、筛选、兼容和敏感字段边界。

Portal：

- Modify: src/apps/portal/src/lib/types.ts — 新增阶段、优先级和下一步联合类型。
- Modify: src/apps/portal/src/lib/api-client.ts — 追加 priority 查询。
- Modify: src/apps/portal/src/components/skills/skill-primary-action.ts — 只映射服务端 next_action，不再独立推导阶段。
- Modify: src/apps/portal/src/components/skills/skill-governance-workbench.tsx — URL、筛选、局部加载和响应式布局。
- Modify: src/apps/portal/src/components/skills/skill-workbench-header.tsx — 唯一 H1、环境、优先级、刷新和调试。
- Modify: src/apps/portal/src/components/skills/skill-governance-summary.tsx — 从大统计卡改为紧凑队列分组。
- Modify: src/apps/portal/src/components/skills/skill-catalog-panel.tsx — 从资产目录改为治理待办。
- Modify: src/apps/portal/src/components/skills/skill-workspace.tsx — 决策区、指标、失败案例、证据轨和固定下一步。
- Modify: src/apps/portal/src/components/skills/skill-lifecycle-stepper.tsx — 五阶段只读步骤条。
- Create: src/apps/portal/src/components/skills/skill-eval-metric-strip.tsx — 固定四指标。
- Create: src/apps/portal/src/components/skills/skill-regression-table.tsx — 回归、改善和全部案例。
- Create: src/apps/portal/src/components/skills/skill-evidence-rail.tsx — 门禁、冻结证据和最近记录。
- Create: src/apps/portal/src/components/skills/skill-next-action-bar.tsx — 唯一主操作和证据入口。
- Modify: src/apps/portal/app/skills/page.tsx — 删除重复标题和装饰页面壳。
- Modify: src/apps/portal/app/skills/layout.tsx — 整理治理待办、资产、草稿、评测中心、发布记录导航。
- Create: src/apps/portal/app/skills/assets/page.tsx — 正式资产入口。
- Modify: src/apps/portal/src/tests/skill-primary-action.test.ts。
- Modify: src/apps/portal/src/tests/skill-workbench.test.tsx。

流程：

- Modify: src/tests/integration/flow/test_skill_evaluation_release_flow.py。
- Modify: src/tests/e2e/pages/portal/skill-catalog.page.ts。
- Modify: src/tests/e2e/flows/portal/skill-catalog.flow.ts。
- Modify: PROGRESS.md — 全部验证通过后记录 7.9 证据。

---

### Task 1: 扩展工作台只读投影

**Files:**
- Modify: src/runtime/skill_management/workbench_service.py
- Modify: src/tests/unit/runtime/skill_management/test_workbench_service.py

- [ ] **Step 1: 写待办派生和排序的失败测试**

沿用测试文件现有 fixture，增加：

~~~python
def test_failed_evaluation_is_a_blocked_diagnosis() -> None:
    service = _service(
        entries=[_entry("failed-skill")],
        runs={
            "failed-skill": [
                _run(
                    "failed-skill",
                    status="failed",
                    regression_count=2,
                    required_total=3,
                    required_passed=2,
                )
            ]
        },
    )

    item = service.list_workbench(page=1, page_size=20).items[0]

    assert item.current_stage == "diagnose"
    assert item.priority == "blocked"
    assert item.next_action == "create_fix_draft"
    assert item.regression_count == 2
    assert item.required_failure_count == 1
    assert item.next_action_reason == "评测门禁未通过，需要先定位回归案例"


def test_linked_editing_draft_moves_failure_to_modify() -> None:
    service = _service(
        entries=[_entry("editing-skill")],
        runs={"editing-skill": [_run("editing-skill", status="failed")]},
        drafts={"editing-skill": [_draft("draft-1", status="editing")]},
    )

    item = service.list_workbench(page=1, page_size=20).items[0]

    assert item.current_stage == "modify"
    assert item.linked_draft_id == "draft-1"
    assert item.linked_draft_status == "editing"
    assert item.next_action == "continue_draft"


def test_required_failure_sorts_before_other_failure_and_approval() -> None:
    now = datetime(2026, 8, 11, 8, tzinfo=timezone.utc)
    service = _service(
        entries=[_entry("normal-failure"), _entry("required-failure"), _entry("approval")],
        runs={
            "normal-failure": [_run("normal-failure", status="failed", created_at=now)],
            "required-failure": [
                _run(
                    "required-failure",
                    status="failed",
                    required_total=2,
                    required_passed=1,
                    created_at=now,
                )
            ],
        },
        releases={"approval": [_release("approval", "approval_pending", created_at=now)]},
        now=lambda: now,
    )

    page = service.list_workbench(page=1, page_size=20)

    assert [item.skill_id for item in page.items] == [
        "required-failure",
        "normal-failure",
        "approval",
    ]


def test_workbench_projection_has_no_sensitive_evidence() -> None:
    payload = _service(
        entries=[_entry("safe-skill")],
        runs={"safe-skill": [_run("safe-skill", status="failed")]},
    ).list_workbench(page=1, page_size=20).model_dump_json()

    assert "question_template" not in payload
    assert "approval_reason" not in payload
    assert "patient_id" not in payload
~~~

- [ ] **Step 2: 运行测试并确认失败**

~~~powershell
python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_workbench_service.py -q --tb=short
~~~

Expected: FAIL，新增枚举和字段不存在。

- [ ] **Step 3: 增加显式枚举、协议和兼容字段**

在 workbench_service.py 增加：

~~~python
class SkillGovernanceStage(StrEnum):
    EVALUATE = "evaluate"
    DIAGNOSE = "diagnose"
    MODIFY = "modify"
    REVIEW = "review"
    RELEASE = "release"
    HEALTHY = "healthy"


class SkillGovernancePriority(StrEnum):
    BLOCKED = "blocked"
    HIGH = "high"
    NORMAL = "normal"


class SkillNextAction(StrEnum):
    REGISTER_VERSION = "register_version"
    RUN_EVALUATION = "run_evaluation"
    CREATE_FIX_DRAFT = "create_fix_draft"
    CONTINUE_DRAFT = "continue_draft"
    MATERIALIZE_DRAFT = "materialize_draft"
    CREATE_CANDIDATE = "create_candidate"
    REQUEST_APPROVAL = "request_approval"
    REVIEW_APPROVAL = "review_approval"
    ACTIVATE_TEST_SHADOW = "activate_test_shadow"
    VIEW_EVIDENCE = "view_evidence"


class _DraftView(Protocol):
    def list_drafts(self, *, skill_id: str | None = None, **kwargs) -> list: ...
~~~

给 SkillWorkbenchItem 追加：

~~~python
current_stage: SkillGovernanceStage = SkillGovernanceStage.EVALUATE
priority: SkillGovernancePriority = SkillGovernancePriority.NORMAL
latest_eval_run_id: str | None = None
candidate_version: str | None = None
baseline_version: str | None = None
regression_count: int = 0
required_failure_count: int = 0
linked_draft_id: str | None = None
linked_draft_status: str | None = None
waiting_since: datetime
next_action: SkillNextAction = SkillNextAction.RUN_EVALUATION
next_action_reason: str | None = None
~~~

构造函数增加可选 draft_service，保持旧调用兼容。

- [ ] **Step 4: 实现单一派生入口**

新增 _derive_workflow，并按以下优先级返回 stage、priority、action、reason、waiting_since：

1. failed/error 或必测未全过，存在 editing/validated 草稿 → modify，continue_draft/materialize_draft；
2. failed/error 或必测未全过，无草稿 → diagnose，blocked，create_fix_draft；
3. approval_pending → review，review_approval；
4. approved → release，activate_test_shadow；
5. candidate → review，request_approval；
6. active → healthy，view_evidence；
7. passed 且无 release → release，create_candidate；
8. 制品未登记或 changed → modify，register_version；
9. 其余 → evaluate，run_evaluation。

实现必须从 latest_run.metrics 读取 regression_count 和 required failure，从 baseline_version_id 读取基线，从最新 editing/validated 草稿读取关联信息。不得读取案例正文或审批理由。

排序键固定为：

~~~python
filtered_items.sort(
    key=lambda item: (
        _ACTION_ORDER[item.next_action],
        0 if item.required_failure_count > 0 else 1,
        item.waiting_since,
        item.skill_id,
    )
)
~~~

- [ ] **Step 5: 运行单元测试并提交**

~~~powershell
python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_workbench_service.py -q --tb=short
git add src/runtime/skill_management/workbench_service.py src/tests/unit/runtime/skill_management/test_workbench_service.py
git commit -m "feat: derive skill governance queue state"
~~~

Expected: PASS。

---

### Task 2: 接入草稿事实并锁定 API 契约

**Files:**
- Modify: src/runtime/api/infra_skill_routes.py
- Modify: src/tests/integration/api/test_infra_skill_workbench_api.py

- [ ] **Step 1: 写 DTO、筛选和兼容失败测试**

~~~python
def test_skill_workbench_returns_daily_projection() -> None:
    response = _client_with_in_memory_dependencies().get(
        f"{PREFIX}/infra-skills/workbench?priority=blocked"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert {
        "current_stage",
        "priority",
        "latest_eval_run_id",
        "candidate_version",
        "baseline_version",
        "regression_count",
        "required_failure_count",
        "linked_draft_id",
        "linked_draft_status",
        "waiting_since",
        "next_action",
        "next_action_reason",
    }.issubset(item)


def test_skill_workbench_keeps_old_fields_and_hides_sensitive_values() -> None:
    response = _client_with_in_memory_dependencies().get(
        f"{PREFIX}/infra-skills/workbench?page=1&page_size=20"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert {"governance_status", "attention_reason", "test_release_status"}.issubset(item)
    assert "question_template" not in response.text
    assert "approval_reason" not in response.text
    assert "patient_id" not in response.text
~~~

- [ ] **Step 2: 运行 API 测试并确认失败**

~~~powershell
python -m pytest -p no:asyncio src/tests/integration/api/test_infra_skill_workbench_api.py -q --tb=short
~~~

Expected: FAIL，priority 或新字段不存在。

- [ ] **Step 3: 复用现有依赖注入**

修改工厂：

~~~python
def get_skill_workbench_service(
    version_service: SkillVersionServiceDependency,
    governance_service: SkillGovernanceServiceDependency,
    draft_service: SkillDraftServiceDependency,
) -> SkillWorkbenchService:
    return SkillWorkbenchService(
        version_service,
        governance_service,
        draft_service=draft_service,
    )
~~~

GET /infra-skills/workbench 增加可选 priority: SkillGovernancePriority，并在分页前筛选。保留 path、旧筛选和响应字段，不新增写路由。

- [ ] **Step 4: 严格运行 T1，再运行 T2a**

~~~powershell
python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_workbench_service.py -q --tb=short
python -m pytest -p no:asyncio src/tests/integration/api/test_infra_skill_workbench_api.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short
~~~

Expected: 依次 PASS。

- [ ] **Step 5: 提交**

~~~powershell
git add src/runtime/api/infra_skill_routes.py src/tests/integration/api/test_infra_skill_workbench_api.py
git commit -m "feat: expose skill governance queue projection"
~~~

---

### Task 3: 让 Portal 只消费服务端下一步

**Files:**
- Modify: src/apps/portal/src/lib/types.ts
- Modify: src/apps/portal/src/lib/api-client.ts
- Modify: src/apps/portal/src/components/skills/skill-primary-action.ts
- Modify: src/apps/portal/src/tests/skill-primary-action.test.ts
- Modify: src/apps/portal/src/tests/skill-catalog.test.ts

- [ ] **Step 1: 写动作映射失败测试**

~~~typescript
it.each([
  ['register_version', 'navigate', 'versions'],
  ['run_evaluation', 'run_evaluation', 'evaluation'],
  ['create_fix_draft', 'navigate', 'development'],
  ['continue_draft', 'navigate', 'development'],
  ['materialize_draft', 'navigate', 'development'],
  ['create_candidate', 'create_candidate', 'release'],
  ['request_approval', 'request_approval', 'release'],
  ['review_approval', 'approve', 'release'],
  ['activate_test_shadow', 'activate', 'release'],
  ['view_evidence', 'none', 'overview'],
] as const)(
  'maps server next_action %s',
  (nextAction, expectedKind, expectedTab) => {
    const action = computePrimaryAction(
      { ...baseItem, next_action: nextAction },
      [],
      [],
      [],
    )
    expect(action.kind).toBe(expectedKind)
    expect(action.targetTab).toBe(expectedTab)
  },
)
~~~

在 API client 测试断言 priority=blocked 被 URL 编码。

- [ ] **Step 2: 运行并确认失败**

~~~powershell
npm exec vitest run src/tests/skill-primary-action.test.ts src/tests/skill-catalog.test.ts
~~~

Workdir: src/apps/portal。Expected: FAIL。

- [ ] **Step 3: 扩展 TypeScript 契约**

~~~typescript
export type SkillGovernanceStage =
  | 'evaluate'
  | 'diagnose'
  | 'modify'
  | 'review'
  | 'release'
  | 'healthy'

export type SkillGovernancePriority = 'blocked' | 'high' | 'normal'

export type SkillNextAction =
  | 'register_version'
  | 'run_evaluation'
  | 'create_fix_draft'
  | 'continue_draft'
  | 'materialize_draft'
  | 'create_candidate'
  | 'request_approval'
  | 'review_approval'
  | 'activate_test_shadow'
  | 'view_evidence'
~~~

给 SkillWorkbenchItem 增加后端同名字段，给 SkillWorkbenchFilter 增加 priority。api-client.ts 只追加：

~~~typescript
if (filter.priority) params.set('priority', filter.priority)
~~~

- [ ] **Step 4: 用单表映射替换前端业务推导**

~~~typescript
const ACTIONS: Record<SkillNextAction, PrimaryAction> = {
  register_version: { kind: 'navigate', label: '登记当前版本', hint: '当前制品尚未登记或已发生变更', targetTab: 'versions' },
  run_evaluation: { kind: 'run_evaluation', label: '运行候选评测', hint: '使用当前登记版本运行固定评测', targetTab: 'evaluation' },
  create_fix_draft: { kind: 'navigate', label: '创建修复草稿', hint: '从失败证据进入可审阅修改', targetTab: 'development' },
  continue_draft: { kind: 'navigate', label: '继续修改', hint: '打开已关联修复草稿', targetTab: 'development' },
  materialize_draft: { kind: 'navigate', label: '人工物化', hint: '草稿已校验，需要人工确认物化', targetTab: 'development' },
  create_candidate: { kind: 'create_candidate', label: '创建发布候选', hint: '固定评测已通过', targetTab: 'release' },
  request_approval: { kind: 'request_approval', label: '申请复审', hint: '发布候选已就绪', targetTab: 'release' },
  review_approval: { kind: 'approve', label: '进入人工复审', hint: '禁止创建人自审', targetTab: 'release' },
  activate_test_shadow: { kind: 'activate', label: '激活 Test Shadow', hint: '复审已通过', targetTab: 'release' },
  view_evidence: { kind: 'none', label: '查看运行证据', hint: 'Test Shadow 已激活', targetTab: 'overview' },
}

export function computePrimaryAction(
  item: SkillWorkbenchItem,
  _versions: SkillVersionResponse[],
  _evalRuns: SkillEvalRunResponse[],
  _releases: SkillReleaseResponse[],
): PrimaryAction {
  return ACTIONS[item.next_action]
}
~~~

保留后三个兼容参数，避免扩大当前 diff；不再用它们推导阶段。

- [ ] **Step 5: 运行测试、ESLint 并提交**

~~~powershell
npm exec vitest run src/tests/skill-primary-action.test.ts src/tests/skill-catalog.test.ts
npm exec eslint src/lib/types.ts src/lib/api-client.ts src/components/skills/skill-primary-action.ts src/tests/skill-primary-action.test.ts src/tests/skill-catalog.test.ts
git add src/lib/types.ts src/lib/api-client.ts src/components/skills/skill-primary-action.ts src/tests/skill-primary-action.test.ts src/tests/skill-catalog.test.ts
git commit -m "refactor: consume server skill governance actions"
~~~

Workdir: src/apps/portal。Expected: PASS。

---

### Task 4: 落地治理待办和响应式页面骨架

**Files:**
- Modify: src/apps/portal/app/skills/layout.tsx
- Modify: src/apps/portal/app/skills/page.tsx
- Create: src/apps/portal/app/skills/assets/page.tsx
- Modify: src/apps/portal/src/components/skills/skill-governance-workbench.tsx
- Modify: src/apps/portal/src/components/skills/skill-workbench-header.tsx
- Modify: src/apps/portal/src/components/skills/skill-governance-summary.tsx
- Modify: src/apps/portal/src/components/skills/skill-catalog-panel.tsx
- Modify: src/apps/portal/src/tests/skill-workbench.test.tsx

- [ ] **Step 1: 写页面结构和移动导航失败测试**

~~~typescript
it('renders one heading and the daily governance queue', async () => {
  render(<SkillGovernanceWorkbench />)
  expect(await screen.findByRole('heading', { level: 1, name: 'Skill 日常治理' })).toBeVisible()
  expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
  expect(screen.getByRole('navigation', { name: '治理待办' })).toBeVisible()
})

it('writes priority and selection to URL without evidence text', async () => {
  const user = userEvent.setup()
  render(<SkillGovernanceWorkbench />)
  await user.selectOptions(await screen.findByLabelText('优先级'), 'blocked')
  await user.click(screen.getByTestId('skill-catalog-item-settlement_explain_skill'))
  expect(window.location.search).toContain('priority=blocked')
  expect(window.location.search).toContain('skill=settlement_explain_skill')
  expect(window.location.search).not.toContain('question_template')
})

it('uses list and detail navigation on mobile', async () => {
  const user = userEvent.setup()
  render(<SkillGovernanceWorkbench />)
  await user.click(await screen.findByTestId('skill-catalog-item-settlement_explain_skill'))
  expect(screen.getByRole('button', { name: '返回治理待办' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: '返回治理待办' }))
  expect(screen.getByRole('navigation', { name: '治理待办' })).toBeVisible()
})
~~~

- [ ] **Step 2: 运行并确认失败**

~~~powershell
npm exec vitest run src/tests/skill-workbench.test.tsx
~~~

Workdir: src/apps/portal。Expected: FAIL。

- [ ] **Step 3: 收敛页面壳和导航**

app/skills/page.tsx 只返回 SkillGovernanceWorkbench。layout.tsx 删除光斑、网格和 backdrop blur，导航固定为：

~~~typescript
const NAV_TABS: NavTab[] = [
  { label: '治理待办', href: '/skills', match: (path) => path === '/skills' },
  { label: 'Skill 资产', href: '/skills/assets', match: (path) => path.startsWith('/skills/assets') || isSkillDetailPath(path) },
  { label: '草稿', href: '/skills/drafts', match: (path) => path.startsWith('/skills/drafts') },
  { label: '评测中心', href: '/skills/evaluations', match: (path) => path.startsWith('/skills/evaluations') || path.startsWith('/skills/eval-') },
  { label: '发布记录', href: '/skills/releases', match: (path) => path.startsWith('/skills/releases') },
]
~~~

将 assets 加入 RESERVED_SEGS。assets/page.tsx 复用现有 catalog 和详情路由，不复制治理写动作。

- [ ] **Step 4: 扩展工作台 URL 和工具栏**

WorkbenchUrlState 增加 priority，白名单仅 blocked/high/normal；replaceWorkbenchUrl 写入 priority。Header 输出唯一 H1“Skill 日常治理”，同一行提供 test/dev、优先级、路由调试和刷新。

SkillGovernanceSummary 改为 40px 紧凑分组条，不再显示 80px 大统计卡。

- [ ] **Step 5: 将目录项改为待办项**

SkillCatalogPanel 使用 aria-label="治理待办"，每项只显示：

- Skill 名称；
- current_stage 对应的一个状态；
- next_action_reason；
- candidate_version 或 linked_draft_status；
- waiting_since 相对时间。

保留上下键、Enter、aria-current、250ms 搜索、防抖和 catalog fallback。空队列提供“查看全部资产”。

纯函数：

~~~typescript
export function waitingLabel(waitingSince: string, now = Date.now()): string {
  const hours = Math.max(Math.floor((now - Date.parse(waitingSince)) / 3_600_000), 0)
  if (hours < 1) return '刚刚进入待办'
  if (hours < 24) return '等待 ' + hours + ' 小时'
  return '等待 ' + Math.floor(hours / 24) + ' 天'
}
~~~

- [ ] **Step 6: 运行 Vitest、ESLint、build 并提交**

~~~powershell
npm exec vitest run src/tests/skill-workbench.test.tsx src/tests/skill-catalog.test.ts
npm exec eslint app/skills/layout.tsx app/skills/page.tsx app/skills/assets/page.tsx src/components/skills/skill-governance-workbench.tsx src/components/skills/skill-workbench-header.tsx src/components/skills/skill-governance-summary.tsx src/components/skills/skill-catalog-panel.tsx src/tests/skill-workbench.test.tsx
npm run build
git add app/skills src/components/skills/skill-governance-workbench.tsx src/components/skills/skill-workbench-header.tsx src/components/skills/skill-governance-summary.tsx src/components/skills/skill-catalog-panel.tsx src/tests/skill-workbench.test.tsx
git commit -m "feat: make skill governance queue the daily entry"
~~~

Workdir: src/apps/portal。Expected: PASS。

---

### Task 5: 构建评测决策区和证据轨

**Files:**
- Modify: src/apps/portal/src/components/skills/skill-workspace.tsx
- Modify: src/apps/portal/src/components/skills/skill-lifecycle-stepper.tsx
- Create: src/apps/portal/src/components/skills/skill-eval-metric-strip.tsx
- Create: src/apps/portal/src/components/skills/skill-regression-table.tsx
- Create: src/apps/portal/src/components/skills/skill-evidence-rail.tsx
- Create: src/apps/portal/src/components/skills/skill-next-action-bar.tsx
- Modify: src/apps/portal/src/tests/skill-workbench.test.tsx

- [ ] **Step 1: 写决策区和局部失败测试**

~~~typescript
it('shows candidate versus baseline metrics and regression cases', async () => {
  render(<SkillGovernanceWorkbench />)
  expect(await screen.findByText('候选通过率')).toBeVisible()
  expect(screen.getByText('活动基线通过率')).toBeVisible()
  expect(screen.getByText('新增回归')).toBeVisible()
  expect(screen.getByText('必测通过数')).toBeVisible()
  expect(screen.getByRole('table', { name: '评测差异案例' })).toBeVisible()
})

it('keeps queue and loaded evidence when one request fails', async () => {
  mockListSkillReleases.mockRejectedValueOnce(new Error('release unavailable'))
  render(<SkillGovernanceWorkbench />)
  expect(await screen.findByRole('navigation', { name: '治理待办' })).toBeVisible()
  expect(screen.getByRole('alert')).toHaveTextContent('release unavailable')
  expect(screen.getByText('候选通过率')).toBeVisible()
})

it('renders one primary action from service reason', async () => {
  render(<SkillGovernanceWorkbench />)
  expect(await screen.findByText('评测门禁未通过，需要先定位回归案例')).toBeVisible()
  expect(screen.getAllByTestId('skill-primary-action')).toHaveLength(1)
})
~~~

- [ ] **Step 2: 运行并确认失败**

~~~powershell
npm exec vitest run src/tests/skill-workbench.test.tsx
~~~

Workdir: src/apps/portal。Expected: FAIL。

- [ ] **Step 3: 将步骤条改为五阶段纯映射**

~~~typescript
const STAGES = [
  ['evaluate', '评测'],
  ['diagnose', '定位问题'],
  ['modify', '修改'],
  ['review', '复审'],
  ['release', '发布'],
] as const

export function lifecycleSteps(item: SkillWorkbenchItem): LifecycleStep[] {
  if (item.current_stage === 'healthy') {
    return STAGES.map(([stage, label]) => ({ stage, label, state: 'completed' }))
  }
  const current = STAGES.findIndex(([stage]) => stage === item.current_stage)
  return STAGES.map(([stage, label], index) => ({
    stage,
    label,
    state: index < current ? 'completed' : index === current ? 'current' : 'pending',
  }))
}
~~~

用 ol aria-label="Skill 治理阶段"，每步同时输出状态文字。

- [ ] **Step 4: 实现固定四指标**

SkillEvalMetricStrip 只接收最新 SkillEvalRunResponse。候选通过率使用 passed/total，基线缺失显示“无活动基线”，新增回归使用 regression_count，必测使用 required_passed/required_total。不得把无基线显示为 0%。

- [ ] **Step 5: 实现失败案例和证据轨**

SkillRegressionTable 默认过滤 new_failure、route_changed、unchanged_fail；改善视图只看 new_pass；全部不筛选。桌面为 table aria-label="评测差异案例"，移动端为同数据摘要列表。只展示脱敏摘要、required/risk tag、candidate/baseline、confidence、现有 diff 和 failure code。

SkillEvidenceRail 顺序固定为门禁结论、冻结证据、最近记录。hash 使用：

~~~typescript
export function shortHash(value: string | null | undefined): string {
  return value && value.length > 12
    ? value.slice(0, 6) + '…' + value.slice(-6)
    : value ?? '—'
}
~~~

审批理由不显示。

- [ ] **Step 6: 组合工作区和固定下一步**

保留现有 Promise.allSettled(detail, versions, eval-runs, releases)。详情局部失败只更新对应 error，不清空队列或其他证据。布局：

~~~tsx
<section className="grid min-h-0 xl:grid-cols-[minmax(0,1fr)_320px]">
  <div className="min-w-0">
    <SkillDecisionHeader item={item} detail={detail} />
    <SkillLifecycleStepper item={item} />
    <SkillEvalMetricStrip run={latestRun} />
    <SkillRegressionTable run={latestRun} onViewEvidence={() => setEvidenceOpen(true)} />
    <SkillNextActionBar
      action={primaryAction}
      reason={item.next_action_reason}
      busy={actionBusy}
      error={actionError}
      onRun={() => void runPrimary()}
      onViewEvidence={() => setEvidenceOpen(true)}
    />
  </div>
  <SkillEvidenceRail item={item} run={latestRun} releases={releases} errors={errors} />
</section>
~~~

900–1119px 隐藏证据轨并使用现有 Drawer；移动端 Drawer 全屏。SkillNextActionBar 只渲染一个 data-testid="skill-primary-action" 写按钮，证据按钮是只读次操作。

- [ ] **Step 7: 运行测试、ESLint、build 并提交**

~~~powershell
npm exec vitest run src/tests/skill-workbench.test.tsx src/tests/skill-primary-action.test.ts
npm exec eslint src/components/skills/skill-workspace.tsx src/components/skills/skill-lifecycle-stepper.tsx src/components/skills/skill-eval-metric-strip.tsx src/components/skills/skill-regression-table.tsx src/components/skills/skill-evidence-rail.tsx src/components/skills/skill-next-action-bar.tsx src/tests/skill-workbench.test.tsx
npm run build
git add src/components/skills src/tests/skill-workbench.test.tsx
git commit -m "feat: add skill evaluation decision workspace"
~~~

Workdir: src/apps/portal。Expected: PASS。

---

### Task 6: 串起修改、复审和发布闭环

**Files:**
- Modify: src/apps/portal/src/components/skills/skill-workspace.tsx
- Modify: src/apps/portal/src/tests/skill-workbench.test.tsx
- Modify: src/tests/integration/flow/test_skill_evaluation_release_flow.py

- [ ] **Step 1: 写草稿路由和门禁失败测试**

~~~typescript
it.each([
  ['create_fix_draft', '/skills/new?source=settlement_explain_skill'],
  ['continue_draft', '/skills/drafts?draft=draft-1'],
  ['materialize_draft', '/skills/drafts?draft=draft-1'],
] as const)('routes %s into existing draft workflow', async (nextAction, href) => {
  mockGetSkillGovernanceWorkbench.mockResolvedValueOnce({
    ...workbenchResponse,
    items: [{
      ...workbenchResponse.items[0],
      next_action: nextAction,
      linked_draft_id: 'draft-1',
    }],
  })
  const user = userEvent.setup()
  render(<SkillGovernanceWorkbench />)
  await user.click(await screen.findByTestId('skill-primary-action'))
  expect(mockRouterPush).toHaveBeenCalledWith(href)
})

it('keeps evidence when activation returns gate conflict', async () => {
  mockActivateSkillRelease.mockRejectedValueOnce(new Error('证据已变化，请重新评测'))
  const user = userEvent.setup()
  render(<SkillGovernanceWorkbench />)
  await user.click(await screen.findByTestId('skill-primary-action'))
  expect(await screen.findByRole('alert')).toHaveTextContent('证据已变化，请重新评测')
  expect(screen.getByRole('table', { name: '评测差异案例' })).toBeVisible()
})
~~~

- [ ] **Step 2: 复用既有路由，不新增写接口**

runPrimary 先处理三个草稿导航动作：

~~~typescript
if (item.next_action === 'create_fix_draft') {
  router.push('/skills/new?source=' + encodeURIComponent(item.skill_id))
  return
}
if (item.next_action === 'continue_draft' || item.next_action === 'materialize_draft') {
  if (!item.linked_draft_id) throw new Error('关联草稿不存在，请刷新治理待办')
  router.push('/skills/drafts?draft=' + encodeURIComponent(item.linked_draft_id))
  return
}
~~~

其余 run_evaluation、create_candidate、request_approval、approve 和 activate 保留现有 API、revision、幂等键和服务端错误处理。成功后局部刷新当前 Skill 和 workbench 汇总，不使用整页 reload。

- [ ] **Step 3: 扩展 Flow 断言读模型随领域事实变化**

~~~python
def _workbench_item(client, skill_id: str) -> dict:
    response = client.get(f"{PREFIX}/infra-skills/workbench?query={skill_id}")
    assert response.status_code == 200
    return next(
        item for item in response.json()["items"]
        if item["skill_id"] == skill_id
    )
~~~

在现有 flow 中依次断言：

~~~python
assert _workbench_item(client, skill_id)["next_action"] == "run_evaluation"
# passed eval 后
assert _workbench_item(client, skill_id)["next_action"] == "create_candidate"
# request approval 后
assert _workbench_item(client, skill_id)["next_action"] == "review_approval"
# approve 后
assert _workbench_item(client, skill_id)["next_action"] == "activate_test_shadow"
# activate 后
assert _workbench_item(client, skill_id)["current_stage"] == "healthy"
~~~

- [ ] **Step 4: 严格运行 T1 → T2a → T2b**

~~~powershell
python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_workbench_service.py -q --tb=short
python -m pytest -p no:asyncio src/tests/integration/api/test_infra_skill_workbench_api.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short
python -m pytest -p no:asyncio src/tests/integration/flow/test_skill_evaluation_release_flow.py -q --tb=short
~~~

Expected: 依次 PASS。

- [ ] **Step 5: 运行 Portal 回归并提交**

~~~powershell
npm exec vitest run src/tests/skill-workbench.test.tsx src/tests/skill-primary-action.test.ts src/tests/skill-governance.test.ts
npm run build
git add src/components/skills/skill-workspace.tsx src/tests/skill-workbench.test.tsx ../../tests/integration/flow/test_skill_evaluation_release_flow.py
git commit -m "feat: close the skill governance daily loop"
~~~

Workdir: src/apps/portal。Expected: PASS。

---

### Task 7: E2E、视觉验收和进度证据

**Files:**
- Modify: src/tests/e2e/pages/portal/skill-catalog.page.ts
- Modify: src/tests/e2e/flows/portal/skill-catalog.flow.ts
- Modify: PROGRESS.md

- [ ] **Step 1: 更新页面对象**

~~~typescript
readonly queue = this.page.getByRole('navigation', { name: '治理待办' })
readonly title = this.page.getByRole('heading', { level: 1, name: 'Skill 日常治理' })
readonly lifecycle = this.page.getByRole('list', { name: 'Skill 治理阶段' })
readonly regressionTable = this.page.getByRole('table', { name: '评测差异案例' })
readonly primaryAction = this.page.getByTestId('skill-primary-action')
readonly evidence = this.page.getByRole('complementary', { name: '治理证据' })
~~~

保留已有 registerCurrentVersion、runFixedEvaluation 和 approveAndActivateTestRelease helper，只把选择入口改为 queue item。

- [ ] **Step 2: 扩展桌面闭环 E2E**

~~~typescript
test('从评测待办推进到 Test Shadow', async ({ page }) => {
  const workbench = new SkillCatalogPage(page)
  await workbench.goto()
  await expect(workbench.title).toBeVisible()
  await workbench.selectSkill('settlement_explain_skill')
  await expect(workbench.regressionTable).toBeVisible()
  await workbench.registerCurrentVersion('settlement_explain_skill')
  await workbench.runFixedEvaluation('统筹自付为什么这么多')
  await workbench.approveAndActivateTestRelease()
  await expect(workbench.lifecycle).toContainText('发布')
  await expect(page.getByText('Test Shadow 已激活')).toBeVisible()
})
~~~

保留刷新恢复、调试抽屉上下文和目录键盘导航测试。

- [ ] **Step 3: 增加响应式和可访问性断言**

- 1440×1000：三栏可见，无页面级横向滚动。
- 1024×900：待办和决策区可见，证据通过抽屉打开。
- 390×844：先显示待办，选择后显示全宽详情和“返回治理待办”；H1 不逐字换行，主按钮可见，无页面级横向滚动。
- 键盘：上下键移动待办，Enter 打开，主按钮和证据按钮可聚焦。
- 200% 缩放：主任务仍可完成。

- [ ] **Step 4: 使用中央脚本启动当前工作区**

~~~powershell
..\ws.ps1 restart skill
..\ws.ps1 list
..\ws.ps1 url all
~~~

确认当前前后端端口健康；不得直接运行 start-servers.ps1、uvicorn 或 npm run dev。

- [ ] **Step 5: 运行 Chromium E2E 和批量视觉检查**

~~~powershell
npx playwright test flows/portal/skill-catalog.flow.ts --project=chromium
~~~

Workdir: src/tests/e2e。Expected: PASS，控制台无新增错误。

随后检查完成态、加载态、空态、详情局部错误、403、409、长文案和高风险失败；执行一次 Impeccable 扫描，以实际渲染为准修复阻断项。

- [ ] **Step 6: 最终质量门禁**

~~~powershell
python -m pytest -p no:asyncio src/tests/unit/runtime/skill_management/test_workbench_service.py -q --tb=short
python -m pytest -p no:asyncio src/tests/integration/api/test_infra_skill_workbench_api.py src/tests/integration/api/test_infra_skill_routes.py -q --tb=short
python -m pytest -p no:asyncio src/tests/integration/flow/test_skill_evaluation_release_flow.py -q --tb=short
~~~

然后在 src/apps/portal：

~~~powershell
npm test
npm run lint
npm run build
~~~

Expected: 全部 PASS，零新增 LSP/ESLint 错误。

- [ ] **Step 7: 更新进度并提交证据**

在 PROGRESS.md 增加 7.9：

~~~text
7.9 Skill 日常治理工作台：由既有版本、评测、Release 和草稿事实派生治理待办，默认主链为评测→定位问题→修改→复审→Test Shadow 发布；无第二套可变状态机。
~~~

记录实际 T1、T2a、T2b、Vitest、ESLint、build、Chromium E2E 数字、工作区端口和回滚边界。回滚只恢复旧 /skills 页面编排和停止消费新增只读字段；既有版本、评测、草稿和发布证据不受影响。

~~~powershell
git add src/tests/e2e/pages/portal/skill-catalog.page.ts src/tests/e2e/flows/portal/skill-catalog.flow.ts PROGRESS.md
git commit -m "test: verify skill governance daily workbench"
~~~

---

## 2. 计划自检

- 六类待办均有后端派生规则；healthy 只是完成态，不制造新领域状态。
- next_action 由后端唯一派生；前端只映射现有写动作或导航。
- 草稿复用 SkillDraftService.list_drafts，回归指标复用 SkillEvalRun.metrics 和 regression_summary。
- 后端新增字段均为 Pydantic 类型，前端字段使用显式联合类型。
- 旧 governance_status、attention_reason、catalog、detail、eval、release、draft 和 regression 接口保持兼容。
- 页面只有一个 H1；默认是治理待办，资产进入 /skills/assets，案例池和案例挖掘归入评测中心导航。
- 失败案例只展示已有 diff、risk tag、failure code 和脱敏摘要，不生成 AI 根因。
- 发布继续受权限、禁止自审、revision、幂等和服务端门禁约束；失败时保留证据和选择上下文。
- 1440px 三栏、1024px 两栏加证据抽屉、390px 列表/详情均有自动化验收。
- 验证顺序为 T1 → T2a → T2b，再执行 Vitest、ESLint、build 和 Chromium E2E。
