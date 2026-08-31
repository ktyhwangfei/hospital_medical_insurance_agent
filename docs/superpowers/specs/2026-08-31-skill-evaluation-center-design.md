# 通用 Skill 测评中心设计

> 日期：2026-08-31  
> 状态：待评审（产品方向已确认）  
> 适用范围：`/skills/evaluations`、Skill 治理领域、评测资产与运行记录  
> 关联设计：`2026-08-11-skill-governance-daily-workbench-design.md`、`2026-08-14-skill-capability-overview-design.md`、`2026-08-26-mzsettlement-verify-skill-design.md`

## 1. 决策摘要

本设计将“全人群自测”从 `mzsettlement_verify_skill` 的专属功能提升为平台级 **Skill 测评中心**能力，并支持所有 Skill。

核心决策如下：

1. 复用现有 `SkillEvalCase`、`SkillRegressionCase`、`SkillEvalRun`、错误案例池和发布门禁，不建设第二套自测系统。
2. 新增“测评集”作为用例组织和运行入口；路由用例与业务回归用例仍按现有类型分别执行、分别统计。
3. 每个 Skill 通过版本化的 `evaluation_contract` 声明可测类型、输入、覆盖维度、数据生成方式和执行器；测评中心不硬编码结算字段。
4. 测评集 ID、用例 ID、运行 ID 均由服务端生成。结算交易号、政策 ID、问答记录 ID 等业务标识只作为数据定位信息，不作为测评资产主键。
5. 用例的日常维护落在 PostgreSQL；Skill 包内 YAML 只作为初始化种子，不再作为生产运行时的可写主存储。
6. “全人群覆盖”按语义层已发布值域计算，展示分母、版本和统计时间；不把当前样例误称为现实世界绝对全量。
7. 路由、业务行为、计算、政策内容、引用、答案质量和安全分别给出指标，不合并成一个缺乏含义的总分。

[来源：`src/domain/skill/governance_models.py` 已有路由用例、运行快照和发布门禁模型；`src/domain/skill/regression_models.py` 已有五类严格回归断言。]

## 2. 背景与现状问题

### 2.1 已有能力

当前仓库已经具备：

- 全局路由用例的增删改查、去重、黄金案例导入；
- 路由候选版与基线版的 Top-1 对比；
- `calculation`、`policy_content`、`citation`、`answer_quality`、`safety` 五类严格回归用例；
- 问答反馈进入案例池，经分型和人工确认后转为评测资产；
- 运行时冻结用例快照、候选版本、基线版本和评测结果；
- 评测结果作为 Skill 测试环境发布门禁。

[来源：`src/runtime/api/infra_skill_routes.py`、`src/runtime/skill_management/governance_service.py`、`src/domain/skill/regression_models.py`。]

### 2.2 当前缺口

现有实现仍存在四个结构性缺口：

1. `skill_eval_suite_state` 只有一个全局版本号，没有可命名、可维护、可按 Skill 分组的测评集。
2. 评测中心页面主要面向路由问题模板，不能统一维护业务行为和五类回归用例。
3. 门诊结算 28 个固定样例保存在 Skill 目录 YAML 中，由专属 API 和专属前端组件维护，无法复用于其他 Skill。
4. 页面将已识别样例称为“全人群”，但没有语义值域分母、缺口状态和统计版本，覆盖结论不可审计。

[来源：`skills/mzsettlement_verify_skill/self_tests.py`、`self_test_cases.yaml`、`outpatient-self-test-panel.tsx`。]

## 3. 目标与非目标

### 3.1 目标

- 所有 Skill 都能从能力卡片进入同一个测评中心。
- 用户可以新建测评集、生成用例、手工维护用例、运行全部或选中用例、查看历史差异。
- 平台提供统一的 ID、权限、审计、版本、并发控制、存储和运行快照。
- Skill 自己声明业务输入、覆盖维度和判断逻辑，平台不理解“个人自付一”等具体业务字段。
- 支持从业务数据、语义值域、问答历史和人工录入四种来源创建用例。
- 已有路由评测、错误案例池、回归用例和发布门禁保持兼容。
- 能够将门诊结算当前 28 个固定样例迁移为正式测评资产，并保留来源和断言。

### 3.2 非目标

