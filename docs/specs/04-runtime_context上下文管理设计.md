# runtime/context 上下文管理详细设计

## 1. 模块定位

`runtime/context/` 负责在一次医保 AI 导办请求中装载、管理、裁剪和传递上下文信息，包括用户上下文、患者上下文、页面上下文、会话历史、文件引用、权限上下文和任务执行上下文。

该模块是连接医院业务入口、统一交互 API、意图识别、任务规划、编排执行和结果生成的关键运行时模块。

## 2. 设计目标

1. 支持从医生站、医保办、收费端、病案端等入口获取页面上下文。
2. 支持患者级、就诊级、任务级上下文装载。
3. 支持长会话历史记忆与模型上下文裁剪。
4. 支持文件、语音、病历证据等对象引用管理。
5. 支持权限过滤和敏感数据脱敏。

## 3. 上下文类型

| 类型 | 说明 | 示例 |
|---|---|---|
| `UserContext` | 用户与角色 | 医保办、医生、收费员、科主任 |
| `PatientContext` | 患者与就诊 | 患者 ID、住院号、当前病例 |
| `PageContext` | 页面来源 | 医生站当前医嘱页、收费结算页 |
| `SessionContext` | 会话状态 | 历史问题、已确认参数、会话变量 |
| `FileContext` | 文件对象 | 上传病历、申诉材料、政策文件 |
| `PermissionContext` | 权限边界 | 可访问科室、可查询数据范围 |
| `ExecutionContext` | 执行状态 | 当前计划、步骤状态、中间结果 |

## 4. 核心数据结构

```text
RuntimeContext
├── requestId
├── traceId
├── userContext
├── patientContext
├── pageContext
├── sessionContext
├── fileContexts[]
├── permissionContext
├── executionContext
└── auditContext
```

## 5. 主要流程

```text
统一交互 API 接收请求
→ 创建 RuntimeContext
→ 装载 UserContext
→ 装载 PageContext
→ 根据页面上下文补全 PatientContext
→ 恢复 SessionContext
→ 关联 FileContext
→ 加载 PermissionContext
→ 执行脱敏与权限过滤
→ 生成供意图识别和任务规划使用的上下文包
```

## 6. 核心接口

```text
ContextService.build(request) -> RuntimeContext
ContextService.enrich(runtimeContext, enrichOptions) -> RuntimeContext
ContextService.trimForModel(runtimeContext, tokenBudget) -> ModelContext
ContextService.save(runtimeContext) -> SaveResult
ContextService.restore(sessionId) -> RuntimeContext
ContextService.attachFile(sessionId, fileRef) -> FileContext
```

## 7. 上下文装载规则

### 7.1 用户上下文

来源：SSO、统一认证、医院门户、嵌入式组件。

关键字段：

```text
userId / userName / roleCodes / deptId / orgId / tenantId / loginChannel
```

### 7.2 患者上下文

来源：页面参数、HIS、EMR、收费系统、医保数据中台。

关键字段：

```text
patientId / encounterId / admissionNo / visitType / currentDept / attendingDoctor / dischargeStatus
```

### 7.3 页面上下文

来源：嵌入式组件传参。

关键字段：

```text
pageCode / pageName / businessObjectType / businessObjectId / selectedRows / currentOperation
```

## 8. 上下文裁剪策略

1. 优先保留当前患者、当前就诊、当前页面上下文。
2. 优先保留最近用户问题和系统确认信息。
3. 对长病历和长政策采用摘要加引用方式。
4. 文件内容不直接放入上下文，只放文件引用和摘要。
5. 对模型上下文输出前进行权限过滤和脱敏。

## 9. 权限与安全

1. 用户只能加载授权科室和授权患者范围内的数据。
2. 不同角色上下文可见字段不同。
3. 患者敏感身份信息默认脱敏。
4. 上下文保存必须加密或按医院安全规范存储。
5. 所有上下文装载行为写入审计。

## 10. 异常处理

| 异常 | 处理方式 |
|---|---|
| 患者上下文缺失 | 触发澄清，要求选择患者或就诊 |
| 页面上下文不完整 | 降级为普通问答或提示缺少参数 |
| 权限不足 | 阻断请求并记录审计 |
| 文件解析失败 | 保留文件引用，提示无法解析 |
| 上下文过长 | 执行裁剪和摘要 |

## 11. MVP 范围

第一期实现用户上下文、患者上下文、页面上下文、会话上下文、文件引用和模型上下文裁剪；暂不实现复杂长期记忆和跨会话画像记忆。

