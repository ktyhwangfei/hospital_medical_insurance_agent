# 政策字段的 bjyb 数据证据增强发现设计

日期：2026-08-20  
状态：已批准；最小页面闭环已实现，完整发布闭环后置
范围：政策规则对象（`zcgz`）遇到现有字段或值域无法准确表达政策语义时，利用 bjyb 数据发现结果寻找相似物理字段、分析值域并辅助人工建模；审核发布后驱动政策重提取、规范编译与版本化索引构建。

> [决策] bjyb 是政策在院端业务系统中的重要结构化实例，是新增政策字段的优先证据，但不是政策模型的完整真相，也不是新增字段的硬性前提。
>
> [关系] 本设计扩展 `2026-08-12-semantic-layer-metric-value-proactive-discovery-design.md` 的 S3 数据发现信号，并为 `2026-08-14-s5-conflict-diagnosis-dimension-candidate-design.md` 产出的维度候选补充数据库证据；不替换 S1/S5、语义提议状态机或人工建模裁决。

---

## 1. 背景与问题

当前政策抽取遇到结构缺口时，容易出现两种错误：

1. 现有字段语义过宽或过窄，模型把新概念硬塞进去。例如“社区卫生服务机构/社区以外其他定点医疗机构”被压入 `hosp_lv`，随后“社区”又被物化为“一级”。
2. 一段政策同时出现综合待遇和多个资金分项时，模型或编译器从整段上下文复制错误归属。例如综合报销 90% 被标成“统筹基金”，又因同段出现“大额医疗互助资金 80%”而被编译为大额互助比例。

这些问题不能只靠增加提示词解决。政策条件在 bjyb 中通常已经以机构主数据、基金分项、结算结果或代码字典的形式出现。系统应利用这些结构化数据回答三个问题：

- 这个政策概念是否已经有正式语义指标？
- 如果没有，bjyb 中是否存在可复用的物理字段？
- 数据库字段的实际值、代码说明和政策概念之间应如何形成标准值域与源值映射？

### 1.1 真实数据证据

2026-08-20 在当前工作区数据发现结果中确认：

| 物理字段 | 数据画像 | 对政策建模的意义 |
|---|---|---|
| `m_institution.H_TYPE` | 描述“机构类型”，非空率 100%，4 个 distinct 值 | “社区/非社区机构”应优先从机构类型建模，不应使用医院等级 |
| `m_institution.H_LEVEL` | 描述“医院等级”，非空率 100%，14 个 distinct 值 | 与机构类型是独立轴，不能互相折叠 |
| `yb_yd_jjfx.FUND_CODE` | 描述“基金款项代码”，7 个 observed 值，备注含代码释义 | 可作为基金归属代码证据 |
| `yb_yd_jjfx.PROVINCE_FUND_NAME` | 描述“基金款项名称”，7 个 observed 值 | 可辅助建立基金归属标准值域与代码映射 |
| `yb_jsqd_MAIN_PAY.UNITE_IN` | 医保统筹基金支付 | 统筹支付是独立资金分项 |
| `yb_jsqd_MAIN_PAY.LARGE_IN` | 大额互助资金支付 | 大额互助是独立资金分项 |
| `yb_jsqd_MAIN_PAY.SUPPLY_IN` | 退休人员补充医疗保险支付 | 综合报销可能包含多个资金来源 |

[来源: 当前工作区 `/api/v1/medical-insurance-ai-agent/semantic/discovery/results` 实时结果；扫描实现见 `src/runtime/discovery/sqlserver_source.py`]

### 1.2 已有能力与缺口

已有能力：

- SQL Server 数据发现已经采集字段名、表名、说明、备注、类型、非空率、distinct 数、样本值、高频值及部分数值统计。
- `DiscoveryStore` 已持久化扫描结果，避免每次政策分析直接扫业务库。
- `/semantic/field-match` 已提供 Milvus 向量匹配和文本降级入口。
- S1/S5 已能生成指标、值域或缺失维度候选，并进入统一人工审核队列。
- 语义注册表已有 `source_field`、`value_domain` 和源值映射能力。

当前缺口：

