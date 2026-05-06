# front-prototype 模块开发设计文档

**日期**: 2026-05-06
**状态**: 待审阅
**OpenSpec 变更**: `openspec/changes/front-prototype/`

## 1. 概述

将现有 `prototype/` 的 Next.js 高保真原型从纯 mock 数据驱动切换为与后端 FastAPI 真实联调，同时新增 MCP 管理、知识扩展浏览和模型测试三个功能页面。

### 1.1 动机

- 原型当前所有数据来自硬编码 mock，无法验证真实 API 契约、鉴权边界和业务闭环
- 后端已具备完整的 MVP API（对话、患者上下文、任务确认、MCP 管理、模型测试）
- 现有 `mcp-admin.html` 功能简陋，需要整合到统一的原型界面中
- 知识扩展和模型测试能力缺少前端展示入口

### 1.2 范围

| 范围 | 说明 |
|------|------|
| **包含** | API 客户端、对话联调、SSE 流式、任务确认、MCP 管理页面、知识浏览页面、模型测试页面、mock 降级、连接状态指示器 |
| **不包含** | 后端 API 变更、认证/登录系统、UI 视觉重构、WebSocket、知识扩展独立 HTTP 端点 |

## 2. 后端 API 契约

### 2.1 核心业务 API

基础路径: `/api/v1/medical-insurance-ai-agent`

| 端点 | 方法 | 请求体 | 响应体 |
|------|------|--------|--------|
| `/chat` | POST | `ChatRequest` | `AgentResponse` |
| `/chat/stream` | POST | `ChatRequest` | SSE 事件流 |
| `/patient-context/{pid}/{eid}` | GET | query: user_id, role | `PatientContextResponse` |
| `/tasks/confirm` | POST | `TaskConfirmRequest` | `TaskConfirmResponse` |
| `/workflows/{id}` | GET | — | `WorkflowStatusResponse` |
| `/tasks/{id}` | GET | — | `TaskStatusResponse` |
| `/model-test` | POST | `ModelTestRequest` | `ModelTestResponse` |
| `/model-test/stream` | POST | `ModelTestRequest` | SSE 事件流 |
| `/version` | GET | — | `{module, mode}` |

### 2.2 MCP 管理 API

基础路径: `/api/v1/medical-insurance-ai-agent/mcp`

| 端点 | 方法 | 请求体 | 响应体 |
|------|------|--------|--------|
| `/storage/health` | GET | — | JSON 健康状态 |
| `/servers` | POST | `McpServer` | 脱敏服务信息 |

### 2.3 关键 Schema

```typescript
// ChatRequest
interface ChatRequest {
  user_id: string
  role: string
  message: string
  patient_id?: string
  encounter_id?: string
}

// AgentResponse
interface AgentResponse {
  scenario?: string
  status: string  // needs_clarification | waiting_human_confirmation | success | not_implemented
  result: Record<string, unknown>
  citations: Array<{ source_type: string; source_id: string; summary: string }>
  tasks: Array<Record<string, unknown>>
  missing_fields: string[]
  uncertainties: string[]
  blocked_actions: string[]
  audit: Record<string, unknown>
}

// ModelTestRequest / ModelTestResponse
interface ModelTestRequest { message: string; scene: string }
interface ModelTestResponse {
  content: string; model_name: string; latency_ms: number
  prompt_tokens: number; completion_tokens: number
}

// McpServer
interface McpServer {
  server_id: string; name: string; endpoint: string
  transport: 'sse' | 'streamable_http' | 'stdio'
  status: 'enabled' | 'disabled' | 'degraded' | 'unhealthy'
  protocol_version?: string; auth_headers: Record<string, string>
  metadata: Record<string, unknown>
}
```

## 3. 架构设计

### 3.1 文件结构（新增/修改）

```
prototype/src/
├── app/
│   ├── layout.tsx          # 修改：包裹 ApiProvider
│   └── page.tsx            # 修改：扩展为 7 个 Tab
├── components/
│   ├── settlement-chat.tsx  # 修改：API 联调
│   ├── discharge-qc.tsx     # 不变
│   ├── dashboard.tsx        # 不变
│   ├── role-switcher.tsx    # 不变
│   ├── mcp-management.tsx   # 新增
│   ├── knowledge-explorer.tsx # 新增
│   └── model-test.tsx       # 新增
├── lib/
│   ├── types.ts             # 新增：TypeScript 类型定义
│   ├── api-client.ts        # 新增：统一 API 客户端
│   ├── api-context.tsx      # 新增：全局 API 状态 Context
│   ├── mock-data.ts         # 修改：扩展 mock 数据
│   └── utils.ts             # 不变
└── .env.example             # 新增
```

### 3.2 设计决策

| ID | 决策 | 选择 | 理由 |
|----|------|------|------|
| D1 | API 代理 | Next.js rewrites | 避免 CORS，前端用相对路径 |
| D2 | API 客户端 | 独立模块 + 手工类型 | 集中管理，MVP 阶段灵活 |
| D3 | 降级策略 | 函数级 try/catch + mock | 后端不可用时仍可演示 |
| D4 | SSE 流式 | fetch + ReadableStream | POST SSE 不支持 EventSource |
| D5 | 状态管理 | React useState + Context | 原型阶段足够轻量 |
| D6 | 页面结构 | Tab 扩展模式 | 保持单页导航一致性 |
| D7 | MCP 迁移 | Next.js 组件替代 mcp-admin.html | 统一技术栈 |
| D8 | 视觉一致性 | 沿用现有 Card/Badge/Progress 模式 | 无需学习新交互 |

