# Skill 全生命周期治理工作台详细设计

> 状态：待评审
>
> 日期：2026-08-05
>
> 设计范围：Portal `/skills`、Skill 控制面 API、版本/发布/评测存储与运行治理
>
> 前置基线：`2026-08-04-skill-management-workbench-design.md` 已实现的总览、详情、路由测试与执行测试

## 1. 背景与问题

当前 Skill 管理页面已经能够：

- 展示文件系统中已加载的 Skill、业务动作、业务对象、关键词和指标数量；
- 查看 Manifest、字段映射、查询计划、目录结构和 `SKILL.md`；
- 对单条自然语言问题执行路由测试；
- 使用脱敏测试上下文调用 Skill assembler 并查看结果、来源和不确定性。

它目前仍然是“Skill 资产查看器和调试器”，尚未形成生产治理闭环：

1. 没有可审计的版本、候选版、活动版和退役版；
2. 单句路由测试不能证明新版本没有产生批量误路由；
3. 缺少发布门禁、人工审批、灰度、回滚和环境隔离；
4. 缺少真实运行数据，无法回答 Skill 是否稳定、是否被错误分发；
5. Git 文件、运行时加载状态和 PostgreSQL 注册信息之间缺少明确的单一事实来源规则。

[来源: `docs/steering/数据库设计文档.md` §2.3] `skills/` 是 YAML/Markdown 声明式配置的版本控制源，PostgreSQL `skills` 表是运行时存储。

[来源: `docs/governance/TEST-VERIFICATION-MATRIX.md` §4] `src/domain/` 与 `src/data_platform/storage/` 属于 R4 变更，实施必须经过人工设计并完成对应测试。

