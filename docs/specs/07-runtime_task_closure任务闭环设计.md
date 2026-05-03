# runtime/task_closure 任务闭环详细设计

## 1. 模块定位

`runtime/task_closure/` 负责将 AI 导办结果转化为可分派、可处理、可确认、可追踪、可审计的业务任务，实现医保办、病案室、收费窗口、临床科室、科主任和信息科之间的协同闭环。

该模块体现平台区别于普通问答系统的核心价值。

## 2. 设计目标

1. 支持根据导办结果生成待办任务。
2. 支持任务分派、领取、处理、确认、关闭。
3. 支持人工确认和高风险动作留痕。
4. 支持任务处理结果反哺指标体系和运营分析。
5. 支持任务全链路审计和结果追踪。

## 3. 任务类型

| 任务类型 | 说明 | 责任角色 |
|---|---|---|
| `SETTLEMENT_EXCEPTION` | 医保结算异常处理 | 收费员、医保办、信息科 |
| `PRE_DISCHARGE_QC` | 出院前风险整改 | 医保办、病案室、临床医生 |
| `DENIAL_APPEAL` | 拒付申诉材料处理 | 医保办 |
| `DRG_DIP_OPERATION` | DRG/DIP 运营整改 | 科主任、运营部、医保办 |
| `MEDICAL_RECORD_RISK` | 病案首页风险处理 | 病案室、临床医生 |
| `POLICY_RULE_CONFIRM` | 政策规则解释确认 | 医保办 |

## 4. 任务状态

```text
CREATED / ASSIGNED / CLAIMED / PROCESSING / WAIT_CONFIRM / COMPLETED / REJECTED / CANCELLED / EXPIRED
```

## 5. 核心对象

```text
GuideTask
├── taskId
├── taskType
├── scenarioCode
├── title
├── description
├── patientId
├── encounterId
├── riskLevel
├── priority
├── assigneeRole
├── assigneeUserId
├── sourcePlanId
├── sourceWorkflowId
├── evidenceRefs[]
├── suggestedActions[]
├── status
├── dueTime
└── auditRefs[]
```

```text
TaskActionRecord
├── actionId
├── taskId
├── actionType
├── operatorId
├── operatorRole
├── comment
├── attachments[]
├── beforeStatus
├── afterStatus
└── operatedAt
```

## 6. 任务生成规则

任务来源：

1. 任务规划步骤 `CREATE_TASK`。
2. 编排执行中的风险结果。
3. 用户主动创建。
4. 定时扫描指标或数据质量异常。

生成原则：

1. 一个明确风险生成一个主任务。
2. 可按责任角色拆分子任务。
3. 必须绑定患者、就诊、证据和来源结果。
4. 高风险任务必须设置人工确认。

## 7. 任务分派策略

| 条件 | 分派策略 |
|---|---|
| 结算错误码 | 分派收费员或信息科 |
| 审核规则命中 | 分派医保办或临床医生 |
| 病案首页缺陷 | 分派病案室 |
| DRG/DIP 亏损 | 分派科主任或运营部 |
| 拒付申诉 | 分派医保办 |

## 8. 核心接口

```text
TaskClosureService.createTask(taskCreateCommand) -> GuideTask
TaskClosureService.assign(taskId, assignee) -> AssignResult
TaskClosureService.claim(taskId, userId) -> ClaimResult
TaskClosureService.submitAction(taskId, actionCommand) -> ActionResult
TaskClosureService.confirm(taskId, confirmCommand) -> ConfirmResult
TaskClosureService.close(taskId, closeCommand) -> CloseResult
TaskClosureService.queryTasks(filters, permissionContext) -> TaskPage
```

## 9. 人工确认机制

需要人工确认的场景：

1. 申诉材料正式提交前。
2. 建议修改病案首页前。
3. 建议调整费用明细前。
4. 涉及退费、冲正、撤销结算等高风险动作时。
5. AI 置信度低或证据不足时。

确认结果：

```text
APPROVED / REJECTED / NEED_MORE_EVIDENCE / TRANSFERRED
```

## 10. 审计与追溯

每个任务必须可追溯：

1. 来源问题。
2. 来源患者和就诊。
3. 来源规则或系统结果。
4. AI 生成内容。
5. 人工确认记录。
6. 实际处理动作。
7. 关闭原因。

## 11. 指标反哺

任务闭环结果反哺指标体系：

1. 任务完成率。
2. 平均处理时长。
3. 超期率。
4. 风险整改率。
5. 申诉追回率。
6. 科室整改闭环率。

## 12. 消息提醒

提醒类型：

1. 新任务提醒。
2. 超期提醒。
3. 人工确认提醒。
4. 任务退回提醒。
5. 任务完成提醒。

## 13. 安全边界

1. 任务闭环只记录建议和处理过程，不直接替代正式业务系统操作。
2. 涉及正式业务动作必须跳转原系统或进入人工确认。
3. 任务内容按角色权限过滤展示。
4. 任务附件必须进行权限控制和脱敏。

## 14. MVP 范围

第一期实现任务创建、分派、处理、人工确认、关闭、查询、审计和消息提醒，优先支持医保结算异常导办和出院前联合质控两个场景。