- 政策结构缺口产生后，不会自动查询已有指标和数据发现字段。
- `field-match` 当前对“医疗机构类别”“基金归属”返回空，`discovery_fields` 向量索引没有形成可靠的扫描后构建/刷新闭环。
- 字段匹配结果只有名称、表和相似度，缺少值域、非空率、字段角色、表用途和推荐理由。
- 数据库 observed 值、数据库文档值、政策原文值和语义标准值没有分层，容易把“出现过”误当成“合法全集”。
- 审核发布后，新增的政策检索维度仍可能被静态 Milvus schema 丢弃，无法用于结构化过滤。

---

## 2. 目标、成功标准与非目标

### 2.1 目标

1. 政策结构缺口自动获得 bjyb 候选字段和数据画像，不再只依赖模型猜测。
2. 优先复用已有语义指标；确需新增时，明确选择“数据库绑定字段”或“政策专用字段”。
3. 枚举字段基于真实 observed 值、字段文档和政策值共同形成可审核的标准值域与映射。
4. 数据库证据只增强决策，不覆盖政策原文，不自动发布。
5. 新增的 indexed 政策维度进入下一候选 release 的 Milvus scalar schema，并可被运行时结构化过滤。
6. 全链路保留政策证据、扫描批次、物理字段和值域映射来源，可重放、可审计、可回滚。

### 2.2 成功标准

- 对“机构类别”候选，系统把 `m_institution.H_TYPE` 排在 `H_LEVEL` 前，并明确两者语义不同。
- 对“基金归属”候选，系统优先识别基金款项代码/名称或支付分项，不把表示“险种类型”的 `FUND_TYPE` 误认成基金支付来源。
- 没有数据库匹配时，审核人可以发布 `policy_only` 指标；下游提取和政策检索仍可使用。
- 数据库字段只有代码、没有代码释义时，系统不得自动发布值域映射。
- 新字段通过审核后，只经“契约重建 → 受影响单元重提取 → 编译 → 候选 release 门禁 → 激活”生效，禁止直接修改活动 Milvus collection。
- `rule_69fc18433e6a7364` 与 `rule_63e89e926492ebd8` 能按机构类别区分；`rule_3222a148156d8c7d` 与 `rule_4df372b59673556e` 不再被压成同一种基金比例。

### 2.3 非目标

- 不从 5833 个数据库字段批量自动创建政策指标。
- 不把 bjyb 表结构当作政策本体的唯一来源。
- 不允许系统绕过人工审核自动发布字段或值域。
- 不在政策编译时实时连接 SQL Server；编译只读持久化的语义注册表和已审核契约。
- 不为本需求建设通用知识图谱、通用规则 DSL 或第二套提议平台。
- 不自动推断未知代码的业务含义；代码释义不完整时保留待审核状态。

---

## 3. 方案比较与选择

### 方案 A：政策缺口触发，bjyb 证据增强（采用）

S1 未知概念、S5 缺失维度候选或人工确认的结构错误先产生语义提议；系统随后匹配已有指标和 bjyb 字段，为同一提议追加数据证据，最后由人工选择复用、绑定、政策专用或驳回。

优点：问题驱动、噪音低；复用现有 S1/S5、DiscoveryStore、统一审核台和发布状态机；数据库证据与政策证据并列，不互相覆盖。

代价：需要补齐候选字段索引刷新、证据模型和审核页面的数据证据区。

### 方案 B：数据库扫描后批量反推政策字段（不采用）

每次数据发现扫描后，对所有 unmapped 字段自动生成政策指标提议。

优点：覆盖广。

缺点：当前 5833 个字段中 5789 个未映射，包含配置、日志、接口、历史表和患者级字段，会造成严重提议噪音；数据库字段存在不代表政策规则需要它。

### 方案 C：数据库严格绑定，没有字段就禁止新增（不采用）

只有找到 bjyb 字段和完整值域时，才允许新增政策字段。

优点：政策模型与业务数据模型一致性最强。

缺点：政策可能包含数据库尚未落地的资格、例外、时间和地域条件；严格绑定会再次丢失政策语义。该方案与用户确认的“数据库优先但非硬前提”边界冲突。

---

## 4. 核心设计原则

