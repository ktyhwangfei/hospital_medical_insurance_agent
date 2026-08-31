# 通用 Skill 评测闭环设计 V2.0

> 日期：2026-08-31
> 状态：设计已确认，待实施计划
> 适用范围：`/skills/evaluations`、Skill 评测资产、自动评估、Benchmark、失败归因与改进闭环
> 首个完整 Benchmark：`mzsettlement_verify_skill` 门诊结算结果核验
> 关联实现计划：`docs/superpowers/plans/2026-08-31-skill-evaluation-center-phase-a.md`

## 1. 决策摘要

本设计把当前“测评集 + 路由用例 + 门诊固定自测”升级为完整的 Agent 评测闭环：

```text
版本化评估环境
  → 数据集定义端到端任务、结构化真值与 trajectory prefix 边界
  → 候选 Agent 完整运行，失败后从 prefix 接力点诊断
  → 确定性验证器 + LLM-as-a-Judge + Rubric 分维度评分
  → 生成稳定失败归因、Benchmark 和问题案例分析
  → 自动提出改进建议，人工确认后修复 Skill / 代码 / 政策 / 数据集
  → 先回归受影响案例，再运行完整 Benchmark
  → 产生新的环境或数据集版本，进入下一轮
```

已确认的产品与工程决策：

1. 采用“平台通用评测契约 + 门诊结算首个完整 Benchmark”；其他 Skill 可接入，但不要求首轮实现全部专用验证器。
2. 复用现有 `SkillEvalSuite`、路由用例、回归用例、案例池、评测运行和发布门禁，不建设平行评测系统。
3. `SkillEvalSuite` 是可编辑的数据集工作区；每次正式运行引用不可变的 `SkillEvalDatasetVersion`。
4. 数据集的基本单位是端到端 `SkillEvalTask`，不是一段标准答案全文。
5. 一个任务可引用多条类型化断言，因此一次执行可以同时验证路由、计算、政策内容、引用、答案质量和安全。
6. trajectory prefix 是可恢复的执行接力点。Benchmark 默认跑完整任务；失败后可从接力点续跑以定位失败阶段。
7. trajectory 只保存动作、工具调用、工具结果和结构化状态，不保存模型隐藏思维过程。
8. 金额、公式、政策事实、引用关系和安全由确定性验证器优先裁决；LLM Judge 只评价开放质量，不能推翻硬错误。
9. 不使用缺乏含义的跨维度单一总分；按维度报告表现，并以独立硬门禁判定是否可发布。
10. 系统可以自动聚类失败、生成归因和修复建议，但代码、Skill、政策和数据集真值的变更必须人工确认。
11. 修复必须先通过受影响案例，再通过完整 Benchmark，才能进入既有发布流程。

[来源：`src/domain/skill/governance_models.py`、`src/domain/skill/regression_models.py`、`src/runtime/skill_management/governance_service.py` 已提供现有评测资产；`docs/steering/skill-AI编写与评测挖掘-PRD.md` 已定义错误案例池和五类回归断言。]

## 2. 当前基础与 V2 缺口

### 2.1 已有能力

- 可命名、可按 Skill 过滤的 `SkillEvalSuite`；
- 路由用例、候选与基线 Top-1 对比及 test 发布门禁；
- `calculation`、`policy_content`、`citation`、`answer_quality`、`safety` 五类回归断言；
- Policy QA 错误反馈进入案例池，经 AI 分型和人工确认生成回归资产；
- 门诊结算 28 条不同人群、险种和支付渠道真实快照；
- 运行记录冻结候选、基线、部分用例与配置证据；
- ModelGateway、语义层、政策知识、任务闭环和审计基础设施。

### 2.2 当前结构性缺口

1. 测评集目前主要组织路由问题模板，不能表达完整 Agent 任务、环境要求和接力边界。
2. 页面选中的测评集只过滤用例列表，尚未成为评测运行的真实输入边界。
3. 门诊 28 条固定自测与路由评测并列展示，用户无法区分“业务结果核验”和“路由回归”。
4. 评测真值分散在 YAML、路由用例和回归断言中，没有统一任务级定义。
5. 没有独立、不可变的数据集版本；Benchmark 难以重复运行和长期比较。
6. 现有运行详情主要展示路由差异，缺少端到端轨迹、组合评分和失败阶段归因。
7. 没有稳定的 Benchmark 定义、失败聚类、问题改进记录与复测闭环。
8. 当前 Skill 概览向收费员等普通角色展示大量治理入口和原始指标，角色边界不清。

V2 必须解决这些语义问题，不能只调整页面样式。

## 3. 目标与非目标

### 3.1 目标

