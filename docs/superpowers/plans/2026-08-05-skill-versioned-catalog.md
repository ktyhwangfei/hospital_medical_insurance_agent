# Skill Versioned Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 `/skills` 文件查看器升级为可追溯的版本化资产库，使每个已加载 Skill 都能登记并展示语义版本、Git 提交、不可变制品哈希和校验状态，同时保持运行时路由与旧 API 不变。

**Architecture:** `src/skill_infra` 负责规范化目录和计算制品快照，`src/domain/skill` 定义不可变版本模型，`src/data_platform/storage/skill` 提供内存/PostgreSQL 多态存储，`src/runtime/skill_management` 编排登记与目录查询，Portal 通过新增 `/infra-skills/catalog` 和版本端点展示证据。阶段 1 不切换运行时解析、不引入发布状态机，也不允许 Portal 上传或编辑 Skill 源文件。

**Tech Stack:** Python 3.12、Pydantic v2、FastAPI、PostgreSQL JSONB、Next.js 16、React 19、TypeScript、pytest、Vitest、Playwright。

---

## 范围与基线

- 实施详细设计的“阶段 1：版本化资产库”。
- 新增领域模型与存储属于 R4，已由 `docs/superpowers/specs/2026-08-05-skill-lifecycle-governance-workbench-design.md` 提供人工先行设计。
- 保留 `GET /infra-skills`、`GET /infra-skills/{skill_id}`、路由测试、执行测试和运行时加载行为。
- 当前基线测试：相关单元测试 `159 passed / 3 failed`。预存失败为 Manifest 名称断言 1 项、缓存反序列化 2 项，不纳入本计划修改。

## 文件结构

- Create: `src/domain/skill/version_models.py` — Skill 制品快照、版本与校验状态领域模型。
- Modify: `src/domain/skill/__init__.py` — 导出新模型。
- Modify: `src/domain/AGENTS.md` — 将新领域术语加入通用语言字典。
- Create: `src/skill_infra/artifact.py` — 安全遍历 Skill 目录并计算确定性 SHA-256。
- Create: `src/data_platform/storage/skill/version_ports.py` — 版本存储 Protocol。
- Create: `src/data_platform/storage/skill/version_in_memory.py` — 内存实现。
- Create: `src/data_platform/storage/skill/version_postgres.py` — PostgreSQL 表结构与实现。
- Create: `src/data_platform/storage/skill/version_factory.py` — 按 `USE_MEMORY_STORAGE` 选择实现并提供进程单例。
- Create: `src/runtime/skill_management/__init__.py` — 应用服务包。
- Create: `src/runtime/skill_management/version_service.py` — 版本登记、目录聚合与详情查询。
- Modify: `src/runtime/api/schemas.py` — 新增显式分页、版本证据 DTO。
- Modify: `src/runtime/api/infra_skill_routes.py` — 新增 catalog、sync、versions 端点。
- Modify: `src/apps/portal/src/lib/types.ts` — 前端 DTO。
- Modify: `src/apps/portal/src/lib/api-client.ts` — 新 API 客户端。
- Modify: `src/apps/portal/src/components/infra-skill-management.tsx` — 版本字段、登记动作和版本证据页签。
- Create: `src/tests/unit/domain/skill/test_skill_version_models.py` — 领域约束。
- Create: `src/tests/unit/skill_infra/test_artifact.py` — 哈希稳定性和边界。
- Create: `src/tests/unit/data_platform/test_skill_version_storage.py` — 存储契约。
- Create: `src/tests/unit/runtime/skill_management/test_version_service.py` — 应用服务。
- Modify: `src/tests/integration/api/test_infra_skill_routes.py` — 新端点与旧契约兼容。
- Create: `src/apps/portal/src/lib/skill-catalog.test.ts` — API 客户端契约。
- Create: `src/tests/e2e/pages/portal/skill-catalog.page.ts` — Portal 版本化资产页 Page Object。
- Create: `src/tests/e2e/flows/portal/skill-catalog.flow.ts` — 资产登记与证据展示流程。
- Modify: `PROGRESS.md` — 增加技能管理阶段 1 的实施与验证状态。

