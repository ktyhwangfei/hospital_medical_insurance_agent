# adapters 业务系统适配器详细设计

## 1. 模块定位

`adapters/` 负责连接医保专业系统、医院业务系统和外部 Agent 系统，将外部系统差异化接口、数据库视图、文件、消息、页面上下文统一封装为平台可调用的标准能力。

该模块是平台落地的关键边界层，不替代原系统，不直接修改正式业务数据，优先读取结果、查询状态、获取证据、封装调用和记录审计。

## 2. 设计目标

1. 支持多种接入方式：API、中间库、数据视图、文件同步、消息订阅、页面嵌入、RPA 兜底。
2. 屏蔽不同医院和厂商接口差异，向上提供统一适配器接口。
3. 保留调用日志、输入输出摘要、错误信息和审计链路。
4. 支持医保结算异常、出院前质控、拒付申诉、DRG/DIP 运营等场景所需数据调用。
5. 对高风险写操作默认禁用或进入人工确认流程。

## 3. 目录结构

```text
adapters/
├── base/
├── insurance_interface/
├── pre_audit/
├── drg_dip/
├── insurance_data_platform/
├── his/
├── emr/
├── billing/
├── medical_record/
├── lis/
├── pacs/
├── finance/
├── integration_platform/
└── external_agent/
```

## 4. 适配器基础规范

### 4.1 统一接口

```text
AdapterClient.call(operationCode, request, context) -> AdapterResponse
AdapterClient.healthCheck() -> HealthStatus
AdapterClient.describeCapabilities() -> CapabilityDescriptor
AdapterClient.validatePermission(operationCode, context) -> PermissionResult
```

### 4.2 标准请求

| 字段 | 说明 |
|---|---|
| `requestId` | 全局请求编号 |
| `traceId` | 链路追踪编号 |
| `operationCode` | 能力编码 |
| `patientId` | 患者标识 |
| `encounterId` | 就诊标识 |
| `params` | 业务参数 |
| `operator` | 操作用户 |
| `sourceChannel` | 来源入口 |

### 4.3 标准响应

| 字段 | 说明 |
|---|---|
| `success` | 是否成功 |
| `data` | 标准化数据 |
| `rawRef` | 原始响应引用 |
| `errorCode` | 错误码 |
| `errorMessage` | 错误描述 |
| `sourceSystem` | 来源系统 |
| `dataTime` | 数据时间 |
| `auditId` | 审计编号 |

## 5. 核心适配器设计

### 5.1 首信医保接口适配器

主要能力：

1. 查询医保交易流水。
2. 查询结算状态。
3. 查询费用上传状态。
4. 获取医保错误码与返回信息。
5. 查询清单上传和反馈结果。

典型操作码：

```text
insurance.transaction.query
insurance.settlement.status.query
insurance.fee_upload.status.query
insurance.error_code.explain
insurance.claim_feedback.query
```

### 5.2 东软医保事前审核适配器

主要能力：

1. 查询审核结果。
2. 查询规则命中明细。
3. 查询违规风险金额。
4. 查询审核解释和处置建议。

典型操作码：

```text
pre_audit.result.query
pre_audit.rule_hit.query
pre_audit.risk_amount.query
pre_audit.explanation.query
```

### 5.3 大瑞集思 DRG/DIP 适配器

主要能力：

1. 查询预分组结果。
2. 查询正式分组结果。
3. 查询盈亏预测。
4. 查询费用结构异常。
5. 查询病案首页影响因素。

典型操作码：

```text
drg_dip.pre_group.query
drg_dip.final_group.query
drg_dip.profit_loss.query
drg_dip.cost_structure.query
drg_dip.record_risk.query
```

### 5.4 HIS/EMR/收费/病案适配器

| 适配器 | 主要能力 |
|---|---|
| `his` | 患者、就诊、住院、科室、医生、医嘱索引 |
| `emr` | 病历、诊断、手术、病程、出院记录、证据抽取 |
| `billing` | 费用明细、结算明细、退费冲正状态 |
| `medical_record` | 病案首页、编码、质控缺陷 |

## 6. 接入方式策略

| 接入方式 | 使用场景 | 优先级 |
|---|---|---|
| API | 系统开放标准接口 | 高 |
| 中间库 | 厂商提供同步库 | 高 |
| 数据视图 | 只读数据查询 | 高 |
| 文件同步 | 批量结果、报表、清单 | 中 |
| 消息订阅 | 状态变更、任务事件 | 中 |
| 页面嵌入 | 医生站、收费端上下文 | 中 |
| RPA 兜底 | 无接口且短期无法改造 | 低 |

## 7. 安全与审计

1. 所有适配器调用必须生成调用审计记录。
2. 所有患者敏感数据返回前必须经过脱敏策略判断。
3. 高风险写操作默认不开放；如必须开放，需要人工确认和双重审计。
4. 外部系统异常不得直接暴露给用户，应转换为平台标准错误。

## 8. 错误处理

| 错误类型 | 处理方式 |
|---|---|
| 网络超时 | 重试、熔断、降级 |
| 权限不足 | 返回权限错误并记录审计 |
| 数据缺失 | 返回缺失字段列表 |
| 接口异常 | 标准化错误码，保留原始错误引用 |
| 数据不一致 | 标记数据质量问题并提示来源 |

## 9. MVP 范围

第一期优先实现：`insurance_interface`、`pre_audit`、`drg_dip`、`his`、`emr`、`billing` 六类适配器，并以查询类、只读类能力为主。

