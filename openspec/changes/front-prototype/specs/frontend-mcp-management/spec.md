## ADDED Requirements

### Requirement: MCP Management Tab Navigation

系统 SHALL 在 `prototype/src/app/page.tsx` 的 Tabs 组件中新增 "MCP 管理" Tab，使用与现有 Tab 相同的图标+文字样式（参考 `Server` 图标 from lucide-react），TabsList 从 4 列扩展为 7 列 grid。

#### Scenario: MCP management tab visible
- **WHEN** 用户打开原型首页
- **THEN** 顶部 Tab 导航 SHALL 显示 7 个 Tab：AI导办对话、结算异常导办、出院前联合质控、运营驾驶舱、MCP管理、知识浏览、模型测试

### Requirement: MCP Server Registration Form

系统 SHALL 在 MCP 管理 Tab 中提供服务注册表单，使用与 `role-switcher.tsx` 相同的 Select/Input/Button 组件样式。表单包含 `server_id`、`name`、`endpoint`、`transport`（下拉选择 sse/streamable_http/stdio）字段，提交后调用后端 `POST /api/v1/medical-insurance-ai-agent/mcp/servers`。

#### Scenario: Register a new MCP server
- **WHEN** 用户填写服务注册表单并点击"注册"按钮
- **THEN** 前端调用 `registerMcpServer({ server_id, name, endpoint, transport, status: 'enabled' })`，成功后在服务列表中显示新注册的服务

#### Scenario: Registration validation error
- **WHEN** 用户提交表单但 `server_id` 或 `name` 为空
- **THEN** 前端 SHALL 显示表单验证错误提示，不发送请求

#### Scenario: Registration backend error
- **WHEN** 后端返回 400 或 500 错误
- **THEN** 前端 SHALL 显示错误消息（来自后端 `detail.message`），保留表单填写内容

### Requirement: MCP Storage Health Check

系统 SHALL 在 MCP 管理 Tab 中提供存储健康检查面板，调用 `GET /api/v1/medical-insurance-ai-agent/mcp/storage/health` 并展示结果。

#### Scenario: Display storage health status
- **WHEN** 用户点击"查看存储状态"按钮或页面加载时
- **THEN** 前端调用 `fetchMcpStorageHealth()`，将返回的 JSON 格式化展示在面板中

#### Scenario: Health check with fallback
- **WHEN** 后端不可达时调用健康检查
- **THEN** 前端 SHALL 显示"存储服务不可用"提示，并标记为离线模式

### Requirement: MCP Server List Display

系统 SHALL 在 MCP 管理 Tab 中展示已注册的 MCP 服务列表，使用与 `page.tsx` SettlementExceptionList 相同的 Card 列表样式（白色背景、hover 阴影、Badge 状态标签）。每个服务卡片显示服务 ID、名称、端点、传输类型和状态。

#### Scenario: Display registered servers
- **WHEN** MCP 管理 Tab 加载
- **THEN** 前端 SHALL 展示已注册服务的列表（当前从 mock 数据获取，后续对接后端列表端点）

#### Scenario: Empty server list
- **WHEN** 没有已注册的服务
- **THEN** 前端 SHALL 显示"暂无已注册服务"的空状态提示

### Requirement: MCP Capability Browse Section

系统 SHALL 在 MCP 管理 Tab 中提供能力浏览区域，使用与 `dashboard.tsx` 指标卡片相同的 4 列 grid Card 布局，展示 MCP 工具、资源、提示和服务能力的分类信息。

#### Scenario: Display capability categories
- **WHEN** MCP 管理 Tab 加载
- **THEN** 前端 SHALL 显示四个能力分类卡片：工具（Tool）、资源（Resource）、提示（Prompt）、服务（Service），每个卡片显示对应类型的能力数量

#### Scenario: Capability data from mock
- **WHEN** 后端不提供能力列表端点
- **THEN** 前端 SHALL 使用 mock 数据展示示例能力信息，并在 UI 中标注"演示数据"
