# Skill Governance Workbench UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Portal `/skills` 从超宽资产表和多页签弹窗重构为左侧 Skill 目录、右侧生命周期治理工作区，并保持现有版本、评测、审批和 test shadow 门禁不变。

**Architecture:** 后端新增只读 `SkillWorkbenchService`，在服务端组合版本目录、最新评测和 test release，提供一次请求可用的治理摘要与目录项；所有写操作继续走现有 `SkillVersionService`、`SkillGovernanceService` 和权限门禁。前端以 `SkillGovernanceWorkbench` 编排 URL、目录、详情和局部刷新，把现有评测/发布组件迁入五页签工作区，路由与执行调试改为右侧抽屉。

**Tech Stack:** FastAPI、Pydantic v2、Python 3.12、Next.js 16、React 19、TypeScript、Tailwind CSS、Vitest、pytest、Playwright Chromium

---

## 0. 执行约束

- 设计依据：`docs/superpowers/specs/2026-08-05-skill-governance-workbench-ui-redesign.md`。
- 风险等级：R4。验证严格按 T1 单元 → T2a API → T2b Flow/E2E 顺序执行。
- 缺陷修复先补失败测试，再改实现。
- 后端新增模型使用 Pydantic，不返回裸 `dict`。
- 新静态路由 `/infra-skills/workbench` 必须声明在 `/infra-skills/{skill_id}` 之前。
- 前端不得推导发布门禁；步骤状态和下一步来自后端读模型。
- 不修改 SkillLoader、assembler、路由算法或生产运行选择。
- 不新增生产灰度、回滚或运行趋势假入口。
- 启停服务只用根目录 `start-servers.ps1` 与 `stop-servers.ps1`。

## 1. 文件结构与职责

### 后端

- Create: `src/runtime/skill_management/workbench_service.py` — 只读工作台模型、治理状态优先级和聚合服务。
- Modify: `src/runtime/skill_management/__init__.py` — 导出工作台服务与读模型。
- Modify: `src/runtime/api/skill_schemas.py` — 工作台与审批证据显式 DTO。
- Modify: `src/runtime/api/infra_skill_routes.py` — 依赖组装、静态工作台端点和 release 审批证据序列化。
- Create: `src/tests/unit/runtime/skill_management/test_workbench_service.py` — 聚合状态、排序、筛选、分页和敏感字段边界。
- Modify: `src/tests/integration/api/test_infra_skill_workbench_api.py` — 工作台端点、路由顺序、兼容和审批证据。

### Portal

- Modify: `src/apps/portal/src/lib/types.ts` — 工作台、步骤和审批证据类型。
- Modify: `src/apps/portal/src/lib/api-client.ts` — 工作台查询和现有端点类型适配。
- Modify: `src/apps/portal/app/skills/page.tsx` — 移除旧背景与嵌套卡片，只挂载新工作台。
- Create: `src/apps/portal/src/components/skills/skill-governance-workbench.tsx` — 页面状态、URL 恢复和局部刷新编排。
- Create: `src/apps/portal/src/components/skills/skill-workbench-header.tsx` — 单一标题、环境、路由调试和刷新。
- Create: `src/apps/portal/src/components/skills/skill-governance-summary.tsx` — 五个可操作指标。
- Create: `src/apps/portal/src/components/skills/skill-catalog-panel.tsx` — 搜索、筛选、排序和 Skill 目录。
- Create: `src/apps/portal/src/components/skills/skill-lifecycle-stepper.tsx` — 四步服务端状态展示。
- Create: `src/apps/portal/src/components/skills/skill-workspace.tsx` — 身份头、五页签和局部数据加载。
- Create: `src/apps/portal/src/components/skills/skill-overview-tab.tsx` — 下一步、证据、评测与发布摘要。
- Create: `src/apps/portal/src/components/skills/skill-versions-tab.tsx` — 当前制品和版本时间线。
- Create: `src/apps/portal/src/components/skills/skill-development-tab.tsx` — 六类技术内容的纵向分组。
- Create: `src/apps/portal/src/components/skills/skill-route-test-drawer.tsx` — 全局路由调试抽屉。
- Create: `src/apps/portal/src/components/skills/skill-execution-test-drawer.tsx` — 选中 Skill 执行调试抽屉。
- Modify: `src/apps/portal/src/components/skills/skill-evaluation-suite.tsx` — 接收外部刷新回调、强化摘要和失败结果。
- Modify: `src/apps/portal/src/components/skills/skill-release-panel.tsx` — 单路径动作、审批证据、门禁错误和激活回调。
- Modify: `src/apps/portal/src/components/infra-skill-management.tsx` — 改为新工作台薄兼容导出，避免旧页面引用断裂。
- Modify: `src/apps/portal/src/tests/skill-catalog.test.ts` — 工作台 API 查询编码。
- Create: `src/apps/portal/src/tests/skill-workbench.test.tsx` — 页面结构、URL、筛选、步骤和局部错误。
- Modify: `src/apps/portal/src/tests/skill-governance.test.ts` — 审批证据和写 API 回归。

### Flow 与进度

- Modify: `src/tests/e2e/pages/portal/skill-catalog.page.ts` — 新双栏页面对象。
- Modify: `src/tests/e2e/flows/portal/skill-catalog.flow.ts` — 登记、评测、审批、激活、刷新恢复和抽屉上下文。
- Modify: `PROGRESS.md` — 记录 UI 重构范围、验证数字和回滚点。

---

### Task 1: 建立工作台只读聚合服务

**Files:**
- Create: `src/runtime/skill_management/workbench_service.py`
- Modify: `src/runtime/skill_management/__init__.py`
- Create: `src/tests/unit/runtime/skill_management/test_workbench_service.py`

- [ ] **Step 1: 写治理状态优先级和摘要的失败测试**

在 `test_workbench_service.py` 用真实 Pydantic 读模型和 mock service 构造固定证据：