### Task 1: 不可变制品模型与确定性哈希

**Files:**
- Create: `src/domain/skill/version_models.py`
- Modify: `src/domain/skill/__init__.py`
- Modify: `src/domain/AGENTS.md`
- Create: `src/skill_infra/artifact.py`
- Test: `src/tests/unit/domain/skill/test_skill_version_models.py`
- Test: `src/tests/unit/skill_infra/test_artifact.py`

- [x] **Step 1: 写领域模型失败测试**

```python
def test_skill_version_rejects_non_sha256_hash():
    with pytest.raises(ValidationError):
        SkillVersion(
            version_id="v1",
            skill_id="demo_skill",
            semantic_version="1.0.0",
            source_commit="abc123",
            source_path="skills/demo_skill",
            artifact_hash="bad",
            manifest_snapshot={},
            dependency_snapshot={},
            file_count=1,
        )
```

- [x] **Step 2: 运行模型测试并确认因模块不存在而失败**

Run: `uv run --frozen python -m pytest src/tests/unit/domain/skill/test_skill_version_models.py -q --tb=short`

Expected: FAIL，原因是 `src.domain.skill.version_models` 尚不存在。

- [x] **Step 3: 实现最小领域模型**

```python
class SkillValidationStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class SkillVersion(BaseModel):
    model_config = ConfigDict(frozen=True)
    version_id: str
    skill_id: str
    semantic_version: str
    source_commit: str
    source_path: str
    artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_snapshot: dict[str, Any] = Field(default_factory=dict)
    dependency_snapshot: dict[str, Any] = Field(default_factory=dict)
    file_count: int = Field(ge=1)
    validation_status: SkillValidationStatus = SkillValidationStatus.PENDING
    validation_issues: list[SkillValidationIssue] = Field(default_factory=list)
    created_by: str = "system"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

- [x] **Step 4: 写制品哈希失败测试**

```python
def test_build_artifact_snapshot_is_stable_and_ignores_pycache(tmp_path):
    skill_dir = _write_skill(tmp_path)
    first = build_skill_artifact(skill_dir, skills_root=tmp_path)
    (skill_dir / "__pycache__").mkdir()
    (skill_dir / "__pycache__" / "assembler.pyc").write_bytes(b"cache")
    second = build_skill_artifact(skill_dir, skills_root=tmp_path)
    assert first.artifact_hash == second.artifact_hash
    assert first.file_paths == second.file_paths


def test_build_artifact_snapshot_rejects_path_outside_skills_root(tmp_path):
    outside = tmp_path.parent / "outside-skill"
    outside.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="SKILLS_DIR"):
        build_skill_artifact(outside, skills_root=tmp_path)
```

- [x] **Step 5: 运行哈希测试并确认失败**

Run: `uv run --frozen python -m pytest src/tests/unit/skill_infra/test_artifact.py -q --tb=short`

Expected: FAIL，原因是 `build_skill_artifact` 尚不存在。

- [x] **Step 6: 实现安全遍历与确定性哈希**

```python
def build_skill_artifact(skill_dir: Path, *, skills_root: Path) -> SkillArtifactSnapshot:
    root = skills_root.resolve()
    resolved = skill_dir.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Skill 路径必须位于 SKILLS_DIR 内")
    manifest_path = resolved / "skill_manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    files = [
        path for path in resolved.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    digest = hashlib.sha256()
    relative_paths: list[str] = []
    for path in sorted(files, key=lambda item: item.relative_to(resolved).as_posix()):
        relative = path.relative_to(resolved).as_posix()
        relative_paths.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return SkillArtifactSnapshot(
        skill_id=str(manifest.get("skill_id") or resolved.name),
        semantic_version=str(manifest.get("version") or "1.0.0"),
        source_path=resolved.relative_to(root.parent).as_posix(),
        artifact_hash=digest.hexdigest(),
        manifest_snapshot=manifest,
        dependency_snapshot=_dependency_snapshot(manifest),
        file_paths=relative_paths,
    )
