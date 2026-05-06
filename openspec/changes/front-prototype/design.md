## Context

当前 [`prototype/`](../../../prototype/) 是独立的 Next.js 16 + React 19 + shadcn/ui 高保真原型，所有数据来自 [`prototype/src/lib/mock-data.ts`](../../../prototype/src/lib/mock-data.ts) 中的硬编码模拟数据，AI 对话通过 `setTimeout` 模拟延迟回复。后端 FastAPI 已实现完整的 MVP API 契约，包括：

**核心业务 API**（[`src/runtime/api/routes.py`](../../../src/runtime/api/routes.py)）：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/v1/medical-insurance-ai-agent/chat` | POST | 统一导办对话 |
| `/api/v1/medical-insurance-ai-agent/chat/stream` | POST | SSE 流式对话 |
| `/api/v1/medical-insurance-ai-agent/patient-context/{pid}/{eid}` | GET | 患者上下文 |
| `/api/v1/medical-insurance-ai-agent/tasks/confirm` | POST | 任务确认/拒绝 |
| `/api/v1/medical-insurance-ai-agent/workflows/{id}` | GET | 流程状态查询 |
| `/api/v1/medical-insurance-ai-agent/tasks/{id}` | GET | 任务状态查询 |
| `/api/v1/medical-insurance-ai-agent/model-test` | POST | 模型测试（同步） |
| `/api/v1/medical-insurance-ai-agent/model-test/stream` | POST | 模型测试（流式） |
| `/api/v1/medical-insurance-ai-agent/version` | GET | 版本信息 |

**MCP 管理 API**（[`src/runtime/api/mcp_routes.py`](../../../src/runtime/api/mcp_routes.py)）：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/v1/medical-insurance-ai-agent/mcp/storage/health` | GET | 存储健康检查 |
| `/api/v1/medical-insurance-ai-agent/mcp/servers` | POST | 注册 MCP 服务 |

**知识扩展服务**（[`src/knowledge_extension/service.py`](../../../src/knowledge_extension/service.py)）：
- `KnowledgeExtensionService.enhance()` — 知识增强（RAG 检索 + 规则解释 + 模板选择）
- 当前无独立 HTTP 端点，通过对话流程内部调用

前后端当前完全独立运行。现有 [`mcp-admin.html`](../../../src/static/mcp-admin.html) 是极简的单页面，功能远不足以演示 MCP 管理能力。

## Goals / Non-Goals

**Goals:**

- 将 AI 导办对话组件从本地 mock 切换为调用后端 `/chat` 端点，支持 SSE 流式响应
- 将角色切换与后端 `role` 参数联动，实现权限感知的对话体验
- 将患者上下文查询接入后端 `/patient-context` 端点
- 将任务确认/拒绝交互接入后端 `/tasks/confirm` 端点
- 新增 MCP 服务管理页面（Tab），替代现有 `mcp-admin.html`，提供服务注册、健康检查、能力浏览功能
- 新增知识扩展浏览页面（Tab），展示知识资产、RAG 检索、规则解释和提示模板
- 新增模型测试页面（Tab），支持同步/流式模型调用测试
- 保留 mock 降级模式：后端不可用时自动回退到本地模拟数据
- 前端增加统一的 API 客户端层、类型定义与错误处理

**Non-Goals:**

- 不改变后端 API 契约或行为
- 不引入认证/登录系统（MVP 阶段角色由前端选择传递）
- 不重构现有 UI 组件结构或视觉风格
- 不实现 WebSocket 双向通信（仅使用 HTTP + SSE）
- 不为知识扩展服务新增独立 HTTP 端点（当前通过对话流程内部调用）
- 不实现 MCP 能力注册的前端 UI（当前后端仅暴露服务注册端点，能力注册通过内部 API）

## Decisions

### D1: API 代理策略 — Next.js API Rewrites

**选择**: 使用 [`next.config.ts`](../../../prototype/next.config.ts) 的 `rewrites` 将 `/api/**` 请求代理到后端 FastAPI 服务。

**理由**: 避免浏览器 CORS 限制，前端代码使用相对路径 `/api/v1/...` 即可，无需硬编码后端地址。开发时后端运行在 `localhost:8000`，Next.js 运行在 `localhost:3000`。

**替代方案**: 前端直接使用完整 URL + CORS headers — 需要修改后端添加 CORS 中间件，增加耦合。

### D2: API 客户端架构 — 独立模块 + TypeScript 类型

**选择**: 在 [`prototype/src/lib/api-client.ts`](../../../prototype/src/lib/api-client.ts) 中创建统一的 API 客户端，导出类型化的请求函数。每个函数对应一个后端端点。

**理由**: 集中管理请求逻辑、错误处理和降级策略，组件层只需调用函数无需关心 HTTP 细节。TypeScript 类型从后端 Pydantic 模型手工镜像为前端 interface。

**替代方案**: 使用 OpenAPI 自动生成（如 openapi-typescript）— 当前后端 schema 变动频繁，自动生成增加构建复杂度，MVP 阶段手工维护更灵活。

### D3: 降级策略 — 函数级 try/catch + mock 回退

**选择**: 每个 API 客户端函数在 catch 块中回退到 [`mock-data.ts`](../../../prototype/src/lib/mock-data.ts) 的对应数据，并在返回值中标记 `fallback: true`。