```python
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.domain.skill.governance_models import SkillEvalRun, SkillRelease
from src.domain.skill.version_models import SkillVersion
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.runtime.skill_management.version_service import (
    SkillCatalogEntry,
    SkillCatalogPage,
    SkillVersionService,
)
from src.runtime.skill_management.workbench_service import (
    SkillGovernanceStatus,
    SkillWorkbenchService,
    _resolve_status,
)


@pytest.fixture
def workbench_fixture() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    failed_version = SkillVersion.model_construct(
        version_id="version-failed",
        validation_status="passed",
    )
    active_version = SkillVersion.model_construct(
        version_id="version-active",
        validation_status="passed",
    )
    catalog = SkillCatalogPage(
        items=[
            SkillCatalogEntry.model_construct(
                skill_id="settlement_explain_skill",
                skill_name="结算解释技能",
                business_action="explain",
                business_object="settlement",
                semantic_version="2.0.0",
                artifact_status="registered",
                registered_version=failed_version,
            ),
            SkillCatalogEntry.model_construct(
                skill_id="policy_query_skill",
                skill_name="政策查询技能",
                business_action="query",
                business_object="policy",
                semantic_version="1.0.0",
                artifact_status="registered",
                registered_version=active_version,
            ),
        ],
        page=1,
        page_size=10_000,
        total=2,
    )
    version_service = Mock(spec=SkillVersionService)
    version_service.list_catalog.return_value = catalog
    governance_service = Mock(spec=SkillGovernanceService)
    governance_service.list_eval_runs.side_effect = lambda skill_id: [
        SkillEvalRun.model_construct(
            skill_id=skill_id,
            version_id=("version-failed" if skill_id == "settlement_explain_skill" else "version-active"),
            status=("failed" if skill_id == "settlement_explain_skill" else "passed"),
            created_at=now,
        )
    ]
    governance_service.list_releases.side_effect = lambda skill_id, environment: (
        []
        if skill_id == "settlement_explain_skill"
        else [
            SkillRelease.model_construct(
                skill_id=skill_id,
                version_id="version-active",
                status="active",
                created_at=now,
            )
        ]
    )
    return SimpleNamespace(
        service=SkillWorkbenchService(version_service, governance_service),
        governance_service=governance_service,
    )
```

核心断言：

```python
def test_workbench_prioritizes_gate_failure_over_pending_and_changed(workbench_fixture):
    service = workbench_fixture.service

    page = service.list_workbench(page=1, page_size=20)

    item = next(row for row in page.items if row.skill_id == "settlement_explain_skill")
    assert item.governance_status == SkillGovernanceStatus.GATE_FAILED
    assert item.attention_reason == "latest_evaluation_failed"


def test_workbench_counts_actionable_summary(workbench_fixture):
    page = workbench_fixture.service.list_workbench(page=1, page_size=20)

    assert page.summary.total == 2
    assert page.summary.healthy == 1
    assert page.summary.needs_evaluation == 0
    assert page.summary.pending_approval == 0
    assert page.summary.test_active == 1


def test_workbench_filters_before_pagination(workbench_fixture):
    page = workbench_fixture.service.list_workbench(
        page=1,
        page_size=1,
        governance_status=SkillGovernanceStatus.HEALTHY,
    )

    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].governance_status == SkillGovernanceStatus.HEALTHY


@pytest.mark.parametrize(
    ("artifact_status", "eval_status", "release_status", "expected"),
    [
        ("registered", "failed", "approval_pending", SkillGovernanceStatus.GATE_FAILED),
        ("registered", "passed", "approval_pending", SkillGovernanceStatus.PENDING_APPROVAL),
        ("registered", None, None, SkillGovernanceStatus.NEEDS_EVALUATION),
        ("changed", "passed", None, SkillGovernanceStatus.ARTIFACT_CHANGED),
        ("registered", "passed", "active", SkillGovernanceStatus.HEALTHY),
    ],
)
def test_governance_status_matrix(
    artifact_status,
    eval_status,
    release_status,
    expected,
):
    status, _ = _resolve_status(
        artifact_status=artifact_status,
        latest_eval_status=eval_status,
        latest_release_status=release_status,
    )
    assert status == expected
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/unit/runtime/skill_management/test_workbench_service.py -q
```

Expected: FAIL，`src.runtime.skill_management.workbench_service` 不存在。

- [ ] **Step 3: 实现最小只读模型与聚合规则**

在 `workbench_service.py` 定义不可变读模型：

```python
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from src.domain.skill.governance_models import SkillEvalRunStatus, SkillReleaseStatus
from src.runtime.skill_management.governance_service import SkillGovernanceService
from src.runtime.skill_management.version_service import SkillVersionService


class SkillGovernanceStatus(StrEnum):
    GATE_FAILED = "gate_failed"
    PENDING_APPROVAL = "pending_approval"
    NEEDS_EVALUATION = "needs_evaluation"
    ARTIFACT_CHANGED = "artifact_changed"
    HEALTHY = "healthy"


class SkillWorkbenchSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    healthy: int
    needs_evaluation: int
    pending_approval: int
    test_active: int
    updated_at: datetime


class SkillWorkbenchItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    skill_id: str
    skill_name: str
    business_action: str
    business_object: str
    semantic_version: str
    artifact_status: str
    validation_status: str
    latest_eval_status: str | None
    test_release_status: str | None
    test_active_version: str | None
    governance_status: SkillGovernanceStatus
    attention_reason: str | None


class SkillWorkbenchPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary: SkillWorkbenchSummary
    items: list[SkillWorkbenchItem]
    total: int
    page: int
    page_size: int
```

实现 `SkillWorkbenchService.list_workbench()`：调用 `SkillVersionService.list_catalog` 时明确传入 `page=1`、`page_size=10_000`、`business_action`、`business_object`、`artifact_status` 和 `query`，得到完整筛选集；再按每个 Skill 的当前登记版本筛选匹配版本的最新 eval run 和 test release。状态优先级必须写成单一函数：

`latest_release_status` 取按 `created_at` 排序后的最新非 retired release；`test_active_version` 独立查找 test 环境 active release 对应版本，不能因为存在更新的 candidate 就丢失当前 active 信息。`summary.test_active` 按存在 active release 的 Skill 数计数。

```python
def _resolve_status(
    *,
    artifact_status: str,
    latest_eval_status: str | None,
    latest_release_status: str | None,
) -> tuple[SkillGovernanceStatus, str | None]:
    if latest_eval_status in {SkillEvalRunStatus.FAILED, SkillEvalRunStatus.ERROR}:
        return SkillGovernanceStatus.GATE_FAILED, "latest_evaluation_failed"
    if latest_release_status == SkillReleaseStatus.APPROVAL_PENDING:
        return SkillGovernanceStatus.PENDING_APPROVAL, "approval_required"
    if latest_eval_status != SkillEvalRunStatus.PASSED:
        return SkillGovernanceStatus.NEEDS_EVALUATION, "passed_evaluation_required"
    if artifact_status != "registered":
        return SkillGovernanceStatus.ARTIFACT_CHANGED, "artifact_not_registered"
    return SkillGovernanceStatus.HEALTHY, None
```

按 `gate_failed → pending_approval → needs_evaluation → artifact_changed → healthy` 排序，治理状态筛选在分页之前执行。`updated_at` 使用 UTC aware datetime。

- [ ] **Step 4: 导出服务并运行单元测试**

在 `src/runtime/skill_management/__init__.py` 导出：