- 任意 Skill 可建立版本化评测数据集；
- 数据集可定义完整端到端任务和可选 trajectory prefix；
- 一次任务执行可被多个确定性验证器和 Rubric 共同评价；
- 自动区分 Agent、环境、数据集和验证器问题；
- 生成可比较的 Benchmark 报告、失败簇和问题案例；
- 问题可关联到 Skill、代码、政策知识、语义层或数据集，并进入人工确认的任务闭环；
- 修复后自动完成影响集回归和完整 Benchmark 对比；
- 历史环境、数据集、轨迹、评分和归因可重复、可追溯、不可被改写；
- 门诊结算作为首个真实完整闭环，验证个人自付一原始值、政策证据和解释质量。

### 3.2 非目标

- 不建设任意代码执行平台；只运行已登记、已审核的执行器；
- 不保存或展示模型隐藏思维过程；
- 不用 LLM Judge 裁决确定金额、政策事实或高风险安全结论；
- 不自动修改或发布代码、Skill、政策和语义指标；
- 不把数据集任务当作真实业务主数据副本；只保存必要的脱敏快照和安全定位信息；
- 不在首轮为所有 Skill 实现专用生成器和验证器；
- 不自动穷举人群、险种和场景的笛卡尔积；
- 不建立第二套发布门禁或问题工单状态机。

## 4. 核心概念与关系

```text
SkillEvalSuite（可编辑数据集工作区）
  ├─ SkillEvalTask（端到端任务）
  │    ├─ EnvironmentRequirement
  │    ├─ DataLocator
  │    ├─ TrajectoryPrefix[]
  │    ├─ SkillEvalCase[]（路由断言）
  │    ├─ SkillRegressionCase[]（业务断言）
  │    └─ EvaluatorPlan
  └─ SkillEvalDatasetVersion（不可变版本）
       └─ SkillEvalBenchmarkDefinition
            └─ SkillEvalRun[]
                 └─ 不可变运行快照
                      ├─ TaskResult[]
                      ├─ FailureAttribution[]
                      └─ FailureCluster[]

runtime/task_closure（现有任务闭环）
  └─ ImprovementTaskLink[]（以 run_id 作为 workflow_id 动态关联）
```

### 4.1 `SkillEvalSuite`

延续现有测评集语义，作为可编辑的数据集工作区。保留 `suite_id`、名称、Skill 范围、用途、状态和乐观锁 revision。

新增或明确：

| 字段 | 说明 |
|---|---|
| `default_environment_id` | 默认评估环境 |
| `default_evaluator_plan_id` | 默认组合评分方案 |
| `readiness` | 派生状态；根据任务、环境、验证器和真值完整性计算，不额外维护状态机 |
| `latest_dataset_version_id` | 最近冻结的数据集版本 |

### 4.2 `SkillEvalTask`

端到端任务是数据集的基本执行单位：

| 字段 | 说明 |
|---|---|
| `task_id` | 服务端生成，格式 `EVT_<uuid4.hex>` |
| `suite_id` | 所属数据集工作区 |
| `target_skill_id` | 目标 Skill |
| `name` | 业务可读名称 |
| `partition` | `regression \| benchmark \| holdout` |
| `input` | 由 Skill 评测契约声明的类型化输入，不使用无约束裸字典 |
| `environment_requirements` | 数据源、政策、语义、工具等环境要求 |
| `data_locators` | 业务数据安全定位，不包含 SQL 或物理表名 |
| `trajectory_prefixes` | 可选接力点 |
| `assertion_refs` | 路由和回归断言引用 |
| `rubric_ref` | 开放质量 Rubric |
| `evaluator_plan_ref` | 任务级覆盖默认评分方案 |
| `required/enabled` | 门禁与启停 |
| `source_type/source_ref` | 人工、业务数据、问答反馈或历史导入 |
| `risk_tags/business_tags` | 风险与业务标签 |
| `revision` | 乐观锁 |

任务不保存标准答案全文。expected 由类型化真值组成：金额、状态、必含事实、禁止结论、政策和引用要求、允许误差、不可回答条件及开放 Rubric。

### 4.3 既有用例的兼容定位

- `SkillEvalCase` 继续只表示路由断言；
- `SkillRegressionCase` 继续表示计算、政策内容、引用、答案质量和安全断言；任务级 `dimension` 可将既有确定性断言归入 `behavior` 业务行为维度，不新增平行验证器；
- 两者逐步增加可选 `task_id`；
- 同一个任务可以引用多条断言；
- 没有 `task_id` 的历史用例由兼容层合成为“单断言任务”，不要求一次性迁移；
- 新 Portal 以任务为主视图，断言在任务详情内维护。

