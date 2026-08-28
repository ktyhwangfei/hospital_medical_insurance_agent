# 单院门诊医保智能助手与智能问数设计

日期：2026-08-27  
状态：对话设计已确认，待书面复核与实施计划  
目标用户：医院医保办经办与运营人员  
首期范围：一家医院、门诊业务、结算交易与费用明细、1～5 分钟近实时

## 1. 决策摘要

1. 当前“政策问答”升级为统一的“医保智能助手”，但政策咨询、单次门诊结算核验、门诊运营问数保持三条隔离执行链路。
2. 页面不再要求用户填写结算 ID。用户按患者和就诊时间表达，系统通过可信身份与 HIS 页面上下文定位就诊，再在后台解析内部结算锚点。
3. 门诊单次结算解释以 `ktyhwangfei/issue-20` 已确认的 `mzsettlement_verify_skill + mzjyxx` 为唯一基线，不扩展住院 `settlement_explain_skill`，也不新增第二个门诊解释 Skill。
4. `mzjyxx` 统一承载门诊单次核验和运营问数的业务语义，避免两套总费用、基金支付和个人支付口径。
5. 大模型只负责意图理解、上下文补全和结果解释；指标校验、权限、查询计划、SQL 编译、金额勾稽和结果验证全部使用确定性程序。
6. 一期不建设自由 NL2SQL、多 Agent 群、Kafka 或分布式 OLAP。优先复用现有 Semantic Registry、PostgreSQL、Redis、Gateway、Security、ModelGateway 和任务闭环。
7. 生产上线门槛为：发布能力范围内最终结果准确率不低于 95%，可信问题结果 100%，权限及高风险动作拦截 100%。语义不唯一时澄清，不猜测执行。

## 2. 背景与现状

当前项目已具备政策问答、政策知识检索、费用解释 Skill、Semantic Registry、模型网关、适配器、安全与审计等基础，但现有主业务入口仍以结算 ID 为前置条件，页面和运行时主要围绕住院结算解释设计。

现有关键限制：

- `PolicyQARequest`要求`settlement_id`，`/policy-qa/stream`会拒绝无结算 ID 的请求；
- 页面上下文使用进程内全局“当前上下文”，不能满足多用户、多会话和患者切换隔离；
- 当前`MetricDataQueryService`主要解决单笔上下文的指标字段取值，不是运营聚合查询引擎；
- Semantic Registry已有草稿、已发布版本、值域和快照能力，但`mzjyxx`查询模型尚未形成完整的数据集、键、字段、关系和质量规则；
- `settlement_explain_skill`及其固定 SQL、模板和政策查询面向住院，不适用于门诊；
- 扫码或院内 SSO 的具体协议尚未确定，但医院能够定位真实用户身份。

## 3. 目标与非目标

### 3.1 目标

1. 医保办人员在一个入口中咨询政策、核验单次门诊结算和查询门诊运营指标。
2. 用户使用自然语言和就诊时间表达，不需要了解结算系统内部 ID。
3. 门诊结算数据与费用明细在源数据变化后 1～5 分钟内可查询。
4. 首期支持受控指标、维度、时间、筛选、趋势、排序、TopN 和固定下钻。
5. 单次门诊核验使用实际结算数据和有效政策双证据，输出勾稽、异常、不确定性和下一步建议。
6. 所有结果可追溯到数据批次、语义版本、指标口径和政策证据。
7. 权限过滤在查询执行前完成，患者数据按角色、数据范围和字段权限控制。

### 3.2 非目标

- 不执行正式结算、退费、冲正、补报、备案或业务数据修改；
- 不替代医保经办系统判责；
- 不支持任意物理表 NL2SQL；
- 不允许模型决定 JOIN、物理字段、SQL 或金额公式；
- 不自动认定违规、欺诈骗保或因果关系；
- 不进行无风险校正的医生绩效排名；
- 不开放门诊明细批量导出；
- 不在一期建设分布式流平台、OLAP 集群或多 Agent 编排集群；
- 不恢复已退役的`/settlement`、`/dashboard`、`/chat`等业务入口。

## 4. 产品定位与成熟产品对齐