**理由**: 确保后端未启动时原型仍可演示，同时前端可展示"离线模式"提示。

**替代方案**: 全局 Service Worker 拦截 — 过度工程化，增加调试复杂度。

### D4: SSE 流式对话 — fetch + ReadableStream

**选择**: 使用 `fetch` + `ReadableStream` 解析 SSE 事件流，而非原生 `EventSource`（因为 POST 请求不被 EventSource 支持）。

**理由**: 后端 `/chat/stream` 是 POST 端点，原生 `EventSource` 仅支持 GET。使用 fetch API 可在所有现代浏览器中工作，无需额外依赖。

**替代方案**: 使用 `eventsource` npm 包 — 引入额外依赖，且对 POST SSE 支持仍需 polyfill。

### D5: 状态管理 — React useState + Context

**选择**: 继续使用组件级 `useState`，新增一个轻量的 `ApiContext` 提供全局 API 状态（连接状态、当前角色/user_id）。

**理由**: 原型阶段无需引入 Zustand/Redux 等状态库，React Context 足够满足跨组件共享角色和连接状态的需求。

**替代方案**: Zustand — 对原型阶段过重，增加依赖。

### D6: 新增页面采用 Tab 扩展模式

**选择**: 在现有 [`page.tsx`](../../../prototype/src/app/page.tsx) 的 Tabs 组件中新增 "MCP 管理"、"知识浏览"、"模型测试" 三个 Tab，每个 Tab 对应一个独立组件。

**理由**: 保持单页应用的导航体验，与现有 "AI 对话"、"结算异常"、"出院质控"、"运营看板" Tab 风格一致。

**替代方案**: 使用 Next.js App Router 多页面路由 — 增加路由复杂度，原型阶段单页 Tab 更直观。

### D7: MCP 管理页面替代 mcp-admin.html

**选择**: 将 [`mcp-admin.html`](../../../src/static/mcp-admin.html) 的功能完整迁移到 Next.js 组件中，并扩展为更丰富的管理界面（服务列表、健康状态面板、能力浏览表格）。

**理由**: 统一前端技术栈，消除独立 HTML 页面，利用 shadcn/ui 组件库提升视觉效果和交互体验。

### D8: 新增页面遵循现有交互设计语言

**选择**: 所有新增页面（MCP 管理、知识浏览、模型测试）严格沿用现有原型的交互模式和视觉风格：

| 模式 | 现有参考 | 新页面应用 |
|------|----------|------------|
| Tab 导航 | `page.tsx` 4 列 grid TabsList | 扩展为 7 列，新增图标+文字 Tab |
| 指标卡片 | `dashboard.tsx` 4 列 metrics grid | MCP 健康状态、知识资产统计、模型测试结果用相同 Card 样式 |
| Badge 状态 | `discharge-qc.tsx` 红/黄/绿风险标签 | MCP 服务状态、知识检索状态、模型错误用相同颜色编码 |
| Card 列表 | `page.tsx` SettlementExceptionList | MCP 服务列表、知识规则列表用相同 Card+hover 阴影样式 |
| Progress 进度条 | `dashboard.tsx` 科室排名 | 知识覆盖度、模型 token 用量用相同 Progress 组件 |
| 左右分栏 | `settlement-chat.tsx` 1:3 grid | 模型测试页面左侧参数+右侧结果用相同分栏布局 |
| 表单+操作 | `role-switcher.tsx` Select 下拉 | MCP 注册表单、场景选择用相同 Select/Input/Button 样式 |

**理由**: 保持原型交互一致性，用户无需学习新的操作模式。所有新页面使用相同的 shadcn/ui 组件库（Card, Badge, Button, Input, Select, Progress, Tabs, ScrollArea）。

**替代方案**: 为新页面设计独立的视觉风格 — 增加设计复杂度，原型阶段不值得投入。

**选择**: 将 [`mcp-admin.html`](../../../src/static/mcp-admin.html) 的功能完整迁移到 Next.js 组件中，并扩展为更丰富的管理界面（服务列表、健康状态面板、能力浏览表格）。

**理由**: 统一前端技术栈，消除独立 HTML 页面，利用 shadcn/ui 组件库提升视觉效果和交互体验。

## Risks / Trade-offs

- **[后端 API 变动]** → 前端类型定义需手工同步，可能遗漏 → 在 API 客户端中增加运行时类型校验（zod 可选），并在 tasks 中安排契约一致性验证步骤
- **[SSE 解析兼容性]** → 部分浏览器可能不支持 ReadableStream → 降级为非流式 `/chat` 端点，保持功能完整
- **[Mock 数据与真实数据结构不一致]** → 降级时 UI 可能显示异常 → 统一前端类型定义，mock 数据也遵循同一类型
- **[Next.js rewrites 仅在开发模式生效]** → 生产部署需另行配置反向代理 → 在 README 中明确说明，MVP 阶段仅支持开发模式联调
- **[知识扩展无独立 HTTP 端点]** → 知识浏览页面只能展示静态说明或 mock 数据 → 在页面中说明该功能通过对话内部调用，前端展示为只读信息面板
- **[MCP 管理页面功能受限于后端端点]** → 当前后端仅暴露服务注册和健康检查，能力注册/策略配置等 UI 需 mock 或预留 → 在 UI 中区分"已对接"和"演示中"功能区域
