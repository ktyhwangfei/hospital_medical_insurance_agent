# MCP Server Tool Boundary Adjustment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前偏业务 skill 的 MCP demo tools 调整为两个 MCP Server 下的原子 tools，并让页面按 Server → Tools 展示。

**Architecture:** 保留现有 MCP registry/storage/client gateway 抽象，重构 demo 数据定义为两个 server 和四个原子 tool。AI 导办场景继续输出 `mcp_insights`，但 insight 来源从业务型 tool 改为原子 tool。MCP 管理 API 新增 capability 查询接口，前端按 server 分组展示 tools。

**Tech Stack:** Python 3、FastAPI、Pydantic、pytest、PostgreSQL MCP storage、Next.js、React、TypeScript。

---

## Task 1: 重构 demo MCP 数据为两个 Server 四个原子 Tool

**Files:**
- Modify: `src/knowledge_extension/mcp_registry/demo_tools.py`
- Modify: `src/runtime/api/mcp_routes.py`
- Modify: `src/tests/knowledge_extension/test_mcp_demo_tools.py`

- [ ] 将旧 server `demo-mcp-medical-insurance` 拆为：
  - `medical-insurance-policy-knowledge-mcp`
  - `pre-discharge-qc-knowledge-mcp`
- [ ] 将旧 tools 替换为：
  - `query_policy_by_error_code`
  - `search_policy_clause`
  - `get_pre_discharge_checklist`
  - `match_drug_restriction`
- [ ] 更新 tool output，确保 `source` 为 server_id，`tool_name` 为原子 tool 名称。
- [ ] 更新测试断言，禁止再出现 `explain_settlement_error` 和 `pre_discharge_risk_supplement`。

## Task 2: 新增 MCP capability 查询 API

**Files:**
- Modify: `src/runtime/api/mcp_routes.py`
- Modify: `src/tests/integration/test_mcp_management_api.py`

- [ ] 新增 `GET /api/v1/medical-insurance-ai-agent/mcp/capabilities`。
- [ ] 新增 `GET /api/v1/medical-insurance-ai-agent/mcp/servers/{server_id}/capabilities`。
- [ ] 返回 capability 的 public JSON，包括 `capability_id`、`server_id`、`name`、`capability_type`、`description`、`supported_scenarios`、`risk_level`、`enabled`。
- [ ] 编写测试验证 server 下 tools 可查询。

## Task 3: AI 导办使用原子 Tool 名称输出 MCP insights

**Files:**
- Modify: `src/business_scenarios/settlement_exception_guide/service.py`
- Modify: `src/business_scenarios/pre_discharge_joint_qc/service.py`
- Modify: `src/tests/integration/test_mcp_runtime_integration.py`

- [ ] 结算失败导办改为调用 `query_policy_by_error_code`，必要时可附加 `search_policy_clause`。
- [ ] 出院前风险导办改为调用 `get_pre_discharge_checklist`，必要时可附加 `match_drug_restriction`。
- [ ] 测试断言响应中出现原子 tool 名称和对应 server id。

## Task 4: 前端 MCP 页面按 Server → Tools 展示

**Files:**
- Modify: `prototype/src/lib/types.ts`
- Modify: `prototype/src/lib/api-client.ts`
- Modify: `prototype/src/components/mcp-management.tsx`

- [ ] 增加 `McpCapability` 前端类型。
- [ ] 增加 `fetchMcpCapabilities()` API client。
- [ ] MCP 管理页面刷新时同时加载 servers 和 capabilities。
- [ ] 页面卡片先展示 server，再在 server 内展示 tools 列表。
- [ ] 移除或弱化顶部静态 mock capability 统计，避免误导为真实 MCP tools。

## Task 5: 验证

**Files:**
- No required production changes.

- [ ] 运行：`python -m pytest src/tests/knowledge_extension/test_mcp_demo_tools.py src/tests/integration/test_mcp_management_api.py src/tests/integration/test_mcp_runtime_integration.py -v`
- [ ] 在 `prototype` 下运行：`npm run lint`
- [ ] 运行：`git diff --check`
- [ ] 页面验证：MCP 管理页显示两个 MCP Server，每个 Server 下有各自 tools；AI 导办显示原子 tool 名称来源。
