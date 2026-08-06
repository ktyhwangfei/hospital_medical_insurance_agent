# Skill 管理工作台实现计划

**版本**: 1.0 | **日期**: 2026-08-06
**依据**: `docs/superpowers/specs/2026-08-06-skill-management-workbench-design.md`（本计划的唯一需求来源）
**定位**: 把设计文档拆解为可执行、可验证、可回滚的最小单元序列。

> 与设计文档冲突时以设计文档为准；本计划只管"怎么交付"。
> 标注：`[已完成]` 现状已具备；`[半成品]` 有骨架未接通；`[未开始]` 尚未实现。

### 阶段进度

| 阶段 | 状态 | 验证证据 |
|------|------|----------|
| P0 领域模型与草稿存储基础 | ✅ 完成 | 单元 35 passed（内存契约 24 + PG SQL 9 + 工厂 2）；真实 PG smoke 10 项过；无回归 |
| P1 草稿 CRUD + 复制后端 | ✅ 完成 | 单元 14 passed + API 14 passed |
| P2 草稿校验 + 包生成 | ✅ 完成 | 单元 18 passed（校验器 + 包生成器）|
| P3 导入服务 | ✅ 完成 | 单元 17 passed（ZIP/Git/Dir 安全校验）|
| P4 输入指标契约 + 语义层交互 | ✅ 完成 | 单元 12 passed + 4 个语义层端点 |
| P5 物化 + 版本登记 | ✅ 完成 | 单元 8 passed（原子写入/回滚/版本登记）|
| P6 生命周期停用/恢复/归档 | ✅ 完成 | 单元 10 passed（状态转换 + governance 联动）|
| P7 前端工作台骨架重构 | ✅ 完成 | Next.js build 成功；layout + 4 页签 + 8 路由 |
| P8 前端创建与编辑器 | ✅ 完成 | Vitest 14 passed（API client 10 + 向导 4）；build 成功 |
| P9 E2E 主链路与验收 | ✅ 完成 | 流程测试 5 passed（创建→保存→校验→物化→停用→恢复→归档）|

---

## 0. 价值地图（决策者视角）

### 0.1 最终目标（一句话）

把 `/skills` 从"治理观测台"升级为"管理闭环工作台"——用户能在工作台内**创建/导入/复制 → 编辑 → 校验 → 物化 → 登记 → 评测 → Test 激活 → 停用/归档**，且 Skill 只声明输入指标、不碰查询实现。

升级后这五个痛点消失：

1. **不能从工作台创建 Skill** → 模板向导 / 导入 / 复制三入口。
2. **草稿直接覆盖正式目录** → 独立草稿存储 + 校验门禁 + 原子物化。
3. **Skill 耦合数据库字段和知识库配置** → 只声明输入指标，查询方式由语义对象决定。
4. **当前 Test Active 被草稿编辑破坏** → 不可变版本快照 + 草稿隔离。
5. **页面深层嵌套、和语义层/政策知识页不一致** → 对齐扁平页签骨架。

### 0.2 价值 × 时机矩阵

| 业务价值 | 阶段 | 见效里程碑 | 当前 |
|---------|------|-----------|------|
| 不破坏现有运行时（安全网） | P0 | 现在 | `[已完成]` 现有版本/评测/发布已 shadow 解耦 |
| 草稿能建能存（管理闭环雏形） | P0–P3 | M1 | `[未开始]` |
| Skill 输入契约与查询解耦（核心设计价值） | P4 | M2 | `[未开始]` |
| 草稿能变正式版本（物化 + 登记） | P5–P6 | M2 | `[未开始]` |
| 工作台能用（前端完整体验） | P7–P8 | M3 | `[未开始]`（当前是单页 InfraSkillManagement） |
| 主链路可验收 | P9 | M4 | `[未开始]` |

### 0.3 为什么 P0–P6 先"看不到前端变化"

策略与政策知识管线重构一致：**先平行建草稿管理新通路，不动现有 SkillLoader/SkillRouter 读路径**。Test Active 仍由现有 `SkillRelease(shadow)` resolver 解析，草稿物化写入 `skills/` 前，业务流量零影响。

- **代价**：P0–P6 是后端建设，前端到 P7 才重构。
- **收益**：重构期 Skill 路由零停摆、可随时回滚（停调草稿/物化端点即可）。
- **里程碑 M1–M4 是可验证的中间交付**，每阶段三层验证（单元→API→Flow）全绿才算完成。