本设计采用当前成熟智能问数产品的共同模式：聚焦业务域、语义模型约束、可信问题、可见的查询理解、评测与人工治理。

- Power BI 使用 AI Data Schema 缩小模型可见范围，并以 Verified Answers 提高稳定性；
- Looker建议按具体业务域建立专用 Explore/Agent，隐藏技术字段并集中定义指标；
- Snowflake Cortex Analyst使用 Verified Query Repository和自动评测；
- Databricks Genie强调可信查询、基准问题、运行监控和人工反馈审核；
- Tableau强调清洁、已建模、受权限约束的数据，而不是让模型直接理解原始表。

本项目在医疗数据安全上采用更严格边界：模型不生成可执行物理 SQL，患者明细下钻重新鉴权，语义或证据不足时失败关闭。

参考：

- <https://learn.microsoft.com/en-us/power-bi/create-reports/copilot-prepare-data-ai-faq>
- <https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-best-practices>
- <https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst/verified-query-repository>
- <https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst-evaluations>
- <https://docs.databricks.com/aws/genie/best-practices>

## 5. 总体架构

```text
医保智能助手
  + 可信用户身份
  + HIS 页面上下文
  + 自然语言问题
        ↓
意图与上下文解析
  ├── policy_consultation
  ├── outpatient_settlement_verification
  ├── outpatient_operational_query
  └── unsupported
        ↓
三条隔离执行链路
  ├── 政策知识检索
  ├── mzsettlement_verify_skill
  │     └── mzjyxx 已发布查询模型
  │           ├── mz_trade
  │           └── mz_fee_item
  └── SemanticQueryService
        └── mzjyxx 已发布查询模型
        ↓
权限、质量、结果验证、脱敏、审计
        ↓
统一结构化结果与分析工作区
```

外部 HIS、医保和认证系统一律通过`adapters/`或 Gateway 防腐边界接入。所有模型调用通过`model_service/gateway`。政策咨询不读取患者上下文。

## 6. 用户流程

### 6.1 政策咨询

用户：

> 职工医保普通门诊起付线是多少？

系统不要求患者或结算信息，检索有效政策并返回适用地区、人员类别、医疗类别、生效时间、政策引用和不确定性。缺少决定政策适用性的条件时再澄清。

### 6.2 单次门诊结算核验

用户：

> 看一下这个患者今天上午那次门诊为什么个人支付这么多。

执行：

```text
可信登录身份 + HIS 当前患者 + “今天上午门诊”
  → 查询门诊就诊索引
  → 唯一匹配：取得 encounter_id
  → 解析内部 settlement_id
  → settlement_id 映射 mz_trade.T_TradeNo
  → 调用 mzsettlement_verify_skill
```

匹配多次就诊时让用户选择；无记录时要求补充时间；用户无权访问时直接拒绝。结算 ID 只在后端作为 Skill 锚点存在，不在页面必填。

### 6.3 门诊运营问数

用户：

> 本月各科室医保门诊人次、总费用和统筹基金支付金额，按基金支付金额降序。

系统展示实际理解的指标、时间口径、范围、分组和排序，执行受控语义查询，返回指标卡、图表、表格、数据更新时间、指标口径和下钻入口。

### 6.4 多轮追问

```text
本月各科室门诊次均费用
→ 只看职工医保
→ 和上月比较
→ 下钻心内科
```

每轮都显示继承后的完整条件。切换患者时旧患者上下文失效并新建或明确切换会话。

## 7. 产品界面

当前单列政策问答页面升级为桌面端双栏分析工作台：

```text
┌────────────────────────────────────────────────────────────┐
│ 医保智能助手        身份 · 权限范围 · 数据更新时间          │
├──────────────────┬─────────────────────────────────────────┤
│ 对话区            │ 分析工作区                              │
│ 用户问题          │ 查询理解                                │
│ 系统澄清          │ 指标卡 / 图表 / 表格                    │
│ 后续追问          │ 下钻结果                                │
│ 输入框            │ 口径 / 来源 / 警告 / 不确定性           │
└──────────────────┴─────────────────────────────────────────┘
```