```python
from src.runtime.skill_management.workbench_service import (
    SkillGovernanceStatus,
    SkillWorkbenchItem,
    SkillWorkbenchPage,
    SkillWorkbenchService,
    SkillWorkbenchSummary,
)
```

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/unit/runtime/skill_management/test_workbench_service.py src/tests/unit/runtime/skill_management/test_governance_service.py -q
```

Expected: PASS；工作台测试和既有治理服务回归全部通过。

- [ ] **Step 5: 提交**

```powershell
git add src/runtime/skill_management/workbench_service.py src/runtime/skill_management/__init__.py src/tests/unit/runtime/skill_management/test_workbench_service.py
git commit -m "feat: aggregate skill governance workbench state"
```

---

### Task 2: 暴露工作台 API 与审批证据

**Files:**
- Modify: `src/runtime/api/skill_schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Modify: `src/tests/integration/api/test_infra_skill_workbench_api.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`

- [ ] **Step 1: 写端点和审批证据失败测试**

新增以下 API 断言：

```python
def test_workbench_route_is_not_captured_as_skill_id(client):
    response = client.get(f"{PREFIX}/infra-skills/workbench")

    assert response.status_code == 200
    assert response.json()["summary"]["total"] >= 1


def test_workbench_returns_actionable_item_without_sensitive_samples(client):
    response = client.get(f"{PREFIX}/infra-skills/workbench?page=1&page_size=20")

    body = response.json()
    item = body["items"][0]
    assert {
        "governance_status",
        "latest_eval_status",
        "test_release_status",
        "attention_reason",
    }.issubset(item)
    assert "question_template" not in response.text
    assert "approval_reason" not in response.text


```

在 `test_infra_skill_routes.py::test_eval_and_manual_approval_are_required_for_test_activation` 现有 candidate → request → approve → activate 流程末尾增加：

```python
    active_item = next(
        item for item in releases.json()["items"] if item["status"] == "active"
    )
    assert active_item["approval"]["approved_by"] == "information-admin"
    assert active_item["approval"]["approver_role"] == "information_department"
    assert "reason" not in active_item["approval"]
```

- [ ] **Step 2: 运行 API 测试确认失败**

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/integration/api/test_infra_skill_workbench_api.py -q
```

Expected: FAIL，工作台端点不存在且 release 响应没有 `approval`。

- [ ] **Step 3: 增加显式 API DTO**

在 `skill_schemas.py` 增加：

```python
class SkillWorkbenchSummaryResponse(BaseModel):
    total: int
    healthy: int
    needs_evaluation: int
    pending_approval: int
    test_active: int
    updated_at: datetime


class SkillWorkbenchItemResponse(BaseModel):
    skill_id: str
    skill_name: str
    business_action: str
    business_object: str
    semantic_version: str
    artifact_status: str
    validation_status: str
    latest_eval_status: str | None
    test_release_status: str | None
    test_active_version: str | None
    governance_status: str
    attention_reason: str | None


class SkillWorkbenchResponse(BaseModel):
    summary: SkillWorkbenchSummaryResponse
    items: list[SkillWorkbenchItemResponse]
    total: int
    page: int
    page_size: int


class SkillReleaseApprovalSummaryResponse(BaseModel):
    approved_by: str
    approver_role: str
    approved_at: datetime
```

给 `SkillReleaseResponse` 增加安全的可选字段：

```python
approval: SkillReleaseApprovalSummaryResponse | None = None
```

不要返回审批理由、问题模板、患者上下文或完整评测样本。

- [ ] **Step 4: 组装依赖和静态路由**

在 `infra_skill_routes.py` 增加 `SkillWorkbenchServiceDependency`，并把静态端点放在第一个 `/{skill_id}` 路由之前：

```python
def get_skill_workbench_service(
    version_service: SkillVersionServiceDependency,
    governance_service: SkillGovernanceServiceDependency,
) -> SkillWorkbenchService:
    return SkillWorkbenchService(
        version_service=version_service,
        governance_service=governance_service,
    )


SkillWorkbenchServiceDependency = Annotated[
    SkillWorkbenchService,
    Depends(get_skill_workbench_service),
]


@router.get("/infra-skills/workbench", response_model=SkillWorkbenchResponse)
def get_infra_skill_workbench(
    service: SkillWorkbenchServiceDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    business_action: str = Query(default=""),
    business_object: str = Query(default=""),
    artifact_status: str = Query(default=""),
    governance_status: str = Query(default=""),
    query: str = Query(default="", max_length=128),
) -> SkillWorkbenchResponse:
    result = service.list_workbench(
        page=page,
        page_size=page_size,
        business_action=business_action,
        business_object=business_object,
        artifact_status=artifact_status,
        governance_status=governance_status,
        query=query,
    )
    return SkillWorkbenchResponse.model_validate(result.model_dump())
```

增加 `_release_response(service, release)`，调用 `service.get_release_approval()`，只投影审批人、角色和时间；列表及 transition 端点统一使用该函数，避免审批后页面仍显示空证据。

- [ ] **Step 5: 运行 T2a API 回归**

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/integration/api/test_infra_skill_workbench_api.py src/tests/integration/api/test_infra_skill_routes.py -q
```

Expected: PASS；工作台静态路由、审批证据和全部现有 Skill API 测试通过。

- [ ] **Step 6: 提交**

```powershell
git add src/runtime/api/skill_schemas.py src/runtime/api/infra_skill_routes.py src/tests/integration/api/test_infra_skill_workbench_api.py src/tests/integration/api/test_infra_skill_routes.py
git commit -m "feat: expose skill governance workbench read model"
```

---

### Task 3: 增加 Portal 工作台类型与 API 客户端

**Files:**
- Modify: `src/apps/portal/src/lib/types.ts`
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Modify: `src/apps/portal/src/tests/skill-catalog.test.ts`
- Modify: `src/apps/portal/src/tests/skill-governance.test.ts`

- [ ] **Step 1: 写 URL 编码和类型字段失败测试**

在 `skill-catalog.test.ts` 增加：

```typescript
it('requests the governance workbench with URL-safe filters', async () => {
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
    summary: {
      total: 0,
      healthy: 0,
      needs_evaluation: 0,
      pending_approval: 0,
      test_active: 0,
      updated_at: '2026-08-05T06:00:00Z',
    },
    items: [],
    total: 0,
    page: 1,
    page_size: 50,
  }))
  vi.stubGlobal('fetch', fetchMock)

  await getSkillGovernanceWorkbench({
    query: '结算 skill',
    governance_status: 'needs_evaluation',
    business_action: 'explain',
  })

  expect(fetchMock.mock.calls[0][0]).toBe(
    '/api/v1/medical-insurance-ai-agent/infra-skills/workbench?business_action=explain&governance_status=needs_evaluation&query=%E7%BB%93%E7%AE%97+skill',
  )
})
```

在 `skill-governance.test.ts` 增加 release `approval` 类型可读取的断言。

- [ ] **Step 2: 运行 Vitest 确认失败**