---

## 1. 现状盘点（Gap 分析）

盘点基于实际代码（非文档）。设计文档是一次**能力扩展**，且已有大量可复用资产。

### 1.1 可复用资产清单（`[已完成]`）

| 资产 | 文件 | 复用于 |
|------|------|--------|
| 版本登记（不可变快照 + 制品哈希） | `domain/skill/version_models.py`、`runtime/skill_management/version_service.py`、`storage/skill/version_*` | P5 物化后登记版本 |
| 评测 + Test 发布门禁（候选/基线/审批/唯一 active/shadow） | `domain/skill/governance_models.py`、`runtime/skill_management/governance_service.py`、`storage/skill/governance_*` | P6 后接评测/发布（设计 §6 复用） |
| 治理工作台聚合读模型 | `runtime/skill_management/workbench_service.py` → `/infra-skills/workbench` | P7 列表页数据源 |
| 幂等机制（reserve→complete + 409 复用） | `infra_skill_routes.py::_idempotent_release_mutation` | P1/P5/P6 写操作 |
| 写权限门禁（dev 模式 + 权限 + 角色审批） | `infra_skill_routes.py::_resolve_dev_principal` | 所有草稿/物化/生命周期写操作 |
| 语义层运行时取数（版本锁定读对象快照） | `semantic_layer/builder.py::BusinessFactsBuilder`、`registry.py::SemanticRegistry` | P4 query-plan / test-query |
| 语义层领域模型（Domain/Object/Metric/Version 快照） | `semantic_layer/models.py` | P4 输入选择器数据源 |
| Skill 基础设施（加载/路由/制品哈希） | `skill_infra/skill_loader.py`、`skill_router.py`、`artifact.py` | P2 包生成 + P5 物化后 reload |
| 前端单页治理组件 | `src/components/skills/*`、`infra-skill-management.tsx` | P7/P8 部分组件可迁移到新骨架 |

### 1.2 必须新建的能力（`[未开始]`）

| 能力 | 设计章节 | 新建位置 |
|------|---------|----------|
| `SkillDraft` 领域模型 + 草稿存储 | §6, §7.1 | `domain/skill/draft_models.py`、`storage/skill/draft_*` |
| `SkillDraftService`（CRUD + 复制） | §7.1, §4.3 | `runtime/skill_management/draft_service.py` |
| `SkillImportService`（ZIP/Git/受控目录） | §7.1, §4.2 | `runtime/skill_management/import_service.py` |
| `SkillDraftValidator`（结构/分类/指标/Schema/脚本） | §7.1, §8.2, §5.4 | `runtime/skill_management/draft_validator.py` |
| `SkillPackageGenerator`（生成标准包） | §7.1, §4.1.4 | `runtime/skill_management/package_generator.py` |
| `SkillMaterializer`（原子写入 + 回滚） | §7.1, §8.3 | `runtime/skill_management/materializer.py` |
| 输入指标语义预览接口 | §7.3, §5.4 | `runtime/api/infra_skill_routes.py`（新增端点） |
| 停用/恢复/归档状态转换 | §6, §7.2 | 复用 governance + 新增 Definition 状态 |
| 前端扁平页签骨架 + 独立路由 | §3 | `app/skills/layout.tsx` + 子路由 |

### 1.3 设计章节 ↔ 现状 ↔ Gap 矩阵