- 初始状态使用统一问题输入框和政策、结算核验、运营问数三类示例；
- 首次生成分析结果后切换为左侧对话、右侧分析结果；
- 小屏幕降级为对话与结果页签；
- 顶部展示已验证用户、医院、权限范围和数据水位；
- HIS上下文存在时展示可移除的患者、科室和就诊时间标签；
- 查询理解卡允许修改日期、科室、险种等结构化条件；
- 图表类型由确定性规则选择，不让模型任意生成前端代码；
- 现有`/policy-qa`路径可暂时保留，产品名称先升级，稳定后再增加`/assistant`别名。

## 8. 门诊时间口径

使用双时间语义，不建立模糊的统一“时间”：

- 就诊时间：患者定位、门诊业务量和就诊费用分析；
- 结算时间：结算笔数、基金支付和结算运营分析。

示例：

| 问题 | 默认时间口径 |
|---|---|
| 今天各科室门诊医保人次 | 就诊时间 |
| 今天完成多少笔医保结算 | 结算时间 |
| 今天统筹基金支付多少 | 结算时间 |
| 这个患者上午那次门诊费用 | 就诊时间 |

每次结果都显示采用的时间角色、起止时间和时区。系统不得静默切换时间口径。

## 9. `mzsettlement_verify_skill`与`mzjyxx`

### 9.1 既有设计基线

本规格继承`ktyhwangfei/issue-20`中的：

- `docs/superpowers/specs/2026-08-26-mzsettlement-verify-skill-design.md`；
- `docs/superpowers/plans/2026-08-26-mzsettlement-verify-skill.md`；
- `docs/superpowers/specs/2026-08-25-semantic-query-planner-design.md`。

Issue 20目前提供设计和实施计划；代码实现尚未并入当前主分支，因此实施时需按计划落地，不能假定能力已经可运行。

### 9.2 唯一门诊结算解释能力

```text
settlement_explain_skill
→ 仅负责现有住院结算费用解释

mzsettlement_verify_skill
→ 唯一门诊结算结果核验与解释 Skill
```

两者共享平台能力，不共享住院固定 SQL、住院政策查询、住院模板或缺失字段默认值。

### 9.3 门诊查询模型

复用`mzjyxx`业务对象：

| 数据集 | 候选来源 | 行粒度 | 用途 |
|---|---|---|---|
| `mz_trade` | `o_Trade` | 一次门诊交易 | 结算汇总、待遇上下文、累计和交易状态 |
| `mz_fee_item` | `o_FeeItem` | 一次交易下一个费用项目 | 项目级医保内外、先自付和超限价解释 |

`o_Trade/o_FeeItem`是院内抽取源候选，`mz_trade/mz_fee_item`是发布给运行时的语义数据集代码。正式运行只保留一条数据路径：

```text
o_Trade / o_FeeItem
→ 只读增量适配器
→ PostgreSQL 门诊交易与费用明细事实
→ mz_trade / mz_fee_item 已发布语义绑定
```

P0可以直接查询源库完成字段画像和口径验证；P1以后助手不同时保留“直查源库”和“查分析库”两条隐式运行路径。

锚点与关系候选：

```text
settlement_id → mz_trade.T_TradeNo
mz_trade 主键 → T_TradeNo
mz_fee_item 主键 → T_TradeNo + ItemId + ItemNo
mz_trade.T_TradeNo 1 → N mz_fee_item.T_TradeNo
```

候选键必须用真实只读数据验证非空、唯一和基数。任一关系歧义、重复键或退费红冲重复汇总都阻断发布。

若`o_FeeItem.FeeIn/FeeOut`不能通过真实金额勾稽证明口径，则切换到释义更明确的`yb_mzfymx_mz`；不得同时接入两张口径相近的费用事实表后直接相加。

### 9.4 九个门诊核验 Profile

1. 整体结算核验；
2. 个人负担解释；
3. 支付渠道核验；
4. 起付线与年度累计；
5. 报销比例与封顶；
6. 医保目录与费用明细；
7. 身份与特殊待遇；
8. 异地与机构待遇；
9. 交易状态与退费。