```powershell
cd src/apps/portal
npm test -- --run src/tests/skill-catalog.test.ts src/tests/skill-governance.test.ts
```

Expected: FAIL，`getSkillGovernanceWorkbench` 和工作台类型未定义。

- [ ] **Step 3: 增加 TypeScript 类型**

在 `types.ts` 增加：

```typescript
export type SkillGovernanceStatus =
  | 'gate_failed'
  | 'pending_approval'
  | 'needs_evaluation'
  | 'artifact_changed'
  | 'healthy'

export type SkillWorkbenchTab =
  | 'overview'
  | 'versions'
  | 'evaluation'
  | 'release'
  | 'development'

export interface SkillWorkbenchSummary {
  total: number
  healthy: number
  needs_evaluation: number
  pending_approval: number
  test_active: number
  updated_at: string
}

export interface SkillWorkbenchItem {
  skill_id: string
  skill_name: string
  business_action: string
  business_object: string
  semantic_version: string
  artifact_status: 'registered' | 'changed' | 'unregistered'
  validation_status: 'pending' | 'passed' | 'failed'
  latest_eval_status: SkillEvalRunResponse['status'] | null
  test_release_status: SkillReleaseResponse['status'] | null
  test_active_version: string | null
  governance_status: SkillGovernanceStatus
  attention_reason: string | null
}

export interface SkillWorkbenchResponse {
  summary: SkillWorkbenchSummary
  items: SkillWorkbenchItem[]
  total: number
  page: number
  page_size: number
}

export interface SkillReleaseApprovalSummary {
  approved_by: string
  approver_role: string
  approved_at: string
}
```

给 `SkillReleaseResponse` 增加 `approval?: SkillReleaseApprovalSummary | null`。

- [ ] **Step 4: 实现客户端查询**

在 `api-client.ts` 增加：

```typescript
export interface SkillWorkbenchFilter extends InfraSkillsFilter {
  page?: number
  page_size?: number
  artifact_status?: string
  governance_status?: SkillGovernanceStatus
  query?: string
}

export async function getSkillGovernanceWorkbench(
  filter: SkillWorkbenchFilter = {},
): Promise<SkillWorkbenchResponse> {
  const params = new URLSearchParams()
  if (filter.page) params.set('page', String(filter.page))
  if (filter.page_size) params.set('page_size', String(filter.page_size))
  if (filter.business_action) params.set('business_action', filter.business_action)
  if (filter.business_object) params.set('business_object', filter.business_object)
  if (filter.artifact_status) params.set('artifact_status', filter.artifact_status)
  if (filter.governance_status) params.set('governance_status', filter.governance_status)
  if (filter.query) params.set('query', filter.query)
  const query = params.toString()
  return requestJson<SkillWorkbenchResponse>(
    `/infra-skills/workbench${query ? `?${query}` : ''}`,
  )
}
```

按固定字段顺序写入 `URLSearchParams`，保证测试和请求可预测。

- [ ] **Step 5: 运行 Vitest 并提交**

```powershell
npm test -- --run src/tests/skill-catalog.test.ts src/tests/skill-governance.test.ts
```

Expected: PASS。

```powershell
cd ..\..\..
git add src/apps/portal/src/lib/types.ts src/apps/portal/src/lib/api-client.ts src/apps/portal/src/tests/skill-catalog.test.ts src/apps/portal/src/tests/skill-governance.test.ts
git commit -m "feat: add skill workbench portal contract"
```

---

### Task 4: 构建双栏工作台骨架、目录与 URL 恢复

**Files:**
- Create: `src/apps/portal/src/components/skills/skill-governance-workbench.tsx`
- Create: `src/apps/portal/src/components/skills/skill-workbench-header.tsx`
- Create: `src/apps/portal/src/components/skills/skill-governance-summary.tsx`
- Create: `src/apps/portal/src/components/skills/skill-catalog-panel.tsx`
- Modify: `src/apps/portal/app/skills/page.tsx`
- Modify: `src/apps/portal/src/components/infra-skill-management.tsx`
- Create: `src/apps/portal/src/tests/skill-workbench.test.tsx`

- [ ] **Step 1: 写页面层级、目录密度和 URL 恢复失败测试**

使用 Testing Library mock `getSkillGovernanceWorkbench`，断言：

```typescript
it('renders one title, actionable summary and compact catalog', async () => {
  render(<SkillGovernanceWorkbench />)

  expect(await screen.findByRole('heading', { name: 'Skill 管理' })).toBeVisible()
  expect(screen.getAllByRole('heading', { name: 'Skill 管理' })).toHaveLength(1)
  expect(screen.getByText('待评测')).toBeVisible()
  expect(screen.getByTestId('skill-catalog-item-settlement_explain_skill')).toBeVisible()
  expect(screen.queryByText('包含关键词')).not.toBeInTheDocument()
  expect(screen.queryByText('artifact hash')).not.toBeInTheDocument()
})


it('restores selected skill and tab from the URL', async () => {
  window.history.replaceState({}, '', '/skills?skill=settlement_explain_skill&tab=evaluation')

  render(<SkillGovernanceWorkbench />)

  expect(await screen.findByTestId('skill-workspace-settlement_explain_skill')).toBeVisible()
  expect(screen.getByRole('tab', { name: '评测' })).toHaveAttribute('aria-selected', 'true')
})


it('keeps the catalog visible when the selected detail fails', async () => {
  mockGetInfraSkillDetail.mockRejectedValueOnce(new Error('SKILL_DETAIL_FAILED'))

  render(<SkillGovernanceWorkbench />)

  expect(await screen.findByTestId('skill-catalog-item-settlement_explain_skill')).toBeVisible()
  expect(await screen.findByText('SKILL_DETAIL_FAILED')).toBeVisible()
})
```

- [ ] **Step 2: 运行组件测试确认失败**

```powershell
cd src/apps/portal
npm test -- --run src/tests/skill-workbench.test.tsx
```

Expected: FAIL，新组件不存在。

- [ ] **Step 3: 实现单一页面头和治理摘要**

`SkillWorkbenchHeader` 只渲染一个标题、副标题、环境选择、路由调试和刷新。test 环境允许治理写操作，dev 环境只读：

```tsx
<header className="flex flex-wrap items-start justify-between gap-4">
  <div>
    <h1 className="text-2xl font-semibold tracking-tight text-slate-950">Skill 管理</h1>
    <p className="mt-1 text-sm text-slate-500">版本证据、固定评测与 Test Shadow 发布治理</p>
  </div>
  <div className="flex items-center gap-2">
    <label htmlFor="skill-environment" className="sr-only">Skill 环境</label>
    <select
      id="skill-environment"
      value={environment}
      onChange={(event) => onEnvironmentChange(event.target.value as 'dev' | 'test')}
      className="h-10 rounded-md border border-slate-200 bg-white px-3 text-sm"
    >
      <option value="test">test</option>
      <option value="dev">dev（只读）</option>
    </select>
    <Button variant="outline" onClick={onOpenRouteTest}>路由调试</Button>
    <Button variant="ghost" size="icon" aria-label="同步状态" onClick={onRefresh}>
      <RefreshCw className="h-4 w-4" />
    </Button>
  </div>
</header>
```

