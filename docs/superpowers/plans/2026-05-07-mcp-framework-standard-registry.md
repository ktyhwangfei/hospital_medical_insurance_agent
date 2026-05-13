# MCP Framework Standard Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 MCP Framework 常见注册方式支持 `mcpServers` JSON 导入、stdio/sse/streamable_http MCP Server 标准字段存储、`tools/list` 自动发现、手工维护 tools 配置和页面展示。

**Architecture:** 在现有 `McpServer` / `McpCapability` 基础上扩展标准字段，通过 `payload_json` 保存完整配置并逐步增加结构化列。新增 config import service 将 `mcpServers` JSON 转换为内部 Server；新增 MCP discovery service 支持 stdio 子进程和 HTTP transport 的 `initialize` / `tools/list` 抽象；页面增加导入、发现、手工编辑和 schema 展示。

**Tech Stack:** Python 3、FastAPI、Pydantic、PostgreSQL、pytest、Next.js、React、TypeScript、MCP JSON-RPC。

---

## Task 1: 扩展 MCP 标准模型

**Files:**
- Modify: `src/knowledge_extension/mcp_registry/models.py`
- Modify: `src/tests/knowledge_extension/test_mcp_registry_models.py`

- [ ] 增加 Server 字段：`description`、`auth_type`、`connection_config`、`capabilities_summary`、`discovery_status`、`last_discovered_at`、`last_error`。
- [ ] 增加 Tool 字段：`title`、`annotations`、`invocation_config`、`discovery_source`、`discovery_payload`、`version`。
- [ ] 保持向后兼容：旧 payload 能正常实例化。

## Task 2: 支持 mcpServers JSON 导入

**Files:**
- Create: `src/knowledge_extension/mcp_registry/config_import.py`
- Modify: `src/runtime/api/mcp_routes.py`
- Test: `src/tests/knowledge_extension/test_mcp_config_import.py`
- Test: `src/tests/integration/test_mcp_management_api.py`

- [ ] 实现 `mcpServers` JSON 解析。
- [ ] 将 `{command,args,env,cwd}` 转换为 `transport=stdio`、`endpoint=stdio://<server_id>`、`connection_config`。
- [ ] 新增 API：`POST /api/v1/medical-insurance-ai-agent/mcp/servers/import-config`。
- [ ] 测试导入 drawio 配置后能在 `mcp_servers` 查询到 server。

## Task 3: 实现 MCP tools/list 发现抽象

**Files:**
- Create: `src/knowledge_extension/mcp_registry/discovery.py`
- Modify: `src/runtime/api/mcp_routes.py`
- Test: `src/tests/knowledge_extension/test_mcp_discovery.py`
- Test: `src/tests/integration/test_mcp_management_api.py`

- [ ] 定义 `McpDiscoveryClient` Protocol。
- [ ] 实现可测试的 `FakeMcpDiscoveryClient`。
- [ ] 定义发现流程：`initialize` → `tools/list` → 标准化 tool payload。
- [ ] 新增 API：`POST /mcp/servers/{server_id}/discover-tools`。
- [ ] 自动发现失败更新 server `discovery_status=failed` 和 `last_error`。
- [ ] 自动发现成功保存 tools 到 `mcp_capabilities`，`discovery_source=auto_tools_list`。

## Task 4: 持久化结构扩展

**Files:**
- Modify: `src/data_platform/storage/mcp/postgres.py`
- Modify: `src/tests/data_platform/test_mcp_postgres_storage.py`

- [ ] `mcp_servers` 增加结构化列：`description`、`auth_type`、`connection_config_json`、`discovery_status`、`last_discovered_at`、`last_error`。
- [ ] `mcp_capabilities` 增加结构化列：`name`、`description`、`input_schema_json`、`output_schema_json`、`annotations_json`、`invocation_config_json`、`discovery_source`、`discovery_payload_json`。
- [ ] 保存和读取时优先结构化列，保留 `payload_json` 兼容。

## Task 5: 前端 MCP 页面标准化

**Files:**
- Modify: `prototype/src/lib/types.ts`
- Modify: `prototype/src/lib/api-client.ts`
- Modify: `prototype/src/components/mcp-management.tsx`

- [ ] 增加 `mcpServers` JSON 导入 textarea 和导入按钮。
- [ ] Server 卡片展示 transport、endpoint、auth_type、discovery_status、last_error。
- [ ] Server 卡片增加“发现 Tools”按钮。
- [ ] Tool 列表展示 name、description、risk、discovery_source、enabled。
- [ ] Tool 详情展示 inputSchema、outputSchema、annotations、invocation_config。
- [ ] 支持手工新增/编辑 Tool 配置。

## Task 6: 验证

**Files:**
- No required production changes.

- [ ] 运行后端测试：`python -m pytest src/tests/knowledge_extension/test_mcp_config_import.py src/tests/knowledge_extension/test_mcp_discovery.py src/tests/integration/test_mcp_management_api.py src/tests/data_platform/test_mcp_postgres_storage.py -v`
- [ ] 运行前端 lint：在 `prototype` 下执行 `npm run lint`
- [ ] 运行 `git diff --check`
- [ ] 页面验证：粘贴 drawio `mcpServers` 配置后能注册 stdio server；点击发现 Tools 后能展示 tools/schema；可手工编辑 Tool 配置。