场景按用户任务组织，不按数据库字段逐项建立。办理备案类问题路由到导办能力；退费、冲正等请求转高风险人工确认；住院问题不得误入门诊Skill。

## 10. 门诊字段与语义模型

### 10.1 核心交易与状态

- `T_SetTid`、`T_TradeNo`、`T_TradeDate`、`T_State`；
- `T_HasRefundmented`、`T_PartialReturnFlag`；
- `T_OraginalTradeNo`、`T_OraginalTradeDate`；
- `NP_Settle_State`、`SETL_DATE`、`NT_ReTradeFlag`。

### 10.2 待遇身份与政策匹配

- `P_FundType`、`PN_PersonType`、`T_CureType`、`P_JCLevel`、`P_HospFlag`；
- `PN_OutTransaction`、`PN_NationFundType`；
- `PN_ChronicFlag`、`PN_ChronicCode`、`PN_IsChronicHosp`；
- `P_Official`、`P_retirementflag`、`P_CivilFlag`、`P_CivilType`；
- `RETIRE_OFFICER_FLAG`、`T_GFBelongFlag`、`T_CompHospFlag`、`T_SpSetlFlag`；
- `T_pneno`、`NT_AllSelfPayFlag`、`PN_NoRightReason`。

### 10.3 当次费用与支付

- `T_FeeAll`、`T_FeeIn`、`T_FeeOut`；
- `T_FirstPay`、`T_SelfPay1`、`T_SelfPay2`、`T_SelfPayAll`；
- `T_BigPay`、`T_BigSelfPay`、`T_BeyondBig`；
- `T_FundPay`、`T_PersonCountPay`、`T_CashPay`；
- `PN_PersonCount`、`T_PersonCountAfter`；
- `T_BCPay`、`T_JCPay`、`T_OfficalPay`、`T_BigillPay`；
- `NT_BasicPay`、`NT_CivilPay`、`NT_OtherPay`、`NT_AgencySumPay`；
- `RETIRE_OFFICER_PAY`、`NT_OUT2_SCALE`、`NT_OUT2_PRICE`。

基础金额和支付总额为核心字段；专项支付按资格和场景条件必需。未经口径确认不得把总额与分项重复相加。

### 10.4 年度累计、起付和封顶

- `TB_FeeIn`、`TA_FeeIn`；
- `TB_BigPay`、`TA_BigPay`；
- `TB_FeeAfterBig`、`TA_FeeAfterBig`；
- `TB_MZTimes`、`TA_MZTimes`；
- `TB_BeyondFeeIn`、`TA_BeyondFeeIn`；
- 大病、民政及居民一级医院等交易前后累计字段。

所有`TB_*`与`TA_*`字段必须先确认交易前、交易后含义和增量关系。现有`TA_MZTimes`释义与物理类型冲突时禁止发布。

### 10.5 费用明细

- 关联键：`T_TradeNo`、`ItemId`、`ItemNo`；
- 项目信息：`ItemCode`、`StandardCode`、`ItemName`、`ItemType`、`FeeType`、`F_LEVEL`；
- 金额数量：`Count`、`UnitPrice`、`Fee`、`FeeIn`、`FeeOut`、`SelfPay2`；
- 自付原因：`FEE_SP_SCALE`、`FEE_MEDIC_L`、`MEDIC_L`、`SPEDRUG_FLAG`；
- 状态：`State`。

姓名、身份证号、卡号、出生日期和处方号不进入公开Skill结果。

### 10.6 字段四态

所有金额和待遇字段统一表达：

```text
non_zero        数据源明确返回非零值
reported_zero   数据源明确返回 0
missing         数据源未返回或关联缺失
not_applicable  资格事实与政策证据共同证明不适用
```

`reported_zero`不能解释为无资格，`not_applicable`不能仅由零金额推断。禁止`null → 0`。

## 11. 一期运营指标与维度

### 11.1 首个闭环指标

1. 门诊医保就诊人次；
2. 门诊有效结算笔数；
3. 门诊总费用；
4. 门诊统筹基金支付金额；
5. 门诊个人支付金额；
6. 门诊次均费用。

### 11.2 首个闭环维度