`SkillGovernanceSummary` 使用五个 button 型指标，点击回传治理筛选；加载失败时数字显示 `—`。

- [ ] **Step 4: 实现紧凑 Skill 目录**

目录项必须包含测试 ID、`aria-current` 和不超过两行的状态：

```tsx
<button
  type="button"
  data-testid={`skill-catalog-item-${item.skill_id}`}
  aria-current={selected ? 'true' : undefined}
  onClick={() => onSelect(item.skill_id)}
  className={cn(
    'w-full border-l-2 px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500',
    selected ? 'border-blue-600 bg-blue-50' : 'border-transparent hover:bg-slate-50',
  )}
>
  <div className="flex items-start justify-between gap-2">
    <span className="truncate text-sm font-medium text-slate-900">{item.skill_name}</span>
    <GovernanceStatusBadge status={item.governance_status} />
  </div>
  <div className="mt-1 truncate font-mono text-xs text-slate-500">{item.skill_id}</div>
  <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
    <span>v{item.semantic_version}</span>
    <span>{item.test_release_status === 'active' ? 'Test Active' : statusHint(item)}</span>
  </div>
</button>
```

搜索 250ms 防抖；目录状态筛选按后端字段请求。键盘 `ArrowDown/ArrowUp` 移动焦点，Enter 由 button 原生处理。

- [ ] **Step 5: 实现页面编排和 URL 同步**

`SkillGovernanceWorkbench` 负责：

```typescript
const VALID_TABS = new Set<SkillWorkbenchTab>([
  'overview',
  'versions',
  'evaluation',
  'release',
  'development',
])

interface WorkbenchUrlState {
  skillId: string | null
  tab: SkillWorkbenchTab
  env: 'dev' | 'test'
  query: string
  governanceStatus: SkillGovernanceStatus | null
  businessAction: string
  businessObject: string
}

function setOrDelete(params: URLSearchParams, key: string, value: string | null): void {
  value ? params.set(key, value) : params.delete(key)
}

function replaceWorkbenchUrl(state: WorkbenchUrlState): void {
  const params = new URLSearchParams()
  setOrDelete(params, 'skill', state.skillId)
  params.set('tab', state.tab)
  params.set('env', state.env)
  setOrDelete(params, 'q', state.query)
  setOrDelete(params, 'status', state.governanceStatus)
  setOrDelete(params, 'action', state.businessAction)
  setOrDelete(params, 'object', state.businessObject)
  window.history.replaceState({}, '', `/skills?${params.toString()}`)
}
```

首次结果到达时选择 URL 中存在的 Skill，否则选择第一项。聚合失败时调用现有 `listInfraSkillCatalog()` 生成基础目录，并让 summary 进入 unavailable 状态。

回退映射固定为：

```typescript
function catalogFallback(item: InfraSkillCatalogItem): SkillWorkbenchItem {
  return {
    skill_id: item.skill_id,
    skill_name: item.skill_name,
    business_action: item.business_action,
    business_object: item.business_object,
    semantic_version: item.semantic_version,
    artifact_status: item.artifact_status,
    validation_status: item.registered_version?.validation_status ?? 'pending',
    latest_eval_status: null,
    test_release_status: null,
    test_active_version: null,
    governance_status: item.artifact_status === 'registered' ? 'needs_evaluation' : 'artifact_changed',
    attention_reason: 'governance_summary_unavailable',
  }
}
```

将 `app/skills/page.tsx` 改为 `max-w-[1600px] bg-slate-50` 页面，仅挂载工作台；`infra-skill-management.tsx` 改为：

```tsx
export { default } from './skills/skill-governance-workbench'
```

- [ ] **Step 6: 运行组件测试、ESLint 并提交**

```powershell
npm test -- --run src/tests/skill-workbench.test.tsx
npx eslint app/skills/page.tsx src/components/infra-skill-management.tsx src/components/skills/skill-governance-workbench.tsx src/components/skills/skill-workbench-header.tsx src/components/skills/skill-governance-summary.tsx src/components/skills/skill-catalog-panel.tsx src/tests/skill-workbench.test.tsx
```

Expected: PASS，零 ESLint error。

```powershell
cd ..\..\..
git add src/apps/portal/app/skills/page.tsx src/apps/portal/src/components/infra-skill-management.tsx src/apps/portal/src/components/skills/skill-governance-workbench.tsx src/apps/portal/src/components/skills/skill-workbench-header.tsx src/apps/portal/src/components/skills/skill-governance-summary.tsx src/apps/portal/src/components/skills/skill-catalog-panel.tsx src/apps/portal/src/tests/skill-workbench.test.tsx
git commit -m "feat: build skill governance workbench shell"
```

---

### Task 5: 增加生命周期步骤、总览、版本与开发详情

**Files:**
- Create: `src/apps/portal/src/components/skills/skill-lifecycle-stepper.tsx`
- Create: `src/apps/portal/src/components/skills/skill-workspace.tsx`
- Create: `src/apps/portal/src/components/skills/skill-overview-tab.tsx`
- Create: `src/apps/portal/src/components/skills/skill-versions-tab.tsx`
- Create: `src/apps/portal/src/components/skills/skill-development-tab.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-governance-workbench.tsx`
- Modify: `src/apps/portal/src/tests/skill-workbench.test.tsx`

- [ ] **Step 1: 写步骤状态和五页签失败测试**

```typescript
it('shows server-backed lifecycle steps and five tabs', async () => {
  render(<SkillGovernanceWorkbench />)

  expect(await screen.findByText('版本登记')).toBeVisible()
  expect(screen.getByText('批量评测')).toBeVisible()
  expect(screen.getByText('人工审批')).toBeVisible()
  expect(screen.getByText('Test 激活')).toBeVisible()
  expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
    '总览',
    '版本',
    '评测',
    '发布',
    '开发详情',
  ])
})


it('navigates a blocked step to its evidence tab', async () => {
  const user = userEvent.setup()
  render(<SkillGovernanceWorkbench />)

  await user.click(await screen.findByRole('button', { name: /批量评测/ }))

  expect(screen.getByRole('tab', { name: '评测' })).toHaveAttribute('aria-selected', 'true')
  expect(window.location.search).toContain('tab=evaluation')
})
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd src/apps/portal
npm test -- --run src/tests/skill-workbench.test.tsx
```

Expected: FAIL，步骤与工作区组件不存在。

- [ ] **Step 3: 实现服务端证据到四步状态的纯映射**