| 设计章节 | 要点 | 现状 | Gap |
|---|---|---|---|
| §3 信息架构（页签 + 独立详情/编辑） | `[半成品]` 现为单页 `InfraSkillManagement`，无独立路由 | **大** | 新建 layout + 6 条子路由 |
| §4.1 模板向导（四步） | `[未开始]` | **大** | 后端包生成 + 前端向导 |
| §4.2 导入（ZIP/Git/受控目录 + 安全校验） | `[未开始]` | **大** | 导入服务 + 安全校验 |
| §4.3 复制（必填新 skill_id） | `[未开始]` | 中 | 草稿复制（不含历史/评测/审计/敏感） |
| §5 输入指标 = 业务指标契约 | `[未开始]` Skill 当前用 `needed_objects` + `field_mapping.yaml` | **大** | 新建 InputSpec 契约 + 校验门禁 + 查询计划预览 |
| §5.2 查询方式由语义对象决定 | `[已完成]` `BusinessFactsBuilder` 已按 adapter_port 路由取数 | 小 | Skill 编辑器改为只读展示查询计划 |
| §5.4 语义校验门禁 + 依赖变化标记 | `[未开始]` | **大** | 校验门禁 + 跨模块依赖标记 |
| §6 领域模型（Draft/Definition/Version/EvalRun/Release） | Version/EvalRun/Release `[已完成]`；Draft/Definition `[未开始]` | 中 | 补 Draft + Definition 状态 |
| §7.1 后端组件（6 个 Service/Validator/Generator/Materializer） | `[未开始]` | **大** | 全部新建 |
| §7.2 草稿接口（10 个端点） | `[未开始]` | **大** | 新增路由 |
| §7.3 语义预览接口（3 个端点） | `[未开始]` | **大** | 新增路由 |
| §8 安全/确认/失败处理 | 幂等 `[已完成]`（release）；草稿幂等/乐观锁/导入安全/原子物化 `[未开始]` | 中 | 移植幂等模式 + 新增乐观锁 + 导入安全 |
| §9 验证策略 | 版本/评测/发布测试 `[已完成]` | 小 | 补草稿/导入/物化/生命周期测试 |

---

## 2. 阶段划分

共 10 个阶段（P0–P9）。依赖链：**P0 → P1 → (P2, P3) → P4 → P5 → P6**（后端，串行为主）；后端稳定后 **P7 → P8 → P9**（前端，P7 骨架可在 P5 完成后并行启动）。

每阶段遵循项目三层验证铁律：**单元测试 → API 测试 → Flow 测试**，三层全绿才算完成。

### P0 — 领域模型与草稿存储基础 ✅ 完成

**目标**：建立 `SkillDraft` 领域模型和草稿存储 port/adapter（PostgreSQL + 内存），带乐观锁修订号。

**范围**：
- 新建 `src/domain/skill/draft_models.py`：
  - `SkillDraft`（frozen Pydantic）：`draft_id`、`skill_id`、`skill_name`、`source_type`(template/import/copy)、`source_skill_id`(复制来源)、`structured_config`(dict：基本信息/业务挂载/输入指标契约/InputOutput Schema)、`raw_files`(可选：导入/源码编辑产物)、`validation_report`(dict|null)、`revision`(乐观锁)、`status`(editing/validated/materialized)、`created_by`、`updated_at`、`deleted_at`(软删)。
  - `SkillDefinition`：承载"正式目录中的可加载定义"的治理状态（`enabled`/`disabled`/`archived`），与不可变 `SkillVersion` 区分。
  - 状态枚举 `SkillDraftStatus`、`SkillLifecycleStatus`。
- 新建 `storage/skill/draft_ports.py`（Protocol）：`save / get / list / delete + conflict error`，带 `expected_revision` 乐观锁。
- 新建 `storage/skill/draft_in_memory.py` + `draft_postgres.py` + `draft_factory.py`（遵循现有 `version_factory`/`governance_factory` 模式）。
- 数据库迁移：`skill_draft` 表（PG 方言，参照 `version_postgres.py`）。

**复用**：现有 `version_*` 存储三件套作为模板；`USE_MEMORY_STORAGE=1` 回退约定。

**验证**：
- 单元测试 `tests/unit/runtime/skill_management/test_draft_storage.py`：CRUD、乐观锁冲突、软删、PG/内存等价。

**依赖**：无。

**风险**：
- ⚠️ `[待确认 D1]` SkillDraft 的 `structured_config` 是存单列 JSON blob（简单，推荐）还是拆多表（规范但复杂）。本计划默认 **JSON blob**（草稿是过渡态，查询需求低）。
- ⚠️ `[待确认 D2]` `SkillDefinition` 是否需要独立持久化表。本计划默认**独立表 `skill_definition`**（承载 enabled/disabled/archived 状态，否则停用/归档无处存）。

---

### P1 — 草稿 CRUD + 复制后端

**目标**：实现 `SkillDraftService`（创建、保存、删除、复制）+ 草稿 API，带乐观锁 409 与审计骨架。

**范围**：
- 新建 `runtime/skill_management/draft_service.py`：
  - `create_from_template(structured_config, created_by)` → 空 `structured_config` 草稿。
  - `save_draft(draft_id, structured_config, expected_revision)` → 乐观锁校验，冲突抛 `SkillDraftConflictError`。
  - `delete_draft(draft_id, expected_revision)` → 软删（保留可恢复窗口期由策略定）。
  - `copy_skill(source_skill_id, new_skill_id, created_by)` → 复制结构化配置 + 文件内容，**排除**版本历史/评测/发布/审计/敏感配置（设计 §4.3）。