1. **政策原文是规则语义权威源**：数据库不能把“综合报销比例”改写成单一基金比例。
2. **bjyb 是结构证据源**：帮助发现字段、验证字段角色、统计 observed 值和建立源值映射。
3. **先找已有指标，再找物理字段**：防止同一业务概念重复建模。
4. **字段角色优先于字段名相似度**：`FUND_TYPE` 如果定义为险种类型，就不能因名字含 FUND 而匹配基金归属。
5. **observed 值不等于标准值域**：数据库现值、文档允许值、政策值和标准值必须分层保存。
6. **低证据不自动补全**：未知代码、零数据字段、配置表字段和跨场景字段只能作为弱证据。
7. **人工裁决后才发布**：匹配、排序和映射都只是建议。
8. **版本化生效**：字段和值域变更通过新契约和新 release 生效，活动版保持不可变。

---

## 5. 总体架构与数据流

```text
政策抽取未知概念 / S5 冲突诊断 / 人工确认结构错误
                         │
                         ▼
                 现有 SemanticProposal
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
    查已发布语义指标             查 DiscoveryStore
  名称/别名/定义/值域匹配      字段语义检索 + 数据画像
            │                         │
            └────────────┬────────────┘
                         ▼
               DatabaseEvidenceEnrichment
       候选字段 + 字段角色 + 值域证据 + 证据等级
                         │
                         ▼
                    统一审核台
       ┌─────────┬──────────┬──────────┬────────┐
       ▼         ▼          ▼          ▼        ▼
   复用指标   新建并绑定   政策专用   仅补映射  修抽取/驳回
       └─────────┴──────────┴──────────┴────────┘
                         │
                         ▼
       semantic_metrics / value_domains / mappings
                         │
                         ▼
       契约重建 → 受影响单元重提取 → 规范编译
                         │
                         ▼
       新候选 release → 质量/答案验证门禁 → 激活
```

### 5.1 处理时机

数据库证据增强在 proposal intake 之后、人工审核之前执行：

- 不阻塞 compiler 的 fail-closed 结论。
- 不改变 S1/S5 的确定性输入和幂等 fingerprint。
- 只读取最近一次成功 discovery snapshot，不在提议请求内重新全库扫描。
- 每次新扫描完成后，可异步刷新仍处于 `proposed/reviewing` 的候选证据。

### 5.2 复用边界

复用现有：

- `SemanticProposal` 与 `DimensionCandidateProposal`；
- `DiscoveryStore` 最新扫描结果；
- `/semantic/field-match` 的查询入口和 embedding provider；
- `semantic_metrics.source_field`、value domain 和 source value mapping；
- 统一审核队列、权限和提议生命周期。

新增的最小职责：

- 一个从提议构造检索查询并汇总数据库证据的服务；
- 一个可嵌入提议详情的数据库证据模型；
- 扫描完成后对 `discovery_fields` 索引的确定性 upsert/刷新；
- indexed 新维度进入 release Milvus schema 的契约。

---

## 6. 字段发现流程

### 6.1 输入

每次匹配必须携带以下上下文，而不是只传一个中文字段名：

| 输入 | 示例 |
|---|---|
| `concept` | 医疗机构类别、基金归属 |
| `definition` | 社区卫生服务机构与其他定点医疗机构的分类 |
| `metric_role` | dimension |
| `semantic_type` | Enum |
| `policy_values` | 社区卫生服务机构、非社区定点医疗机构 |
| `measure_core` | 支付比例、最高支付限额 |
| `policy_context` | 门诊、城镇职工、退休人员 |
| `evidence_excerpt` | 触发提议的精确政策片段 |

### 6.2 两级检索

#### 第一级：已发布语义指标

按指标名称、别名、定义、extraction hint、值域名称和标准值匹配。

命中后优先建议：

- 直接复用已有指标；
- 为政策原词补一条 source value mapping；
- 如果定义不一致，保留为候选但不得自动复用。

#### 第二级：数据发现字段

对 discovery 字段的以下文本生成检索文档：

```text
datasource + schema + table + field_name + description + remark
+ data_type + enum profile 摘要 + suggested_object
```

检索顺序：

1. 字段名、描述、备注和既有别名的精确/包含匹配；
2. `discovery_fields` 稠密向量相似检索；
3. Milvus 不可用时，从最新 DiscoveryStore snapshot 做文本降级；
4. 返回 top candidates 后执行字段角色、类型、场景和值域的确定性重排。

