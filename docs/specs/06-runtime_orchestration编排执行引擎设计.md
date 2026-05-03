# runtime/orchestration 编排执行引擎详细设计

## 1. 模块定位

`runtime/orchestration/` 负责执行任务规划模块生成的 `ExecutionPlan`，按照步骤依赖关系调度模型、知识、工具、业务系统适配器和任务闭环服务，完成导办任务的端到端执行。

该模块是平台运行时的核心控制器。

## 2. 设计目标

1. 支持 DAG 编排、顺序执行、并行执行和条件分支。
2. 支持步骤超时、重试、熔断、降级和断点续执。
3. 支持调用知识服务、模型服务、Tools、MCP、业务系统适配器。
4. 支持执行状态持久化和审计追踪。
5. 支持人工确认节点暂停和恢复。

## 3. 核心对象

```text
WorkflowInstance
├── instanceId
├── planId
├── scenarioCode
├── status
├── currentStepId
├── stepStates[]
├── runtimeContextRef
├── startedAt
├── finishedAt
└── auditRefs[]
```

```text
StepState
├── stepId
├── stepType
├── status
├── inputRef
├── outputRef
├── errorInfo
├── retryCount
└── durationMs
```

## 4. 执行状态

```text
PENDING / RUNNING / WAITING_CONFIRM / SUCCEEDED / FAILED / CANCELLED / SUSPENDED
```

## 5. 执行流程

```text
接收 ExecutionPlan
→ 创建 WorkflowInstance
→ 校验依赖和权限
→ 初始化步骤状态
→ 按 DAG 调度可执行步骤
→ 调用能力调度模块
→ 保存步骤输入输出引用
→ 处理异常和重试
→ 遇到人工确认则暂停
→ 全部完成后进入结果生成与任务闭环
```

## 6. 能力调用类型

| 能力 | 调用目标 |
|---|---|
| 模型调用 | `model_service/model_gateway` |
| 知识检索 | `knowledge_extension/rag` |
| 规则解释 | `knowledge_extension/rule_explanation` |
| 工具调用 | `knowledge_extension/tool_registry` |
| MCP 调用 | `knowledge_extension/mcp` |
| 适配器调用 | `adapters/*` |
| 任务创建 | `runtime/task_closure` |

## 7. 调度策略

1. 无依赖步骤可并行执行。
2. 高成本模型调用需要进入资源队列。
3. 外部系统调用受限流策略控制。
4. 高风险步骤必须等待人工确认。
5. 失败步骤根据错误类型决定重试、降级或终止。

## 8. 异常处理

| 异常 | 处理方式 |
|---|---|
| 适配器超时 | 重试，超过阈值后降级 |
| 模型输出不合规 | 重新生成或进入人工确认 |
| 权限校验失败 | 终止步骤并记录审计 |
| 数据缺失 | 触发澄清或重规划 |
| 高风险动作 | 暂停并等待人工确认 |

## 9. 断点续执

断点保存内容：

1. 当前流程实例。
2. 已完成步骤输出引用。
3. 失败步骤错误信息。
4. 上下文快照。
5. 审计记录。

恢复策略：

```text
加载 WorkflowInstance
→ 校验计划版本
→ 恢复 RuntimeContext
→ 跳过已成功步骤
→ 从失败或暂停节点继续执行
```

## 10. 核心接口

```text
OrchestrationService.start(plan, runtimeContext) -> WorkflowInstance
OrchestrationService.resume(instanceId, confirmInput) -> WorkflowInstance
OrchestrationService.cancel(instanceId, reason) -> CancelResult
OrchestrationService.getStatus(instanceId) -> WorkflowStatus
OrchestrationService.getStepOutput(instanceId, stepId) -> StepOutput
```

## 11. 审计要求

每个步骤必须记录：

1. 调用时间。
2. 调用能力。
3. 输入摘要。
4. 输出摘要。
5. 数据来源。
6. 操作用户。
7. 风险校验结果。

## 12. MVP 范围

第一期实现顺序执行、基础 DAG、步骤状态持久化、适配器调用、知识检索、模型调用、失败重试、人工确认暂停和恢复。