```

- [x] **Step 7: 运行两组测试并提交**

Run: `uv run --frozen python -m pytest src/tests/unit/domain/skill/test_skill_version_models.py src/tests/unit/skill_infra/test_artifact.py -q --tb=short`

Expected: PASS。

Commit: `feat: add immutable skill artifact model`

### Task 2: 版本存储端口与内存/PostgreSQL 实现

**Files:**
- Create: `src/data_platform/storage/skill/version_ports.py`
- Create: `src/data_platform/storage/skill/version_in_memory.py`
- Create: `src/data_platform/storage/skill/version_postgres.py`
- Create: `src/data_platform/storage/skill/version_factory.py`
- Test: `src/tests/unit/data_platform/test_skill_version_storage.py`

- [x] **Step 1: 写存储契约失败测试**

```python
def test_in_memory_version_storage_is_idempotent_by_artifact():
    storage = InMemorySkillVersionStorage()
    version = _version("a" * 64)
    assert storage.save_version(version) == version
    assert storage.save_version(version.model_copy(update={"version_id": "other"})) == version
    assert storage.list_versions("demo_skill") == [version]


def test_in_memory_version_storage_rejects_semver_collision():
    storage = InMemorySkillVersionStorage()
    storage.save_version(_version("a" * 64))
    with pytest.raises(SkillVersionConflictError):
        storage.save_version(_version("b" * 64))
```

- [x] **Step 2: 运行并确认失败**

Run: `uv run --frozen python -m pytest src/tests/unit/data_platform/test_skill_version_storage.py -q --tb=short`

Expected: FAIL，原因是版本存储类尚不存在。

- [x] **Step 3: 实现端口和内存存储**

```python
class SkillVersionStorage(Protocol):
    def save_version(self, version: SkillVersion) -> SkillVersion: ...
    def get_version(self, skill_id: str, version_id: str) -> SkillVersion | None: ...
    def find_by_artifact_hash(self, skill_id: str, artifact_hash: str) -> SkillVersion | None: ...
    def list_versions(self, skill_id: str) -> list[SkillVersion]: ...
```

内存实现按 `(skill_id, semantic_version)` 检查冲突，按 `(skill_id, artifact_hash)` 保证幂等，并始终返回深拷贝。

- [x] **Step 4: 实现 PostgreSQL 表与适配器**

```sql
CREATE TABLE IF NOT EXISTS skill_versions (
    version_id VARCHAR(64) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL REFERENCES skills(skill_id),
    semantic_version VARCHAR(64) NOT NULL,
    source_commit VARCHAR(64) NOT NULL,
    source_path TEXT NOT NULL,
    artifact_hash VARCHAR(64) NOT NULL,
    manifest_snapshot JSONB NOT NULL DEFAULT '{}',
    dependency_snapshot JSONB NOT NULL DEFAULT '{}',
    file_count INTEGER NOT NULL,
    validation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    validation_issues JSONB NOT NULL DEFAULT '[]',
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(skill_id, semantic_version),
    UNIQUE(skill_id, artifact_hash)
);
```

保存版本前以 Manifest 快照中的 `skill_id/skill_name` 幂等补齐 `skills` 身份行，再写入带外键的版本行。捕获唯一约束冲突并转换为 `SkillVersionConflictError`，禁止 API 泄露数据库异常文本。

- [x] **Step 5: 运行存储测试并提交**

Run: `uv run --frozen python -m pytest src/tests/unit/data_platform/test_skill_version_storage.py -q --tb=short`

Expected: PASS。

Commit: `feat: persist immutable skill versions`

### Task 3: 版本应用服务和兼容 API

**Files:**
- Create: `src/runtime/skill_management/__init__.py`
- Create: `src/runtime/skill_management/version_service.py`
- Modify: `src/runtime/api/schemas.py`
- Modify: `src/runtime/api/infra_skill_routes.py`
- Create: `src/tests/unit/runtime/skill_management/test_version_service.py`
- Modify: `src/tests/integration/api/test_infra_skill_routes.py`

- [x] **Step 1: 写服务失败测试**

```python
def test_sync_current_version_is_idempotent(tmp_path):
    loader = _loader_with_demo_skill(tmp_path)
    service = SkillVersionService(InMemorySkillVersionStorage(), loader, tmp_path)
    first = service.sync_version("demo_skill", source_commit="abc123", created_by="tester")
    second = service.sync_version("demo_skill", source_commit="abc123", created_by="tester")
    assert first.version_id == second.version_id
    assert len(service.list_versions("demo_skill")) == 1