向量相似度只用于候选发现，不能证明语义相同。

### 6.3 `discovery_fields` 索引生命周期

每次成功扫描后，以以下复合身份 upsert：

```text
datasource_id + table_schema + table_name + field_name
```

索引记录必须带：

- `scan_task_id`、`scanned_at`、字段结构 fingerprint；
- 字段说明、备注、类型、表名和数据源；
- 非空率、distinct 数、是否枚举、质量等级；
- embedding model/version。

新扫描中消失或结构 fingerprint 变化的字段标记 stale；提议详情展示证据所属扫描批次。索引构建失败不影响 discovery 扫描结果落库，但字段匹配进入 degraded 状态并使用文本降级。

### 6.4 候选重排与证据等级

不使用一个不可解释的总分直接自动决策。相似度只负责排序，审核依据使用离散证据等级：

| 等级 | 条件 | 处理 |
|---|---|---|
| `strong` | 字段定义与政策概念角色一致；类型兼容；值域或代码说明可验证；数据非空；表场景匹配 | 默认推荐绑定，仍需人审 |
| `supporting` | 字段角色和类型基本一致，但值域释义不全、场景范围不同或样本较弱 | 展示为候选，要求补证据 |
| `weak` | 仅名称相似、零数据、配置/历史表、代码含义未知或跨业务场景 | 不推荐自动绑定 |
| `rejected` | 字段角色明确冲突，如“险种类型”匹配“基金支付来源” | 从推荐列表排除，保留拒绝原因 |

确定性重排因素：

- 字段业务定义与 metric role；
- 数据类型与 semantic type；
- 候选值和值域重合度；
- 数据完整性和扫描新鲜度；
- 表角色（主数据/字典/交易事实优先于配置/日志/历史备份）；
- 政策场景与数据表场景（门诊、住院、异地等）；
- 已有 source_field 使用情况。

---

## 7. 值域发现与映射

### 7.1 四层值域必须分开

| 层次 | 含义 | 是否可直接发布 |
|---|---|---|
| `policy_values` | 政策原文出现的概念，如“社区卫生服务机构” | 否，需归一化 |
| `observed_values` | 当前数据库实际出现的值，如 `01/02/03/05` | 否，只说明出现过 |
| `documented_values` | 字段备注、代码表或接口文档声明的允许值 | 可作为强证据，仍需审核 |
| `standard_values` | 语义层正式值域 | 是，审核发布后的唯一标准 |

源值映射负责连接前三层与标准值，不允许直接把 observed 值集合覆盖到正式值域。

### 7.2 枚举字段画像

对 `semantic_type=Enum` 候选展示：

- distinct 数、非空率、非空行数；
- observed values 与频次；
- 字段备注中解析出的代码释义；
- 同表明确的 code/name 成对字段；
- 与 policy values、已有 standard values 的对齐结果；
- 未映射值和一对多/多对一关系。

当 distinct 数较大时，只展示 top frequency 与总 distinct 数，不建议把所有值建成政策值域。人员、流水号、机构编码等高基数字段默认不是 Enum 值域候选。

### 7.3 代码—名称配对

只在以下任一证据成立时建议 code/name 映射：

- 字段备注明确列出代码与名称；
- 同一字典/分项表中存在明确的 `*_CODE` 与 `*_NAME` 配对列；
- 已发布语义字典已有相同映射。

仅凭两个字段同表、值数量相同，不推断它们一一对应。

### 7.4 粗粒度政策值与细粒度数据库值

政策值域可以比数据库值域更粗。例如数据库 `H_TYPE` 有 4 个机构类型，而当前政策只区分“社区”和“社区以外”。允许多个数据库源值映射到同一个政策标准值：

```text
H_TYPE=<社区代码>           → 社区卫生服务机构
H_TYPE=<其他多个机构代码>   → 非社区定点医疗机构
```

前提是每个代码含义已经由字典、备注或人工确认；未确认前不发布映射。

### 7.5 数值字段

Amount/Ratio 字段不把每个 observed 数值当作值域成员。数据库画像只用于验证：