- 新建 API 端点（`infra_skill_routes.py`）：
  - `POST /infra-skills/drafts`、`GET /infra-skills/drafts`、`GET /infra-skills/drafts/{draft_id}`
  - `PATCH /infra-skills/drafts/{draft_id}`（带 `expected_revision`，冲突 409）
  - `DELETE /infra-skills/drafts/{draft_id}`（带 `expected_revision`）
  - `POST /infra-skills/{skill_id}/copy`（body 含 `new_skill_id`）
- 新建 `src/runtime/api/skill_schemas.py` 中追加草稿请求/响应模型。
- 审计事件骨架：草稿写操作记录 actor/before/after/idempotency_key（接入 P0 后续审计表，或先用日志占位）。
- 移植幂等模式到草稿写操作（reserve→complete）。

**复用**：`_resolve_dev_principal`（写权限门禁）、`_idempotent_release_mutation`（幂等模式）、`error_detail`（错误契约）。

**验证**：
- 单元测试 `test_draft_service.py`：三种创建来源、修订冲突、删除规则、复制排除项。
- API 测试 `tests/integration/api/test_skill_draft_api.py`：完整 CRUD、409 冲突、权限拒绝。

**依赖**：P0。

---

### P2 — 草稿校验 + 包生成

**目标**：实现 `SkillDraftValidator`（结构/分类/Schema/脚本安全，不含语义，语义在 P4）+ `SkillPackageGenerator`（生成标准 Skill 包结构），暴露 validate 与 package-preview 端点。

**范围**：
- 新建 `runtime/skill_management/draft_validator.py`：
  - 结构校验：`skill_manifest.yaml` 必需字段、目录结构完整性。
  - 领域分类校验：`BusinessAction`/`BusinessObject` 在 `domain/common/actions.py` 白名单内。
  - Schema 校验：`input.schema.json`/`output.schema.json` 可解析、字段类型合法。
  - 脚本安全校验：检测危险调用（`eval`/`exec`/`subprocess`/`os.system`）、密钥/患者信息泄露（设计 §8.2）。
  - 产出 `ValidationReport`（issues 列表 + blocking/warning 分级）。
- 新建 `runtime/skill_management/package_generator.py`：
  - 输入：`structured_config` + `raw_files`。
  - 输出：内存中的 `SkillPackage`（文件树 dict：`SKILL.md`、`skill_manifest.yaml`、`config.yaml`、`schemas/*`、`templates/*`、`scripts/*`、`references/*`），**不落盘**。
  - 模板向导第四步"生成预览"的数据源（设计 §4.1.4）。
- 新建 API 端点：
  - `POST /infra-skills/drafts/{draft_id}/validate` → 返回 `ValidationReport`。
  - `GET /infra-skills/drafts/{draft_id}/package-preview` → 返回文件树 + 文件 diff（与现有正式包对比）。

**复用**：`skill_infra/artifact.py`（制品哈希计算，用于 diff）、`domain/common/actions.py`（VALID_ACTION_OBJECT_PAIRS 白名单）、现有 `settlement_explain_skill` 作为生成模板蓝本。

**验证**：
- 单元测试 `test_draft_validator.py`：各校验门禁触发 + 通过、脚本危险调用拦截、敏感内容检测。
- 单元测试 `test_package_generator.py`：生成结构完整、模板渲染正确。
- API 测试：validate 返回错误字段、package-preview 返回文件树。

**依赖**：P1。

**风险**：脚本安全静态分析可能误报/漏报——初版用关键词 + AST 黑名单，后续可加强。

---

### P3 — 导入服务

**目标**：实现 `SkillImportService`（ZIP / Git / 受控目录三种来源）+ 安全校验，导入只生成草稿不自动写入、不自动执行脚本。

**范围**：
- 新建 `runtime/skill_management/import_service.py`：
  - `import_from_zip(upload_bytes)`、`import_from_git(url)`、`import_from_controlled_dir(rel_path)`。
  - 统一产出 `SkillDraft(source_type=import, raw_files=...)`，不写入 `skills/`，不执行脚本。
