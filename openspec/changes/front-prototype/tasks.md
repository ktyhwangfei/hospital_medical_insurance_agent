## 1. 基础设施与类型定义

- [ ] 1.1 创建 `prototype/src/lib/types.ts`，定义与后端 schema 一致的 TypeScript interface（`ChatRequest`, `AgentResponse`, `PatientContextResponse`, `TaskConfirmRequest`, `TaskConfirmResponse`, `WorkflowStatusResponse`, `TaskStatusResponse`, `ModelTestRequest`, `ModelTestResponse`, `McpServer`, `McpStorageHealth`, `SSEEvent`）
- [ ] 1.2 创建 `prototype/.env.example`，说明 `NEXT_PUBLIC_API_BASE_URL` 配置项，默认 `http://127.0.0.1:8000`
- [ ] 1.3 修改 `prototype/next.config.ts`，添加 `rewrites` 将 `/api/v1/medical-insurance-ai-agent/:path*` 代理到 `NEXT_PUBLIC_API_BASE_URL`
- [ ] 1.4 验证代理配置：启动后端 + Next.js dev server，浏览器访问 `/api/v1/medical-insurance-ai-agent/version` 返回正确 JSON

## 2. API 客户端模块

- [ ] 2.1 创建 `prototype/src/lib/api-client.ts`，实现 `sendChat` 函数（POST `/chat`），含类型化请求/响应和 try/catch mock 降级
- [ ] 2.2 实现 `sendChatStream` 函数（POST `/chat/stream`），使用 `fetch` + `ReadableStream` 解析 SSE 事件流，支持 `step`/`final`/`error`/`done` 四种事件类型
- [ ] 2.3 实现 `fetchPatientContext` 函数（GET `/patient-context/{pid}/{eid}`），含 mock 降级
- [ ] 2.4 实现 `confirmTask` 函数（POST `/tasks/confirm`），含 mock 降级
- [ ] 2.5 实现 `fetchWorkflowStatus` 函数（GET `/workflows/{id}`），含 mock 降级
- [ ] 2.6 实现 `fetchTaskStatus` 函数（GET `/tasks/{id}`），含 mock 降级
- [ ] 2.7 实现 `testModel` 函数（POST `/model-test`），含 mock 降级
- [ ] 2.8 实现 `testModelStream` 函数（POST `/model-test/stream`），使用 SSE 解析
- [ ] 2.9 实现 `fetchMcpStorageHealth` 函数（GET `/mcp/storage/health`），含 mock 降级
- [ ] 2.10 实现 `registerMcpServer` 函数（POST `/mcp/servers`），含 mock 降级
- [ ] 2.11 统一所有函数的错误处理模式：网络错误 → 返回 mock 数据 + `fallback: true`；HTTP 错误 → 抛出带 `error_code` 的结构化错误

## 3. 对话组件集成

- [ ] 3.1 重构 `prototype/src/components/settlement-chat.tsx` 的 `handleSend` 函数，调用 `sendChat` 替代 `setTimeout` mock
- [ ] 3.2 处理 `needs_clarification` 状态：当后端返回 `missing_fields` 非空时，在对话中显示缺失字段提示
- [ ] 3.3 处理 `waiting_human_confirmation` 状态：当后端返回 `blocked_actions` 非空时，显示高风险拦截卡片，包含确认/拒绝按钮
- [ ] 3.4 将角色参数 `currentRole` 作为 `role` 字段传递给 `sendChat` 请求
- [ ] 3.5 实现 SSE 流式对话模式：调用 `sendChatStream`，实时显示 step 进度提示和 final 结果
- [ ] 3.6 保留快捷问题功能，确保预设问题仍可正常触发后端对话

## 4. 任务确认与患者上下文集成

- [ ] 4.1 在高风险拦截卡片中实现确认按钮，调用 `confirmTask({ task_id, action: 'confirm', user_id, reason })`
- [ ] 4.2 在高风险拦截卡片中实现拒绝按钮，调用 `confirmTask({ task_id, action: 'reject', user_id, reason })`
- [ ] 4.3 实现确认/拒绝结果的 UI 反馈（成功提示、状态更新）
- [ ] 4.4 在患者信息展示区域集成 `fetchPatientContext`，根据 `visible_fields` 动态渲染字段

## 5. MCP 管理页面