- 字段角色和单位；
- 取值范围；
- 是否存在独立资金分项；
- 政策公式所需的输入字段是否存在。

政策比例和限额仍以政策原文及规范规则为准，不能由历史结算数据反推政策标准。

---

## 8. 数据模型

### 8.1 数据库字段引用

`DatabaseFieldRef`：

| 字段 | 说明 |
|---|---|
| `datasource_id` | 数据源标识 |
| `table_schema` | schema |
| `table_name` | 表名 |
| `field_name` | 字段名 |
| `source_field` | 三段式或兼容两段式寻址 |
| `scan_task_id` | 数据证据所属扫描批次 |
| `field_fingerprint` | 字段结构版本 |

### 8.2 字段画像证据

`DatabaseFieldEvidence`：

| 字段 | 说明 |
|---|---|
| `field_ref` | 物理字段引用 |
| `description/remark/data_type` | 字段元数据 |
| `non_null_rate/non_null_count/distinct_count` | 数据画像 |
| `observed_values` | 脱敏后的样本/枚举值 |
| `documented_values` | 从备注或代码表得到的声明值 |
| `value_mapping_candidates` | 建议源值映射 |
| `semantic_similarity` | 候选排序用相似度，不作为通过证明 |
| `match_reasons` | 可解释匹配理由 |
| `rejection_reasons` | 角色冲突、场景冲突等理由 |
| `evidence_grade` | strong/supporting/weak/rejected |
| `evidence_status` | available/degraded/unavailable/stale |

### 8.3 提议扩展

现有 `SemanticProposal`/`DimensionCandidateProposal` 增加：

- `database_evidence: list[DatabaseFieldEvidence]`；
- `recommended_metric_code`：复用已有指标时填写；
- `recommended_source_field`：建议绑定字段；
- `binding_mode`：`database_bound | policy_only | unresolved`；
- `evidence_refreshed_at`；
- `database_evidence_status`。

不新增第二套 proposal 表。数据库证据作为提议的版本化 supporting evidence 保存。

### 8.4 正式指标绑定状态

正式 `semantic_metrics` 明确记录：

- `database_bound`：存在可用 `source_field`；
- `policy_only`：没有业务数据字段，仅用于政策抽取、编译和检索；
- `derived`：由多个已绑定指标计算。

`source_field is null` 不再同时表示“遗漏绑定”和“刻意政策专用”。

---

## 9. 人工审核与状态流转

### 9.1 审核人可选结论

数据库证据区加入现有统一审核队列，不新增独立页面。审核人必须选择：

1. **复用已有指标**：政策原词映射到现有 metric/value domain。
2. **新增并绑定数据库字段**：创建政策指标，绑定确认后的 source field。
3. **新增政策专用字段**：`binding_mode=policy_only`，允许下游政策抽取和检索使用。
4. **仅新增值域/源值映射**：字段已存在，只补标准值或别名。
5. **拆分指标**：综合待遇与基金分项等 measure core 不同。
6. **修复抽取**：现有字段足够，错误来自范围、否定或证据绑定。
7. **证据不足/驳回**：不发布，保留理由。

### 9.2 审核页面信息

提议详情分为三块：

- 政策证据：原文、rule IDs、冲突值、抽取 snapshot、S1/S5 诊断。
- 数据证据：候选字段、说明、表用途、数据画像、值域对齐、证据等级和拒绝理由。
- 建模结论：复用/新增/政策专用/补映射/拆分/修抽取/驳回。

审核人选择数据库绑定时必须确认：

- 指标 code、名称、定义和 semantic type；
- source field；
- standard values；
- source value mappings；
- indexed 标志；
- 受影响政策单元。

### 9.3 生命周期与幂等

沿用提议状态：

```text
proposed → reviewing → accepted → published
                │           │
                └→ rejected └→ superseded/stale
```

同一 proposal 重复匹配只增加证据版本，不创建重复提议。新 discovery snapshot 改变候选字段或值域时，保留旧证据并更新 `evidence_refreshed_at`。

---

## 10. 发布与下游生效

### 10.1 发布动作

审核通过后按结论执行：