步骤状态只使用 `SkillWorkbenchItem`：

```typescript
export type LifecycleVisualState = 'completed' | 'current' | 'blocked' | 'pending'

export interface LifecycleStep {
  tab: SkillWorkbenchTab
  label: string
  state: LifecycleVisualState
  description: string
}

function buildStep(
  tab: SkillWorkbenchTab,
  label: string,
  completed: boolean,
  current: boolean,
  blocked: boolean,
  description: string,
): LifecycleStep {
  return {
    tab,
    label,
    state: completed ? 'completed' : blocked ? 'blocked' : current ? 'current' : 'pending',
    description,
  }
}

export function lifecycleSteps(item: SkillWorkbenchItem): LifecycleStep[] {
  const registered = item.artifact_status === 'registered' && item.validation_status === 'passed'
  const evaluated = item.latest_eval_status === 'passed'
  const approved = item.test_release_status === 'approved' || item.test_release_status === 'active'
  const active = item.test_release_status === 'active'
  return [
    buildStep('versions', '版本登记', registered, !registered, false, '需要登记并校验当前制品'),
    buildStep(
      'evaluation',
      '批量评测',
      evaluated,
      registered && !evaluated,
      item.governance_status === 'gate_failed',
      '需要通过当前固定评测',
    ),
    buildStep('release', '人工审批', approved, evaluated && !approved, false, '需要不同身份人工审批'),
    buildStep('release', 'Test 激活', active, approved && !active, false, '等待激活 Test Shadow'),
  ]
}
```

`buildStep()` 只能映射读模型，不读取按钮状态或当前时间。`blocked` 文案使用 `attention_reason` 的安全中文映射。

- [ ] **Step 4: 实现 SkillWorkspace 和五页签**

身份头显示名称、ID、版本、动作/对象和 Test 状态。页签值固定为设计中的五个值，并把 `onTabChange` 回传给页面编排器。详情、版本、eval runs 和 releases 通过 `Promise.allSettled` 局部加载；单项失败保存独立 error。

```tsx
<Tabs value={activeTab} onValueChange={(value) => onTabChange(value as SkillWorkbenchTab)}>
  <TabsList aria-label="Skill 治理视图">
    <TabsTrigger value="overview">总览</TabsTrigger>
    <TabsTrigger value="versions">版本</TabsTrigger>
    <TabsTrigger value="evaluation">评测</TabsTrigger>
    <TabsTrigger value="release">发布</TabsTrigger>
    <TabsTrigger value="development">开发详情</TabsTrigger>
  </TabsList>
  <TabsContent value="overview"><SkillOverviewTab /></TabsContent>
  <TabsContent value="versions"><SkillVersionsTab /></TabsContent>
  <TabsContent value="evaluation"><SkillEvaluationSuite /></TabsContent>
  <TabsContent value="release"><SkillReleasePanel /></TabsContent>
  <TabsContent value="development"><SkillDevelopmentTab /></TabsContent>
</Tabs>
```

- [ ] **Step 5: 重组总览、版本和开发详情**

`SkillOverviewTab` 依次渲染下一步、当前证据、最近评测、发布摘要和调试入口。完整 hash 不直接铺开，只显示前 12 位和复制按钮。

`SkillVersionsTab` 复用原版本登记逻辑，成功后调用 `onChanged()`；版本历史改为时间线。`SkillDevelopmentTab` 使用六个原生 `<details>` 分组：费用项解析、查询计划、字段映射、Manifest、目录结构、`SKILL.md`；目录使用嵌套列表，不使用目录 Card 矩阵。

- [ ] **Step 6: 运行测试、ESLint 并提交**

```powershell
npm test -- --run src/tests/skill-workbench.test.tsx src/tests/skill-catalog.test.ts
npx eslint src/components/skills/skill-lifecycle-stepper.tsx src/components/skills/skill-workspace.tsx src/components/skills/skill-overview-tab.tsx src/components/skills/skill-versions-tab.tsx src/components/skills/skill-development-tab.tsx src/components/skills/skill-governance-workbench.tsx src/tests/skill-workbench.test.tsx
```

Expected: PASS，零 ESLint error。

```powershell
cd ..\..\..
git add src/apps/portal/src/components/skills/skill-lifecycle-stepper.tsx src/apps/portal/src/components/skills/skill-workspace.tsx src/apps/portal/src/components/skills/skill-overview-tab.tsx src/apps/portal/src/components/skills/skill-versions-tab.tsx src/apps/portal/src/components/skills/skill-development-tab.tsx src/apps/portal/src/components/skills/skill-governance-workbench.tsx src/apps/portal/src/tests/skill-workbench.test.tsx
git commit -m "feat: present skill lifecycle governance workspace"
```

---

### Task 6: 重排评测与发布主流程

**Files:**
- Modify: `src/apps/portal/src/components/skills/skill-evaluation-suite.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-release-panel.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-workspace.tsx`
- Modify: `src/apps/portal/src/tests/skill-workbench.test.tsx`

- [ ] **Step 1: 写单主动作、审批证据和刷新失败测试**

```typescript
it('shows exactly one primary release action for approval pending', async () => {
  mockListSkillReleases.mockResolvedValue(releasePage('approval_pending'))
  render(<SkillGovernanceWorkbench />)

  await userEvent.click(await screen.findByRole('tab', { name: '发布' }))

  expect(screen.getByRole('button', { name: '人工审批通过' })).toBeEnabled()
  expect(screen.queryByRole('button', { name: '申请审批' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '激活 Test Shadow' })).not.toBeInTheDocument()
})


it('refreshes catalog and lifecycle after activation', async () => {
  render(<SkillGovernanceWorkbench />)
  await userEvent.click(await screen.findByRole('tab', { name: '发布' }))
  await userEvent.click(screen.getByRole('button', { name: '激活 Test Shadow' }))

  await waitFor(() => expect(mockGetSkillGovernanceWorkbench).toHaveBeenCalledTimes(2))
  expect(await screen.findByText('Test Shadow 已激活')).toBeVisible()
})
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd src/apps/portal
npm test -- --run src/tests/skill-workbench.test.tsx
```

Expected: FAIL，旧组件仍显示并列操作且没有外部刷新回调。

- [ ] **Step 3: 重排评测页**

给 `SkillEvaluationSuiteProps` 增加 `onChanged?: () => Promise<void> | void`。新增用例和评测成功后执行 `await load(); await onChanged?.()`。

评测首屏固定显示四个指标：必测通过率、Top-1、误接管、新增失败；只在失败时展开失败用例。用例新增输入保留字段级错误容器 `role="alert"`，不把敏感模板复制到全局错误。

- [ ] **Step 4: 重排发布页**

给 `SkillReleasePanelProps` 增加 `onChanged?: () => Promise<void> | void`。按最新非 retired release 计算单一主动作：