### 3.3 数据流

```
用户操作 → React 组件
  → api-client.ts（类型化请求）
    → Next.js rewrites 代理
      → 后端 FastAPI
    ← JSON 响应
  ← 类型化响应 / mock 降级
← UI 更新
```

SSE 流式路径：
```
用户发送消息 → settlement-chat.tsx
  → sendChatStream()
    → fetch POST /chat/stream
      → ReadableStream 解析
        → step 事件 → 显示进度提示
        → final 事件 → 渲染完整回复
        → error 事件 → 显示错误
```

## 4. 功能规格

### 4.1 API 客户端模块（frontend-api-integration）

- `sendChat(req)` → `AgentResponse` | mock 降级
- `sendChatStream(req)` → SSE 事件流解析
- `fetchPatientContext(pid, eid, role)` → `PatientContextResponse`
- `confirmTask(req)` → `TaskConfirmResponse`
- `fetchWorkflowStatus(id)` → `WorkflowStatusResponse`
- `fetchTaskStatus(id)` → `TaskStatusResponse`
- `testModel(req)` → `ModelTestResponse`
- `testModelStream(req)` → SSE 事件流
- `fetchMcpStorageHealth()` → 健康状态 JSON
- `registerMcpServer(server)` → 脱敏服务信息

所有函数统一错误处理：网络错误 → mock + `fallback: true`；HTTP 错误 → 结构化异常。

### 4.2 对话组件联调

- `handleSend` 从 `setTimeout` mock 切换为 `sendChat` / `sendChatStream`
- 处理 `needs_clarification`：显示缺失字段提示
- 处理 `waiting_human_confirmation`：高风险拦截卡片 + 确认/拒绝按钮
- 角色参数 `currentRole` 作为 `role` 传递

### 4.3 MCP 管理页面（frontend-mcp-management）

- 服务注册表单：server_id, name, endpoint, transport 下拉
- 存储健康检查面板：格式化 JSON 展示
- 已注册服务列表：Card 列表 + Badge 状态
- 能力浏览：4 列 grid 分类卡片（Tool/Resource/Prompt/Service）

### 4.4 知识浏览页面（frontend-knowledge-explorer）

- 知识资产概览：4 列指标卡片（错误码/政策/DRG 知识库）
- RAG 检索测试：Input + 检索结果列表
- 规则解释展示：错误码解释卡片 + DRG/DIP 规则摘要
- 提示模板预览：模板列表（名称、场景、角色）
- 注：知识扩展服务无独立 HTTP 端点，数据为 mock + 标注"演示数据"

### 4.5 模型测试页面（frontend-model-test）

- 参数配置：消息输入 + 场景下拉（default/settlement_exception/pre_discharge_qc/drg_analysis）
- 同步模式：调用 `testModel`，展示 content/model_name/latency_ms/tokens
- 流式模式：调用 `testModelStream`，实时追加输出
- 错误处理：503 配置错误、502 上游错误、429 限流
- 测试历史：Card 列表，时间倒序，支持清除

### 4.6 连接状态

- `ApiProvider` Context 管理连接状态和 user_id
- 顶部导航栏指示器：绿色"已连接" / 橙色"离线模式"

## 5. 交互设计一致性

所有新增页面严格沿用现有原型的组件和布局模式：

| 模式 | 现有参考 | 新页面应用 |
|------|----------|------------|
| Tab 导航 | `page.tsx` 4 列 grid | 扩展为 7 列 |
| 指标卡片 | `dashboard.tsx` 4 列 metrics | MCP/知识/模型统计 |
| Card 列表 | `SettlementExceptionList` | MCP 服务/测试历史 |
| Badge 状态 | `discharge-qc.tsx` 风险标签 | 服务状态/检索状态 |
| Progress | `dashboard.tsx` 科室排名 | 知识覆盖度/token 用量 |
| 左右分栏 | `settlement-chat.tsx` 1:3 | 模型测试参数+结果 |
| 表单组件 | `role-switcher.tsx` Select | MCP 注册/场景选择 |

## 6. 实施任务（46 项）

| 组 | 名称 | 任务数 | 依赖 |
|----|------|--------|------|
| 1 | 基础设施与类型定义 | 4 | 无 |
| 2 | API 客户端模块 | 11 | 组 1 |
| 3 | 对话组件集成 | 6 | 组 2 |
| 4 | 任务确认与患者上下文 | 4 | 组 2 |
| 5 | MCP 管理页面 | 6 | 组 2 |
| 6 | 知识浏览页面 | 6 | 组 1 |
| 7 | 模型测试页面 | 6 | 组 2 |
| 8 | 连接状态与全局上下文 | 4 | 组 2 |
| 9 | Mock 数据扩展 | 3 | 无 |
| 10 | 验证与文档 | 7 | 组 3-8 |

详细任务清单见 `openspec/changes/front-prototype/tasks.md`。

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 后端 API 变动导致前端类型不同步 | API 客户端统一错误处理，运行时容错 |
| SSE 解析浏览器兼容性 | 降级为非流式 `/chat` 端点 |
| Mock 与真实数据结构不一致 | 统一 TypeScript 类型定义 |
| 知识扩展无独立端点 | 页面标注"演示数据"，后续对接 |
| MCP 管理功能受限于后端端点 | UI 区分"已对接"和"演示中" |