def test_catalog_marks_changed_artifact(tmp_path):
    service = _service(tmp_path)
    service.sync_version("demo_skill", source_commit="abc123", created_by="tester")
    (tmp_path / "demo_skill" / "SKILL.md").write_text("changed", encoding="utf-8")
    assert service.list_catalog(page=1, page_size=20).items[0].artifact_status == "changed"
```

- [x] **Step 2: 运行并确认失败**

Run: `uv run --frozen python -m pytest src/tests/unit/runtime/skill_management/test_version_service.py -q --tb=short`

Expected: FAIL，原因是 `SkillVersionService` 尚不存在。

- [x] **Step 3: 实现最小应用服务**

服务必须：校验 Skill 已加载；从 `SKILLS_DIR/<skill_id>` 构建快照；按制品哈希幂等登记；生成 `uuid4().hex`；目录查询返回 `registered / changed / unregistered`；筛选在分页前执行；不存在时抛出显式 `SkillNotFoundError`。

- [x] **Step 4: 写 API 失败测试**

```python
def test_catalog_is_paginated_without_breaking_legacy_list(client):
    legacy = client.get(f"{PREFIX}/infra-skills")
    catalog = client.get(f"{PREFIX}/infra-skills/catalog?page=1&page_size=20")
    assert legacy.status_code == 200 and isinstance(legacy.json(), list)
    assert catalog.status_code == 200
    assert {"items", "page", "page_size", "total"} <= catalog.json().keys()


def test_sync_and_read_version_evidence(client):
    synced = client.post(
        f"{PREFIX}/infra-skills/settlement_explain_skill/versions/sync",
        json={"source_commit": "abc123", "created_by": "tester"},
    )
    assert synced.status_code == 201
    versions = client.get(f"{PREFIX}/infra-skills/settlement_explain_skill/versions")
    assert versions.status_code == 200
    assert versions.json()[0]["artifact_hash"] == synced.json()["artifact_hash"]
```

- [x] **Step 5: 运行 API 测试并确认失败**

Run: `uv run --frozen python -m pytest src/tests/integration/api/test_infra_skill_routes.py -q --tb=short`

Expected: FAIL，新增端点返回 404。

- [x] **Step 6: 实现 DTO 与端点**

新增端点必须位于 `/{skill_id}` 动态路由之前：

```text
GET  /infra-skills/catalog
GET  /infra-skills/{skill_id}/versions
GET  /infra-skills/{skill_id}/versions/{version_id}
POST /infra-skills/{skill_id}/versions/sync
```

`sync` 仅接受 `source_commit` 和 `created_by`，不接受任意文件内容；冲突返回 409，路径/Manifest 校验失败返回 422，不存在返回 404，错误统一通过 `error_detail()`。

- [x] **Step 7: 按顺序运行单元与 API 测试并提交**

Run 1: `uv run --frozen python -m pytest src/tests/unit/domain/skill/test_skill_version_models.py src/tests/unit/skill_infra/test_artifact.py src/tests/unit/data_platform/test_skill_version_storage.py src/tests/unit/runtime/skill_management/test_version_service.py -q --tb=short`

Run 2: `uv run --frozen python -m pytest src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_infra_skill_workbench_api.py -q --tb=short`

Expected: 两步均 PASS。

Commit: `feat: expose versioned skill catalog api`

### Task 4: Portal 版本化资产视图

**Files:**
- Modify: `src/apps/portal/src/lib/types.ts`
- Modify: `src/apps/portal/src/lib/api-client.ts`
- Create: `src/apps/portal/src/lib/skill-catalog.test.ts`
- Modify: `src/apps/portal/src/components/infra-skill-management.tsx`

- [ ] **Step 1: 写 API 客户端失败测试**

```typescript
it('requests the paginated skill catalog', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    items: [], page: 1, page_size: 20, total: 0,
  }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
  await listInfraSkillCatalog({ page: 1, page_size: 20 })
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/infra-skills/catalog?page=1&page_size=20'), expect.anything())
})
```

- [ ] **Step 2: 运行并确认失败**

Run: `npm test -- --run src/lib/skill-catalog.test.ts`

Workdir: `src/apps/portal`

Expected: FAIL，原因是 `listInfraSkillCatalog` 尚未导出。

- [ ] **Step 3: 实现前端 DTO 和客户端**

```typescript
export interface InfraSkillCatalogItem extends InfraSkillItem {
  semantic_version: string
  source_commit?: string | null
  artifact_hash: string
  artifact_status: 'registered' | 'changed' | 'unregistered'
  validation_status: 'pending' | 'passed' | 'failed' | 'unregistered'
  file_count: number
}