这种结构避免同一个用户输入因五类评测被重复执行五次，也不改变现有路由 Top-1 的统计语义。

### 4.4 `SkillEvalDatasetVersion`

不可变的数据集快照：

| 字段 | 说明 |
|---|---|
| `dataset_version_id` | `EVD_<uuid4.hex>` |
| `suite_id/suite_revision` | 来源工作区及 revision |
| `version_number` | 同一 suite 内单调递增 |
| `task_snapshots` | 冻结任务、prefix、断言与 Rubric |
| `environment_contract_hash` | 环境契约哈希 |
| `evaluator_plan_hash` | 评分方案哈希 |
| `content_hash` | 全部数据集内容聚合哈希 |
| `created_by/created_at` | 审计 |

任务、真值、Rubric、任务声明的环境要求或验证器需求发生变化时必须生成新数据集版本。实际环境、验证器或 Judge 的运行版本变化只生成新 Benchmark，不改写数据集版本。历史版本不修改、不删除，只能归档。

### 4.5 `SkillEvalBenchmarkDefinition`

Benchmark 是以下不可变组合：

```text
数据集版本
+ 评估环境版本
+ evaluator plan 与版本
+ Rubric / Judge 版本
+ 各维度门禁阈值
```

字段至少包括 `benchmark_id`、名称、Skill、数据集版本、环境版本、评分方案、门禁阈值、状态、创建人和时间。Benchmark 晋升和替换需要人工确认。

`EvaluatorPlan` 首期不是可上传代码或独立配置平台，而是服务端批准注册表中的版本化组合：声明要调用哪些现有验证器、顺序和阈值，Benchmark 冻结其 ID、版本与哈希。

## 5. 评估环境

### 5.1 `SkillEvalEnvironment`

评估环境是可版本化、可预检的运行契约，不等同于服务器地址：

- 数据源模式与数据快照版本；
- Skill 候选和基线的隔离制品；
- 政策知识活动快照或指定版本；
- 语义契约版本；
- Tool / MCP 注册表快照；
- ModelGateway 路由、提示词和 Judge 配置版本；
- 超时、最大步骤、恢复预算和输出大小；
- 脱敏、安全和高风险动作策略版本。

环境版本只保存安全引用、版本和哈希，不保存数据库密码、API Key 或患者身份信息。

首期不建设独立环境编排平台。环境契约复用现有运行配置、Skill/政策/语义版本和工具注册表，在 Benchmark 与运行中冻结为类型化快照；只有出现多人维护或独立晋升需求时再拆为独立持久化资产。

### 5.2 环境预检

正式运行前确定性检查：

1. 数据集版本存在且内容哈希一致；
2. 任务引用的数据和快照可解析；
3. 候选与基线版本存在且验证状态允许评测；
4. 需要的执行器、工具、政策和语义版本可用；
5. prefix 状态符合其 schema；
6. 安全与脱敏配置完整。

预检失败时不启动 Agent，任务结果为 `blocked` 或 `invalid_dataset`，不得计为 Agent 失败。

## 6. Trajectory 与 Prefix 边界

### 6.1 定义

trajectory 是一次执行的可审计轨迹：

- 公开输入；
- 动作和步骤类型；
- 工具名称、版本及脱敏参数摘要；
- 工具观察结果的脱敏摘要和哈希；
- 结构化 RuntimeContext；
- Skill 选择、政策检索引用、验证和终止状态；
- 最终公开答案。

禁止保存隐藏 chain-of-thought。内部推理只能记录为可审计的结构化事实、假设、验证状态或业务理由。

### 6.2 `TrajectoryPrefix`

| 字段 | 说明 |
|---|---|
| `prefix_id` | 任务内稳定 ID |
| `boundary_kind` | 如 `after_settlement_loaded`、`after_skill_selected`、`after_policy_retrieved` |
| `state_schema_version` | 可恢复状态 schema |
| `state_snapshot` | 脱敏结构化状态 |
| `observation_refs` | 已发生工具结果引用与哈希 |
| `resume_contract` | 候选 Agent 可执行的下一步及预算 |

### 6.3 使用方式

- Benchmark 主结果来自完整端到端运行；
- 完整运行失败后，系统按任务声明的 prefix 从前到后进行有界诊断；
- prefix 运行不替代完整运行，也不计为重试成功；
- prefix 结果用于定位故障在边界之前还是之后；
- 没有可恢复状态或 schema 不匹配时，诊断结果为 `blocked`，不猜测补全。

示例：完整任务失败，从 `after_settlement_loaded` 接力后通过，说明问题位于结算取数或上下文补全阶段，而不是后续解释逻辑。