```typescript
function nextReleaseAction(release: SkillReleaseResponse | undefined): ReleaseAction {
  if (!release) return 'create_candidate'
  if (release.status === 'candidate') return 'request_approval'
  if (release.status === 'approval_pending') return 'approve'
  if (release.status === 'approved') return 'activate'
  return 'none'
}
```

动作文案固定为：`从通过评测创建候选`、`申请审批`、`人工审批通过`、`激活 Test Shadow`。active 状态显示稳定卡片 `Test Shadow 已激活`。审批摘要展示 `approved_by`、`approver_role` 和 `approved_at`，不展示审批 reason。

解析 API error detail 中的 `audit_event.gate_failures`，逐条映射制品、测试集、路由 Manifest、配置和基线变化；409 revision conflict 显示“状态已变化，刷新后重新确认”。使用现有 `ApiClientError`，不要从 message 字符串反向解析：

```typescript
const GATE_LABELS: Record<string, string> = {
  artifact_changed: '制品内容已变化，需要重新登记和评测',
  config_changed: '评测配置已变化，需要重新评测',
  suite_changed: '固定测试集已变化，需要重新评测',
  routing_manifest_changed: '路由 Manifest 已变化，需要重新评测',
  baseline_changed: '活动基线已变化，需要重新评测和审批',
  manual_approval_required: '需要不同身份的人工审批',
}

function gateFailureLabels(error: unknown): string[] {
  if (!(error instanceof ApiClientError)) return []
  const raw = error.detail.audit_event?.gate_failures
  if (!Array.isArray(raw)) return []
  return raw
    .filter((value): value is string => typeof value === 'string')
    .map((value) => GATE_LABELS[value] ?? value)
}
```

- [ ] **Step 5: 串联局部刷新并运行测试**

`SkillWorkspace` 在版本、评测或发布写入成功后只重新加载当前 Skill 证据，再调用父级 `refreshWorkbench()` 刷新目录和指标。

当环境为 dev 时，版本和技术详情仍可读，评测/发布写按钮不渲染；发布页仅显示 dev release 历史和“dev 环境在本工作台只读”。test 环境继续使用现有写操作。

```powershell
npm test -- --run src/tests/skill-workbench.test.tsx src/tests/skill-governance.test.ts
npx eslint src/components/skills/skill-evaluation-suite.tsx src/components/skills/skill-release-panel.tsx src/components/skills/skill-workspace.tsx src/tests/skill-workbench.test.tsx
```

Expected: PASS，零 ESLint error。

- [ ] **Step 6: 提交**

```powershell
cd ..\..\..
git add src/apps/portal/src/components/skills/skill-evaluation-suite.tsx src/apps/portal/src/components/skills/skill-release-panel.tsx src/apps/portal/src/components/skills/skill-workspace.tsx src/apps/portal/src/tests/skill-workbench.test.tsx
git commit -m "feat: streamline skill evaluation and test release flow"
```

---

### Task 7: 将路由与执行调试迁入右侧抽屉

**Files:**
- Create: `src/apps/portal/src/components/skills/skill-route-test-drawer.tsx`
- Create: `src/apps/portal/src/components/skills/skill-execution-test-drawer.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-governance-workbench.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-overview-tab.tsx`
- Modify: `src/apps/portal/src/tests/skill-workbench.test.tsx`

- [ ] **Step 1: 写抽屉上下文和隐私失败测试**

```typescript
it('keeps selected skill and tab after closing route diagnostics', async () => {
  const user = userEvent.setup()
  render(<SkillGovernanceWorkbench />)

  await user.click(await screen.findByRole('button', { name: '路由调试' }))
  expect(screen.getByRole('dialog', { name: '路由调试' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: '关闭路由调试' }))

  expect(screen.getByTestId('skill-workspace-settlement_explain_skill')).toBeVisible()
  expect(window.location.search).toContain('skill=settlement_explain_skill')
})


it('does not persist diagnostic questions in the URL', async () => {
  render(<SkillGovernanceWorkbench />)
  await userEvent.click(await screen.findByRole('button', { name: '路由调试' }))
  await userEvent.type(screen.getByLabelText('路由问题'), '统筹自付为什么这么多')

  expect(window.location.href).not.toContain(encodeURIComponent('统筹自付为什么这么多'))
})
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
cd src/apps/portal
npm test -- --run src/tests/skill-workbench.test.tsx
```

Expected: FAIL，调试抽屉不存在。

- [ ] **Step 3: 实现路由调试抽屉**

使用现有 Dialog 基础组件实现右侧面板。输入只保存在组件 state；调用 `testInfraSkillRouting()` 后显示命中 Skill、置信度、匹配方式、命中/排除关键词和候选列表。候选 Skill 按钮调用 `onSelectSkill(candidate.skill_id)`，不自动执行 Skill。

```tsx
<Dialog open={open} onOpenChange={onOpenChange}>
  <DialogContent className="fixed inset-y-0 left-auto right-0 h-screen w-full max-w-xl translate-x-0 translate-y-0 overflow-y-auto rounded-none">
    <DialogHeader><DialogTitle>路由调试</DialogTitle></DialogHeader>
    <label htmlFor="route-question" className="text-sm font-medium">路由问题</label>
    <Textarea id="route-question" value={question} onChange={handleQuestionChange} />
    <Button onClick={run} disabled={!question.trim() || loading}>分析路由</Button>
    {result && <RouteExplanation result={result} onSelectSkill={onSelectSkill} />}
    <DialogClose asChild>
      <Button variant="outline" aria-label="关闭路由调试">关闭</Button>
    </DialogClose>
  </DialogContent>
</Dialog>
```

- [ ] **Step 4: 实现执行调试抽屉**

执行调试只能从选中 Skill 的总览/开发详情打开。复用原脱敏示例表单与 `testInfraSkillExecution()`；结果顺序固定为结构化摘要、citations、uncertainties、warnings、折叠 trace/JSON。输入和结果不写 URL、sessionStorage 或 localStorage。

- [ ] **Step 5: 运行测试、ESLint 并提交**

```powershell
npm test -- --run src/tests/skill-workbench.test.tsx
npx eslint src/components/skills/skill-route-test-drawer.tsx src/components/skills/skill-execution-test-drawer.tsx src/components/skills/skill-governance-workbench.tsx src/components/skills/skill-overview-tab.tsx src/tests/skill-workbench.test.tsx
```

Expected: PASS，零 ESLint error。

```powershell
cd ..\..\..
git add src/apps/portal/src/components/skills/skill-route-test-drawer.tsx src/apps/portal/src/components/skills/skill-execution-test-drawer.tsx src/apps/portal/src/components/skills/skill-governance-workbench.tsx src/apps/portal/src/components/skills/skill-overview-tab.tsx src/apps/portal/src/tests/skill-workbench.test.tsx
git commit -m "feat: move skill diagnostics into workbench drawers"
```