- 时间；
- 科室；
- 门诊业务类别；
- 险种；
- 结算状态。

### 11.3 后续指标

在首个闭环通过后再增加个人账户、现金支付、医保内外、费用类别、次均基金支付、个人负担占比和结算明细差额等指标，总数控制在约20个，不为凑数量发布口径不稳定的指标。

### 11.4 指标治理字段

每个指标必须配置：中文名称、同义词、业务定义、公式、聚合方式、单位、精度、兼容维度、默认时间角色、数据来源、刷新频率、权限等级、负责人、审核人和已发布版本。

“报销比例”不直接作为模糊指标名称，应发布为明确的“统筹基金支付占总费用比例”等业务口径。

## 12. 受控语义查询

### 12.1 查询契约

```text
SemanticQuery
  metrics
  dimensions
  time_role
  time_range
  filters
  order_by
  limit
  semantic_version
```

示例：

```json
{
  "metrics": [
    "mzjyxx.insured_encounter_count",
    "mzjyxx.pooling_fund_payment"
  ],
  "dimensions": ["organization.department"],
  "time_role": "settlement_time",
  "time_range": {
    "start": "2026-08-01T00:00:00+08:00",
    "end": "2026-09-01T00:00:00+08:00"
  },
  "filters": [],
  "order_by": [
    {
      "metric": "mzjyxx.pooling_fund_payment",
      "direction": "desc"
    }
  ],
  "limit": 50,
  "semantic_version": "1"
}
```

契约中禁止出现物理表名、物理字段名、SQL、任意JOIN表达式和未发布公式。

### 12.2 查询服务

```text
SemanticQueryService
  validate()
  authorize()
  compile()
  execute()
  verify()
```

服务只接受结构化`SemanticQuery`，不接受自然语言。LLM生成候选意图后必须通过Registry、权限、范围、粒度和数据质量校验。

现有`MetricDataQueryService`继续服务已有单笔取值，不扩展为聚合查询引擎。

### 12.3 固定下钻

```text
全院门诊
→ 科室
→ 门诊就诊记录
→ 单次门诊结算
→ 费用类别
→ 费用项目明细
```

每次进入患者级或费用明细级数据都重新鉴权。

## 13. 单次结算确定性核验

所有金额使用`Decimal`并按人民币分舍入，默认允许0.01元舍入差。

在字段完整、口径确认时执行：

```text
总费用 = 医保内费用 + 医保外费用
总费用 = 基金支付总额 + 个人支付总额
个人支付总额 = 个人账户支付 + 现金支付
交易后累计 - 交易前累计 = 本次累计增量
```

个人自付一、个人自付二、起付、大额、专项补助等组合关系只有在字段定义和适用政策共同证明时执行。比例核验还要求险种、人群、医疗类别、机构等级、异地/慢特病、交易日期和有效政策完整。

数据证明“系统实际如何结算”；政策证明“该条件下应如何处理”。缺政策时只解释实际金额，不能判断待遇是否正确。

## 14. 可信问题库与Agent治理

### 14.1 可信问题库

每条可信问题保存：标准问题、同义表达、适用角色、指标、维度、时间口径、筛选、查询计划、允许下钻、预期结果特征、审核人和版本。

一期建设50～100个高频问题。生产运行优先匹配可信问题，长尾问题再走受控语义生成。

### 14.2 Agent职责

Agent可以：

- 推荐源字段与标准概念的映射；
- 生成字段说明、指标同义词和示例问题；
- 发现重复指标和异常数据模式；
- 推荐可信问题候选；
- 汇总失败问题并提出治理建议。

Agent不能：

- 修改源数据；
- 自动发布指标；
- 自动改变公式；
- 自动修复金额；
- 根据字段名猜测后直接投入生产；
- 将差评直接转化为生产规则。

一期只需要一个治理助手配合确定性服务，不建设多Agent群。

### 14.3 发布流程

```text
草稿
→ Agent建议
→ 数据工程校验
→ 医保业务审核
→ 自动回归
→ 发布新版本
→ 影子运行
→ 正式生效
```

发布失败继续使用上一已发布版本。

## 15. 数据加工与近实时

