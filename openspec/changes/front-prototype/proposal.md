## Why

现有 [`prototype/`](../../../prototype/) 是以静态模拟数据驱动的 Next.js 高保真原型，无法验证真实后端 API 契约、鉴权边界、错误处理与业务闭环体验。当前后端已具备统一导办入口、患者上下文、任务确认、MCP 服务管理、知识扩展和模型测试等 MVP API，但前端原型仅覆盖对话和质控两个场景。需要将原型全面接入真实接口，新增 MCP 管理、知识扩展浏览和模型测试页面，用于产品演示、联调验证与后续验收。

## What Changes

- 为 [`prototype/`](../../../prototype/) 增加后端 API 客户端、环境配置与类型化响应模型。
- 将 AI 导办对话从本地模拟回复切换为调用后端 `/api/v1/medical-insurance-ai-agent/chat`。
- 将患者上下文、工作流状态、任务确认等联调能力接入后端 API。
- 新增 MCP 服务管理页面：服务注册、存储健康检查、能力浏览与策略配置，替代现有简陋的 [`mcp-admin.html`](../../../src/static/mcp-admin.html)。
- 新增知识扩展浏览页面：展示知识资产、RAG 检索结果、规则解释和提示模板，对接后端知识扩展服务。
- 新增模型测试页面：提供模型调用测试界面，支持同步和流式两种模式，对接后端 `/model-test` 端点。
- 保留可演示的 mock 降级能力，确保后端未启动时仍可展示基础原型。
- 增加前端联调说明与验证脚本，支持本地同时启动后端与 Next.js 原型。

## Capabilities

### New Capabilities
- `frontend-api-integration`: 定义 Next.js 原型与院端医保智能体后端 API 的联调契约、降级策略、错误提示与任务确认交互要求。
- `frontend-mcp-management`: 定义 MCP 服务管理前端页面的注册、健康检查、能力浏览与策略配置交互要求。
- `frontend-knowledge-explorer`: 定义知识扩展浏览前端页面的资产展示、RAG 检索、规则解释与模板查看交互要求。
- `frontend-model-test`: 定义模型测试前端页面的同步/流式调用、参数配置与结果展示交互要求。

### Modified Capabilities
- 无

## Impact

- 影响 [`prototype/src/`](../../../prototype/src/) 下页面、组件、mock 数据与新增 API 客户端模块。
- 依赖后端现有 `/api/v1/medical-insurance-ai-agent` 路由和 `/api/v1/medical-insurance-ai-agent/mcp` 路由，不改变后端公开 API 契约。
- 需要新增前端环境变量，如 `NEXT_PUBLIC_API_BASE_URL`，默认指向本地 FastAPI 服务。
- 可能更新 [`prototype/README.md`](../../../prototype/README.md) 与交付文档，说明前后端联调启动流程。
- 新增页面将扩展 [`prototype/src/app/page.tsx`](../../../prototype/src/app/page.tsx) 的 Tab 导航结构。