---

### Task 8: 完成响应式、无障碍、Flow 和最终验证

**Files:**
- Modify: `src/apps/portal/src/components/skills/skill-governance-workbench.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-catalog-panel.tsx`
- Modify: `src/apps/portal/src/components/skills/skill-lifecycle-stepper.tsx`
- Modify: `src/tests/e2e/pages/portal/skill-catalog.page.ts`
- Modify: `src/tests/e2e/flows/portal/skill-catalog.flow.ts`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 更新 Page Object 让旧弹窗路径测试失败**

页面对象改用稳定语义选择器：

```typescript
this.title = page.getByRole('heading', { name: 'Skill 管理' });
this.workspace = page.getByTestId('skill-governance-workbench');
this.lifecycle = page.getByLabel('Skill 生命周期');
this.routeDrawer = page.getByRole('dialog', { name: '路由调试' });

async selectSkill(skillId: string): Promise<void> {
  await this.page.getByTestId(`skill-catalog-item-${skillId}`).click();
  await this.page.getByTestId(`skill-workspace-${skillId}`).waitFor({ state: 'visible' });
}

async openTab(name: '总览' | '版本' | '评测' | '发布' | '开发详情'): Promise<void> {
  await this.page.getByRole('tab', { name }).click();
}
```

删除对“详情”按钮、详情 Dialog 和 `Close` 的依赖。

- [ ] **Step 2: 更新桌面 E2E 流程**

覆盖：

```typescript
test('固定评测与人工审批后激活 Test Shadow 并刷新恢复', async ({ page }) => {
  const workbench = new SkillCatalogPage(page);
  await workbench.goto();
  await workbench.selectSkill('settlement_explain_skill');
  await workbench.registerCurrentVersion('settlement_explain_skill');
  await workbench.runFixedEvaluation('统筹自付为什么这么多');
  await workbench.approveAndActivateTestRelease();

  await expect(workbench.lifecycle).toContainText('Test 激活');
  await expect(page.getByText('Test Shadow 已激活')).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/skill=settlement_explain_skill/);
  await expect(page.getByRole('tab', { name: '发布' })).toHaveAttribute('aria-selected', 'true');
});
```

新增路由抽屉关闭后仍保留选中 Skill 的断言。

- [ ] **Step 3: 增加窄屏和键盘验证**

新增同文件测试：设置 viewport `390x844`，断言页面 `document.documentElement.scrollWidth <= window.innerWidth`；选择 Skill 后显示“返回 Skill 目录”。键盘测试用 Tab 聚焦目录项、ArrowDown 移动到下一项，并断言 `aria-current` 更新。

- [ ] **Step 4: 完成响应式与 focus-visible 实现**

- ≥1280px：`grid-cols-[288px_minmax(0,1fr)]`，目录和内容分别滚动；
- 768–1279px：`grid-cols-[240px_minmax(0,1fr)]`，指标 `grid-cols-3`；
- <768px：目录与详情二选一，详情提供“返回 Skill 目录”，抽屉全屏；
- 五页签使用横向滚动容器，文字不得纵向断字；
- 所有 button/tab/input 提供可见 focus ring；
- `SkillLifecycleStepper` 添加 `aria-label="Skill 生命周期"`，当前步骤使用 `aria-current="step"`；
- 图标按钮都有中文 `aria-label`，状态不是纯颜色表达。

- [ ] **Step 5: 按硬性顺序运行最终验证**

T1：

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/unit/runtime/skill_management/test_workbench_service.py src/tests/unit/runtime/skill_management/test_governance_service.py src/tests/unit/skill_infra/test_route_evaluator.py src/tests/unit/data_platform/test_skill_governance_storage.py -q
```

Expected: PASS。

T2a：

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/integration/api/test_infra_skill_workbench_api.py src/tests/integration/api/test_infra_skill_routes.py -q
```

Expected: PASS。

T2b：

```powershell
.\.venv\Scripts\python.exe -m pytest src/tests/integration/flow/test_skill_evaluation_release_flow.py -q
```

Expected: PASS。

Portal：

```powershell
cd src/apps/portal
npm test -- --run src/tests/skill-catalog.test.ts src/tests/skill-governance.test.ts src/tests/skill-workbench.test.tsx
npx eslint app/skills/page.tsx src/components/infra-skill-management.tsx src/components/skills src/lib/api-client.ts src/lib/types.ts src/tests/skill-catalog.test.ts src/tests/skill-governance.test.ts src/tests/skill-workbench.test.tsx
npm run build
cd ..\..\..
```

Expected: Vitest PASS、ESLint 零 error、Next.js build PASS。

Chromium E2E：

```powershell
$env:USE_MEMORY_STORAGE='1'
.\start-servers.ps1
cd src/tests/e2e
npx playwright test flows/portal/skill-catalog.flow.ts --project=chromium --workers=1
cd ..\..\..
.\stop-servers.ps1
```

Expected: 所有 Skill 工作台 E2E PASS，服务最终停止。

- [ ] **Step 6: 浏览器人工视觉检查**

使用 Orca 打开 `http://127.0.0.1:3000/skills`，检查：

- 单一页面标题；
- 五指标和双栏首屏完整；
- 无超宽表格、无完整关键词墙、无页面级横向滚动；
- 生命周期步骤当前/完成/阻塞状态清晰；
- 评测和发布不再位于详情弹窗；
- 路由抽屉关闭后上下文保留；
- 390px 视口可返回目录，按钮和页签不截断。

- [ ] **Step 7: 更新进度并提交**

在 `PROGRESS.md` 的技能管理条目记录方案 2、聚合读模型、双栏工作台、验证命令与实际通过数字；不预填未执行的数字。

```powershell
git add src/apps/portal/src/components/skills/skill-governance-workbench.tsx src/apps/portal/src/components/skills/skill-catalog-panel.tsx src/apps/portal/src/components/skills/skill-lifecycle-stepper.tsx src/tests/e2e/pages/portal/skill-catalog.page.ts src/tests/e2e/flows/portal/skill-catalog.flow.ts PROGRESS.md
git commit -m "test: verify skill governance workbench flow"
```

---

## 2. 最终完成标准

- 工作区 `git status --short` 为空；
- 每个 Task 有独立 Angular 格式提交；
- T1 → T2a → T2b 顺序有新鲜通过证据；
- Portal Vitest、ESLint、build 和 Chromium E2E 通过；
- 浏览器视觉检查通过且服务已停止；
- 代码复审无阻塞项；
- `PROGRESS.md` 只记录实际验证数字；
- 新页面可以通过恢复 `app/skills/page.tsx` 使用旧薄兼容入口回滚，后端只读端点不影响运行时。
