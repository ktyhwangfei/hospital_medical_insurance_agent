# 住院费用全分段语义查询与 SQL 编译设计

日期：2026-08-25  
状态：已确认
范围：语义元数据、受限语义查询、Query Planner、SQL 编译与执行、Policy QA 切换、语义编辑器和 Policy QA 前端。  
核心样例：住院费用查询，结算单号 `1671213`，住院超过 90 天并产生多个待遇结算分段。

## 1. 决策摘要

采用“LLM/Skill 生成受限 `SemanticQuery`，确定性 Query Planner 基于已发布语义模型生成逻辑计划，SQLAlchemy Core 编译参数化 SQL”的方案。

核心决策如下：

1. 删除 `src/knowledge_extension/rule_explanation/policy_retrieval/config/business_sql.yaml` 的运行时依赖；完成切换后删除文件和固定 SQL 执行路径。
2. 不引入 Cube、MetricFlow 或其他新的语义层运行时。第一阶段复用现有 `SemanticRegistry`、PostgreSQL 注册表、SQL Server 连接通道和已安装的 SQLAlchemy Core。
3. 语义层从“指标直接映射 `table.field`”升级为“业务对象 → 数据集 → 键/字段 → 关系 → 指标 → 质量规则”的语义图。
4. 查询请求显式区分“业务主体锚点”和“普通行过滤”。结算单号用于确定整次住院范围，不能被误编译为仅保留一个分段的行过滤。
5. 多事实表不能先拼明细再聚合。Planner 必须把每个事实分支先聚合到公共粒度，再关联并聚合到结果粒度。
6. Policy QA 只消费已发布语义模型；语义查询失败时失败关闭，不回退固定 SQL，也不把不完整分段解释为全部住院费用。
7. 语义编辑器需要实质性改造；Policy QA 对话页只增加查询范围、分段数和完整性展示，不暴露 SQL、表名或内部计划。

## 2. 背景与根因

### 2.1 用户问题

用户查询“住院费用，结算单 1671213”时，系统给出无法解释或错误费用。真实业务中该住院超过 90 天，医保系统按周期形成多个待遇分段。用户要的是整次住院费用，当前路径实际只消费了第一个结果行。

成功结果必须回答：

- 查询范围是不是整次住院；
- 一共有多少个分段；
- 是否完整覆盖所有分段；
- 整次住院的总费用及基金支付、个人负担等汇总；
- 数据不完整时为什么不能给确定性解释。

### 2.2 当前运行链路

```text
Policy QA SSE/REST
  → create_settlement_data_provider()
  → RealDbSettlementDataProvider
  → business_sql.yaml / settlement_context
  → SqlServerBusinessDataClient._query_one()
  → cursor.fetchone()
  → 单行 SettlementContext
  → settlement_explain_skill
  → PolicyQAPublicResult
```

证据：

- `business_sql.yaml:46-97` 的 `settlement_context` 按 `djh` 查询，关联 `yb_dyxxzy` 与 `yb_zyfdxx` 的分段数据，没有把结果收敛为一行。
- `sqlserver_business_data_client.py:143-196` 使用 `cursor.fetchone()`，多分段结果只保留第一行。
- `settlement_data_provider.py:77-138` 直接把这一行转换成扁平 `SettlementContext`。
- `policy_qa_routes.py:667-722` 的真实运行时直接创建上述 provider；现有语义层不是该链路的取数入口。

因此根因不是回答文案，而是数据查询粒度错误：返回了“一个分段行”，上层却把它当作“整次住院上下文”。

### 2.3 当前语义层为什么没有生效

当前语义层能管理业务对象、指标、值域和发布版本，但运行时查询能力仍是字段读取器：

- `src/semantic_layer/models.py:47-74` 把物理来源直接放在 `Metric.source_field`。
- `src/semantic_layer/data_query.py:37-90` 仅把指标解析为 `table.field` 并按表分组。
- `src/runtime/discovery/semantic_source.py:242-304` 对每张表执行 `SELECT TOP 1`。
- `semantic_source.py:306-346` 的 joined 模式仍复用 `business_sql.yaml`。
- `runtime/intent/planner.py` 的 `must_query_semantic` 只是上下文需求标志，Policy QA 费用查询并未据此切换到语义查询执行器。