- 不建设任意代码执行平台；只允许注册表中已审核的执行器。
- 不穷举人群、险种、就医类别和支付渠道的笛卡尔积。
- 不因生成了用例就自动发布 Skill 或自动批准政策、语义指标。
- 不把真实结算数据复制成新的业务主数据；测评资产只保存必要的脱敏快照或安全定位信息。
- 不在本次设计中替换现有模型网关、语义发现、问答反馈和发布流程。

## 4. 产品信息架构

### 4.1 入口

`/skills` 中每个 Skill 卡片统一显示“测评”操作：

```text
/skills
  └─ Skill 卡片：测评
       └─ /skills/evaluations?skill=<skill_id>
```

进入后默认选中来源 Skill，不再仅为 `mzsettlement_verify_skill` 显示“全人群自测”。

### 4.2 测评中心页面

`/skills/evaluations` 保留为唯一页面，分为四个主视图：

| 视图 | 主要内容 | 用户任务 |
|---|---|---|
| 测评集 | Skill、名称、类型、状态、用例数、最近运行 | 新建、复制、停用、删除、选择测评集 |
| 用例 | 类型、业务维度、数据来源、断言、启用状态 | 生成、编辑、复制、停用、删除、批量选择 |
| 覆盖分析 | 已发布值域、已覆盖值、缺口、不可用原因 | 查缺口、跳转语义发现、生成补齐用例 |
| 运行记录 | 状态、候选版本、基线、分型指标、差异 | 运行全部/选中、查看失败、比较历史 |

现有“错误案例池”和“案例挖掘”作为测评资产来源保留，不另建同义页面。

### 4.3 页面按钮

测评集级操作：

- 新建测评集
- 复制测评集
- 停用测评集
- 删除空测评集
- 运行全部
- 运行选中
- 查看历史差异

用例生成操作：

- 从业务数据生成
- 批量生成覆盖用例
- 从问答历史加入
- 手工新增

用例维护操作：

- 编辑
- 复制
- 启用/停用
- 删除

“从业务数据生成”和“批量生成覆盖用例”必须先展示候选预览与去重结果，用户确认后才生成正式用例 ID。

## 5. 领域模型

### 5.1 测评集 `SkillEvalSuite`

新增平台领域对象：

| 字段 | 类型 | 说明 |
|---|---|---|
| `suite_id` | `str` | 平台生成主键，格式 `EVS_<uuid4.hex>` |
| `name` | `str` | 业务可读名称 |
| `scope` | `platform \| skill` | 平台路由集或单 Skill 测评集 |
| `skill_id` | `str \| None` | `scope=skill` 时必填 |
| `purpose` | `str` | 测评目的和适用边界 |
| `status` | `active \| inactive` | 停用后不可发起新运行 |
| `default_for_release_gate` | `bool` | 是否为该 Skill 的默认发布门禁集 |
| `semantic_contract_version` | `str \| None` | 计算覆盖分母时使用的语义契约版本 |
| `revision` | `int` | 乐观锁版本，从 1 开始 |
| `created_by/updated_by` | `str` | 操作人 |
| `created_at/updated_at` | `datetime` | 审计时间 |

一个用例只属于一个测评集。需要复用时执行“复制”，生成新的用例 ID。当前需求不引入多对多成员表。

### 5.2 用例

复用现有两类资产：

- `SkillEvalCase`：路由用例；
- `SkillRegressionCase`：Skill 业务回归用例。

两者新增通用字段：

| 字段 | 说明 |
|---|---|
| `suite_id` | 所属测评集 |
| `revision` | 编辑并发控制 |
| `updated_by` | 最近修改人 |
| `content_fingerprint` | 规范化输入、断言、目标 Skill 和类型的 SHA-256，用于幂等去重 |

`SkillRegressionCase` 增加 `behavior` 类型，承载“字段原值必须保留”“不得执行某个不适用公式”“必须选择某个场景”等确定性业务行为。其余五类继续使用已有严格断言。

测评中心统一展示以下类型：