- 安全校验（设计 §8.2）：
  - ZIP：大小上限、文件数量上限、扩展名白名单、目录穿越（`..`/绝对路径）、符号链接检测。
  - Git：协议白名单（https/ssh）、允许主机列表、禁止本机/内网/保留地址、克隆深度限制。
  - 受控目录：限制在配置的导入根目录（`config` 新增 `SKILL_IMPORT_ROOT`），禁止 `..` 跳出。
  - 内容扫描：复用 P2 的敏感内容检测（密钥/患者信息）。
- 新建 API 端点：
  - `POST /infra-skills/drafts/import`（multipart：来源类型 + ZIP 文件 / Git URL / 目录相对路径）。
- `config/` 新增导入安全配置项（根目录、大小/数量上限、允许主机）。

**复用**：P2 的 `SkillDraftValidator`（导入后立即跑结构校验）、P1 的草稿创建。

**验证**：
- 单元测试 `test_import_service.py`：ZIP 路径穿越、符号链接、大小/数量超限、Git 地址违规、受控目录越界、敏感内容拦截、正常导入生成草稿。
- API 测试：三种来源导入成功 + 各类失败 4xx。

**依赖**：P1、P2。

**风险**：
- Git 克隆在生产环境可能受限（无网络/凭据）——Git 来源可标注为"开发环境可选能力"，受控目录与 ZIP 优先。
- ⚠️ `[待确认 D3]` 受控目录的根目录是否已有约定路径，需与部署对齐。

---

### P4 — 输入指标契约 + 语义层交互

**目标**：实现设计 §5 核心——Skill 只声明输入指标，语义层决定查询方式。提供输入指标校验门禁、查询计划预览、样例取数测试、输入选择器数据。

**范围**：
- 扩展 `SkillDraftValidator`（P2）增加输入指标校验门禁（设计 §5.4）：
  - 指标不存在或未发布 → 阻止登记。
  - 指标所属对象未配置查询实现（`source_adapter_port` 空） → 阻止登记。
  - 结构化指标无有效字段映射 → 阻止登记。
  - 政策知识指标无法提供来源引用 → 阻止登记。
  - 可选指标异常 → 警告，不阻塞。
- 定义 `InputSpec`（domain/skill）：`metric_code`、`alias`、`required`、`purpose`（设计 §5.3 YAML 契约）。
- 新建语义预览端点（设计 §7.3，接收 `InputSpec[]`，不要求草稿已物化）：
  - `POST /semantic/skill-inputs/validate` → 跑上述门禁，返回 `ValidationReport`。
  - `POST /semantic/skill-inputs/query-plan` → 只读查询计划（按对象分组，展示来源类型/adapter_port/字段映射/政策知识状态），**只读，不可被 Skill 覆盖**。
  - `POST /semantic/skill-inputs/test-query` → 样例取数（复用 `BusinessFactsBuilder.build`），返回样例数据（**必脱敏**：患者标识与返回数据走 `security/desensitization`）。
- 输入选择器数据接口（级联 业务域→语义对象→指标）：
  - `GET /infra-skills/input-selector` → 返回域/对象/指标树，每指标带：编码、名称、定义、来源类型、物理/政策知识状态、质量分、值域完整性、当前发布版本、被哪些 Skill 引用。
- 语义依赖变化标记（设计 §5.4 末段）：
  - 语义对象/指标发布变化时，引用它的 `SkillDefinition` 标记 `semantic_dependency_changed=True`。
  - `[待确认 D4]` 标记触发机制：在语义层 publish 路径增加回调扫描引用该对象/指标的 Skill，置标记位。当前 Test Active 不变，但未重新校验不得发布新版本。

**复用**：`SemanticRegistry`（get_metric_mapping / 版本快照）、`BusinessFactsBuilder`（样例取数）、`security/desensitization`（脱敏）。

**验证**：
- 单元测试 `test_input_validation.py`：各类门禁触发、必填/可选失败处理、查询计划生成、样例取数脱敏。
- 单元测试 `test_semantic_dependency.py`：语义变化 → Skill 标记位翻转。
- API 测试：三个语义预览端点 + input-selector 级联数据。

**依赖**：P2（Validator 基础）、P0（SkillDefinition 标记位）。

**风险**：
- 这是设计核心，门禁规则需与语义层实际数据对齐（指标 `status`/`source_adapter_port` 完整性）——P4 启动前需抽样核对现有 seed 指标的这些字段是否齐备。

---

### P5 — 物化 + 版本登记