### 15.1 数据流

```text
门诊源数据
→ 只读适配器
→ 每分钟增量读取
→ 暂存与标准化
→ 主键、状态和金额校验
→ 幂等合并
→ 刷新必要日汇总
→ 标记批次 published
→ 更新公开数据水位
```

默认每分钟执行，水位重叠10分钟，通过业务主键与版本幂等合并。只有源系统缺可靠更新时间、无法识别删除/冲正或压测不达标时才引入CDC。

### 15.2 一致性

查询只读取`published`批次。`mz_trade`与`mz_fee_item`使用同一公开水位，不能暴露只更新一半的批次。

数据源失败或质量阻断时保留上一稳定批次并明确显示水位和警告；严重延迟的实时问题不输出确定性结论。

### 15.3 四层数据质量

1. 结构质量：主键、必填、类型、时间、枚举；
2. 业务质量：金额、状态转换、结算时间和待遇字段；
3. 跨表质量：交易与明细关联、金额勾稽、退费冲正；
4. 语义质量：指标基准、查询回归、重复汇总和权限范围。

任何可能造成金额放大的重复键、关系歧义或多事实原始行直接JOIN都属于阻断错误。

## 16. 容量、存储与性能

### 16.1 规划基线

按一家三级医院门诊保守规划：

| 项目 | 基线 | 峰值预留 |
|---|---:|---:|
| 门诊就诊 | 8,000次/日 | 15,000次/日 |
| 有效结算 | 8,000笔/日 | 15,000笔/日 |
| 费用明细 | 12万条/日 | 30万条/日 |
| 活跃医保办用户 | 20人 | 50人 |
| 同时查询用户 | 10人 | 30人 |
| 查询峰值 | 约2 QPS | 约5 QPS |

按12万条明细/日计算，每年约4380万条，三年约1.31亿条。

### 16.2 存储决策

- 一期使用现有PostgreSQL；
- 门诊交易和费用明细按月份分区；
- 费用明细在线保存三年；
- 三年以上进入历史存储，但保留日月汇总；
- 建立一张“日期×科室×门诊类别×险种”的日汇总；
- Redis只缓存汇总结果，缓存键包含语义版本、数据水位和有效权限范围；
- 一期不缓存患者级明细。

只有合理分区、索引和汇总后仍无法满足目标，或明细持续超过3亿、并发持续超过50个分析查询时，才评估ClickHouse或Doris。

### 16.3 建议性能目标

| 指标 | 目标 |
|---|---|
| 数据刷新 | 正常≤2分钟，P95≤5分钟 |
| 首个SSE事件 | ≤1秒 |
| 可信问题 | P95≤3秒 |
| 普通汇总 | P95≤5秒 |
| 就诊下钻 | P95≤8秒 |
| 单次查询超时 | 15秒 |
| 页面最大结果 | 500行 |

只读查询账号、只读事务、参数化SQL、`statement_timeout`、行数限制和连接池限制为强制要求。

## 17. 身份、权限和安全

### 17.1 身份

扫码或院内SSO最终通过后端换取可信身份并生成：

```text
AuthenticatedPrincipal
  user_id
  tenant_id
  hospital_id
  department_id
  roles
  permissions
  data_scope
  authenticated_at
  expires_at
```

身份、角色和权限不能由请求体或未经验证的`X-User-Id`、`X-Role`头声明。生产环境没有有效身份时返回401，不使用`demo`或默认角色。

### 17.2 权限模型

- 功能权限控制能使用的能力；
- 数据范围控制可读取的医院、科室、险种和患者记录；
- 字段权限控制汇总、脱敏就诊、患者身份和费用明细。

建议权限：

```text
assistant:policy:ask
assistant:encounter:explain
analytics:summary:read
analytics:encounter:read
analytics:fee_detail:read
analytics:query:drill
analytics:export
```

一期默认不开通`analytics:export`。技术治理权限不自动获得患者明细权限。

### 17.3 页面上下文

上下文按`tenant_id + user_id + session_id`隔离并设置有效期。患者切换、退出登录、权限变化或会话过期使旧上下文失效。禁止生产链路使用全局`current_context()`。