| 页面分类 | 持久化类型 | 主要判断 |
|---|---|---|
| 路由 | `routing` | 是否选择期望 Skill |
| 业务行为 | `behavior` | 结构化输出、状态或路径是否满足 Skill 契约 |
| 计算 | `calculation` | 数值、容差、进位和步骤 |
| 政策证据 | `policy_content`、`citation` | 政策适用性、内容和引用支撑 |
| 答案质量 | `answer_quality` | 可答性、必含/禁含和 rubric |
| 安全 | `safety` | 脱敏、高风险动作拦截和期望状态 |

页面分类只是展示聚合，不改变已有持久化枚举和指标口径。

### 5.3 数据定位 `SkillEvalDataLocator`

业务 ID 与测评资产 ID 分离。所有需要真实业务数据的用例使用显式数据定位对象：

| 字段 | 说明 |
|---|---|
| `resource_type` | Skill 契约定义的逻辑资源，如 `settlement`、`policy`、`qa_turn` |
| `resource_id` | 结算交易号、政策 ID 或问答记录 ID |
| `snapshot_mode` | `frozen` 或 `resolve_on_run` |
| `snapshot_hash` | 保存冻结快照时的 SHA-256 |
| `as_of` | 数据统计或冻结时间 |

`resource_type` 是逻辑语义，不允许保存物理表名、SQL 或数据库字段名。数据解析必须通过语义层或 adapters 防腐层。

门诊案例中，`settlement_id` 即业务定位 ID；它不再充当 `case_id`。

### 5.4 运行 `SkillEvalRun`

扩展现有运行模型：

| 新增或明确字段 | 说明 |
|---|---|
| `run_id` | 新运行格式 `EVR_<uuid4.hex>`；历史 ID 保留 |
| `suite_id` | 本次运行使用的测评集 |
| `suite_revision` | 发起时冻结的测评集版本 |
| `selected_case_ids` | 空表示全部，否则记录选中集合 |
| `case_snapshot_hash` | 全部用例快照的聚合哈希 |
| `evaluation_contract_hash` | Skill 评测契约哈希 |
| `dimension_summaries` | 各类型独立统计结果 |

现有 `case_snapshots`、`regression_results`、候选版本、基线版本和配置哈希继续保留。运行一旦创建不可修改，只能取消或重新运行。

### 5.5 ID 规则

| 资产 | 新 ID 格式 | 生成方式 |
|---|---|---|
| 测评集 | `EVS_<uuid4.hex>` | 服务端创建时生成 |
| 用例 | `EVC_<uuid4.hex>` | 服务端确认保存时生成 |
| 运行 | `EVR_<uuid4.hex>` | 服务端发起运行时生成 |

采用 Python 标准库 `uuid4`，不新增 ULID 依赖。ID 不编码人群、险种或 Skill 名称，避免业务属性变化导致主键失真。已有无前缀 ID 不改写，API 同时接受新旧 ID。

## 6. Skill 评测契约

### 6.1 契约归属

每个 Skill 版本可声明 `evaluation_contract`。它与现有 `execution_contract` 一样随 Skill 版本冻结，不由测评中心页面随意修改。

未声明契约的 Skill 仍可维护和运行路由用例；业务数据生成、覆盖分析和业务回归运行按钮置灰，并明确提示“该 Skill 尚未声明评测契约”。

### 6.2 最小结构

```yaml
evaluation_contract:
  version: 1
  supported_case_types:
    - behavior
    - calculation
    - policy_content
    - citation
    - answer_quality
    - safety
  data_resources:
    - resource_type: settlement
      resolver_id: semantic_settlement_v1
  coverage_dimensions:
    - dimension_code: person_type
      metric_code: outpatient_person_type
      required: true
    - dimension_code: insurance_type
      metric_code: outpatient_insurance_type
      required: true
  generators:
    - generator_id: outpatient_population_samples_v1
      source: business_data
      case_type: behavior
  evaluators:
    - evaluator_id: mzsettlement_raw_field_v1
      case_type: behavior
      version: 1
```

这是结构说明，不要求平台识别门诊字段。平台只校验：引用的资源解析器、生成器和执行器均已在批准注册表中登记，且用例输入和断言通过对应 schema。

### 6.3 执行器边界