**目标**：实现 `SkillMaterializer`（管理员确认后将校验通过的包原子写入正式 `skills/`），并复用 `SkillVersionService` 登记不可变版本。

**范围**：
- 新建 `runtime/skill_management/materializer.py`：
  - 前置门禁：草稿 `validation_report` 必须 blocking 全绿（含 P4 输入指标门禁）。
  - 生成临时包 → 校验通过 → 原子替换 `skills/{skill_id}/`（新 Skill 直接写入；已存在则备份旧目录→替换→失败回滚）。
  - 写入后调用 `refresh_loader()` 热重载（复用现有 `/infra-skills/refresh` 逻辑）。
  - 物化失败必须回滚，不产生半成品（设计 §8.3）。
  - 版本登记失败时保留草稿和校验报告。
- 新建 API 端点：
  - `POST /infra-skills/drafts/{draft_id}/materialize`（幂等键 + 二次确认 body：影响范围声明 + 原因）→ 写入 + 登记 `SkillVersion`（复用 `SkillVersionService.sync_version`）+ 创建草稿→materialized 状态转换。
- 二次确认（设计 §8.1）：返回 Skill/版本/影响范围/状态变化摘要，前端确认后才真正写入。

**复用**：`SkillVersionService.sync_version`（登记版本）、`refresh_loader`（热重载）、P2 `PackageGenerator`（生成临时包）、P1 幂等模式、P4 校验门禁。

**验证**：
- 单元测试 `test_materializer.py`：原子写入、写入失败回滚、版本登记失败保留草稿、半成品检测。
- Flow 测试 `tests/integration/flow/test_skill_materialize_flow.py`：草稿校验通过 → 物化 → 版本登记 → reload → SkillLoader 可加载。

**依赖**：P2（包生成）、P4（输入指标门禁）。

**风险**：
- 原子替换需处理 Windows 文件锁（备份目录 + 重试）。参照现有 `skill_loader` 的路径处理。

---

### P6 — 生命周期停用/恢复/归档

**目标**：实现设计 §6 的 disable/restore/archive 状态转换，与现有评测/发布门禁衔接。

**范围**：
- `SkillDefinition` 状态机：`enabled`（参与路由）→ `disabled`（解除 Test Active，不删定义/版本/审计）→ `archived`（默认不参与路由，历史证据可查）。
  - restore：`disabled` → `enabled`。
- 新建 API 端点（设计 §7.2）：
  - `POST /infra-skills/{skill_id}/disable`（幂等 + 二次确认 + 审计）。
  - `POST /infra-skills/{skill_id}/restore`。
  - `POST /infra-skills/{skill_id}/archive`。
- 与现有 `SkillRelease`（candidate/active/retired）的关系：
  - disable = 将该 Skill 当前 test active release 转 `retired` + Definition 置 `disabled`。
  - restore = Definition 置 `enabled`（需重新走发布流程才有新的 active）。
  - archive = Definition 置 `archived` + 该 Skill 默认不参与路由（`SkillRouter` 过滤）。
- 永久删除仅限草稿（设计 §6 规则 + §8.1 二次确认），正式 Skill 不可删。
- 审计记录：状态转换前后、actor、原因、幂等键、关联版本（设计 §8.1）。

**复用**：`SkillGovernanceService`（release 状态转换）、`SkillRouter`（归档过滤需扩展）、P1 审计骨架。

**验证**：
- 单元测试 `test_lifecycle_service.py`：disable→Test Active 退役、restore、archive→路由过滤、不可删正式版本、状态转换合法性。
- Flow 测试：物化登记 → 评测 → Test 激活 → 停用 → 恢复 → 归档 全链路状态正确。

**依赖**：P5（需要已物化的正式 Skill 才能停用）。

---

### P7 — 前端工作台骨架重构

**目标**：把单页 `InfraSkillManagement` 重构为对齐 `semantic-layer` 的扁平页签骨架 + 独立路由（设计 §3）。

**范围**：
- 新建 `app/skills/layout.tsx`（参照 `app/semantic-layer/layout.tsx`）：页签导航 + 页面标题头 + 背景氛围。
  - 页签：`Skill`（/skills）、`草稿`（/skills/drafts）、`评测记录`（/skills/evaluations）、`发布记录`（/skills/releases）。
