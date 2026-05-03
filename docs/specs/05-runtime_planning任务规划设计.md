# runtime/planning 任务规划详细设计

## 1. 模块定位

`runtime/planning/` 负责将用户自然语言请求和运行时上下文转化为可执行任务计划。任务计划包括查询、检索、规则解释、模型调用、业务系统调用、材料生成、人工确认和任务分派等步骤。

该模块是医保 AI 导办从“问答”升级为“可执行导办”的核心。

## 2. 设计目标

1. 根据医保业务意图生成结构化执行计划。
2. 支持简单任务直接执行，复杂任务分步规划。
3. 支持动态重规划和异常补偿。
4. 支持计划可解释、可审计、可人工确认。
5. 支持不同业务场景的计划模板化。

## 3. 输入输出

### 3.1 输入

```text
PlanningInput
├── runtimeContext
├── intentResult
├── userQuestion
├── scenarioCode
├── availableCapabilities
└── constraints
```

### 3.2 输出

```text
ExecutionPlan
├── planId
├── scenarioCode
├── objective
├── steps[]
├── dependencies[]
├── riskLevel
├── needHumanConfirm
├── expectedOutput
└── auditInfo
```

## 4. 计划步骤类型

| 步骤类型 | 说明 |
|---|---|
| `QUERY_SYSTEM` | 查询业务系统或医保系统 |
| `RETRIEVE_KNOWLEDGE` | 检索政策、规则、错误码、模板 |
| `EXPLAIN_RULE` | 解释规则命中原因 |
| `CALL_MODEL` | 调用模型生成、摘要、分类 |
| `EXTRACT_EVIDENCE` | 抽取病历或材料证据 |
| `GENERATE_DOCUMENT` | 生成申诉材料、报告、清单 |
| `CREATE_TASK` | 生成待办任务 |
| `HUMAN_CONFIRM` | 人工确认 |
| `RETURN_RESPONSE` | 返回用户结果 |

## 5. 场景规划模板

### 5.1 医保结算异常导办

```text
查询医保交易流水
→ 查询费用上传状态
→ 查询错误码知识库
→ 查询收费结算状态
→ 汇总异常原因
→ 生成处理建议
→ 必要时生成任务待办
```

### 5.2 出院前联合质控

```text
查询患者费用、医嘱、诊断、病案首页
→ 查询医保接口状态
→ 查询事前审核结果
→ 查询 DRG/DIP 预分组和盈亏
→ 检索规则解释
→ 生成风险清单
→ 分派整改任务
```

### 5.3 拒付申诉助手

```text
读取拒付原因
→ 查询费用和审核结果
→ 抽取病历证据
→ 检索政策依据和申诉模板
→ 生成申诉材料草稿
→ 人工确认
→ 记录申诉任务
```

## 6. 规划策略

1. 优先使用规则模板规划，降低大模型不确定性。
2. 对复杂问题可调用模型生成初始计划，但必须经过计划校验。
3. 所有系统调用步骤必须声明目标适配器和操作码。
4. 所有高风险步骤必须标记 `needHumanConfirm`。
5. 所有输出必须声明来源引用要求。

## 7. 计划校验

校验项：

1. 用户权限是否允许执行计划。
2. 所需上下文是否完整。
3. 所需适配器能力是否可用。
4. 是否包含高风险动作。
5. 是否存在循环依赖。
6. 输出格式是否满足场景要求。

## 8. 核心接口

```text
PlanningService.plan(input) -> ExecutionPlan
PlanningService.validate(plan, runtimeContext) -> PlanValidationResult
PlanningService.replan(plan, failedStep, errorContext) -> ExecutionPlan
PlanningService.explain(plan) -> PlanExplanation
PlanningTemplateService.getTemplate(scenarioCode) -> PlanTemplate
```

## 9. 动态重规划

触发条件：

1. 外部系统调用失败。
2. 关键数据缺失。
3. 用户补充信息。
4. 风控模块拦截。
5. 模型输出不满足结构化要求。

处理方式：

```text
保留已完成步骤
→ 标记失败步骤
→ 分析失败原因
→ 替换能力或降级路径
→ 生成新计划版本
→ 继续执行或请求人工确认
```

## 10. 安全边界

1. 任务规划不得生成直接结算、退费、冲正、修改病案首页、修改费用明细等自动执行步骤。
2. 对高风险业务仅能生成建议、材料草稿、待办任务和人工确认步骤。
3. 计划必须可解释，不能只保存模型生成文本。
4. 所有计划版本必须留痕。

## 11. MVP 范围

第一期实现基于模板的规划能力，覆盖医保结算异常导办和出院前联合质控；支持失败重试、人工确认标记和计划审计。