## 7. 真值与 Evaluator Plan

### 7.1 结构化真值

每项真值必须属于严格类型：

| 类型 | 示例 |
|---|---|
| `route` | 必须选择 `mzsettlement_verify_skill` |
| `behavior` | 个人自付一必须取结算单原始字段；禁止执行通用反推公式 |
| `calculation` | 期望数值、容差、舍入和步骤约束 |
| `policy_content` | 适用条件、必含事实、禁止结论和政策版本 |
| `citation` | 必需来源、最低引用数及结论支撑关系 |
| `answer_quality` | answerability、必含/禁含表达和 Rubric |
| `safety` | 脱敏字段、高风险动作拦截和期望终止状态 |

AI 或历史系统回答不能直接成为 expected。真值必须来自真实结算字段、已发布政策/语义事实、确定性计算或人工确认。

### 7.2 组合评分顺序

```text
环境预检
  → 完整 Agent 运行
  → 确定性验证器
  → LLM Judge 评价开放 Rubric
  → 必要时 prefix 诊断
  → 失败归因
  → 分维度汇总和门禁
```

确定性验证器优先覆盖：任务完成、路由、金额、公式、状态、政策适用性、引用关系、脱敏和高风险动作。

LLM Judge 只覆盖：相关性、完整性、清晰度、面向用户的可理解性和必要范围控制。

### 7.3 LLM-as-a-Judge 约束

- 必须通过 `model_service.gateway.ModelGateway`，使用独立 scene `skill_eval_judge`；
- 输入只包含脱敏任务、允许展示的轨迹证据、结构化真值和 Rubric；
- 不向 Judge 暴露候选/基线身份，降低偏见；
- 输出为严格 DTO：rubric 分项、证据引用、failure codes、uncertainties；
- 冻结模型路由、Prompt、Rubric 和解析 schema 版本；
- 首轮每任务调用一次；临界分数、Judge 与确定性结果冲突时进入人工复核，不做多模型投票；
- Judge 不能把确定性失败改为通过。

### 7.4 评分与门禁

分别输出：

- 任务完成；
- 路由；
- 业务行为；
- 计算；
- 政策内容；
- 引用；
- 答案质量；
- 安全。

每个维度展示通过数、总数、阻塞数、分数或通过率及失败代码分布。不计算跨类型平均总分。安全必测失败、确定金额错误、必需政策事实错误或必测执行器阻塞时直接门禁失败。

## 8. 运行状态与失败归因

### 8.1 任务结果状态

| 状态 | 含义 |
|---|---|
| `passed` | 硬断言通过且 Rubric 达到阈值 |
| `failed` | 有证据确认属于 Agent 的错误 |
| `blocked` | 环境、数据源或验证器不可用 |
| `needs_review` | Judge 临界、验证器冲突或真值存疑 |
| `invalid_dataset` | 数据集定义或真值错误 |

运行级状态由任务结果派生，不把 `blocked` 和 `invalid_dataset` 计入 Agent 失败率，同时必须单独展示其数量。

### 8.2 归因结构

每个失败或阻塞结果生成：

| 字段 | 说明 |
|---|---|
| `owner_type` | `agent \| environment \| dataset \| evaluator` |
| `stage` | 失败阶段 |
| `failure_code` | 稳定机器码 |
| `summary` | 面向质量人员的简洁说明 |
| `evidence_refs` | 轨迹步骤、断言和来源引用 |
| `confidence` | 归因置信度 |
| `suggested_target` | Skill、代码、政策、语义、环境或数据集 |

稳定阶段枚举：

```text
environment
data_resolution
context_rewrite
routing
policy_retrieval
calculation
citation
answer_composition
safety
evaluator_or_dataset
```

证据优先级：环境预检与确定性断言 > prefix 差异 > LLM Judge。证据冲突时状态必须为 `needs_review`。

### 8.3 失败聚类

Benchmark 按以下稳定键聚类：

```text
owner_type + stage + failure_code + target_skill_id + business_tags
```

聚类展示影响任务数、首次/最近出现、候选与基线变化、代表案例、风险等级和建议责任对象。不得只按自然语言相似度聚类；向量相似度只能辅助合并候选。

## 9. Benchmark 与防过拟合

### 9.1 数据分区

- `regression`：已知历史问题，详细结果对维护者可见；
- `benchmark`：稳定代表性任务，用于候选和基线比较；
- `holdout`：案例数量和治理能力足够后启用，详细真值对 Skill 作者受限展示。

已确认的新失败经人工校验后进入 regression。Benchmark 或 holdout 组成变化时必须发布新数据集版本，不能静默替换。

### 9.2 报告内容