| 结论 | 落地 |
|---|---|
| 复用已有指标 | 增加原词/源值映射，不创建重复 metric |
| 新增并绑定 | 写入 `semantic_metrics`、value domain、source value mappings、binding mode |
| 政策专用 | 写入 `semantic_metrics`，`binding_mode=policy_only`、`source_field=null` |
| 仅补映射 | 更新 value domain/mappings |
| 修复抽取/拆指标 | 不直接新增字段，形成受治理的抽取或指标变更 |

### 10.2 提取契约

新 metric/value domain 发布后：

- 重建 `zcgz` 提取契约；
- 提取提示包含字段定义、值域、数据库别名和否定表达说明；
- 只重提取 proposal evidence 关联的受影响单元；
- 旧 extraction snapshot 保留审计，不覆盖。

### 10.3 编译与索引

规范编译必须保留新维度和精确 evidence excerpt。对于 `indexed=True` 的已发布 Enum 维度：

- 下一 release 的 rules collection schema 从已发布 indexed policy metrics 派生 scalar fields；
- 建立对应 scalar index；
- 非 indexed 或 policy-only 详情字段可以作为 dynamic detail 保存，但不得被静态白名单静默丢弃；
- `rule_type` 保留宽业务类别，规范 `subject` 和新增维度分别保存，避免比例语义再次塌缩。

发布路径固定为：

```text
proposal published
→ extraction contract version +1
→ affected units re-extracted
→ canonical compile
→ candidate full snapshot build
→ unit/API/flow + quality/answer-verification gates
→ human promote
```

禁止直接 update/upsert 活动 release 的单条 Milvus entity。

### 10.4 Runtime 数据映射

数据库绑定字段用于把结算上下文标准化成政策规则条件。例如机构编码先关联 `m_institution`，再把 `H_TYPE` 源值映射为政策标准值；结构化检索使用标准值过滤，而不是直接使用数据库原码。

政策专用字段没有业务数据绑定时：

- 可以用于政策知识浏览、文本问答和规则解释；
- 若某验证场景要求以结算单自动过滤该字段，返回 `not_evaluable/missing_context_mapping`，不得猜测。

---

## 11. 两组真实样例的目标结果

### 11.1 机构类别与医院等级

候选分析：

| 候选 | 结论 |
|---|---|
| `m_institution.H_TYPE` | `supporting`：字段角色、非空率和 distinct 数匹配；4 个代码的业务释义确认后可升级 strong |
| `m_institution.H_LEVEL` | rejected：它是医院等级，不是机构类别 |
| `COMM_STAT_CONFIG.HOSP_LEVEL` | weak/rejected：配置字段，表示报表可查询范围，不是患者就医机构事实 |

推荐建模：

```text
metric_code: zcgz.provider_category
name: 医疗机构类别
semantic_type: Enum
indexed: true
binding_mode: database_bound
source_field: <datasource>.m_institution.H_TYPE
standard_values:
  - 社区卫生服务机构
  - 非社区定点医疗机构
```

代码释义未确认前，不发布 `01/02/03/05` 到标准值的映射。

重提取目标：

| rule | provider_category | hosp_lv | ratio |
|---|---|---|---:|
| `rule_63e89e926492ebd8` | 社区卫生服务机构 | 空 | 0.90 |
| `rule_69fc18433e6a7364` | 非社区定点医疗机构 | 空 | 0.70 |

只有政策原文明示一级/二级/三级时才填写 `hosp_lv`；删除任何“社区→一级”的语义折叠。

### 11.2 基金归属与综合报销

候选分析：

| 候选 | 结论 |
|---|---|
| `yb_yd_jjfx.FUND_CODE + PROVINCE_FUND_NAME` | strong/supporting：代码与名称明确，适合 fund attribution 值域证据；仍需校验具体业务场景 |
| `yb_jsqd_MAIN_PAY.UNITE_IN/LARGE_IN/SUPPLY_IN` | supporting：证明资金分项独立，适合验证综合待遇由多个来源组成 |
| `yb_brdjxx.FUND_TYPE` | rejected：字段定义是险种类型，不是基金支付来源 |

现有已发布 `jjgs`（展示名“基金归属”）应优先复用，避免再创建重复 `fund_type` 指标；如后续统一英文 code，走受治理的指标变更和兼容别名，不在本需求中重复建轴。

目标规则：