- 路由执行器复用现有 `evaluate_route_suite`。
- Skill 业务执行器调用已物化 Skill 的公开执行入口，不直接 import 任意文件路径。
- 需要模型判断的答案质量执行器统一通过 `model_service/gateway`。
- 计算、行为和安全优先使用确定性执行器。
- 执行器返回结构必须包含 `status`、`passed`、`failure_codes`、`evaluator_version` 和可脱敏的实际值摘要。
- 找不到执行器时返回 `blocked_by_evaluator`；必测用例被阻塞时门禁失败，不得当作通过。

## 7. 用例生成

### 7.1 从业务数据生成

流程：

```text
选择 Skill 与测评集
  → 读取 evaluation_contract
  → 选择已登记 generator
  → 通过语义层/adapters 查询候选业务 ID
  → 脱敏并预览业务维度与断言候选
  → content_fingerprint 去重
  → 用户确认
  → 服务端生成 EVC_* 并保存
```

生成器只返回构建用例所需的业务数据，不向前端暴露患者姓名、证件号、手机号、物理表名或 SQL。

### 7.2 批量生成覆盖用例

覆盖分母来自 Skill 契约引用的已发布语义指标值域。例如门诊结算 Skill 可声明：

- 参保人群；
- 险种；
- 就医类别；
- 支付渠道；
- 核心结算场景。

平台逐维度计算：

```text
已发布值域值
  - 已有启用用例覆盖值
  = 待覆盖值
```

默认每个待覆盖值选择一个代表性真实案例；多维组合只在 Skill 契约明确声明为关键组合时生成，不自动做笛卡尔积。

语义指标不存在或值域未发布时：

1. 覆盖状态显示为“缺少语义指标”或“值域未发布”，不显示虚假的 100%；
2. 提供“去语义发现补齐”入口；
3. 将 Skill 契约中的指标需求批量送入语义发现模块生成候选；
4. 经现有语义审核和批量发布后，用户返回测评中心重新生成用例。

测评中心不得绕过语义治理直接发布指标。

### 7.3 从问答历史加入

复用现有错误案例池：

- 用户反馈进入 `SkillEvalCasePoolItem`；
- AI 只生成分型和断言 proposal；
- 人工确认后创建正式 `EVC_*` 资产并关联测评集；
- 原问答记录只保存安全引用和脱敏摘录。

### 7.4 手工新增

用户先选择用例类型。表单由 `evaluation_contract` 的输入 schema 和断言 schema 驱动；服务端再次校验，禁止前端自由提交未声明字段。

## 8. 覆盖语义与展示口径

“全人群覆盖”定义为：**在指定语义契约版本和统计时间下，已发布人群值域中存在启用且可执行用例的比例**。

页面必须展示：

- `已覆盖值数量 / 已发布值域数量`；
- 语义契约版本；
- 值域统计时间；
- 未覆盖值；
- 无可用业务样例的值；
- 执行器缺失或数据源不可用的值。

覆盖状态：

| 状态 | 含义 |
|---|---|
| `covered` | 已有至少一个启用且可执行用例 |
| `partial` | 有用例，但缺关键组合或执行器阻塞 |
| `missing` | 值域已知但无用例 |
| `unavailable` | 值域、数据源或执行器不可用 |

页面推荐文案为“已识别人群覆盖 28/28（语义值域 vX，截至 YYYY-MM-DD）”，不再只显示“全人群 28 个”。

## 9. 执行与指标

### 9.1 运行流程

```text
校验测评集状态和 Skill 版本
  → 冻结 suite revision、用例、评测契约和数据快照
  → 按 case_type 分组
  → 调用已登记执行器
  → 生成逐用例结果
  → 分维度汇总
  → 保存不可变运行记录
  → 计算发布门禁
```

同一次运行中某类执行器失败，不抹掉其他类型已完成结果；运行状态为 `error`，并保留已完成分组和故障原因。

### 9.2 指标隔离

| 类型 | 指标 |
|---|---|
| 路由 | Top-1 accuracy、基线 Top-1、误接管数、路由变化数 |
| 业务行为 | 通过率、必测通过率、失败代码分布 |
| 计算 | 通过率、超容差数、步骤缺失数 |
| 政策内容 | 适用性错误数、必含/禁含失败数 |
| 引用 | 必需来源命中率、无支撑引用数 |
| 答案质量 | rubric 通过率、不可答误答数 |
| 安全 | 脱敏失败数、高风险动作漏拦截数 |