- 各维度候选、基线和差异；
- 通过、失败、阻塞、待复核和数据集错误数量；
- 新失败、新通过、持续失败和已消失任务；
- 失败阶段和失败代码分布；
- 人群、险种、就医类别、支付渠道等业务覆盖；
- 环境、数据集、验证器和 Judge 版本；
- 成本、时延、工具调用和恢复预算使用；
- 与历史 Benchmark 的趋势。

### 9.3 发布门禁

发布门禁引用指定 `benchmark_id` 和成功运行，至少校验：

1. 数据集、环境、验证器和候选制品哈希仍一致；
2. 全部必测任务完成；
3. 安全、金额和政策硬门禁通过；
4. 没有未处理的 `needs_review` 必测案例；
5. 候选没有超过阈值的新回归；
6. 运行未被新数据集版本或新活动基线失效。

## 10. 问题与改进闭环

```text
失败聚类
  → 生成归因和修复建议
  → 人工确认责任对象与范围
  → 复用 runtime/task_closure 创建改进任务
  → 关联代码提交、Skill 版本、政策变更或数据集 revision
  → 运行受影响任务
  → 运行完整 Benchmark
  → 对比候选与基线
  → 通过后进入既有发布流程
```

评测域不再建设一套工单状态机。它只保存失败簇与现有任务闭环的关联 ID、建议、证据和复测运行 ID。

自动化允许：

- 失败聚类和影响范围计算；
- 归因候选和修复建议；
- 推荐责任对象；
- 生成改进任务草稿；
- 计算受影响任务集；
- 人工确认后的自动复测。

自动化禁止：

- 直接修改、物化或发布 Skill；
- 直接修改政策知识或语义真值；
- 直接变更 expected、Rubric 或 holdout；
- 因复测通过而绕过现有审批和发布门禁。

## 11. 门诊结算首个完整 Benchmark

### 11.1 数据集

创建工作区：

```text
名称：门诊结算结果核验基准集
skill_id：mzsettlement_verify_skill
目的：验证不同已识别人群、险种、就医类别和支付渠道下的真实结算取值、勾稽、政策证据和解释质量
```

现有 28 条 YAML 样例迁移为端到端任务：

| 当前内容 | 新模型 |
|---|---|
| `settlement_id` | `DataLocator(resource_type=settlement)` |
| 人群、险种、就医类别、金额上下文 | 冻结脱敏环境快照 |
| `expected_self_pay_one` | behavior / calculation 确定性断言 |
| `note` | 任务说明和来源 |
| `enabled` | 任务启用状态 |

### 11.2 代表任务

交易号 `011100030X260417004975`：

- 输入：“011100030X260417004975，费用组成”；
- 必须查询并补全人员、险种、医疗类别和结算金额；
- 个人自付一必须使用真实结算单原始值 `510.96`；
- 禁止使用已确认不适用于该人群的通用反推公式；
- 面向用户只展示结算单可见金额，不展示无必要中间范围；
- 政策性结论必须有适用于本次人群、险种、机构和日期的证据；
- 证据不足时必须明确不确定性，不能伪造政策依据。

建议 prefix：

- `after_settlement_loaded`；
- `after_context_rewritten`；
- `after_skill_selected`；
- `after_policy_retrieved`。

### 11.3 首个闭环验收故事

1. 运行含已知错误的候选版本；
2. 确定性验证器识别个人自付一取值或公式错误；
3. prefix 诊断将问题定位到 calculation 或 answer_composition，而非环境；
4. Benchmark 形成失败簇和代表案例；
5. 系统生成 Skill / 代码修复建议并创建待确认改进任务；
6. 人工完成修复并登记新候选版本；
7. 受影响任务转为通过；
8. 完整 Benchmark 无新增回归；
9. 历史失败运行保持不变，可对比修复前后轨迹与分数。

## 12. 页面信息架构

`/skills/evaluations?skill=<skill_id>` 是统一入口，进入时自动选中来源 Skill，不重复要求用户选择。

页面分为四个连续工作区：

| 工作区 | 核心任务 |
|---|---|
| 数据集 | 维护任务、真值、prefix、覆盖和不可变版本 |
| 运行与实验 | 选择 Benchmark、候选/基线和运行模式 |
| Benchmark 分析 | 查看分维度表现、趋势、失败簇和案例下钻 |
| 问题与改进 | 确认归因、创建任务、关联修复和复测 |

### 12.1 顶部固定上下文

始终显示：Skill、数据集、数据集版本、环境版本、候选、基线、任务数、必测数和最近运行状态。页面展示的启用任务数必须与实际运行使用的任务数一致。

### 12.2 数据集工作区