export interface InfraSkillCatalogResponse {
  items: InfraSkillCatalogItem[]
  page: number
  page_size: number
  total: number
}
```

- [ ] **Step 4: 升级列表和详情交互**

列表新增“版本 / 制品状态 / 校验”三列；哈希只显示前 12 位并保留完整 title；详情新增“版本证据”页签；未登记或文件已变化时显示“登记当前版本”按钮；登记成功只刷新当前 Skill 和目录，不清空筛选或其他已加载区域；错误显示在局部区域。

- [ ] **Step 5: 运行前端测试、lint、build 并提交**

Run 1: `npm test -- --run src/lib/skill-catalog.test.ts`

Run 2: `npm run lint`

Run 3: `npm run build`

Workdir: `src/apps/portal`

Expected: 全部 PASS。

Commit: `feat: show skill version evidence in portal`

### Task 5: Flow 验证、进度记录与回滚说明

**Files:**
- Create: `src/tests/e2e/pages/portal/skill-catalog.page.ts`
- Create: `src/tests/e2e/flows/portal/skill-catalog.flow.ts`
- Modify: `PROGRESS.md`

- [ ] **Step 1: 先补充 E2E 期望**

```typescript
test('登记当前 Skill 版本并查看不可变证据', async ({ page }) => {
  const catalogPage = new SkillCatalogPage(page)
  await catalogPage.goto()
  await catalogPage.registerCurrentVersion('settlement_explain_skill')
  await expect(catalogPage.versionEvidence).toContainText('artifact hash')
  await expect(catalogPage.versionEvidence).toContainText(/Git commit/i)
})
```

- [ ] **Step 2: 启动服务并运行 E2E**

Run 1: `.\start-servers.ps1`

Run 2: `npx playwright test flows/portal/skill-catalog.flow.ts`

Workdir: `src/tests/e2e`

Expected: PASS。失败时保留截图和 trace；完成后运行项目根目录 `.\stop-servers.ps1`。

- [ ] **Step 3: 严格执行 R4 收尾验证**

Run 1（T1）: `uv run --frozen python -m pytest src/tests/unit/domain/skill src/tests/unit/skill_infra src/tests/unit/data_platform/test_skill_version_storage.py src/tests/unit/runtime/skill_management -q --tb=short`

Run 2（T2a）: `uv run --frozen python -m pytest src/tests/integration/api/test_infra_skill_routes.py src/tests/integration/api/test_infra_skill_workbench_api.py -q --tb=short`

Run 3（T2b）: `uv run --frozen python -m pytest src/tests/integration/flow/test_skill_mention.py src/tests/integration/flow/test_skill_intent_matching.py -q --tb=short`

Run 4（前端）: `npm test && npm run lint && npm run build`

Workdir: `src/apps/portal`

Expected: 新增及相关测试全部通过；预存 3 项基线失败单独列示，不得伪装为本次回归。

- [ ] **Step 4: 更新进度和兼容/回滚说明**

在 `PROGRESS.md` 技能管理下新增阶段 1：记录版本模型、目录 API、Portal 展示和验证结果。回滚方式为恢复旧 Portal 使用 `GET /infra-skills`，停止调用版本端点；运行时始终未切换，故回滚不影响 SkillRouter/SkillLoader。

- [ ] **Step 5: 提交进度证据**

Commit: `docs: record skill catalog phase one verification`