[参考: Agent Skills 规范](https://github.com/agentskills/agentskills) Skill 以包含 `SKILL.md` 的目录作为可移植、可版本控制的能力包。

[参考: Dify Plugin Daemon](https://github.com/langgenius/dify-plugin-daemon) 插件生命周期与本地、调试、Serverless 运行环境分离。
[参考: n8n Nodes Starter](https://github.com/n8n-io/n8n-nodes-starter) 插件包将脚手架、lint、测试、凭据契约和发布工具作为完整研发链路管理。

## 2. 设计目标

本设计把 `/skills` 升级为院端 Skill 控制面，覆盖四类闭环：

1. **资产闭环**：知道有哪些 Skill、谁负责、当前版本、健康与风险状态；
2. **研发闭环**：知道一个版本由哪个 Git 提交产生、依赖是否完整、校验是否通过；
3. **发布闭环**：候选版必须经过回归评测与人工审批，支持灰度、切换和回滚；
4. **运营闭环**：持续观察调用量、成功率、延迟、误路由、人工改派和依赖故障。

成功标准：

- 任一生产调用都能追溯到 `skill_id + version + artifact_hash + release_id`；
- 未通过最新评测门禁的候选版不能发布；
- 生产发布和回滚必须经过权限校验、风险控制与审计留痕；
- 路由变更能用固定测试集与当前活动版对比，而非仅凭单句测试判断；
- 页面默认面向业务管理员，高级技术信息按需展开；
- 所有 AI/Skill 结果继续携带 `citations` 或 `uncertainties`，测试输入与运行数据必须脱敏。

## 3. 非目标

第一阶段不做以下能力：

- 不建设公共或第三方 Skill Marketplace；
- 不允许在 Portal 中直接编辑或上传生产 Skill 源文件；
- 不自动生成并直接发布 Skill；
- 不重写 `SkillLoader`、`SkillRouter` 或现有业务 Skill 算法；
- 不替代 Git 评审、CI、院内正式变更审批和既有业务系统；
- 不保存完整患者问题、患者上下文或原始业务数据用于运营统计。

## 4. 用户与权限

| 角色 | 主要任务 | 默认权限 |
|---|---|---|
| 业务管理员 | 查找 Skill、查看用途、健康和运行效果 | 只读资产、评测和运行数据 |
| Skill 开发者 | 查看包内容、创建候选版、运行校验和评测 | 开发/测试环境操作；不可直接生产发布 |
| 测试/质控人员 | 管理评测集、执行回归、审核差异 | 评测集与评测运行；不可修改制品 |
| 信息科管理员 | 配置环境、审批发布、灰度和回滚 | 发布控制；生产动作需二次确认 |
| 审计人员 | 查看版本、审批、发布和运行证据 | 全量只读，不可触发执行 |

权限通过 `security/authorization/` 校验；发布、扩大灰度和回滚通过 `security/risk_control/` 形成 `waiting_human_confirmation`，由有权人员确认。任何角色都不能从该页面触发退费、冲正、正式结算或病案修改。

## 5. 方案比较与决策

### 5.1 方案 A：继续扩充文件系统查看器

直接在现有 API 上追加版本、状态和测试字段，仍以扫描本地目录为全部状态来源。

- 优点：代码少、交付快；
- 缺点：无法处理多实例一致性、历史版本、发布审批和回滚；文件状态与生产状态混在一起。

### 5.2 方案 B：Git 不可变制品 + PostgreSQL 控制面（采用）

Git 提交中的 Skill 目录作为不可变制品；PostgreSQL 保存制品索引、评测、发布和运行状态。运行时只解析某环境当前活动发布所指向的制品。

- 优点：符合现有数据库设计，版本可追溯，可做发布门禁、灰度和回滚；
- 缺点：需要新增领域模型、存储端口和数据库迁移，属于 R4 变更。

### 5.3 方案 C：独立 Skill Registry / Marketplace 服务

建立远程包仓库、签名分发、租户安装和跨项目共享。

- 优点：扩展性最强；
- 缺点：明显超出当前单院项目需要，引入供应链、租户和制品分发复杂度。

**决策**：采用方案 B。方案 C 仅保留未来扩展点，不进入本次数据模型和 API。

## 6. 核心设计原则

### 6.1 单一事实来源

- **源代码事实**：Git 中的 `skills/<skill_id>/`；
- **制品事实**：`skill_versions` 中的 `source_commit + artifact_hash`；
- **环境生效事实**：`skill_releases` 中每个环境唯一的 `active` 发布；
- **运行事实**：事件日志与聚合指标；
- **展示事实**：Portal 只通过控制面 API 获取，不直接推断文件状态。

现有 `/infra-skills/refresh` 仅保留为开发环境热重载能力，生产环境不可用。

### 6.2 制品不可变

版本创建完成后，Manifest 快照、文件清单、依赖快照、Git 提交和 SHA-256 制品哈希不可修改。内容变化必须产生新版本。

### 6.3 发布与启用分离

`enabled` 表示该 Skill 是否允许被运行时考虑；`active release` 表示某环境实际使用的版本。禁用不会删除历史版本，回滚也不会修改旧制品。

### 6.4 门禁优先

生产发布必须满足：制品校验通过、依赖健康、最新回归评测通过、评测集版本未变化、基线版本未变化、审批完整。任一条件变化都使原审批失效。

## 7. 总体架构

```text
Git skills/ 目录
    │ CI/手动同步：计算 artifact_hash、读取 Manifest、执行 lint
    ▼
Skill Catalog Service ───────────────┐
    │                                │
    ├─ Version Service               ├─ PostgreSQL
    ├─ Evaluation Service            │   skills
    ├─ Release Service               │   skill_versions
    └─ Runtime Analytics Service     │   skill_eval_cases/runs/results
                                     │   skill_releases/approvals
                                     └─ event_log / audit_logs
    │
    ├─ security/authorization
    ├─ security/risk_control
    ├─ security/desensitization
    └─ runtime skill resolver → SkillLoader / SkillRouter / assembler

Portal /skills
    ├─ 资产库
    ├─ 研发与发布
    ├─ 路由评测
    └─ 运行治理
```

### 7.1 模块边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| `src/domain/skill/` | 版本、发布、评测状态与领域规则 | 文件读取、SQL、HTTP |
| `src/data_platform/storage/skill/` | 版本、发布、评测持久化端口及适配器 | 发布规则判断 |
| `src/skill_infra/` | 包扫描、校验、哈希、路由和加载 | 权限、审批、页面 DTO |
| `src/runtime/skill_management/` | 控制面应用服务与事务编排 | 直接访问前端或外部系统 |
| `src/runtime/api/infra_skill_routes.py` | HTTP 契约、输入校验、响应转换 | 领域逻辑和裸 SQL |
| `src/observability/` | 运行事件采集与聚合查询 | 保存患者原始内容 |
| Portal | 交互、可视化和局部状态 | 推导服务端发布门禁 |

## 8. 页面信息架构

`/skills` 保持一个入口，一级切换为四个视图。页面记住用户最后使用的视图和筛选条件，但不在 URL 中保存患者或测试输入。

### 8.1 资产库

默认视图用于回答“有哪些 Skill、当前是否健康”。

顶部指标：

- Skill 总数；
- 生产活动版本数；
- 待发布候选数；
- 异常/依赖降级数；
- 最近 24 小时调用与失败数。

列表字段：

| 字段 | 含义 |
|---|---|
| 名称 / ID | Skill 业务名与稳定标识 |
| 动作 / 对象 | `BusinessAction + BusinessObject` |
| 生产版本 | 当前 active 语义版本 |
| 生命周期状态 | 聚合展示状态：draft / validated / candidate / active / suspended / retired / rejected |
| 健康状态 | healthy / degraded / unhealthy / unknown |
| 风险等级 | LOW / MEDIUM / HIGH |
| 负责人 | owner |
| 24h 运行 | 调用量、成功率、P95 延迟 |
| 最近变更 | 提交摘要与发布时间 |

筛选支持：动作、对象、生命周期、健康、风险、负责人、环境。搜索覆盖名称、ID、标签和说明。

### 8.2 Skill 详情工作区

点击 Skill 后进入同页详情工作区，分为六个页签：

1. **概览**：用途、负责人、风险、当前环境版本、依赖健康、最近告警；
2. **版本**：版本时间线、Git 提交、制品哈希、差异摘要、校验结果；
3. **研发**：现有费用项解析、查询计划、Manifest、字段映射、目录和 `SKILL.md`；
4. **评测**：测试集、运行历史、候选版与活动版差异；
5. **发布**：环境、门禁、审批、灰度、切换、回滚；
6. **运行**：调用趋势、成功率、延迟、路由方式、人工改派和错误分布。

业务用户默认只看到“概览、评测、运行”；开发者和信息科管理员按权限看到全部页签。

### 8.3 研发与发布

版本详情页采用“证据包”布局：

- 来源：Git 提交、分支、作者、构建时间、artifact hash；
- 校验：Manifest、目录契约、字段映射、MCP/指标依赖、权限声明、安全扫描；
- 变更：与当前活动版的文件/Manifest/关键词/依赖差异；
- 门禁：每项通过、失败、过期或待审批状态；
- 动作：创建候选、发起评测、申请发布、扩大灰度、回滚。

Portal 不编辑源文件。“创建候选版”只登记已经存在于当前 Git 工作区或 CI 制品中的已校验版本。

### 8.4 路由评测

保留现有单句测试，新增批量回归：

- 测试用例字段：问题、期望 Skill、期望不匹配、标签、来源、是否含敏感样本；
- 运行范围：候选版、活动版、全部已启用 Skill；
- 指标：Top-1 准确率、未匹配率、冲突率、误接管率、排除命中率、平均置信度；
- 对比：candidate vs baseline 的新增通过、新增失败和路由变化；
- 明细：匹配 Skill、候选列表、命中/排除关键词、匹配方式和置信度。

默认发布阈值：

- 必需用例通过率 100%；
- 总体 Top-1 准确率不低于活动基线；
- 新增误接管为 0；
- 高风险标签用例全部通过；
- 失败用例必须有质控人员处置结论。

阈值由服务端配置读取，前端只展示，不自行计算发布资格。

### 8.5 运行治理

展示窗口支持 24 小时、7 天和 30 天：

- 调用量、成功率、P50/P95 延迟；
- keyword / LLM / explicit mention 等路由方式占比；
- no-match、低置信度、多 Skill 冲突；
- 错误码与依赖故障分布；
- 人工改派率和改派去向；
- 当前版本与上一个版本的运行对比。

运营事件只记录哈希化问题指纹、问题类别和脱敏标签，不记录患者原始问题或完整上下文。

## 9. 生命周期状态机

```text
draft
  └─ validate success → validated
       └─ create candidate → candidate
            ├─ evaluation failed → rejected
            └─ evaluation passed + approval → approved
                 ├─ activate/gray rollout → active
                 └─ cancel → retired
active
  ├─ replaced by new active → retired
  ├─ rollback target → active
  └─ emergency disable → suspended
suspended
  ├─ approval to resume → active
  └─ retire → retired
```

规则：

- 一个 `skill_id + environment` 同时只能有一个 `active` release；
- `rejected`、`retired` 制品不可重新编辑，可基于同一 Git 提交重新创建新版本；
- 灰度期间 `active` 仍指当前基线，candidate 通过确定性分流获得流量；
- 灰度扩大和全量切换必须重新校验基线与评测快照未变化；
- `suspended` 表示紧急停止，不等同于删除或退役。

## 10. 领域模型与数据模型

### 10.1 现有 `skills` 表

继续保存 Skill 的稳定身份、负责人、角色、风险和启用状态，不保存历史版本内容。新增可选字段：

- `current_version`：便于查询的生产活动版本冗余字段；
- `health_status`：最近聚合健康状态；
- `health_checked_at`：健康状态更新时间。

活动版本的权威来源仍为 `skill_releases`，更新两者必须在同一事务内完成。

### 10.2 新增表

#### `skill_versions`

| 字段 | 类型 | 说明 |
|---|---|---|
| version_id | UUID PK | 内部版本 ID |
| skill_id | VARCHAR(128) FK | Skill ID |
| semantic_version | VARCHAR(64) | 语义版本，Skill 内唯一 |
| source_commit | VARCHAR(64) | Git commit SHA |
| source_path | TEXT | Skill 目录相对路径 |
| artifact_hash | VARCHAR(64) | 规范化目录 SHA-256 |
| manifest_snapshot | JSONB | 结构化 Manifest 快照 |
| dependency_snapshot | JSONB | MCP、指标、对象及工具依赖 |
| validation_status | VARCHAR(32) | pending/passed/failed |
| validation_report | JSONB | 结构化校验结果 |
| created_by / created_at | 字段组 | 创建审计 |

唯一约束：`(skill_id, semantic_version)`、`(skill_id, artifact_hash)`。

#### `skill_eval_cases`

| 字段 | 类型 | 说明 |
|---|---|---|
| case_id | UUID PK | 用例 ID |
| suite_version | INTEGER | 测试集版本 |
| question_template | TEXT | 脱敏问题或模板 |
| expected_skill_id | VARCHAR(128) NULL | 期望 Skill；空表示应不匹配 |
| required | BOOLEAN | 是否发布必需用例 |
| risk_tags / business_tags | JSONB | 风险与业务标签 |
| source_type / source_ref | VARCHAR/TEXT | 来源与追溯引用 |
| enabled | BOOLEAN | 是否参与新运行 |
| created_by / created_at | 字段组 | 审计 |

#### `skill_eval_runs` 与 `skill_eval_results`

`skill_eval_runs` 保存版本、基线、测试集版本、配置哈希、汇总指标和最终状态；`skill_eval_results` 每个用例一行，保存候选结果、基线结果、差异分类与结构化解释。原始患者数据禁止写入。

#### `skill_releases`

| 字段 | 类型 | 说明 |
|---|---|---|
| release_id | UUID PK | 发布 ID |
| skill_id / version_id | FK | Skill 与制品版本 |
| environment | VARCHAR(32) | dev/test/prod |
| status | VARCHAR(32) | candidate/approved/active/retired/suspended |
| baseline_release_id | UUID NULL | 创建候选时的基线 |
| eval_run_id | UUID | 发布所绑定的 passed 评测 |
| rollout_percent | INTEGER | 0/10/25/50/100 |
| rollout_key | VARCHAR(32) | tenant/user/session 哈希策略 |
| config_hash | VARCHAR(64) | 路由及门禁配置快照 |
| activated_at / retired_at | TIMESTAMP | 生命周期时间 |
| created_by / created_at | 字段组 | 审计 |

#### `skill_release_approvals`

保存审批人、角色、结论、理由、审批时的 `artifact_hash + eval_run_id + config_hash + baseline_release_id`。任一哈希或基线变化后审批自动过期。

### 10.3 运行指标

第一阶段不新增明细业务日志表。`runtime/event_log` 增加结构化 Skill 事件，由查询服务按时间窗口聚合；数据量达到阈值后再引入按小时/天聚合表。

事件最小字段：

- `request_id`、`timestamp`；
- `skill_id`、`skill_version`、`release_id`；
- `route_method`、`confidence_bucket`、`candidate_count`；
- `status`、`error_code`、`latency_ms`；
- `question_fingerprint`、`business_action`、`business_object`；
- `human_override`、`override_target_skill_id`；
- `citation_count`、`uncertainty_count`。

## 11. API 设计

统一前缀仍为 `/api/v1/medical-insurance-ai-agent`。现有端点保持兼容。

### 11.1 资产与版本

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/infra-skills` | 保持现有数组响应不变，供旧页面兼容 |
| GET | `/infra-skills/catalog` | 新资产列表；支持分页、状态、负责人、风险筛选 |
| GET | `/infra-skills/overview` | 首页聚合指标 |
| GET | `/infra-skills/{skill_id}` | 详情；保留现有字段并新增活动版本摘要 |
| GET | `/infra-skills/{skill_id}/versions` | 版本列表 |
| GET | `/infra-skills/{skill_id}/versions/{version_id}` | 版本证据包与差异摘要 |
| POST | `/infra-skills/{skill_id}/versions/sync` | 从当前 Git/CI 制品登记不可变版本 |
| POST | `/infra-skills/{skill_id}/versions/{version_id}/validate` | 执行结构化校验 |

`sync` 只接受 `source_commit`、`source_path` 和期望版本，不接受任意文件内容。服务端负责读取、规范化、哈希和校验路径必须位于 `SKILLS_DIR`。

### 11.2 评测

| 方法 | 路径 | 用途 |
|---|---|---|
| GET/POST | `/infra-skills/eval-cases` | 查询或新增评测用例 |
| PUT | `/infra-skills/eval-cases/{case_id}` | 更新用例并递增 suite version |
| GET | `/infra-skills/{skill_id}/eval-runs` | 评测历史 |
| POST | `/infra-skills/{skill_id}/eval-runs` | 创建候选版对基线评测 |
| GET | `/infra-skills/{skill_id}/eval-runs/{run_id}` | 汇总与逐案结果 |
| POST | `/infra-skills/{skill_id}/eval-runs/{run_id}/rerun` | 使用最新测试集创建新运行 |

运行创建返回 `202 Accepted + run_id`；前端轮询状态，避免长请求占用。完成状态为 `passed / failed / cancelled / error`。

### 11.3 发布

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/infra-skills/{skill_id}/releases` | 按环境查询发布历史 |
| POST | `/infra-skills/{skill_id}/releases` | 从已校验版本创建 candidate |
| POST | `/infra-skills/{skill_id}/releases/{release_id}/request-approval` | 冻结证据并申请审批 |
| POST | `/infra-skills/{skill_id}/releases/{release_id}/approve` | 人工审批 |
| POST | `/infra-skills/{skill_id}/releases/{release_id}/rollout` | 设置 10/25/50/100 灰度 |
| POST | `/infra-skills/{skill_id}/releases/{release_id}/rollback` | 回滚到历史活动版本 |
| POST | `/infra-skills/{skill_id}/releases/{release_id}/suspend` | 紧急停止 |

修改状态的请求均要求 `Idempotency-Key` 和 `expected_revision`，并返回新的 revision。并发冲突返回 `409 RELEASE_REVISION_CONFLICT`。

### 11.4 运行治理

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/infra-skills/{skill_id}/runtime/summary` | 时间窗口运行汇总 |
| GET | `/infra-skills/{skill_id}/runtime/trends` | 调用、成功率和延迟趋势 |
| GET | `/infra-skills/{skill_id}/runtime/routes` | 路由方式、冲突与改派摘要 |
| GET | `/infra-skills/{skill_id}/runtime/errors` | 错误码与依赖故障分布 |

### 11.5 DTO 约束

- 后端所有请求/响应使用 Pydantic `BaseModel`；新增契约从 `infra_skill_routes.py` 拆到 `runtime/api/skill_schemas.py`，避免继续膨胀通用 `schemas.py`；
- 前端使用显式 TypeScript 类型，字段保持 snake_case 与后端一致；
- 列表端点返回分页模型，不返回裸 `dict`；
- 发布门禁失败返回结构化 `gate_failures[]`，而不是把原因拼成一个字符串；
- 错误统一使用 `{error_code, message, audit_event}`。

## 12. 关键流程

### 12.1 创建候选并发布

```text
开发者合并 Git 变更
  → 同步版本（计算 artifact_hash）
  → Manifest/目录/依赖/安全校验
  → 创建 candidate release
  → 运行 candidate vs active 回归
  → 质控处理失败用例
  → 冻结 artifact/eval/config/baseline 证据
  → 信息科审批
  → 10% 灰度
  → 运行指标观察
  → 25% → 50% → 100%
  → 原 active 自动 retired
```

### 12.2 回滚

```text
选择历史 active release
  → 校验制品仍完整、依赖兼容
  → 展示影响与当前故障证据
  → 风险控制转 waiting_human_confirmation
  → 人工确认
  → 原子切换 active 指针
  → 清理运行时缓存
  → 写 audit_log 与 release event
```

回滚不重新构建制品；若依赖已不兼容，禁止一键回滚，必须创建兼容的新版本。

### 12.3 运行时解析

1. 请求进入统一编排；
2. Skill Router 生成候选；
3. Release Resolver 按环境取得 active 与灰度 candidate；
4. 使用稳定哈希决定本请求版本，保证同一 session 不漂移；
5. SkillLoader 按 `artifact_hash` 获取只读制品；
6. 执行后写入结构化事件；
7. 结果继续经过脱敏、来源和风险控制。

解析失败时优先回退到同 Skill 的 active 基线；基线也不可用则返回明确降级，不得静默调用其他业务含义不同的 Skill。

## 13. 校验与发布门禁

### 13.1 静态校验

- `SKILL.md` 必需元数据和说明可解析；
- `skill_manifest.yaml` 与领域动作/对象白名单一致；
- 目录不得逃逸 `SKILLS_DIR`，不得包含符号链接越界；
- assembler 入口、schema、模板和脚本引用存在；
- MCP、指标、字段、工具和角色依赖可解析；
- 高风险能力声明与 `allowed_tools`、`required_roles` 一致；
- 不允许在包内出现密钥、连接串或患者样本明文；
- `semantic_version` 与 Manifest 一致；
- 规范化制品哈希稳定可重现。

### 13.2 动态校验

- Skill 加载隔离测试；
- assembler 最小样本测试；
- 输出结构、`citations/uncertainties` 和脱敏检查；
- 超时、异常分类和依赖降级测试；
- 批量路由回归与基线对比；
- 高风险动作必须被拦截为人工确认。

## 14. 错误处理与恢复

| 场景 | 系统行为 | 前端行为 |
|---|---|---|
| Git 提交或路径不存在 | 版本同步失败，不创建半成品 | 显示 `SKILL_SOURCE_NOT_FOUND` 和可操作建议 |
| artifact hash 已存在 | 幂等返回现有版本 | 提示“版本已同步” |
| Manifest/依赖校验失败 | version 保留为 failed，不可成为 candidate | 展示逐项校验与文件位置 |
| 评测任务失败 | run 标记 error，保留已完成明细 | 可重跑，不覆盖旧运行 |
| 门禁或审批过期 | 拒绝发布 | 指明变化的证据项 |
| 发布并发冲突 | 事务回滚 | 刷新最新状态后重新确认 |
| 灰度异常 | 停止扩大；允许 suspend/rollback | 顶部持续告警 |
| 运行事件聚合不可用 | 不影响业务执行 | 运行页显示数据延迟，不伪造 0 |

页面局部请求失败不得清空其他已加载区域；重试必须保持当前 Skill、页签和筛选状态。

## 15. 安全、隐私与审计

### 15.1 权限

- 列表和详情：`skill:read`；
- 创建/校验版本：`skill:develop`；
- 管理评测集：`skill:evaluate`；
- 测试环境发布：`skill:release:test`；
- 生产审批与发布：`skill:release:prod`；
- 紧急停止与回滚：`skill:rollback:prod`。

### 15.2 审计事件

至少记录：

- `skill_version_synced`、`skill_validation_completed`；
- `skill_eval_started/completed`；
- `skill_release_requested/approved/rejected`；
- `skill_rollout_changed/activated/suspended/rolled_back`；
- 评测用例新增、修改、停用；
- 生产 Skill 执行测试。

每条事件包含操作者、角色、时间、对象 ID、前后状态、证据哈希、请求 ID 和结果，不记录密钥及患者明文。

### 15.3 供应链边界

- 只允许同步已授权 Git 仓库、允许分支和 `SKILLS_DIR` 下目录；
- 制品创建后重新计算哈希，运行前核对；
- 第三方 Skill 安装、远程下载和自动更新不在本期范围；
- 未来引入 Marketplace 时必须增加发布者身份、签名验证、许可证、来源信誉和沙箱执行。

## 16. 可观测性

控制面指标：

- `skill_version_validation_total{status}`；
- `skill_eval_run_total{status}` 与评测耗时；
- `skill_release_transition_total{from,to,environment}`；
- `skill_release_gate_failure_total{gate}`；
- `skill_rollout_percentage{skill_id,version}`。

运行面指标：

- `skill_invocation_total{skill_id,version,status}`；
- `skill_execution_latency_ms`；
- `skill_route_total{method,outcome}`；
- `skill_route_override_total{from_skill,to_skill}`；
- `skill_dependency_failure_total{dependency_type}`。

日志与指标中的 `skill_id/version/release_id/request_id` 必须能互相关联。

## 17. 前端状态与交互约束

前端按功能拆分状态：

- `catalogState`：列表、筛选、分页；
- `skillDetailState`：选中 Skill 与详情；
- `versionState`：版本、差异和校验；
- `evaluationState`：测试集、运行、对比；
- `releaseState`：环境、门禁、审批与灰度；
- `runtimeState`：时间窗口、趋势和故障；
- `mutationState`：每个写操作独立 pending/error/success。

交互规则：

- URL 保存 `skill_id`、视图、页签和非敏感筛选，支持刷新恢复；
- 写操作完成后仅刷新受影响资源；
- 发布按钮必须展示具体动作、环境、当前版、目标版和影响；
- 灰度/发布/回滚使用二次确认，生产动作不能依赖浏览器乐观更新；
- 运行指标标注数据更新时间与统计窗口；
- 色彩不是唯一状态表达，所有状态同时提供文本与图标；
- 桌面采用列表 + 详情双栏，窄屏切换为列表页和详情页。

建议组件拆分：

```text
app/skills/page.tsx
src/components/skills/
  skill-catalog.tsx
  skill-filters.tsx
  skill-overview-panel.tsx
  skill-version-timeline.tsx
  skill-validation-report.tsx
  skill-evaluation-suite.tsx
  skill-evaluation-comparison.tsx
  skill-release-panel.tsx
  skill-runtime-dashboard.tsx
  skill-technical-details.tsx
src/lib/skill-api.ts
src/lib/skill-types.ts
```

现有 `infra-skill-management.tsx` 在实施时按上述边界渐进拆分；不同时重构无关 Portal 组件。

## 18. 兼容与迁移

### 18.1 数据迁移

1. 为现有每个已加载 Skill 计算 artifact hash；
2. 从 Manifest 的版本或默认 `1.0.0` 创建首个 `skill_versions`；
3. 将当前生产加载状态登记为 prod active release；
4. 保留原 `skills` 行及现有 API；
5. 校验迁移前后 `SkillLoader` 列表、路由和执行结果一致；
6. 新 resolver 先以 shadow 模式记录选择结果，不影响真实执行；
7. shadow 一致后切换读取 active release。

迁移脚本必须幂等，可重复执行且不得覆盖已有历史版本。

### 18.2 API 兼容

- `GET /infra-skills` 继续返回现有数组；新分页接口固定为 `GET /infra-skills/catalog`，避免以响应形态变化破坏旧前端；
- 现有单句 `/route-test` 与 `/{skill_id}/test` 保留；
- `/refresh` 在 dev/test 可用，prod 返回 `403 SKILL_REFRESH_DISABLED`；
- 新字段全部先以可选方式加入，完成前后端同步后再收紧必填。

## 19. 测试与验证策略

实施风险定为 R4，因为涉及领域模型、存储、发布状态和生产运行选择。严格按单元 → API → Flow 顺序验证。

### 19.1 单元测试

- 生命周期合法/非法迁移；
- artifact hash 稳定性与路径越界；
- 校验门禁和审批过期；
- 评测指标与 candidate/baseline 差异分类；
- 灰度稳定哈希和 session 粘性；
- 活动版本唯一约束与回滚；
- 脱敏事件和禁止字段；
- 内存与 PostgreSQL 存储契约一致。

### 19.2 API 测试

- 版本同步幂等、校验失败、404/409；
- 评测任务创建、恢复、失败与重跑；
- 门禁未通过、无权限、审批过期拒绝发布；
- 正常灰度、全量、停止和回滚；
- 列表筛选、分页和 DTO 前后端字段一致；
- prod `/refresh` 被拒绝；
- 错误契约符合 `{error_code, message, audit_event}`。

### 19.3 Flow / E2E 测试

最小完整故事：

1. 管理员打开资产库并选择 Skill；
2. 开发者查看版本证据并创建 candidate；
3. 质控人员运行批量评测并查看回归差异；
4. 未通过时发布按钮不可用且原因明确；
5. 通过并审批后进入 10% 灰度；
6. 信息科管理员扩大到 100%；
7. 运行页显示新版本指标；
8. 回滚后活动版本恢复且审计事件完整。

安全 Flow：无生产权限用户发布返回 403；高风险 Skill 的发布和回滚进入人工确认；执行测试不泄露患者敏感字段。

### 19.4 非功能验证

- 资产列表 500 个 Skill 时首屏接口 P95 小于 500ms；
- 运行趋势查询 30 天窗口 P95 小于 1s；
- 发布切换为单事务，失败不产生双 active；
- 控制面不可用不影响已缓存 active release 的业务执行；
- Portal `npm run build`、可访问性检查和关键浏览器流程通过。

## 20. 分阶段交付

### 阶段 1：版本化资产库

- 新增版本领域模型、存储和迁移；
- 现有 Skill 登记为不可变版本；
- Portal 增加版本、负责人、风险、健康和证据包；
- 保持运行时选择逻辑不变。

独立验收：用户能从列表追溯当前 Skill 到 Git 提交和 artifact hash。

### 阶段 2：批量评测与发布门禁

- 新增评测集、运行和差异报告；
- 新增 candidate、审批、active、retired 状态；
- 先支持 dev/test 发布，再开放 prod 人工审批；
- Release Resolver 以 shadow 模式运行。

独立验收：候选版必须通过固定测试集并完成人工审批才能成为 test active。

### 阶段 3：灰度、回滚与运行治理

- 切换运行时读取 active release；
- 增加确定性灰度和回滚；
- 采集脱敏运行事件并展示趋势；
- 完成异常告警、应急停止与生产 E2E。

独立验收：生产版本能灰度、观测、全量和回滚，且每一步可审计。

## 21. 验收清单

- [ ] Git、版本、发布和运行四类事实来源没有冲突；
- [ ] 任一 active Skill 可追溯到不可变制品与审批证据；
- [ ] 版本内容改变必须产生新 artifact hash；
- [ ] 批量路由评测可比较 candidate 与 baseline；
- [ ] 门禁未通过、审批过期、基线变化时均禁止发布；
- [ ] 同一环境不存在两个 active release；
- [ ] 灰度分流稳定且回滚不重新构建制品；
- [ ] 无权限用户无法发布、扩大灰度、停止或回滚；
- [ ] Skill 输出保持 citations/uncertainties 约束；
- [ ] 运行事件不含患者原始问题或完整上下文；
- [ ] 前端 DTO、后端 Pydantic 和数据库列显式一致；
- [ ] 单元、API、Flow 三阶段验证全部通过。

## 22. 已确定的设计决策

本设计不存在待定占位项，关键决策如下：

1. Git Skill 目录是源代码事实，数据库不保存可编辑源码；
2. 采用不可变版本与环境发布指针，不使用覆盖式更新；
3. 第一阶段不做 Marketplace、远程安装或页面源码编辑；
4. 生产发布默认要求批量评测、人工审批和风险控制；
5. 运行指标基于脱敏事件聚合，不保存患者原始问题；
6. 现有路由/执行测试接口保持兼容，按三阶段渐进切换运行时。