- 数据集列表和版本；
- 任务表：分区、来源、覆盖、验证器就绪度、最近结果；
- 从业务数据、语义覆盖缺口、问答案例池或人工创建任务；
- 任务详情内维护输入、prefix、类型化断言和 Rubric；
- 冻结新数据集版本前展示校验结果和变更摘要。

### 12.3 运行与实验

- 深链进入时锁定当前 Skill；
- 选择候选与基线版本；
- 选择已冻结数据集版本和环境；
- 默认“完整任务，失败后自动 prefix 诊断”；
- 启动前预览任务数、预计 Judge 调用数和阻塞项；
- 运行不可修改，只能取消或重新运行。

### 12.4 Benchmark 分析

- 分维度候选/基线差异；
- 业务覆盖、失败阶段和失败代码；
- 失败簇与代表案例；
- 单任务完整轨迹、断言、Judge Rubric 和 prefix 对比；
- 两次运行按任务指纹比较。

### 12.5 问题与改进

- 失败簇、归因置信度和证据；
- 推荐责任对象和修复建议；
- 人工修改和确认后创建改进任务；
- 关联代码提交、Skill 版本、政策或数据集版本；
- 显示影响集复测和完整 Benchmark 复测结果。

### 12.6 角色边界

- 收费员等普通业务用户只在 Policy QA 提交“回答有误”；
- 质量人员与 Skill 管理员维护数据集、发起评测和确认归因；
- Skill 作者只能修改其权限范围内的 Skill，不能自行修改 holdout 真值；
- 政策和语义真值变更继续经过现有审核/发布权限。

Skill 概览默认只展示名称、能力、状态、场景和覆盖摘要；原始业务指标折叠到技术详情。

## 13. API 方向

统一前缀仍为 `/api/v1/medical-insurance-ai-agent`。

### 13.1 数据集与任务

| 方法 | 路径 | 用途 |
|---|---|---|
| GET/POST | `/infra-skills/eval-suites` | 工作区查询和创建 |
| GET/PUT | `/infra-skills/eval-suites/{suite_id}` | 工作区详情和乐观锁更新 |
| GET/POST | `/infra-skills/eval-suites/{suite_id}/tasks` | 任务查询和创建 |
| GET/PUT | `/infra-skills/eval-tasks/{task_id}` | 任务详情和更新 |
| POST | `/infra-skills/eval-suites/{suite_id}/dataset-versions` | 校验并冻结数据集版本 |
| GET | `/infra-skills/eval-suites/{suite_id}/dataset-versions` | 历史版本 |

### 13.2 环境与 Benchmark

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/infra-skills/eval-environments` | 可用环境版本 |
| POST | `/infra-skills/eval-environments/{environment_id}/preflight` | 确定性预检 |
| GET/POST | `/infra-skills/eval-benchmarks` | Benchmark 查询和创建 |
| POST | `/infra-skills/eval-benchmarks/{benchmark_id}/runs` | 发起完整运行 |
| GET | `/infra-skills/eval-runs/{run_id}` | 运行、任务结果和轨迹详情 |
| GET | `/infra-skills/eval-runs/compare` | 候选/基线或历史运行比较 |

### 13.3 归因与改进

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/infra-skills/eval-runs/{run_id}/failure-clusters` | 失败簇 |
| POST | `/infra-skills/eval-failure-clusters/{cluster_id}/improvement-task` | 人工确认后创建改进任务 |
| POST | `/infra-skills/eval-runs/{run_id}/retest` | 运行影响集或完整 Benchmark |

所有接口使用显式 Pydantic DTO。写操作要求 `skill:evaluate`、乐观锁或幂等键；错误保持 `{error_code, message, audit_event}`。

### 13.4 兼容策略

- 现有 `/infra-skills/eval-cases*` 继续服务路由断言；
- 现有 `/infra-skills/{skill_id}/eval-runs*` 在迁移期映射到默认 Benchmark；
- 历史用例自动合成为单断言任务；
- 门诊 `/self-tests*` 在任务迁移完成前只读保留，之后退役；
- 新运行必须携带数据集版本或 benchmark ID，不能只靠页面筛选决定范围。

## 14. 存储、并发与不可变性

首期新增表：

- `skill_eval_tasks`；
- `skill_eval_dataset_versions`；
- `skill_eval_benchmarks`。

现有表扩展：

- `skill_eval_cases.task_id`；
- `skill_regression_cases.task_id`；
- `skill_eval_runs.dataset_version_id`、`benchmark_id`、`environment_snapshot`、`task_results`、`trajectory_summary`、`failure_attributions`、`failure_clusters` 和分维度摘要。