现有语义层缺少：

- 数据集及其真实行粒度；
- 主键、唯一键、外键和复合键；
- 可执行的关系图与路径选择；
- 事实、维度和聚合指标的区分；
- 多事实预聚合；
- 结果粒度推导；
- 分段覆盖和重复键质量核验；
- 从语义查询到参数化 SQL 的确定性编译器。

## 3. 目标与非目标

### 3.1 目标

1. 用结算单号 `1671213` 查询时，返回整次住院全部分段的费用，而不是分段 1。
2. 所有 SQL 都由已发布语义模型和受限查询结构确定性生成。
3. LLM 不接触物理表名、列名、JOIN 条件或原始 SQL。
4. 多事实查询不会因明细 JOIN 产生扇出和金额膨胀。
5. 运行时能证明查询范围、结果粒度、分段数和完整性。
6. 语义模型发布前能够发现缺键、歧义路径、非法表达式和不可编译查询。
7. Policy QA、语义编辑器和后端公开契约保持跨层一致。

### 3.2 第一阶段非目标

- 不接入 Cube、MetricFlow 或 Looker。
- 不允许管理员编写或覆盖生成 SQL。
- 不支持任意 SQL 表达式、窗口函数、累计指标和复杂同期/环比。
- 不支持跨数据库联邦查询。
- 不自动推导多对多关系。
- 不建设物化预聚合、缓存和高并发查询集群。
- 不做可视化拖拽关系图。
- 不在 Policy QA 页面展示内部 SQL、物理表名或查询计划。

## 4. 成熟产品对照与技术选型

### 4.1 成熟产品的共同结构

截至 2026-08-25，成熟语义层产品的共同方向是：

- 用实体/键连接语义模型，而不是让 LLM 猜 JOIN；
- 明确区分维度与聚合指标；
- 声明关系基数，避免聚合扇出；
- 根据查询所需成员动态生成 JOIN；
- 用受治理模型向 BI、应用和 AI Agent 提供一致定义。

参考：