| rule | subject | jjgs | ratio |
|---|---|---|---:|
| `rule_3222a148156d8c7d` | `large_medical_mutual_aid_payment_ratio` | 大额医疗互助资金 | 0.80 |
| `rule_4df372b59673556e` | `overall_reimbursement_ratio` | 空/不适用 | 0.90 |

`rule_4df...` 的90%含退休补充医疗保险，不能因为数据库存在统筹支付字段就改成统筹基金单项比例；数据库证据只用于支持“这是多资金来源综合结果”的判断。

---

## 12. API 与界面契约

### 12.1 API

优先扩展现有接口而不是新增平行 API：

- `POST /semantic/field-match`
  - 输入增加 metric role、semantic type、policy values 和 policy context；
  - 输出增加 field ref、数据画像、match reasons、rejection reasons、evidence grade/status。
- proposal detail/list 响应增加 database evidence 摘要；列表只返回最高等级候选和状态，详情返回完整画像。
- 增加 proposal 级“刷新数据库证据”动作，只读最新 DiscoveryStore snapshot；不触发全量数据库扫描。

扫描仍由现有 `/semantic/discovery/scan` 管理。证据刷新与全库扫描分离，避免审核请求成为重查询入口。

### 12.2 Portal

复用统一语义提议页面，在提议详情增加“数据证据”区域：

- 候选字段卡：表/字段、定义、数据类型、证据等级；
- 数据画像：非空率、distinct 数、样本/高频值；
- 值域对齐：政策值、数据库值、标准值、建议映射；
- 排除候选：展示为什么 `H_LEVEL` 或险种 `FUND_TYPE` 不适用；
- 建模结论选择器：复用、数据库绑定、政策专用、补映射、拆分、修抽取、驳回。

页面不得只展示一个黑盒相似度分数。

---

## 13. 异常、安全与性能

### 13.1 异常处理

| 异常 | 行为 |
|---|---|
| 无成功 discovery snapshot | proposal 正常生成，`database_evidence_status=unavailable`，允许 policy_only |
| Milvus discovery index 不可用 | 使用 DiscoveryStore 文本降级，标记 degraded |
| 候选字段零数据/低非空 | 证据降级为 weak，不自动推荐绑定 |
| 值域只有代码无释义 | 不生成正式映射，要求人工补证据 |
| 多个字段均为 strong | 展示竞争候选，禁止自动任选 |
| 扫描后字段消失或结构变化 | 证据标记 stale，已发布 binding 产生治理提醒 |
| 数据证据刷新失败 | 不改变原 proposal 状态，不影响 compiler fail-closed 结论 |

### 13.2 安全

- 数据发现和证据增强使用只读 SQL Server 账户。
- 默认只读取持久化聚合画像，不在审核请求中查询患者明细。
- 高基数、疑似患者标识、姓名、证件号、流水号字段不返回原始样本值，只返回计数和脱敏摘要。
- 所有 Portal 输出经过现有脱敏边界；日志不记录连接凭据和敏感样本。
- 提议发布沿用语义管理员权限和审计事件。

### 13.3 性能

- 全表 distinct/频率统计只在 discovery scan 执行，proposal enrichment 不重复扫描。
- 字段索引按 scan task 批量 upsert；查询只取 top candidates。
- 列表接口返回证据摘要，完整值域和样本只在详情加载。
- 新扫描完成后的 active proposal 刷新异步执行，失败可重试且幂等。

---

## 14. 测试与验收

本需求会改变政策 schema、值域、发布索引和运行时过滤，按 R4 处理。开发完成后严格按单元测试 → API 测试 → Flow 测试顺序验证，再执行 Portal 和性能验证。

### 14.1 T1 单元测试

- 字段检索：`H_TYPE` 对“机构类别”的排序高于 `H_LEVEL`。
- 角色冲突：描述为“险种类型”的 `FUND_TYPE` 不得匹配基金归属。
- 值域分层：observed values 不直接变成 standard values。
- 代码映射：没有代码释义时不产出可发布映射。
- policy-only：无字段匹配时可形成合法政策专用指标。
- 证据等级：strong/supporting/weak/rejected 判定稳定、可解释。
- 索引幂等：同 scan snapshot 重建不重复字段；字段 fingerprint 变化标 stale。
- 敏感字段：高基数字段不暴露样本。

