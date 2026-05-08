# [`prototype`](../../../prototype/) 前端统一与 [`src/static`](../../../src/static/) 清理设计

## 背景

当前前端主实现已经迁移到 [`prototype`](../../../prototype/)，基于 Next.js 提供高保真原型与后端 API 联调能力。旧的 [`src/static`](../../../src/static/) 目录仍包含 [`index.html`](../../../src/static/index.html)、[`mcp-admin.html`](../../../src/static/mcp-admin.html) 和未跟踪的 [`prototype.html`](../../../src/static/prototype.html)，并由 [`src/runtime/api/app.py`](../../../src/runtime/api/app.py) 的根路径、`/mcp-admin`、`/prototype` 静态路由暴露。

用户已明确：前端统一使用 [`prototype`](../../../prototype/) 目录，弃用 [`src/static`](../../../src/static/)；后端只保留 API。

## 目标

- 删除整个 [`src/static`](../../../src/static/) 目录，避免旧页面继续被误用。
- 移除 FastAPI 应用中的静态页面路由，只保留健康检查、版本/API 路由与 MCP API 路由。
- 删除依赖旧静态页面文件的测试。
- 更新项目说明，明确前端启动与维护位置为 [`prototype`](../../../prototype/)。
- 保留已有 CORS 配置和所有业务 API 行为。

## 备选方案

### 方案 A：完全删除旧静态前端（推荐）

删除 [`src/static`](../../../src/static/)、删除 `/`、`/mcp-admin`、`/prototype` 三个静态页面路由、删除旧静态页测试。优点是边界清晰，符合“后端只保留 API”；缺点是直接访问 FastAPI 根路径不再返回页面。

### 方案 B：删除静态文件但保留提示路由

删除 [`src/static`](../../../src/static/) 后，让 `/`、`/mcp-admin`、`/prototype` 返回 JSON 提示前端已迁移到 [`prototype`](../../../prototype/)。优点是用户访问旧地址可获得提示；缺点是后端仍承担前端入口语义，不符合“只保留 API”。

### 方案 C：仅删除 [`prototype.html`](../../../src/static/prototype.html)

只删除最近新增的旧原型静态页。优点是变更最小；缺点是继续保留旧 [`index.html`](../../../src/static/index.html) 和 [`mcp-admin.html`](../../../src/static/mcp-admin.html)，仍会造成入口混乱。

## 最终设计

采用方案 A。

### 后端应用

在 [`src/runtime/api/app.py`](../../../src/runtime/api/app.py) 中移除 `Path` 和 `FileResponse` 导入，删除返回静态文件的三个路由。保留：

- `/health`
- `/api/v1/medical-insurance-ai-agent` 下的业务 API
- MCP 管理 API 路由
- 现有 CORS 中间件

### 文件清理

删除：

- [`src/static/index.html`](../../../src/static/index.html)
- [`src/static/mcp-admin.html`](../../../src/static/mcp-admin.html)
- [`src/static/prototype.html`](../../../src/static/prototype.html)
- [`src/tests/integration/test_mcp_management_ui.py`](../../../src/tests/integration/test_mcp_management_ui.py)

### 文档更新

更新 [`AGENTS.md`](../../../AGENTS.md) 中“前端演示页”说明，改为指向 [`prototype`](../../../prototype/)，并说明 FastAPI 根路径不再承载页面。

如 [`README.md`](../../../README.md) 当前内容可正常编辑，则同步补充前端目录说明；若文件编码异常，则不在本次范围内重写，避免引入无关改动。

## 测试策略

- 运行 [`python -m pytest src/tests -q`](../../../AGENTS.md) 验证后端 API 与集成测试。
- 在 [`prototype`](../../../prototype/) 目录运行 [`npm run build`](../../../prototype/package.json) 验证前端目录可独立构建。
- 搜索 [`src/static`](../../../src/static/) 引用，确认不再存在运行时代码依赖。历史设计文档和归档记录中的引用可作为历史记录保留。

## 风险与边界

- 访问 FastAPI `/`、`/mcp-admin`、`/prototype` 将不再返回页面；这是目标行为。
- 不迁移或重写旧 HTML 页面功能，因为对应能力已在 [`prototype`](../../../prototype/) 中承接。
- 不删除历史设计文档、OpenSpec 归档中对 [`src/static`](../../../src/static/) 的历史引用。