- [dbt Semantic Models](https://docs.getdbt.com/docs/build/semantic-models)：语义模型由 entity、dimension 和 metric 组成，MetricFlow 使用实体构建语义图并在查询时生成必要关联。
- [dbt Entities](https://docs.getdbt.com/docs/build/entities)：实体支持 primary、unique、foreign、natural，并可使用复合列作为跨模型连接键。
- [Cube Joins](https://docs.cube.dev/docs/data-modeling/joins)：关系基数与主键用于自动生成 JOIN，并防止聚合扇出；歧义场景需要显式 join path。
- [Cube Data Modeling](https://cube.dev/product/data-modeling)：业务实体、维度、指标和关系形成统一的数据图，供应用和 AI Agent 消费。
- [Looker Join Parameters](https://docs.cloud.google.com/looker/docs/reference/param-join)：Explore 通过显式关系把多个 view 暴露给查询，并声明 relationship。

由此判断，“LLM → 受限语义查询 → 语义图/Planner → 确定性 SQL”是当前主流 Data Agent 的可靠实现方向；“LLM 直接生成生产 SQL”只适合探索性分析，不适合医保金额解释。

### 4.2 为什么现在不引入 Cube/MetricFlow

Cube 和 MetricFlow 已实现更完整的语义图、查询规划和多消费者协议，但当前项目具有以下边界：

- 第一阶段只有一个 SQL Server 数据源；
- 主要消费者是本项目 Policy QA 和 Skill；
- 当前急需解决的是分段、复合键和多事实扇出；
- 项目已有注册表、版本发布、Portal 编辑器和 SQLAlchemy；
- 直接引入外部语义运行时会增加模型迁移、部署、权限和双注册表同步成本。

因此采用最小自建编译器：吸收成熟产品的数据模型和 Planner 原则，不复制其缓存、物化、协议和多租户运行时。

满足以下任一条件时再评估 Cube 或 MetricFlow：

- 语义指标达到数百个，关系图长期由多人并行维护；
- BI、嵌入式分析和多个 Agent 需要共享同一语义 API；
- 查询并发、缓存或预聚合成为明确瓶颈；
- 需要跨数据源查询或成熟的时间指标能力。

## 5. 总体架构

```text
用户问题 / Skill 输入
        │
        ▼
意图与业务范围解析
  action=query|explain
  object=inpatient_settlement
  scope=whole_admission
        │
        ▼
SemanticQuery Builder
  只生成对象、锚点、指标、维度、过滤和排序
        │
        ▼
SemanticQueryService
  ├─ PublishedModelResolver
  ├─ QueryPlanner
  ├─ SQLAlchemyRenderer
  ├─ SQL Server 执行
  └─ QualityEvaluator
        │
        ▼
SemanticQueryResult
  rows + result_grain + query_scope + quality + evidence
        │
        ├─ 语义编辑器查询验证
        └─ SettlementDataProvider 适配 → SettlementContext → Skill → Policy QA
```

### 5.1 组件职责

| 组件 | 职责 | 依赖 |
|---|---|---|
| `SemanticRegistry` | 保存草稿与已发布语义模型，提供版本快照 | 现有 RegistryStore |
| `SemanticQueryBuilder` | 把意图/Skill 需求转换为受限查询 | 业务对象和公开字段，不依赖数据库 |
| `QueryPlanner` | 解析模型、关系路径、粒度、预聚合和质量计划 | 已发布模型 |
| `SQLAlchemyRenderer` | 把逻辑计划编译成参数化 SQL Server SQL | SQLAlchemy Core |
| `SemanticQueryService` | 编排解析、规划、编译、执行和质量判定 | 上述具体组件 |
| `SettlementDataProvider` | 复用现有 Skill 边界，把通用查询结果映射成 `SettlementContext` | `SemanticQueryService` |
| 语义编辑器 | 管理模型、发布校验、查询验证 | Semantic API |
| Policy QA | 展示安全业务结果及完整性 | `PolicyQAPublicResult` |

不新增只有一个实现的抽象工厂；`SemanticQueryService` 第一阶段是具体服务。外部系统连接仍通过现有数据源/适配边界。

## 6. 元数据模型

### 6.1 `BusinessObject`

复用现有 `BusinessObject`，定位为用户可见的语义主题，例如“住院结算”“住院费用”“政策规则”。它不再直接代表一张物理表，也不保存一个模糊的单字段 `identifier` 作为全部粒度依据。

### 6.2 `SemanticDataset`

描述一个可查询物理数据集：

```text
dataset_code
object_code
datasource_id
schema_name
table_name
name
status
```

第一阶段仅允许已登记的 SQL Server 表或视图，不允许在元数据中保存任意子查询 SQL。

### 6.3 `DatasetKey`

```text
key_code
dataset_code
entity_code
key_type: primary | unique | foreign
columns: [column_a, column_b, ...]
```

约束：

- 每个可参与查询的数据集必须有一个 primary key。
- 支持复合键，分段关系不能只靠 `djh` 猜测。
- primary key 的列必须非空且唯一。
- foreign key 可重复或为空。
- `entity_code` 表示业务实体，如 `inpatient_admission`、`admission_segment`、`fiscal_year`。

数据集行粒度由 primary key 推导，不再维护可与主键矛盾的手工 `grain` 字段。

### 6.4 `SemanticField`

```text
field_code
dataset_code
column_name
name
field_role: identifier | dimension | fact
semantic_type
value_domain
nullable
status
```

- `identifier`：业务标识或连接键。
- `dimension`：分组、筛选或描述字段。
- `fact`：可被指标聚合的原子数值。

物理字段先成为 `SemanticField`，再由指标引用。禁止 discovery 页面从物理列直接创建最终 Metric。

### 6.5 `DatasetRelation`

```text
relation_code
from_dataset
from_key
to_dataset
to_key
cardinality: one_to_one | many_to_one | one_to_many
status
```

关系由键决定，不让管理员手工输入 `join_type` 或 SQL `ON` 表达式。第一阶段只支持等值复合键关系。

`BusinessObject` 保存必要的 `preferred_relation_paths`：每条配置由 `from_dataset`、`to_dataset` 和有序 `relation_codes` 组成。多条可行路径时必须命中唯一首选路径；否则 Planner 返回歧义错误。多对多关系必须先建关联数据集，不自动推断。

### 6.6 `Metric`

保留现有 `Metric` 业务身份，但运行时含义调整为真正的聚合指标：

```text
metric_code
object_code
metric_type: aggregate | derived
fact_field_code                 # aggregate 指标
aggregation: sum|min|max|avg|count|count_distinct
expression                     # derived 指标的受限表达式
dependencies
non_additive_dimensions
unit
status
```

不再使用一个 `Metric.role` 同时表示字段和指标；原子字段由 `SemanticField` 表达，Metric 只表达可消费的业务度量。

兼容边界：当前 `zcgz` 政策抽取契约把 field/entity/relation 也存成 `Metric.metric_kind`。本次最小用户故事不原地重解释这些历史行：Query Planner 只接受“对象存在已发布 Dataset/Key/Field，且 Metric 存在 `fact_field_code` 或合法 `expression`”的可查询模型；既有政策抽取继续按原契约工作。后续如迁移政策字段命名，必须单独立项并先改抽取契约，不与住院费用切换绑在一起。

### 6.7 `DataQualityRule`

```text
rule_code
rule_type: coverage | uniqueness | not_null
target_dataset_or_relation
severity: warning | blocking
parameters
status
```

关系基数描述模型预期，质量规则验证真实数据是否满足预期，两者分离。

第一阶段需要的规则：

- 分段键唯一；
- 锚点字段非空；
- 各事实分支的分段覆盖一致；
- 连接前后的 unmatched segment 数可计算。

住院分段 coverage 规则必须在 `parameters.reference_dataset` 中指定权威分段数据集。`segment_count` 来自该数据集；其他事实分支分别计算缺失段和额外段，不能用多个事实表的交集冒充完整范围。

### 6.8 发布版本

`BusinessObjectVersion` 快照必须从只冻结对象和 Metric，扩展为冻结完整查询模型：

```text
object
datasets
keys
fields
relations
metrics
quality_rules
```

运行时只读已发布快照。Skill 可跟随最新已发布版本，也可锁定特定版本；草稿永远不参与生产查询。

## 7. 受限语义查询契约

```yaml
object_code: inpatient_settlement
scope:
  entity_code: inpatient_admission
  anchor:
    field_code: registration_id
    value: "1671213"
metrics:
  - total_amount
  - medical_insurance_inner_amount
  - basic_pooling_payment
  - basic_pooling_self_pay
  - large_amount_payment
  - large_amount_self_pay
  - personal_total_pay
group_by: []
filters: []
order_by: []
limit: 100
```

### 7.1 `scope.anchor` 与 `filters` 的区别

- `scope.anchor`：用用户给出的标识找到本次查询的业务主体和完整范围。
- `filters`：限制参与计算的数据行，例如费用年度、费用类别或日期范围。

若把 `1671213` 仅作为一个分段表的普通过滤条件，Planner 可能只保留命中的那一段。作为 admission scope 的 anchor，它的含义是“定位这次住院，再查询该住院下全部分段”。

本设计按当前数据源的实际查询行为，把 `djh` 声明为 `inpatient_admission` 实体的 anchor key：同一 `djh` 下可以存在多个待遇分段。若后续医院数据源的结算单号只标识一个分段，则由该数据源的关系图先解析到 admission，再展开全部分段；查询契约不需要变化。

### 7.2 允许的查询能力

- 多个指标；
- 维度分组；
- 等值、范围、集合、空值过滤；
- 排序和有限行数；
- admission/segment 等实体锚点；
- 一个 SQL Server 数据源内的复合等值关联。

所有字段、指标、操作符都通过发布模型白名单解析，不接受物理标识符或 SQL 字符串。

## 8. Query Planner

### 8.1 规划阶段

```text
SemanticQuery
  1. 解析已发布模型和版本
  2. 解析 scope anchor 与目标实体
  3. 解析指标依赖的数据集和字段
  4. 在关系图中选择唯一连接路径
  5. 推导每个数据集的源粒度
  6. 确定事实分支的公共连接粒度
  7. 为每个事实分支生成预聚合
  8. 生成分支关联与最终聚合
  9. 附加质量核验计划
  → LogicalQueryPlan
```

### 8.2 粒度规则

1. 源粒度由 DatasetKey.primary 推导。
2. 查询结果粒度由 `group_by` 推导；无 `group_by` 时为 `scope.entity_code`。
3. 多事实表的公共粒度是所有分支都能无损到达的最低共同实体粒度。
4. 每个事实分支必须先聚合到公共粒度，禁止先 JOIN 原始事实行。
5. 最终再从公共粒度聚合到结果粒度。
6. 不可加指标跨 `non_additive_dimensions` 时直接拒绝或要求更细 group_by。

### 8.3 1671213 的规划结果

```text
目标实体：InpatientAdmission
锚点：registration_id = 1671213

待遇事实源粒度：BenefitSegmentRow
费用支付事实源粒度：FeeSegmentRow
公共粒度：AdmissionSegment
  (admission_id, fiscal_year, segment_start_date)
结果粒度：InpatientAdmission
```

`yb_dyxxzy` 和 `yb_zyfdxx` 分别先按复合分段键聚合。二者在公共分段粒度上关联后，再按 admission 聚合全部分段。`yb_dyxxnd` 的年度数据必须通过 admission + fiscal year 连接，不能只按 `djh` 连接后放大跨年度行数。

本数据源把 `yb_dyxxzy` 声明为 coverage reference。Planner 先从它生成 `segment_spine`，再把预聚合后的支付分支 LEFT JOIN 到 spine；另用 anti-join 检查支付分支的额外段。这样缺失支付段仍会留在质量结果中，不会被 INNER JOIN 静默删除。

### 8.4 逻辑计划

```yaml
model_version: "3"
root_object: inpatient_settlement
scope:
  entity: inpatient_admission
  anchor_field: registration_id
result_grain: [inpatient_admission]
branches:
  - branch_id: benefit_segments
    dataset: yb_dyxxzy
    source_grain: [admission_id, fiscal_year, segment_start_date, cycle_no]
    aggregate_to: [admission_id, fiscal_year, segment_start_date]
    metrics: [deductible, medical_insurance_inner_amount]
  - branch_id: payment_segments
    dataset: yb_zyfdxx
    source_grain: [admission_id, segment_start_date, segment_end_date]
    aggregate_to: [admission_id, fiscal_year, segment_start_date]
    metrics: [total_amount, pooling_payment, personal_total_pay]
joins:
  - left: segment_spine
    right: benefit_segments
    type: left
    on: [admission_id, fiscal_year, segment_start_date]
  - left: segment_spine
    right: payment_segments
    type: left
    on: [admission_id, fiscal_year, segment_start_date]
final_aggregation:
  grain: [admission_id]
quality_checks:
  - benefit_segment_key_unique
  - payment_segment_key_unique
  - payment_segments_cover_segment_spine
  - payment_segments_have_no_extra_keys
```

逻辑计划是测试、审计和前端查询验证的稳定契约；生成 SQL 只是它的数据库方言表达。

## 9. SQL 编译与执行

### 9.1 SQLAlchemy Core

使用项目现有 SQLAlchemy Core 构建 CTE、SELECT、JOIN、GROUP BY 和 bind parameters。编译器不拼接用户输入的表名、列名或 SQL 片段。

允许的聚合：

- `SUM`
- `MIN`
- `MAX`
- `AVG`
- `COUNT`
- `COUNT DISTINCT`

允许的派生表达式只由已解析指标、数值常量和受限算术操作符组成。

### 9.2 生成 SQL 的形态

```sql
WITH admission_anchor AS (...),
segment_spine AS (
    SELECT DISTINCT admission_id, fiscal_year, segment_start_date
    FROM ...
    JOIN admission_anchor ...
),
benefit_segments AS (
    SELECT admission_id, fiscal_year, segment_start_date, ...
    FROM ...
    JOIN admission_anchor ...
    GROUP BY admission_id, fiscal_year, segment_start_date
),
payment_segments AS (
    SELECT admission_id, fiscal_year, segment_start_date, ...
    FROM ...
    JOIN admission_anchor ...
    GROUP BY admission_id, fiscal_year, segment_start_date
),
joined_segments AS (
    SELECT ...
    FROM segment_spine
    LEFT JOIN benefit_segments ...
    LEFT JOIN payment_segments ...
)
SELECT admission_id, SUM(...)
FROM joined_segments
GROUP BY admission_id
```

这里只规定形态，不保存手写 SQL 模板。实际标识符、关联键和指标表达式均来自发布模型，锚点值通过 bind parameter 传递。

JOIN 类型由 Planner 固定推导，不进入用户可编辑元数据：事实到多对一维度使用 LEFT JOIN 保留事实行；多个事实分支只能先预聚合，再 LEFT JOIN 到 coverage reference 生成的 spine。完整性由质量计划判断，不通过切换 INNER/LEFT JOIN 改变业务口径。

### 9.3 执行结果

```text
SemanticQueryResult
  rows
  model_version
  result_grain
  query_scope
  quality_status
  evidence
  warnings
```

`evidence` 至少包括：计划哈希、使用的数据集、预期分段数、匹配分段数、重复键数和执行耗时。

## 10. 数据质量与结果状态

统一状态：

```text
complete     数据、关系和分段覆盖完整
partial      SQL 成功，但部分非阻断数据或分段覆盖不完整
unavailable  无法形成可靠费用结果
```

| 情况 | 状态 | 处理 |
|---|---|---|
| 锚点唯一且全部分段匹配 | complete | 正常解释 |
| 应有 2 段，仅匹配 1 段 | partial | 明确缺失，不给确定性费用结论 |
| 锚点不存在 | unavailable | 提示核对结算单号 |
| 锚点关联多个 admission | unavailable | 数据异常，阻断 |
| 分段主键重复 | unavailable | 可能重复计费，阻断 |
| 关系路径歧义 | unavailable | 模型错误，阻断 |
| 模型未发布或指标缺失 | unavailable | 不消费草稿 |
| SQL Server 超时/连接失败 | unavailable | 不回退固定 SQL |
| 非阻断描述字段缺失 | partial | 保留可验证指标并说明缺失 |

任何可能导致金额重复的情况都必须 blocking。

## 11. 语义模型发布门禁

### 11.1 结构校验

- 每个查询数据集有 primary key。
- 键字段存在且类型兼容。
- primary key 非空且声明唯一。
- 指标表达式只引用已声明字段/指标。
- 派生指标无循环依赖。
- 不存在隐式多对多关系。

### 11.2 路径与粒度校验

- 每个 Skill 需要的指标在关系图中连通。
- 歧义关系有唯一 preferred path。
- Planner 能推导公共粒度和结果粒度。
- 不可加指标不会越过受限维度求和。

### 11.3 编译校验

- 发布候选能生成 `LogicalQueryPlan`。
- SQLAlchemy 能编译为参数化 SQL Server SQL。
- SQL 不含未登记表、字段、函数或原始片段。

### 11.4 影响校验

- 展示受影响 Skill。
- 每个关联 Skill 至少编译一条代表性查询。
- 任一 blocking 项存在时禁止发布。

数据内容质量在运行时继续核验；发布校验不能假设未来每条住院数据都完整。

## 12. Policy QA 运行时切换

### 12.1 目标链路

```text
policy_qa_routes
  → Runtime Intent / Context Planner
  → settlement_explain_skill 的语义输入需求
  → SemanticQueryBuilder
  → SemanticQueryService
  → SemanticQueryResult
  → 复用 SettlementDataProvider 边界映射 SettlementContext
  → Skill 计算与政策检索
  → PolicyQAPublicResult
```

Skill 声明业务指标、业务对象和默认范围，不声明物理字段或 SQL。LLM 可协助识别用户是在问“整次住院”还是“某个分段”，但不能决定 JOIN。

“查询住院费用，结算单 1671213”的默认范围为 `whole_admission`；只有用户明确说“第 1 段”“某分段”时才查询 segment 粒度。

### 12.2 兼容与删除

复用现有 `SettlementDataProvider` Protocol，替换其真实数据库实现为语义查询适配，不再新增第二套 Skill 数据接口。

完成验收后删除：

- `business_sql.yaml`；
- `RealDbSettlementDataProvider` 对固定 YAML SQL 的依赖；
- `SqlServerBusinessDataClient._query_one()` 在费用解释运行时的调用；
- `SemanticDataSource` 的 `SELECT TOP 1` 费用查询路径；
- `SemanticDataSource._query_joined()` 对旧 YAML 的复用；
- 语义一致性接口中“语义层 vs business_sql”的旧双路径对比，改为“逻辑计划 vs 预期结果”验证。

值域码表迁移到 `src/semantic_layer/seed.py` 的部分可保留，因为它已经成为语义注册表的数据，不是 SQL 执行配置。

切换后不保留隐藏降级路径。新模型发布失败时继续使用上一个已发布语义版本；查询执行失败时返回 `unavailable`。

## 13. 前端设计

### 13.1 语义编辑器必须修改

现有 `/semantic-layer` 导航是“概览、业务域、业务对象、业务指标、映射、发现”。第一阶段保留整体信息架构，只做必要变化：

| 页面 | 调整 |
|---|---|
| 概览 | 增加数据集数、关系数、可发布对象数、歧义/无效模型数和运行时覆盖状态 |
| 业务对象 | 展示模型健康；发布弹窗增加键、关系、粒度、编译和受影响 Skill 检查 |
| 业务指标 | 编辑聚合方式、事实字段、派生表达式、依赖和不可加维度 |
| 映射 | 导航名称改为“数据模型”；管理数据集、键、字段、关系和质量规则，保留现有值域管理 |
| 发现 | “快速创建指标”改为“纳入数据集/创建语义字段”，不能跳过数据模型 |
| 查询验证 | 新增 `/semantic-layer/query`，用于执行受控样例和查看逻辑计划 |

第一阶段不引入图形建模库。数据集/键/关系用表格和详情面板已经足够。

### 13.2 查询验证页

输入：

- 业务对象；
- 目标实体；
- 锚点字段和值；
- 指标；
- group by；
- 普通过滤、排序和 limit。

输出：

- 查询范围；
- 结果粒度；
- 分段数和覆盖状态；
- 查询结果；
- 只读 `LogicalQueryPlan`；
- 管理员“技术详情”中的参数化 SQL。

生成 SQL 永远只读。第一阶段只增加一个管理员端点 `POST /api/v1/medical-insurance-ai-agent/semantic/query/test`，编译并以安全行数上限执行；Runtime 不绕 HTTP，直接调用 `SemanticQueryService`。

### 13.3 Policy QA 页面

`PolicyQACaseContext` 增加安全公开字段：

```text
query_scope: whole_admission | segment
segment_count: number
matched_segment_count: number
coverage_status: complete | partial
stay_start_date
stay_end_date
```

现有“计算依据”组件增加：

```text
查询范围：整次住院
住院期间：2026-01-01 至 2026-04-15
结算分段：2 个，已完整汇总
住院总费用：xxx.xx 元
```

当前组件已有 `totalAmount` 类型但没有展示，应补充“住院总费用”。

覆盖不完整时显示：

```text
发现 2 个结算分段，目前仅匹配 1 个。
结果不代表整次住院费用，暂不提供确定性解释。
```

第一阶段不展示逐分段费用列表；只有出现明确人工核对需求时再增加折叠明细。

Policy QA 继续递归移除内部字段，禁止公开 `query_trace`、SQL、表名、plan 或运行 ID。

## 14. 安全与可观测性

每次查询内部记录：

```text
model_version
object_code
result_grain
query_scope
plan_hash
datasets_used
segment_count
matched_segment_count
quality_status
duration_ms
error_code
```

- 结算单号等参数不写普通日志；只进入受控审计记录或脱敏后记录。
- 语义编辑器 SQL 技术详情受语义管理员权限控制。
- SQL 只读，连接账号保持最小权限。
- limit、超时和允许聚合函数由服务端固定。
- 公共回答必须携带可展示引用或 uncertainties。

## 15. 测试策略

### 15.1 单元测试

- `1671213` 作为 admission anchor 时生成范围定位 CTE。
- anchor 不会退化为只限制一个分段的普通 row filter。
- 待遇与支付事实分别预聚合后再 JOIN。
- 跨年度关系使用复合键，不按 `djh` 单列放大数据。
- 多路径歧义被阻断。
- 重复分段主键被阻断。
- 不可加指标跨受限维度聚合被阻断。
- 编译器只生成 bind parameters。
- 未登记字段、函数和任意 SQL 表达式被拒绝。

测试重点断言逻辑计划、绑定参数和业务结果；不对完整 SQL 文本做脆弱快照。

### 15.2 API 测试

- 数据集、键、字段、关系、指标和质量规则 CRUD。
- 对象发布返回明确 blocking/warning 项。
- 查询验证端点返回计划、权限允许时的只读 SQL、结果和质量状态。
- 非管理员不能读取 SQL 技术详情。
- 未发布模型不能执行。

### 15.3 Flow 测试

| 场景 | 预期 |
|---|---|
| 1671213，超过 90 天，2 个完整分段 | 返回整次住院总额，`segment_count=2` |
| 普通住院，单分段 | complete，`segment_count=1` |
| 2 段缺 1 段支付数据 | partial，禁止确定性解释 |
| 分段复合键重复 | unavailable，禁止金额输出 |
| 锚点不存在 | 提示核对结算单号 |
| 关系路径歧义 | 发布失败或运行时阻断 |
| SQL Server 不可用 | unavailable，不回退 `business_sql.yaml` |
| Policy QA 展示 | 明确显示整次住院、2 个分段、完整汇总 |

### 15.4 前端测试

- 新增 snake_case → camelCase 范围字段转换。
- “住院总费用”正确展示。
- complete/partial 使用不同文案。
- 查询验证页不能编辑生成 SQL。
- 发布弹窗展示阻断错误和受影响 Skill。
- discovery 页面不能再直接从物理字段创建 Metric。

实现验证严格按项目要求执行：单元测试 → API 测试 → Flow 测试；Portal 再执行相关 Vitest、TypeScript、Next.js build 和核心浏览器流程。

## 16. 落地顺序与切换门槛

### 16.1 最小可验证用户故事

> 经办人在 Policy QA 输入“查询住院费用，结算单 1671213”。系统使用已发布语义模型把该号码锚定到整次住院，分别聚合两个待遇/支付分段，再汇总为 admission 结果；页面显示“整次住院、2 个分段、完整汇总”和住院总费用。任一分段缺失或重复时，系统拒绝给出确定性金额解释。

### 16.2 实施顺序

1. 扩展注册表元数据与发布快照。
2. 实现受限 `SemanticQuery`、Planner、逻辑计划和 SQLAlchemy 编译器。
3. 建立 1671213 的两分段测试数据并完成质量核验。
4. 复用 `SettlementDataProvider` 边界接入 Policy QA。
5. 改造语义编辑器和 Policy QA 的最小必要前端。
6. 验证运行时只读新语义服务后，删除 YAML 和旧查询路径。

### 16.3 切换门槛

- 1671213 的人工核验总额与语义查询一致；
- 逻辑计划明确显示两个预聚合分支和 admission 结果粒度；
- complete/partial/unavailable 流程均通过；
- 搜索仓库确认 Policy QA 和语义数据源不再运行时引用 `business_sql.yaml`；
- 单元、API、Flow 和相关 Portal 验证通过；
- 前一个已发布语义版本可用于模型版本回滚。

## 17. 最终验收标准

1. 查询 1671213 返回全部住院分段，不再只返回分段 1。
2. 结果明确标注整次住院范围、分段数和完整性。
3. 多事实表不会因原始明细 JOIN 造成金额膨胀。
4. Policy QA 不读取 `business_sql.yaml`，仓库无旧固定 SQL 运行时降级路径。
5. LLM 无法生成或执行物理 SQL。
6. 关系歧义、重复主键或覆盖不足时失败关闭。
7. 语义编辑器能完成数据模型维护、发布检查和查询验证。
8. Policy QA 不公开 SQL、表名和内部计划。
9. 不新增 Cube 等依赖，第一阶段使用现有 SQLAlchemy Core。

## 18. 明确延后

- 查询缓存和物化预聚合；
- 跨 SQL Server/数据源联邦；
- 窗口、累计、同比和环比指标；
- 自动多对多推断；
- 可视化关系图；
- Policy QA 逐分段费用明细；
- 面向第三方 BI 的标准语义查询协议。

这些能力在实际规模或性能指标触发前不建设。