### 14.2 T2a API 测试

- `field-match` 返回增强证据和降级状态。
- proposal list/detail 正确返回数据库证据摘要/详情。
- 数据证据刷新不触发 SQL Server 全量扫描。
- 审核七类结论的合法/非法状态流转。
- 未授权发布被拦截；只读匹配不产生注册表写入。

### 14.3 T2b Flow 测试

Flow A：

```text
69/63 规则冲突
→ S5 机构类别候选
→ H_TYPE 数据证据
→ 审核新增 provider_category
→ 重提取
→ 70%/90% 按机构类别分开
→ 新 release scalar filter 命中正确规则
```

Flow B：

```text
3222/4df 同段比例
→ 基金归属数据证据
→ 80% 保持大额互助分项
→ 90% 保持 overall reimbursement
→ compiler 不被兄弟规则原文污染
```

Flow C：

```text
政策出现 bjyb 无字段的新资格条件
→ 无数据库候选
→ 审核 policy_only
→ 契约与政策检索可用
→ 需要结算上下文自动过滤时返回 missing_context_mapping
```

### 14.4 Portal 与性能

- Vitest：候选字段、值域证据、排除理由、七类审核结论。
- TypeScript `tsc --noEmit` 与 Next.js build。
- Playwright：从维度候选查看数据证据、审核发布到新字段可见。
- 性能：5833 字段规模下 field match 和 proposal detail 满足既有 R4 响应门槛；Milvus 不可用时文本降级不超时。

### 14.5 业务验收条件

全部满足才算完成：

1. 数据发现页能定位 `m_institution.H_TYPE/H_LEVEL`，政策提议能解释两者差异。
2. 基金归属能展示 `FUND_CODE/PROVINCE_FUND_NAME` 及 observed 值，同时排除险种 `FUND_TYPE`。
3. 审核人可以选择数据库绑定或 policy-only。
4. 新 indexed 维度在候选 Milvus collection 中有字段和 scalar index。
5. 四条冻结规则按 §11 目标结构重提取并通过规范编译。
6. 发布质量门禁、答案验证门禁和活动版完整性检查全部通过。
7. 活动 collection 未被直接修改，旧规则和提议证据可追溯。

---

## 15. 分阶段落地边界

### MVU-1：数据库证据增强

复用最新 DiscoveryStore snapshot，补齐字段匹配、数据画像、证据等级和 proposal supporting evidence。成功标准：两个真实例子都能获得正确候选和排除理由。

### MVU-2：人工裁决与正式绑定

统一审核台支持数据库绑定、policy-only、仅补映射等结论，并正确写入 registry/value domain/mappings。成功标准：不自动发布，状态机和审计完整。

### MVU-3：契约、重提取与版本化索引

发布字段进入提取契约；受影响单元重提取；indexed 字段进入候选 rules collection 和 scalar index；经质量/答案验证门禁后激活。成功标准：四条冻结规则达到 §11 的目标结构和检索结果。

三个 MVU 可独立验证和回滚；MVU-1 不改变政策运行时，MVU-2 不直接改 Milvus，MVU-3 只生成新 release。

---

## 16. 最终决策清单

- [决策] 采用“政策缺口触发 + bjyb 数据证据增强”，不做数据库字段批量反推。
- [决策] bjyb 优先但非硬前提，允许明确标记的 policy-only 指标。
- [决策] 数据库匹配先查已有语义指标，再查物理字段。
- [决策] observed/documented/policy/standard 四层值域分开。
- [决策] 字段相似度只排序，不自动证明语义一致。
- [决策] 复用现有 proposal、value domain、mapping 和统一审核台，不新建平行治理系统。
- [决策] 复用现有 `jjgs`，不重复创建 fund_type 轴。
- [决策] 新 indexed 政策维度必须进入版本化 Milvus scalar schema。
- [决策] 所有生效动作通过新 extraction contract 与新 release，禁止直接修补活动 collection。
- [决策] 数据证据不可覆盖政策原文；综合待遇与资金分项必须分别建模。

本文没有待定占位项。进入实施前，用户需书面确认本设计；确认后再编写分任务、分验证层级的实施计划。