运行结果、归因和失败簇首期沿用现有运行快照的 JSONB 存储方式，不为每类结果新增表。改进任务继续写入现有 `runtime/task_closure`，以 `run_id` 作为 `workflow_id` 查询关联，避免修改不可变运行。页面查询均以单次运行为边界；只有任务量或跨运行分析出现可测量的查询瓶颈时再规范化拆表。

原则：

- 工作区和任务更新使用 `expected_revision`；
- 数据集版本、Benchmark、运行、任务结果、轨迹和归因不可修改；
- 被运行引用的任务和断言只能停用，不能物理删除；
- 内容指纹覆盖输入、环境要求、prefix、真值、Rubric 和 evaluator plan；
- PostgreSQL 新字段必须同时维护 CREATE 和 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`；
- 运行创建时在一个事务内冻结所有引用和哈希。
- 数据集版本的 `task_snapshots` 首期整体冻结；当单版本任务量导致行大小或加载时延达到数据库监控阈值时，再拆分版本明细表。

## 15. 安全、隐私与审计

- 真实业务数据通过语义层或 adapters 获取，任务不得包含 SQL、物理表名或连接信息；
- 前端和评测存储不展示患者姓名、身份证、手机号、住址等信息；
- 结算号等业务定位 ID 按权限展示，运行快照保存前再次脱敏；
- trajectory 不保存隐藏思维过程和敏感工具原始响应；
- Judge 输入先脱敏，只能通过 ModelGateway；
- 测试执行器使用批准注册表，不允许从数据集指定任意模块或 URL；
- 运行和归因保留环境、数据、验证器、Judge、Skill、政策和语义版本；
- 数据集真值、Rubric、Benchmark 晋升和改进确认记录操作者与审计事件；
- 高风险动作仍必须由 `security/risk_control` 拦截为人工确认。

## 16. 错误处理

| 场景 | 处理 |
|---|---|
| 环境瞬时连接或超时 | 全局最多自动重试一次 |
| Agent 业务失败 | 不自动重试；可执行 prefix 诊断 |
| 数据不存在或快照失效 | `blocked`，不计 Agent 失败 |
| 真值或 task schema 错误 | `invalid_dataset`，隔离案例 |
| 执行器未登记 | `blocked`；必测任务门禁失败 |
| Judge 不可用 | 开放维度 `blocked`，保留确定性结果 |
| Judge 临界或结果冲突 | `needs_review` |
| 单分组执行器异常 | 保留已完成结果，运行标记 partial/error |
| revision 冲突 | 409，要求刷新，不覆盖他人修改 |
| 复测时版本已变化 | 拒绝运行或明确创建新 Benchmark，不静默替换 |

## 17. 分阶段实施

### 阶段 A：测评集资产入口（已完成）

- `SkillEvalSuite`、存储、API 和通用 Skill 入口；
- 路由用例归属测评集；
- 保持旧运行和发布门禁兼容。

### 阶段 B：数据集优先

- `SkillEvalTask` 和任务级类型化真值；
- 不可变 `SkillEvalDatasetVersion`；
- 既有路由/回归用例兼容合成；
- 门诊 28 条样例迁移；
- 页面重组为数据集工作区；
- 运行请求真实绑定数据集版本。

### 阶段 C：端到端运行与组合评分

- 版本化环境和预检；
- 完整 Agent 执行轨迹；
- prefix 恢复和有界诊断；
- 确定性验证器组合；
- ModelGateway Judge 和 Rubric；
- 分维度状态、分数与硬门禁。

### 阶段 D：Benchmark 与改进闭环

- Benchmark 定义和候选/基线比较；
- 失败归因、聚类和问题案例分析；
- 关联现有任务闭环；
- 影响集复测和完整 Benchmark 复测；
- 发布门禁引用正式 Benchmark。

### 阶段 E：通用生成与覆盖扩展

- 其他 Skill 声明评测契约；
- 从业务数据、语义值域和问答历史批量生成任务；
- 缺失指标送语义发现审核；
- 数据量足够后启用 holdout；
- 按真实失败补齐专用验证器。

每阶段均是一条可独立验证、回滚的用户故事，不要求一次实现全部平台能力。

## 18. 验收标准

### 18.1 数据集

- 用户可在一个工作区维护端到端任务、prefix、真值和 Rubric；
- 冻结后生成不可变数据集版本和内容哈希；
- 修改工作区不影响旧版本和旧运行；
- 历史路由/回归用例可兼容执行；
- 不保存标准答案全文或患者原始敏感上下文。

### 18.2 运行和评分

- 运行真实引用选中的数据集版本，页面任务数与实际一致；
- 完整任务失败后可从声明 prefix 接力诊断；
- 确定性错误不能被 Judge 覆盖；
- Judge 模型、Prompt 和 Rubric 版本可追溯；
- 结果明确区分 passed、failed、blocked、needs_review 和 invalid_dataset；
- 各维度分别报告，不使用掩盖失败的单一总分。

### 18.3 Benchmark 与改进

- 候选和基线在同一 Benchmark 上比较；
- 环境问题不计作 Agent 失败；
- 失败归因包含责任类型、阶段、稳定代码和证据；
- 相同根因可聚类并下钻代表案例；
- 改进任务关联修复资产和复测运行；
- 受影响案例与完整 Benchmark 均通过后才允许进入发布流程。

### 18.4 页面与权限

- 页面按数据集、运行、Benchmark、改进四个工作区组织；
- Skill 深链自动锁定当前 Skill；
- 门诊固定自测和路由评测不再无解释地混在同一页面；
- 收费员不直接维护测评资产；
- 原始指标默认折叠，治理人员可查看技术详情；
- 键盘、标签、状态文本和错误提示满足基础可访问性。

### 18.5 首个真实闭环

- `011100030X260417004975` 的个人自付一稳定验证为 `510.96`；
- 不适用的通用反推公式能够被确定性验证器识别；
- 至少一个已知失败完成“运行→归因→修复任务→修复→影响集复测→完整 Benchmark”闭环；
- 修复前后轨迹、分数、证据和版本均可比较；
- 28 条门诊样例迁入正式数据集资产且历史来源可追溯。

## 19. 验证策略

遵循仓库要求的单元测试 → API 测试 → Flow 测试，只运行与当前阶段相关的最小集合，再执行 Portal 组件测试和构建。

### 单元测试

- 任务、prefix、真值判别联合和数据集版本哈希；
- 环境预检、状态派生和一次恢复预算；
- 确定性验证器优先级与 Judge 不可翻案；
- prefix 差异归因和失败聚类键；
- 数据集不可变、revision 冲突和 CREATE + ALTER 覆盖。

### API 测试

- 数据集、任务、版本、环境预检、Benchmark、运行、归因和改进链接；
- 权限、幂等、409、422、blocked 和 invalid_dataset 契约；
- 旧用例和旧运行 API 兼容；
- 页面选择的数据集版本与运行快照一致。

### Flow 测试

首轮只要求一条真实价值主链：

```text
门诊任务冻结
→ 已知错误候选运行失败
→ 确定性断言和 prefix 归因
→ 创建改进任务
→ 新候选复测通过
→ 完整 Benchmark 无新增回归
```

不为本设计扩大无关全仓测试范围。

## 20. 关键取舍

| 取舍 | 结论 | 原因 |
|---|---|---|
| 新建独立评测平台 | 否 | 会重复既有测评、回归、案例池和发布门禁 |
| 只改页面形成“闭环” | 否 | 无法保证数据、环境和运行可重复 |
| 标准答案全文作为真值 | 否 | 多种表达均可能正确，且容易把历史错误固化 |
| 端到端任务作为基本单位 | 是 | 一次执行可被多维验证并支持轨迹归因 |
| 完整运行 + 可选 prefix | 是 | 兼顾真实效果与问题定位 |
| 保存 chain-of-thought | 否 | 不必要且存在安全与治理风险 |
| Judge 裁决金额/政策/安全 | 否 | 客观和高风险维度必须确定性验证 |
| 多模型 Judge 投票 | 首轮否 | 成本高；固定单 Judge + 临界人工复核足够 |
| 单一综合总分 | 否 | 会掩盖安全、金额或政策硬错误 |
| 自动修复并发布 | 否 | 医保高风险场景必须人工确认 |
| 新建改进工单状态机 | 否 | 复用现有 task closure，只保存关联证据 |
| 首轮同时覆盖所有 Skill | 否 | 平台契约通用，门诊真实闭环先验证方法 |

## 21. 最终用户体验

```text
Skill 能力概览
  → 进入评测中心并自动选中 Skill
  → 选择数据集工作区，维护端到端任务和真值
  → 冻结数据集版本
  → 选择 Benchmark、候选和基线
  → 运行完整任务，失败后自动 prefix 诊断
  → 查看分维度评分、失败簇和代表案例
  → 确认责任对象并创建改进任务
  → 关联修复版本，运行影响集和完整 Benchmark
  → 通过后进入原有审批与发布流程
  → 真实新问题继续回流数据集，形成下一版本
```

评测中心的核心不是“运行一次测试”，而是让每个已确认问题都能沉淀成可重复任务，让每次修复都能证明没有破坏其他能力，并让环境、数据、评估和改进共同演进。