不计算跨类型平均总分。发布门禁以各类型的独立阈值共同判断；任一必需安全用例失败时直接不通过。

### 9.3 运行差异

用户选择两个运行后，按 `content_fingerprint` 对齐用例，显示：

- 新通过；
- 新失败；
- 持续失败；
- 新增/删除用例；
- 实际输出变化；
- 执行器版本变化。

历史用例被编辑后产生新 revision，但旧运行继续显示当时冻结快照。

## 10. 持久化设计

### 10.1 新表

新增 `skill_eval_suites`：

```sql
CREATE TABLE IF NOT EXISTS skill_eval_suites (
    suite_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    scope VARCHAR(16) NOT NULL,
    skill_id VARCHAR(128),
    purpose TEXT NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    default_for_release_gate BOOLEAN NOT NULL DEFAULT FALSE,
    semantic_contract_version VARCHAR(64),
    revision INTEGER NOT NULL DEFAULT 1,
    created_by VARCHAR(128) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (
        (scope = 'platform' AND skill_id IS NULL)
        OR (scope = 'skill' AND skill_id IS NOT NULL)
    )
);
```

同一 Skill 最多一个启用的默认发布门禁集，由 PostgreSQL 条件唯一索引约束。

### 10.2 现有表扩展

- `skill_eval_cases`：增加 `suite_id`、`revision`、`updated_by`、`content_fingerprint`。
- `skill_regression_cases`：增加相同通用字段，并允许 `behavior` 类型。
- `skill_eval_runs`：增加 `suite_id`、`suite_revision`、`selected_case_ids`、`case_snapshot_hash`、`evaluation_contract_hash`、`dimension_summaries`。

每个新增列必须同时出现在 `CREATE TABLE` 和 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 中，兼容已有数据库。

[来源：根 `AGENTS.md` 已知陷阱要求模型新增字段时同步维护 CREATE 与 ALTER。]

### 10.3 并发与删除

- 更新测评集或用例必须提交 `expected_revision`；不一致返回 409。
- 有运行快照引用的用例不做物理删除，只停用。
- 无任何运行引用的用例允许物理删除。
- 测评集包含用例或运行历史时不允许删除，只允许停用。
- 批量生成按 `content_fingerprint` 幂等；重复项返回 `reused`，不生成新 ID。

## 11. API 设计

统一前缀仍为 `/api/v1/medical-insurance-ai-agent`。

### 11.1 测评集

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/infra-skills/eval-suites` | 按 Skill、状态分页查询 |
| POST | `/infra-skills/eval-suites` | 新建测评集，服务端生成 `EVS_*` |
| GET | `/infra-skills/eval-suites/{suite_id}` | 测评集详情 |
| PUT | `/infra-skills/eval-suites/{suite_id}` | 依据 `expected_revision` 更新 |
| DELETE | `/infra-skills/eval-suites/{suite_id}` | 仅删除空且无历史的测评集 |

### 11.2 用例与生成

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/infra-skills/eval-suites/{suite_id}/cases` | 分类型查询用例 |
| POST | `/infra-skills/eval-suites/{suite_id}/cases` | 手工创建单个用例 |
| POST | `/infra-skills/eval-suites/{suite_id}/case-proposals` | 按 `business_data`、`coverage`、`qa_history` 生成预览 |
| POST | `/infra-skills/eval-suites/{suite_id}/cases/batch` | 确认候选并批量创建/复用 |
| PUT | `/infra-skills/eval-cases/{case_id}` | 更新路由或回归用例 |
| DELETE | `/infra-skills/eval-cases/{case_id}` | 删除未被运行引用的用例 |
| GET | `/infra-skills/eval-suites/{suite_id}/coverage` | 返回覆盖分母、分子和缺口 |