- 路由拆分（设计 §3.4）：
  - `/skills`（管理列表）、`/skills/drafts`、`/skills/evaluations`、`/skills/releases`
  - `/skills/new`（模板向导，P8）、`/skills/import`（导入，P8）
  - `/skills/[skillId]`（独立详情）、`/skills/[skillId]/edit`（草稿编辑，P8）
- 管理列表页（设计 §3.2）：
  - 顶部：标题 + 说明 + `新建 Skill` 主按钮 + `导入 Skill` 次按钮 + 摘要数量（全部/草稿/待评测/待发布/Test Active）。
  - 平面表格：Skill 名称/skill_id、当前版本、BusinessAction/Object、治理状态、最近修改人/时间、行内操作（按状态匹配，设计 §3.2 典型行内操作清单）。
  - 筛选/排序。
- 数据源：复用 `/infra-skills/workbench`（P0 后扩展草稿/定义状态）。

**复用**：`semantic-layer/layout.tsx`（骨架范本）、`skill-governance-workbench.tsx` 等现有组件（迁移进新骨架）、`workbench_service` 数据。

**验证**：
- Vitest `src/tests/skill-workbench.test.tsx`：页签导航、列表筛选、行内操作渲染、摘要数量。
- ESLint（变更文件零错误）+ Next.js build 通过。
- 响应式（390px 无横向溢出，参照现有 7.6 验收）。

**依赖**：P0–P1（列表需展示草稿与定义状态）。P7 骨架可在 P5 完成后并行启动（列表先用现有 workbench 数据）。

---

### P8 — 前端创建与编辑器

**目标**：实现模板向导、导入页、结构化编辑器、输入指标级联选择器、详情/编辑页。

**范围**：
- 模板向导 `/skills/new`（设计 §4.1 四步）：
  1. 基本信息（skill_id、名称、说明、负责人）
  2. 业务挂载（BusinessAction/Object 下拉、关键词、排除意图）
  3. 输入输出契约（输入指标选择器、必填性、别名、用途、Input/Output Schema）
  4. 生成预览（SKILL.md / manifest / schema / 模板 / 目录结构 + diff + 校验结果）
  - 每步可保存草稿。
- 导入页 `/skills/import`（设计 §4.2）：三来源切换 + 安全校验提示 + 导入后跳转草稿编辑。
- 输入指标级联选择器（设计 §5.3）：业务域→语义对象→指标，每指标展示完整信息（编码/名称/定义/来源类型/物理或政策知识状态/质量分/值域/发布版本/被引用 Skill/核心可选标记）。
- 草稿编辑页 `/skills/[skillId]/edit`（设计 §4 + §5.4）：
  - 结构化表单为主，文件树 + 源码编辑为高级能力。
  - 语义校验与查询预览面板（只读查询计划 + 样例取数 + 来源引用/不确定性预览 + 跳转）。
  - 乐观锁（revision 冲突 → 提示并刷新）。
  - 未保存提示、URL 恢复、响应式。
- 详情页 `/skills/[skillId]`（设计 §3.3）：生命周期状态、当前 Active 版本、输入指标契约、版本记录、评测证据、Test 发布记录、开发详情/文件预览、审计记录。
- 二次确认弹窗（设计 §8.1）：物化/激活/停用/恢复/归档/删除草稿均展示影响范围 + 确认。

**复用**：现有 `skill-development-tab.tsx`、`skill-versions-tab.tsx`、`skill-evaluation-suite.tsx`、`skill-release-panel.tsx`（迁移进详情页）、`skill-query-plan.tsx`（查询计划展示）。

**验证**：
- Vitest：向导步骤、指标级联、编辑器乐观锁冲突、未保存提示、二次确认。
- ESLint + Next.js build 通过。
- 响应式 390px。

**依赖**：P3–P6 后端端点就绪（导入、语义预览、物化、生命周期）、P7 骨架。

**风险**：
- ⚠️ `[待确认 D5]` 结构化编辑与源码编辑的双向同步策略（改 YAML 是否回写表单）。初版建议：结构化为主、源码为只读预览 + 高级覆盖（不同步回写，避免双向解析复杂度）。

---

### P9 — E2E 主链路与验收

**目标**：打通设计 §9.3 主链路 + 异常链路，对照 §9.4 验收标准。

**范围**：
- E2E 主链路（设计 §9.3）：
  ```
  模板创建 → 选结构化指标 + 政策知识指标 → 查询计划预览 → 校验通过
    → 生成正式包 → 登记版本 → 运行评测 → Test 激活
    → 生成新草稿 → 停用旧版本 → 归档 Skill
  ```