### 17.4 数据最小化和脱敏

```text
原始数据
→ 权限过滤
→ 只提取当前问题需要的字段
→ 输入模型前最小化/脱敏
→ 模型解释
→ 输出前再次脱敏
```

运营聚合不向模型发送患者身份。政策咨询不读取患者数据。

### 17.5 高风险动作

退费、冲正、撤销、修改费用、修改病案和正式结算不执行；如未来创建协同任务，状态必须为`waiting_human_confirmation`，由有权限人员在正式业务系统处理。

## 18. API与事件契约

### 18.1 统一助手入口

```http
POST /api/v1/medical-insurance-ai-agent/assistant/stream
```

请求：

```json
{
  "question": "本月各科室医保门诊人次和基金支付金额",
  "session_id": "sess_xxx",
  "context_id": "ctx_xxx"
}
```

用户身份、角色、患者和结算ID不由请求体声明。

### 18.2 结构化重查

```http
POST /api/v1/medical-insurance-ai-agent/analytics/query
```

筛选修改和固定下钻直接提交语义查询，不再次调用大模型，但每次重新鉴权。

### 18.3 SSE事件

```text
start
intent
context_need
step
query_plan
result
error
done
```

`done`始终发送，终止原因包括：

- `verified`；
- `clarification_required`；
- `unsupported`；
- `permission_denied`；
- `data_unavailable`；
- `quality_blocked`；
- `non_retryable_error`。

### 18.4 结果类型

```text
AssistantResult
├── PolicyAnswerResult
├── OutpatientSettlementVerificationResult
└── MetricQueryResult
```

门诊核验结果继承Issue 20契约：

```text
status
scenario_id
summary
context_checks[]
amount_checks[]
field_explanations[]
anomalies[]
citations[]
uncertainties[]
next_actions[]
```

旧`/policy-qa/stream`兼容保留；新功能不继续堆入旧`PolicyQARequest`。

## 19. 准确性与评测

### 19.1 三套资产

1. 生产可信问题库；
2. 不进入提示词的隐藏验收集；
3. 越权、注入、上下文污染和高风险动作安全对抗集。

一期隐藏验收集至少200题，覆盖指标、时间、筛选、粒度、多轮、患者定位、歧义、超范围、权限和数据质量。

### 19.2 评测维度

- 意图分类；
- 指标和业务口径；
- 时间范围和时间角色；
- 筛选与分组；
- 最终数值与记录集合；
- 澄清和拒答；
- 来源、不确定性和数据水位；
- 权限、脱敏和高风险动作。

不以SQL字符串相同作为正确标准，以业务结果和安全行为为准。

### 19.3 上线门槛

- 最终业务结果正确率≥95%；
- 可信问题结果正确率100%；
- 权限与高风险动作拦截100%；
- 数据来源和更新时间展示100%；
- 歧义正确澄清率≥95%；
- 超范围正确拒答率≥95%；
- 安全对抗集100%通过。

### 19.4 门诊黄金案例

继承Issue 20门诊结算图片黄金案例，覆盖所有非零与零值，并验证：

- 总费用双向勾稽；
- 个人账户与现金；
- 有证据时复算比例；
- 缺单位补充政策时不伪造公式；
- 每个显示字段都有解释或明确不确定性。

## 20. 错误处理与降级

| 情况 | 结果 |
|---|---|
| 就诊时间匹配多次门诊 | `clarification_required` |
| 无权访问患者或科室 | `permission_denied` |
| 结算锚点不存在 | `unavailable` |
| 一个锚点命中多个有效交易 | `unavailable`，质量阻断 |
| 明细重复或关系歧义 | `unavailable`，质量阻断 |
| 缺可选专项字段 | `partial` |
| 缺政策证据 | `partial`，只解释实际支付 |
| 数据源瞬时故障 | 有界恢复一次 |
| 恢复后仍失败 | `unavailable` |
| 用户要求退费或冲正 | `waiting_human_confirmation`，不执行 |
| 数据严重延迟 | 停止实时确定性结论 |

系统不回退示例假数据，不让模型自行修正公式或忽略质量错误。