### 11.3 运行

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/infra-skills/eval-suites/{suite_id}/runs` | 运行全部或 `selected_case_ids` |
| GET | `/infra-skills/eval-suites/{suite_id}/runs` | 运行历史 |
| GET | `/infra-skills/eval-runs/{run_id}` | 运行详情 |
| GET | `/infra-skills/eval-runs/compare` | 比较两个运行 |

所有请求和响应使用显式 Pydantic DTO。错误结构继续使用 `{error_code, message, audit_event}`。

### 11.4 兼容策略

现有接口暂时保留：

- `/infra-skills/eval-cases*` 映射到平台默认路由测评集；
- `/infra-skills/{skill_id}/eval-runs*` 映射到该 Skill 的默认发布门禁集；
- `/infra-skills/mzsettlement_verify_skill/self-tests*` 在迁移期间只读代理到新测评集，前端切换完成后删除。

兼容层不再写 YAML，避免新旧主存储双写。

## 12. 权限、安全与审计

### 12.1 权限

| 操作 | 权限 |
|---|---|
| 查看测评集、用例、覆盖和运行 | Skill 治理只读权限 |
| 创建/编辑/停用用例、生成候选、发起运行 | `skill:evaluate` |
| 变更默认发布门禁集 | Skill 发布治理权限 |
| 发布语义指标 | 现有语义审核/发布权限 |

### 12.2 安全要求

- 用例创建和生成都执行敏感信息检测。
- 前端不展示患者姓名、身份证、手机号、住址等信息。
- 业务数据查询必须经过语义层或 adapters，禁止测评契约携带 SQL。
- 模型评测只通过统一模型网关，不允许执行器直接调用外部模型 HTTP 接口。
- 运行快照保存前再次脱敏。
- 测评结果必须保留来源、执行器版本和不确定性；证据不足不能伪装为通过。

### 12.3 审计事件

至少记录：

- 测评集创建、更新、停用和删除；
- 用例来源、生成参数摘要、人工确认、编辑和停用；
- 语义指标缺口跳转和候选创建；
- 运行发起、取消、完成和错误；
- 默认发布门禁集变更。

## 13. 门诊结算样例迁移

创建 Skill 测评集：

```text
名称：门诊结算人群覆盖回归
scope：skill
skill_id：mzsettlement_verify_skill
purpose：验证不同已识别人群、险种、就医类别和支付渠道下，结算单原始字段与解释行为保持正确
```

当前 28 个 YAML 样例迁移规则：

| 当前字段 | 新资产字段 |
|---|---|
| `case_id: person-xx` | 记录为 `source_ref`，正式主键生成 `EVC_*` |
| `settlement_id` | `data_locator.resource_type=settlement`、`resource_id=<交易号>` |
| `context` | 冻结的脱敏输入快照 |
| `expected_self_pay_one` | `behavior` 断言的期望原始字段值 |
| `note` | 用例说明 |
| `enabled` | 用例启用状态 |

门诊执行器 `mzsettlement_raw_field_v1` 至少校验：

1. 对外解释中的“个人自付一”取真实结算单字段；
2. 不执行已确认不适用于全人群的通用反推公式；
3. 不在面向用户的答案中展示无必要的中间计算范围；
4. 失败时返回稳定的 failure code，便于回归比较。

迁移完成后：

- 删除评测中心页面对 `mzsettlement_verify_skill` 的条件渲染；
- 所有 Skill 卡片统一显示“测评”；
- `outpatient-self-test-panel.tsx` 的业务字段表单由 Skill 评测契约驱动的通用用例表单取代；
- `self_test_cases.yaml` 保留为一次性导入种子或迁移归档，不再运行时写入。

## 14. 错误处理

| 场景 | HTTP/状态 | 用户提示 |
|---|---|---|
| 测评集或用例不存在 | 404 | 资产不存在或已删除 |
| `expected_revision` 冲突 | 409 | 数据已被他人修改，请刷新后重试 |
| 用例 schema 与 Skill 契约不匹配 | 422 | 指出不匹配字段和契约版本 |
| 业务数据源暂不可用 | 503 | 保留生成条件，可稍后重试 |
| 缺少语义指标/值域 | 200 + `unavailable` | 展示缺口并提供语义发现入口 |
| 执行器未登记 | `blocked_by_evaluator` | 用例不执行；必测门禁失败 |
| 批量创建部分重复 | 200 | 分别返回 `created`、`reused`、`rejected` |
| 运行期间单类执行器异常 | 运行 `error` | 保留已完成结果和故障原因 |

数据缺失、证据不足和执行器缺失不做无界自动重试。

## 15. 分阶段落地边界

### 阶段 A：统一资产入口

- 新增测评集与 ID；
- 现有路由/回归用例关联测评集；
- 所有 Skill 卡片进入通用测评中心；
- 迁移 28 个门诊样例；
- 移除运行时 YAML 写入。

### 阶段 B：通用生成与覆盖

- 落地 `evaluation_contract`；
- 从业务数据生成和候选预览；
- 接入语义值域覆盖分析；
- 缺指标批量送语义发现。

### 阶段 C：完整运行与门禁

- 分类型执行器和指标；
- 选中运行、运行比较；
- 默认发布门禁集；
- 兼容接口退役。

每个阶段都必须保持现有路由发布门禁可用，不要求一次性迁移所有 Skill 的高级执行器。

## 16. 验收标准

### 16.1 通用性

- 任意已物化 Skill 卡片都有“测评”入口。
- 未声明 `evaluation_contract` 的 Skill 可维护路由用例，并能看到高级功能不可用原因。
- 测评中心代码中不存在 `mzsettlement_verify_skill` 条件分支或门诊金额字段常量。

### 16.2 资产维护

- 用户可创建测评集并获得服务端生成的 `EVS_*`。
- 用户可通过四种来源生成/创建用例，并获得 `EVC_*`。
- 用例可编辑、复制、停用和按规则删除。
- 并发编辑返回 409，不覆盖他人修改。
- 重复候选按 fingerprint 复用。

### 16.3 覆盖

- 页面显示每个契约维度的分子、分母、版本、时间和缺口。
- 缺语义指标时不显示 100%，并可跳转语义发现生成候选。
- 不生成未声明的多维笛卡尔积。

### 16.4 运行与回归

- 可运行全部或选中用例并获得 `EVR_*`。
- 运行冻结 Skill 版本、测评集 revision、用例、数据和执行器版本。
- 路由与回归指标分开显示。
- 任一必需安全用例失败或必测用例被执行器阻塞时，发布门禁失败。
- 历史运行不因后续编辑而变化。

### 16.5 门诊迁移

- 28 个现有样例均迁入“门诊结算人群覆盖回归”。
- `011100030X260417004975` 等案例继续验证“个人自付一取原始结算字段，不使用不适用的通用反推公式”。
- 页面显示语义值域口径下的人群、险种、就医类别和支付渠道覆盖，而不是无分母的“全人群”。

### 16.6 验证顺序

实施完成后严格按仓库要求执行：

1. 单元测试：ID、fingerprint、契约校验、覆盖计算、分型聚合和并发规则；
2. API 测试：测评集、用例、候选、覆盖、运行、权限和兼容接口；
3. Flow 测试：从 Skill 卡片进入、生成门诊覆盖用例、运行、查看失败与历史差异；
4. Portal 构建和 LSP 诊断。

## 17. 关键取舍

| 取舍 | 结论 | 原因 |
|---|---|---|
| 新建独立“全人群测试系统” | 否 | 会重复现有评测、回归、案例池和发布门禁 |
| 将所有用例塞入一个自由 JSON 模型 | 否 | 无法在保存前验证断言，也不利于安全审计 |
| 路由与回归合并为一个分数 | 否 | 不同失败含义不可比较 |
| 用业务 ID 作为 case ID | 否 | 业务属性会变且可能泄露含义 |
| 引入 ULID 依赖 | 否 | 标准库 UUID 已满足唯一和不可猜测需求 |
| 用例多对多复用 | 暂不支持 | 当前复制即可满足需求，避免额外成员关系和版本语义 |
| 自动穷举覆盖组合 | 否 | 会产生大量无意义和无真实数据支撑的用例 |
| 自动发布缺失语义指标 | 否 | 必须经过现有语义审核和发布流程 |

## 18. 最终用户体验

用户不再寻找某个 Skill 的专属“自测页面”。标准路径统一为：

```text
Skill 能力概览
  → 选择一个 Skill 的“测评”
  → 选择或新建测评集
  → 从业务数据/覆盖缺口/问答历史/手工生成用例
  → 确认候选，平台生成稳定 ID
  → 维护、启停并运行用例
  → 查看分类型结果、覆盖缺口和历史差异
  → 通过门禁后进入原有发布流程
```

门诊结算“全人群自测”是该通用流程的第一个落地实例，不再是平台中的特例。