- 异常链路：导入失败、必填指标缺失、语义指标失效、写入回滚、重复发布（幂等）。
- 验收对照（设计 §9.4）逐条核对。
- 更新 `PROGRESS.md` 技能管理领域（新增 §7.7 Skill 管理工作台）。

**验证**：
- Flow 测试 `tests/integration/flow/test_skill_management_workbench_flow.py`（主链路 + 异常）。
- E2E（Chromium）覆盖前端主链路。
- 本地 PG/Milvus 真实环境验证（参照 7.4/7.5/7.6 验收证据格式）。

**依赖**：P0–P8 全部完成。

---

## 3. 跨阶段关注点

### 3.1 安全、确认与审计（设计 §8.1，贯穿）

- 所有写操作（草稿 CRUD / 物化 / 激活 / 停用 / 恢复 / 归档 / 删草稿）走 `_resolve_dev_principal` 权限门禁 + 幂等键 + 二次确认。
- 审计记录统一字段：actor / 时间 / before / after / 原因 / idempotency_key / 关联版本。
- `[待确认 D6]` 审计持久化：复用 `security/audit`（含 PG store）还是新建 `skill_audit` 表。建议**复用 `security/audit`**，按 `event_type` 区分。

### 3.2 一致性与恢复（设计 §8.3）

- 草稿乐观锁（revision）→ 冲突 409，不覆盖。
- 物化临时包 + 原子替换 + 失败回滚。
- 写接口幂等键（移植 `_idempotent_release_mutation`）。

### 3.3 脱敏（设计 §8.4）

- 样例取数、执行测试中的患者标识与返回数据走 `security/desensitization`。

### 3.4 路由前缀

- 草稿接口沿用 `/api/v1/medical-insurance-ai-agent/infra-skills/*`。
- 语义预览接口按设计 §7.3 用 `/semantic/skill-inputs/*`，挂在现有语义层路由组（`infra_skill_routes.py` 同级或 `policy_workbench_routes` 风格）。

---

## 4. 待确认技术决策点

执行前需拍板（本计划已给出推荐方案，标注 `[建议]`）：

| 编号 | 决策点 | 推荐 | 影响 |
|------|--------|------|------|
| D1 | SkillDraft.structured_config 存储粒度 | `[建议]` 单列 JSON blob | P0 表结构 |
| D2 | SkillDefinition 是否独立持久化 | `[建议]` 独立 `skill_definition` 表 | P0/P6 |
| D3 | 受控导入根目录路径 | 需与部署对齐 | P3 config |
| D4 | 语义依赖变化标记触发机制 | `[建议]` 语义层 publish 回调扫描引用 | P4 跨模块 |
| D5 | 结构化编辑 ↔ 源码编辑双向同步 | `[建议]` 结构化为主 + 源码只读/高级覆盖 | P8 |
| D6 | 审计持久化位置 | `[建议]` 复用 `security/audit` | §3.1 |

---

## 5. 验收标准映射（设计 §9.4）

| 验收标准 | 覆盖阶段 |
|---------|---------|
| `/skills` 能找到新建/导入/复制/编辑/校验/发布/停用/归档入口 | P7、P8 |
| 编辑器可配置完整输入指标契约 | P4、P8 |
| Skill 不需关心指标背后的数据库或政策知识查询方式 | P4 |
| 语义层提供统一输入、来源引用和不确定性 | P4 |
| 正式变更都有不可变版本和审计记录 | P5、§3.1 |
| 当前 Test Active 不会被草稿编辑直接破坏 | P0、P5、P6 |
| 页面层级与语义层、政策知识页一致 | P7 |

---

## 6. 与 PROGRESS.md 的衔接

完成后在 `PROGRESS.md` §1 技能管理领域新增：

- **§7.7 Skill 管理工作台**：草稿管理（创建/导入/复制/编辑/校验/物化）+ 输入指标契约 + 生命周期（停用/恢复/归档）+ 扁平页签骨架。
- 状态流转：P0–P6 `impl_done` → P7–P8 `impl_done` → P9 三层验证全绿后 `verified`。

---

## 7. 非目标（设计 §10，本期不实现）

- 生产发布（仅 Test 激活）。
- Skill 覆盖语义对象查询方式。
- 任意服务器路径访问（仅受控根目录）。
- 在线脚本执行环境。
- 删除已有版本/评测/发布审计记录。