- [ ] 5.1 创建 `prototype/src/components/mcp-management.tsx` 组件，包含服务注册表单（server_id, name, endpoint, transport 下拉）和注册按钮
- [ ] 5.2 实现服务注册功能：表单提交调用 `registerMcpServer`，成功后更新服务列表，失败显示后端错误消息
- [ ] 5.3 实现存储健康检查面板：调用 `fetchMcpStorageHealth`，格式化展示 JSON 结果
- [ ] 5.4 实现已注册服务列表展示：表格形式显示服务 ID、名称、端点、传输类型、状态
- [ ] 5.5 实现能力浏览区域：四个分类卡片（Tool/Resource/Prompt/Service），展示 mock 能力数据并标注"演示数据"
- [ ] 5.6 在 `prototype/src/app/page.tsx` 的 Tabs 中新增 "MCP 管理" Tab，引入 `mcp-management.tsx` 组件

## 6. 知识扩展浏览页面

- [ ] 6.1 创建 `prototype/src/components/knowledge-explorer.tsx` 组件，包含知识资产概览面板
- [ ] 6.2 实现知识资产分类卡片：错误码知识库、政策规则库、DRG/DIP 知识库，显示条目数量（mock 数据，标注"演示数据"）
- [ ] 6.3 实现 RAG 检索测试区域：输入框 + 检索按钮 + 模拟检索结果列表（来源、相关度、摘要）
- [ ] 6.4 实现规则解释展示区域：错误码解释卡片（ERR_001/002/003，含描述、原因、步骤）和 DRG/DIP 规则摘要
- [ ] 6.5 实现提示模板预览区域：模板列表（名称、场景、角色），mock 数据标注"演示数据"
- [ ] 6.6 在 `prototype/src/app/page.tsx` 的 Tabs 中新增 "知识浏览" Tab，引入 `knowledge-explorer.tsx` 组件

## 7. 模型测试页面

- [ ] 7.1 创建 `prototype/src/components/model-test.tsx` 组件，包含参数配置区域（消息输入框 + 场景下拉框）
- [ ] 7.2 实现同步模式测试：调用 `testModel`，展示响应内容、模型名称、延迟、token 用量
- [ ] 7.3 实现流式模式测试：调用 `testModelStream`，实时追加输出文本
- [ ] 7.4 处理模型测试错误：503 配置错误、502 上游错误、429 限流等，显示对应中文提示
- [ ] 7.5 实现测试历史记录：时间倒序展示，包含时间戳、场景、延迟、响应摘要，支持清除历史
- [ ] 7.6 在 `prototype/src/app/page.tsx` 的 Tabs 中新增 "模型测试" Tab，引入 `model-test.tsx` 组件

## 8. 连接状态与全局上下文

- [ ] 8.1 创建 `prototype/src/lib/api-context.tsx`，提供 `ApiProvider` Context，管理连接状态（`connected`/`fallback`）和全局 `user_id`
- [ ] 8.2 在 `prototype/src/app/layout.tsx` 中包裹 `ApiProvider`
- [ ] 8.3 在页面顶部导航栏添加连接状态指示器（绿色"已连接" / 橙色"离线模式"）
- [ ] 8.4 API 客户端函数在成功请求后通知 Context 更新为 `connected`，失败时更新为 `fallback`

## 9. Mock 数据扩展

- [ ] 9.1 扩展 `prototype/src/lib/mock-data.ts`，新增 MCP 相关 mock 数据（示例服务列表、能力列表、健康检查响应）
- [ ] 9.2 新增知识扩展 mock 数据（知识资产统计、RAG 检索结果、规则解释、提示模板列表）
- [ ] 9.3 新增模型测试 mock 数据（模拟模型响应，含 content、model_name、latency_ms、token 用量）

## 10. 验证与文档

- [ ] 10.1 端到端验证：启动后端 + 前端，测试"为什么这个患者结算失败"对话走通真实 API
- [ ] 10.2 降级验证：停止后端，确认前端自动回退到 mock 数据且显示"离线模式"标记
- [ ] 10.3 任务确认验证：触发高风险动作 → 确认/拒绝 → 验证 UI 反馈正确
- [ ] 10.4 MCP 管理验证：注册服务 → 查看健康状态 → 验证服务列表更新
- [ ] 10.5 模型测试验证：同步模式测试 → 流式模式测试 → 验证历史记录
- [ ] 10.6 更新 `prototype/README.md`，添加前后端联调启动说明（后端 `uvicorn` + 前端 `npm run dev`）
- [ ] 10.7 更新 `prototype/原型交付文档.md`，补充 API 集成、MCP 管理、知识浏览、模型测试章节
