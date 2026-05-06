## ADDED Requirements

### Requirement: API Client Module

系统 SHALL 在 `prototype/src/lib/api-client.ts` 中提供类型化的 API 客户端模块，导出与后端端点一一对应的异步函数。每个函数 SHALL 接受类型化的请求参数并返回类型化的响应对象。

#### Scenario: Successful chat request
- **WHEN** 调用 `sendChat({ user_id, role, message, patient_id, encounter_id })` 且后端返回 200
- **THEN** 函数返回 `AgentResponse` 类型对象，包含 `scenario`, `status`, `result`, `citations`, `tasks`, `missing_fields`, `uncertainties`, `blocked_actions`, `audit` 字段

#### Scenario: Backend unreachable with fallback
- **WHEN** 调用任意 API 客户端函数且后端不可达（网络错误或超时）
- **THEN** 函数返回 mock 降级数据，响应中包含 `fallback: true` 标记

### Requirement: TypeScript Type Definitions

系统 SHALL 在 `prototype/src/lib/types.ts` 中定义与后端 Pydantic schema 一致的 TypeScript interface，至少包含 `ChatRequest`, `AgentResponse`, `PatientContextResponse`, `TaskConfirmRequest`, `TaskConfirmResponse`, `WorkflowStatusResponse`, `TaskStatusResponse`, `ModelTestRequest`, `ModelTestResponse`, `McpServer`, `McpStorageHealth`。

#### Scenario: Type consistency with backend
- **WHEN** 后端 `AgentResponse` 的 Pydantic 模型包含字段 `scenario: str | None`, `status: str`, `result: dict`, `citations: list`, `tasks: list`
- **THEN** 前端 `AgentResponse` interface SHALL 包含对应的 TypeScript 类型 `scenario?: string`, `status: string`, `result: Record<string, unknown>`, `citations: Citation[]`, `tasks: Task[]`

### Requirement: Next.js API Proxy

系统 SHALL 在 `prototype/next.config.ts` 中配置 `rewrites`，将前端 `/api/v1/medical-insurance-ai-agent/**` 路径代理到后端 `NEXT_PUBLIC_API_BASE_URL`（默认 `http://127.0.0.1:8000`）。

#### Scenario: Proxy forwards chat request
- **WHEN** 前端发送 POST `/api/v1/medical-insurance-ai-agent/chat`
- **THEN** Next.js 开发服务器 SHALL 将请求代理到 `http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/chat`

#### Scenario: Missing backend URL defaults to localhost
- **WHEN** 环境变量 `NEXT_PUBLIC_API_BASE_URL` 未设置
- **THEN** 代理 SHALL 默认指向 `http://127.0.0.1:8000`

### Requirement: Chat Component API Integration

[`settlement-chat.tsx`](../../../../prototype/src/components/settlement-chat.tsx) 组件 SHALL 将 `handleSend` 函数从本地 `setTimeout` mock 切换为调用 API 客户端的 `sendChat` 函数。角色参数 SHALL 从组件 props 的 `currentRole` 传递。

#### Scenario: User sends message to real backend
- **WHEN** 用户在对话框输入消息并点击发送
- **THEN** 组件调用 `sendChat({ user_id: 'demo', role: currentRole, message: userInput, patient_id: 'P001', encounter_id: 'E001' })`，并将响应渲染为 AI 回复

#### Scenario: Backend returns needs_clarification status
- **WHEN** 后端返回 `status: 'needs_clarification'` 且 `missing_fields` 非空
- **THEN** 组件 SHALL 显示缺失字段提示，引导用户补充信息

#### Scenario: Backend returns waiting_human_confirmation status
- **WHEN** 后端返回 `status: 'waiting_human_confirmation'` 且 `blocked_actions` 非空
- **THEN** 组件 SHALL 显示高风险动作拦截提示，并提供确认/拒绝按钮

### Requirement: SSE Streaming Chat

系统 SHALL 支持通过 `fetch` + `ReadableStream` 解析后端 `/chat/stream` 的 SSE 事件流，实现打字机效果的流式回复。

#### Scenario: Streaming step events
- **WHEN** 后端发送 SSE `step` 事件（如 `intent_detection`, `risk_control`）
- **THEN** 前端 SHALL 在对话区域显示对应的进度提示（如"正在识别意图"、"正在检查高风险动作"）

#### Scenario: Streaming final event
- **WHEN** 后端发送 SSE `final` 事件
- **THEN** 前端 SHALL 将 `final` 事件的 data 解析为 `AgentResponse`，渲染完整回复

#### Scenario: Streaming error event
- **WHEN** 后端发送 SSE `error` 事件
- **THEN** 前端 SHALL 在对话区域显示错误提示，并停止 loading 状态

### Requirement: Patient Context Integration

系统 SHALL 在患者上下文相关交互中调用后端 `/patient-context/{patient_id}/{encounter_id}` 端点，传递当前角色参数。

#### Scenario: Fetch patient context with role
- **WHEN** 用户选择患者 P001/E001 且当前角色为 `insurance_office`
- **THEN** 前端调用 `GET /api/v1/medical-insurance-ai-agent/patient-context/P001/E001?user_id=demo&role=insurance_office`，并根据返回的 `visible_fields` 动态渲染患者信息

### Requirement: Task Confirmation Integration

系统 SHALL 在高风险动作确认场景中调用后端 `/tasks/confirm` 端点。

#### Scenario: Confirm high-risk task
- **WHEN** 用户点击确认按钮确认一个高风险任务
- **THEN** 前端调用 `POST /api/v1/medical-insurance-ai-agent/tasks/confirm`，body 为 `{ task_id, action: 'confirm', user_id, reason }`，并更新 UI 显示确认结果

#### Scenario: Reject high-risk task
- **WHEN** 用户点击拒绝按钮拒绝一个高风险任务
- **THEN** 前端调用 `POST /api/v1/medical-insurance-ai-agent/tasks/confirm`，body 为 `{ task_id, action: 'reject', user_id, reason }`，并更新 UI 显示拒绝结果

### Requirement: Connection Status Indicator

系统 SHALL 在页面顶部显示后端连接状态指示器，实时反映 API 可达性。

#### Scenario: Backend connected
- **WHEN** 前端成功调用任意 API 端点并收到响应
- **THEN** 状态指示器 SHALL 显示绿色"已连接"标记

#### Scenario: Backend disconnected with fallback active
- **WHEN** 前端 API 请求失败并回退到 mock 数据
- **THEN** 状态指示器 SHALL 显示橙色"离线模式"标记，提示用户当前为模拟数据

### Requirement: Environment Configuration

系统 SHALL 支持通过 `.env.local` 文件配置 `NEXT_PUBLIC_API_BASE_URL`，且提供 `.env.example` 文件说明配置项。

#### Scenario: Custom backend URL
- **WHEN** `.env.local` 中设置 `NEXT_PUBLIC_API_BASE_URL=http://192.168.1.100:8000`
- **THEN** API 代理和客户端 SHALL 使用该地址作为后端目标

#### Scenario: No env file present
- **WHEN** 不存在 `.env.local` 文件
- **THEN** 系统 SHALL 使用默认值 `http://127.0.0.1:8000`，不报错