## 21. 实施分期

### P0：口径与契约

- 复核Issue 20字段画像和值域；
- 验证`o_Trade/o_FeeItem`键、基数和金额口径；
- 确认首批5个可确定指标、5类维度和50个验收问题；门诊医保就诊人次保持 unavailable；
- 冻结身份、上下文和数据接入契约。

完成标志：医保办和数据负责人确认口径，候选数据集通过只读画像。

### P1：近实时数据与查询模型

- 真实门诊适配器；
- 每分钟增量、水位重叠和幂等合并；
- `mz_trade/mz_fee_item`数据集、键、字段、关系和质量规则；
- 发布`mzjyxx`可查询版本。

完成标志：`mzjyxx.queryable=true`，数据延迟和金额核对通过。

### P2：门诊结算核验

- 按Issue 20实施`mzsettlement_verify_skill`九个Profile；
- `Decimal`勾稽和字段四态；
- 政策双证据；
- 黄金案例和回归矩阵。

完成标志：单次门诊核验API稳定返回complete/partial/unavailable。

### P3：运营语义问数

- SemanticQuery DSL；
- Registry校验、确定性Planner和参数化编译；
- 首批5个可确定指标、5类维度、可信问题库；
- 科室到就诊的固定下钻。

完成标志：首个运营问数用户故事可通过API自动验收。

### P4：统一助手与分析工作台

- `/assistant/stream`意图路由；
- 就诊时间定位与可信上下文；
- 双栏页面、查询理解、图表、表格、下钻和反馈；
- 移除前端结算ID必填。

完成标志：政策、门诊核验和运营问数在同一入口完成端到端验收。

### P5：上线加固

- 扫码/SSO正式接入；
- 行级和字段级权限；
- 审计、影子运行、回归、监控和回滚；
- 性能和安全对抗验证。

完成标志：全部准确性、安全性、时效和审计门槛通过。

## 22. 首个最小可验证用户故事

> 医保办人员登录后，询问“本月各科室医保门诊人次、总费用和统筹基金支付金额”。系统使用已发布`mzjyxx`语义模型，按明确时间口径和用户数据范围返回可信结果，并支持从科室下钻到有权限查看的门诊就诊记录。随后用户询问某患者当天某次门诊“为什么个人支付这么多”，系统按就诊时间定位内部结算锚点，调用`mzsettlement_verify_skill`完成金额勾稽和政策解释；用户全程不需要输入结算ID。

## 23. 最终验收标准

1. 页面没有结算ID必填项，用户可按就诊时间定位单次门诊；
2. 政策、门诊核验和运营问数共用入口但执行链路隔离；
3. `mzsettlement_verify_skill`是唯一门诊结算解释Skill；
4. `mzjyxx`同时服务单次核验和运营问数，查询模型已发布可运行；
5. 首批5个可确定指标和5类维度口径经过确认，门诊医保就诊人次未被交易笔数替代；
6. 源数据变化后1～5分钟可查询；
7. 金额计算不因交易与明细关联重复；
8. 零值、缺失和不适用明确区分；
9. 可信问题100%正确，隐藏验收集最终结果准确率≥95%；
10. 越权、高风险动作、提示词注入和上下文污染100%拦截；
11. 所有结果包含数据来源、语义版本、数据水位、政策引用或不确定性；
12. 生产身份来自可信认证，不信任客户端角色和用户请求头；
13. 语义、数据或政策证据不足时失败关闭；
14. 验证按单元测试→API测试→Flow测试顺序执行，前端补充Vitest、类型检查、构建和核心浏览器流程。

## 24. 明确依赖与延后项

生产上线依赖医院选定扫码或院内SSO提供方，并提供用户、组织、角色和数据范围查询能力；具体厂商和协议不属于本规格，但P5完成前必须接入。

以下能力延后到有真实需求或压测证据时建设：

- 明细批量导出；
- ClickHouse、Doris等专用OLAP；
- Kafka或通用CDC平台；
- 多Agent自治数据加工；
- 自动异常归因和因果结论；
- 任意SQL查询；
- 医生绩效排名；
- 自动执行正式医保业务动作。
