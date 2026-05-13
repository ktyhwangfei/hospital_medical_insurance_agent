# 后端架构升级：MCP SDK + LangGraph + Skill 降级

## TL;DR

> **Quick Summary**: 用官方 MCP Python SDK 替换自写 MCP 传输层，用 LangGraph 统一替换 engine.py 和 orchestration/service.py 两条硬编码执行路径，Skill 从通用市场模型降级为领域工作流模板，MCP 注册/发现参考开源 Gateway 架构自建。
> 
> **Deliverables**:
> - MCP transport 层：mcp SDK streamable_http/stdio client 替换自写 StdioMcpClient + InMemoryMcpClientGateway
> - 编排层：单个统一 LangGraph StateGraph 替换 engine.py + orchestration/service.py 的 if/elif 链
> - 领域模型：Skill/Tool 降级为工作流模板，去 ExecutionStrategy/Step mapping，去枚举重复
> - MCP 注册/发现：参考 MCP Gateway 架构重构，保留现有 API 契约
> - 两个业务场景完整迁移到 LangGraph
> - TDD 全量测试覆盖
> 
> **Estimated Effort**: Large
> **Parallel Execution**: YES — 5 waves
> **Critical Path**: MCP SDK 引入 → LangGraph 基础设施 → 业务场景迁移 → 模型清理 → 旧代码删除

---

## Context

### Original Request
后端 MCP 管理和 Skill 管理太初级，缺乏生产级能力。参考外部建议：MCP 层用官方 SDK、编排层用 LangGraph、Skill 降级为模板、管理 UI 最小化。

### Interview Summary
**Key Discussions**:
- 审计发现 6 个后端缺口：无 SSE/HTTP 客户端、无连接池、无 Redis、Skill/Tool 仅内存、引擎硬编码、MCP 调用未接入
- 编排引擎：选 LangGraph（非 Semantic Kernel），interrupt() 天然适配人工确认
- 迁移策略：一次性替换（非渐进），所有测试通过即上线
- MCP Gateway：参考架构自建（非部署外部平台），用 mcp SDK transport
- 测试策略：TDD，先写测试再写实现

**Metis 发现的关键风险**:
- **两条执行路径**：不止 engine.py，`orchestration/service.py` 也有独立的 if/elif 链 → 计划用统一 LangGraph 图替换两者
- **枚举重复**：StepType vs ToolType、McpRiskLevel vs RiskLevel → 计划中合并
- **SkillStep.depends_on** 天然映射 LangGraph 边 → 降低迁移复杂度

### Research Findings
- mcp SDK v1.19 稳定版，streamable_http_client + ClientSession 覆盖全部传输需求
- LangGraph interrupt() → waiting_human_confirmation 映射
- LangGraph checkpoint → 审计持久化映射
- psycopg_pool 官方连接池（已有 psycopg 3）
- redis-py 官方客户端（已有 RedisMcpCache 接口）

### Metis Review
**Identified Gaps** (addressed in plan):
- **Q1 两条执行路径**: 统一为一个 LangGraph 图，同时替换 engine.py 和 orchestration/service.py → Wave 2 解决
- **Q2 SkillStep.depends_on 映射**: 直接转 LangGraph add_edge → Wave 2 解决
- **Q3 状态对象定义**: 每个业务场景一个 TypedDict State → Wave 1 定义
- **Q4 业务场景服务封装**: 保留现有 adapters/ 调用，包装为 LangGraph node → Wave 3 解决
- **Q5 ExecutionStrategy 枚举**: 移除，LangGraph 图结构自然表达 → Wave 4 解决
- **Q6 InMemoryMcpClientGateway**: 完全删除，mcp SDK 原生支持 → Wave 1 解决

---

## Work Objectives

### Core Objective
用官方 MCP Python SDK + LangGraph 替换自写的 MCP 客户端和硬编码编排引擎，Skill 模型降级为工作流模板，MCP 注册/发现参考开源架构重构。

### Concrete Deliverables
- `src/knowledge_extension/mcp_registry/transport.py` — 基于 mcp SDK 的统一传输层
- `src/runtime/langgraph/` — LangGraph 状态图基础设施（State、Graph、Nodes）
- `src/runtime/langgraph/settlement_exception.py` — 结算异常导办 LangGraph 图
- `src/runtime/langgraph/pre_discharge_qc.py` — 出院前联合质控 LangGraph 图
- `src/domain/skill/models.py` — 简化后的 Skill/Tool 模型
- `src/tests/langgraph/` — TDD 测试套件
- 删除: `engine.py` 硬编码部分、`orchestration/service.py` if/elif 链、`InMemoryMcpClientGateway`

### Definition of Done
- [ ] `python -m pytest src/tests -v` 全部通过（含新 langgraph/ transport/ 测试）
- [ ] `POST /chat` 结算异常消息 → LangGraph 图执行 → 返回 AgentResponse（含 citations）
- [ ] `POST /chat` 出院前质控消息 → LangGraph 图执行 → 返回 AgentResponse（含 citations）
- [ ] 高风险动作 → interrupt() → waiting_human_confirmation → POST /tasks/confirm → 继续执行
- [ ] MCP 工具调用经过 mcp SDK 的 streamable_http_client → 真实 MCP server 响应
- [ ] @-mention 技能调用正常工作
- [ ] 意图匹配自动路由到正确的 LangGraph 图
- [ ] API 响应格式不变（AgentResponse 结构、字段名、路由前缀）

### Must Have
- mcp SDK transport 替换自写 stdio client 和 client gateway
- 统一 LangGraph 图替换两条硬编码执行路径
- Skill/Tool 枚举去重（StepType/ToolType、McpRiskLevel/RiskLevel）
- TDD 覆盖全部新增和修改代码
- API 契约完整兼容（路由、请求体、响应体、错误格式）

### Must NOT Have (Guardrails)
- 不引入新 API 路由或修改现有路由前缀
- 不改变 AgentResponse 响应结构中的任何字段名
- 不在 LangGraph node 中直接调用外部系统（必须通过 adapters/）
- 不做 PostgreSQL/Redis 持久化（那是另一个计划）
- 不修改前端原型
- 不引入 Semantic Kernel
- 不部署外部 MCP Gateway 平台
- LangGraph 版本锁定（避免 breaking change）
- 不在 LangGraph State 中传播中文关键词（用 intent_id）
- 不删除现有 adapters/ 接口（保留所有 Protocol）

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed.

### Test Decision
- **Infrastructure exists**: YES (pytest + FastAPI TestClient)
- **Automated tests**: TDD
- **Framework**: pytest + pytest-asyncio
- **Each task**: RED (failing test) → GREEN (minimal impl) → REFACTOR → COMMIT

### QA Policy
Every task includes agent-executed QA scenarios.
- **API**: Bash (curl) — 发送请求，断言 status code + 响应字段
- **Python module**: Bash (pytest) — 运行测试，断言通过
- **Import check**: Bash (python -c) — 验证模块可导入

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (MCP 基础设施 — MAX PARALLEL):
├── Task 1: mcp SDK 引入 + 传输层封装
├── Task 2: LangGraph 引入 + 基础设施
├── Task 3: LangGraph State 类型定义
└── Task 4: MCP transport 层 TDD 测试

Wave 2 (LangGraph 图构建 — MAX PARALLEL):
├── Task 5: 结算异常导办 LangGraph 图
├── Task 6: 出院前联合质控 LangGraph 图
└── Task 7: LangGraph interrupt + 人工确认模式

Wave 3 (业务场景迁移 — 依赖 Wave 2):
├── Task 8: 业务场景服务适配 LangGraph node
└── Task 9: 编排层统一（替换 route 中的调用链）

Wave 4 (模型清理 — 依赖 Wave 3):
├── Task 10: Skill/Tool 领域模型简化
├── Task 11: 枚举去重（StepType/ToolType, RiskLevel）
└── Task 12: 种子数据迁移

Wave 5 (集成验证 + 旧代码清理):
├── Task 13: 端到端集成测试
├── Task 14: 删除旧代码（engine.py 硬编码、orchestration if/elif、InMemoryMcpClientGateway）
└── Task 15: 全量回归测试 + API 契约验证

Critical Path: Task 1 → Task 2 → Task 5 → Task 8 → Task 9 → Task 13 → Task 15
Max Concurrent: 4 (Wave 1)
```

---

## TODOs

- [ ] 1. **引入 mcp SDK + 传输层封装**

  **What to do**:
  - `pip install mcp` 添加到 requirements
  - 创建 `src/knowledge_extension/mcp_registry/transport.py`
  - 实现 `McpTransport` 类，封装 `streamable_http_client` + `ClientSession`
  - 支持 stdio 和 streamable_http 两种传输
  - 实现 `initialize()` → `list_tools()` → `call_tool()` 完整生命周期
  - 错误处理：连接失败、协议错误、超时

  **Must NOT do**:
  - 不修改现有 `stdio_client.py`（保留作为参考，Wave 5 删除）
  - 不改变现有 `McpServer` 模型
  - 不引入新的外部依赖（mcp SDK 除外）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 需要理解 MCP 协议和现有 stdio_client.py 的协议映射

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2, 3, 4)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 5, 6
  - **Blocked By**: None

  **References**:
  - `src/knowledge_extension/mcp_registry/stdio_client.py` — 现有自写 MCP JSON-RPC 协议实现，理解 `initialize`/`tools/list`/`tools/call` 的调用模式和错误处理
  - `src/knowledge_extension/mcp_registry/client_gateway.py` — InMemoryMcpClientGateway 接口，理解 transport 需要暴露的方法签名
  - `src/knowledge_extension/mcp_registry/models.py` — McpServer、McpCapability、McpTransportType 模型，理解 transport 产出的数据形状
  - `mcp` SDK docs: `https://github.com/modelcontextprotocol/python-sdk` — 官方 SDK streamable_http_client 和 ClientSession API

  **Acceptance Criteria**:
  - [ ] `python -c "from mcp import ClientSession; print('mcp SDK OK')"` 成功
  - [ ] `McpTransport` 类可导入
  - [ ] `McpTransport.list_tools(server)` 返回 `List[McpCapability]`
  - [ ] `McpTransport.call_tool(server, tool_name, args)` 返回 dict

  **QA Scenarios**:
  ```
  Scenario: mcp SDK import
    Tool: Bash
    Steps:
      1. python -c "from mcp import ClientSession; from mcp.client.streamable_http import streamable_http_client; print('SDK_OK')"
    Expected Result: stdout contains "SDK_OK"
    Failure Indicators: ImportError, ModuleNotFoundError
    Evidence: .sisyphus/evidence/task-1-sdk-import.txt

  Scenario: McpTransport module import
    Tool: Bash
    Steps:
      1. python -c "from src.knowledge_extension.mcp_registry.transport import McpTransport; print('TRANSPORT_OK')"
    Expected Result: stdout contains "TRANSPORT_OK"
    Failure Indicators: ImportError
    Evidence: .sisyphus/evidence/task-1-transport-import.txt
  ```

  **Commit**: YES
  - Message: `feat(mcp): introduce official mcp SDK transport layer`
  - Files: `requirements.txt`, `src/knowledge_extension/mcp_registry/transport.py`
  - Pre-commit: `python -c "from src.knowledge_extension.mcp_registry.transport import McpTransport"`

- [ ] 2. **LangGraph 引入 + 基础设施搭建**

  **What to do**:
  - `pip install langgraph langgraph-checkpoint` 添加到 requirements
  - 创建 `src/runtime/langgraph/__init__.py`
  - 创建 `src/runtime/langgraph/states.py` — 定义 `BaseAgentState` TypedDict（公共字段：messages, intent, role, workflow_id, citations, uncertainties, requires_confirmation）
  - 创建 `src/runtime/langgraph/graph_builder.py` — `build_agent_graph()` 工厂函数，接受 nodes 和 edges 配置，返回 `StateGraph`
  - 创建 `src/runtime/langgraph/nodes.py` — 通用 LangGraph node 实现：
    - `adapter_call_node`: 通过 capability_ref 路由到 adapters/ 层
    - `human_confirmation_node`: 调用 `interrupt()` 暂停等待人工确认
    - `response_build_node`: 构建 AgentResponse
  - 创建 `src/runtime/langgraph/checkpoint.py` — MemorySaver 或 SqliteSaver 用于 checkpoint 持久化

  **Must NOT do**:
  - 不修改现有 `engine.py`（保留运行，Wave 5 删除）
  - 不在 LangGraph node 中直接调用外部系统（必须通过 adapters/）
  - 不创建新的 API 路由（复用现有 routes.py）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 需要理解 LangGraph 的 StateGraph API 和现有 engine.py 的执行模式

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 1, 3, 4)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 5, 6, 7
  - **Blocked By**: None

  **References**:
  - `src/runtime/skill_registry/engine.py` — SkillExecutionEngine 的执行策略（sequential/parallel/conditional），理解现有执行模式
  - `src/runtime/orchestration/service.py` — 第二条硬编码执行路径，`execute_plan()` 中的 if/elif 链
  - `src/domain/skill/models.py` — SkillStep.depends_on、ExecutionStrategy 枚举，理解 DAG 依赖关系
  - `src/runtime/api/routes.py:process_chat_request` — 理解当前 /chat 入口的调用链
  - LangGraph docs: `https://langchain-ai.github.io/langgraph/` — StateGraph、interrupt、checkpoint API

  **Acceptance Criteria**:
  - [ ] `python -c "from langgraph.graph import StateGraph; print('LG_OK')"` 成功
  - [ ] `BaseAgentState` TypedDict 包含所有公共字段
  - [ ] `build_agent_graph()` 函数返回 `StateGraph` 实例
  - [ ] `adapter_call_node` 能通过 capability_ref 前缀路由到 adapters/

  **QA Scenarios**:
  ```
  Scenario: LangGraph import
    Tool: Bash
    Steps:
      1. python -c "from langgraph.graph import StateGraph; from langgraph.checkpoint.memory import MemorySaver; print('LangGraph_OK')"
    Expected Result: stdout contains "LangGraph_OK"
    Evidence: .sisyphus/evidence/task-2-langgraph-import.txt

  Scenario: State type creation
    Tool: Bash
    Steps:
      1. python -c "from src.runtime.langgraph.states import BaseAgentState; s = BaseAgentState(intent='test', role='cashier', messages=[], citations=[], uncertainties=[], requires_confirmation=False, workflow_id='wf1'); print(s['intent'])"
    Expected Result: stdout contains "test"
    Evidence: .sisyphus/evidence/task-2-state-type.txt
  ```

  **Commit**: YES
  - Message: `feat(langgraph): add unified state graph infrastructure`
  - Files: `requirements.txt`, `src/runtime/langgraph/__init__.py`, `states.py`, `graph_builder.py`, `nodes.py`, `checkpoint.py`

- [ ] 3. **LangGraph State 类型定义（两个业务场景）**

  **What to do**:
  - 创建 `src/runtime/langgraph/settlement_state.py` — 继承 `BaseAgentState`，添加结算特有字段：`claim_detail`, `error_code`, `error_detail`, `recommendation`, `blocked_actions`
  - 创建 `src/runtime/langgraph/pre_discharge_state.py` — 继承 `BaseAgentState`，添加出院前特有字段：`patient_summary`, `quality_issues`, `rule_results`, `qc_recommendation`
  - 确保所有字段使用 Pydantic BaseModel 或 TypedDict（禁止裸 dict）
  - 写对应的 TDD 测试

  **Must NOT do**:
  - 不在 State 中使用裸 dict
  - 不在 State 中传播中文关键词

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: 类型定义为主，需要理解现有业务场景的数据流

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 1, 2, 4)
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 5, 6
  - **Blocked By**: Task 2 (BaseAgentState)

  **References**:
  - `src/business_scenarios/settlement_exception_guide/service.py` — 理解结算异常的数据流（claim_id → query_claim → get_error_detail → build_recommendation）
  - `src/business_scenarios/pre_discharge_joint_qc/service.py` — 理解出院前质控的数据流（patient_id → get_summary → run_rules → build_qc）
  - `src/domain/patient/models.py` — PatientSummary 字段
  - `src/domain/insurance/models.py` — ClaimDetail 字段

  **Acceptance Criteria**:
  - [ ] `SettlementState` TypedDict 包含所有结算特有字段
  - [ ] `PreDischargeState` TypedDict 包含所有出院前特有字段
  - [ ] 无裸 dict 类型

  **QA Scenarios**:
  ```
  Scenario: SettlementState instantiation
    Tool: Bash
    Steps:
      1. python -c "from src.runtime.langgraph.settlement_state import SettlementState; s = SettlementState(intent='settlement', role='cashier', messages=[], citations=[], uncertainties=[], requires_confirmation=False, workflow_id='wf1', claim_detail={}, error_code='', error_detail={}, recommendation='', blocked_actions=[]); print(s.keys())"
    Expected Result: stdout contains "claim_detail", "error_code", "recommendation"
    Evidence: .sisyphus/evidence/task-3-state.txt
  ```

  **Commit**: YES
  - Message: `feat(langgraph): define business scenario state types`
  - Files: `src/runtime/langgraph/settlement_state.py`, `src/runtime/langgraph/pre_discharge_state.py`

- [ ] 4. **MCP transport 层 TDD 测试**

  **What to do**:
  - 创建 `src/tests/mcp_registry/test_transport.py`
  - 写测试：mock mcp SDK 的 streamable_http_client → 验证 McpTransport 正确封装
  - 写测试：传输类型选择（stdio vs streamable_http）
  - 写测试：连接失败 → 抛出明确异常
  - 写测试：list_tools → 返回 List[McpCapability]
  - 写测试：call_tool → 返回 dict 结果
  - 写测试：session 生命周期管理

  **Must NOT do**:
  - 不依赖真实 MCP server（用 unittest.mock）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 需要理解 mcp SDK 的 async context manager 模式和 mock 策略

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 1, 2, 3)
  - **Parallel Group**: Wave 1
  - **Blocks**: None
  - **Blocked By**: Task 1

  **References**:
  - `src/knowledge_extension/mcp_registry/stdio_client.py` — 现有 stdio client 测试模式参考
  - `mcp SDK` streamable_http_client 签名 — 理解 mock 目标

  **Acceptance Criteria**:
  - [ ] `python -m pytest src/tests/mcp_registry/test_transport.py -v` → 全部 PASS
  - [ ] 至少 6 个测试用例

  **QA Scenarios**:
  ```
  Scenario: Run transport tests
    Tool: Bash
    Steps:
      1. python -m pytest src/tests/mcp_registry/test_transport.py -v
    Expected Result: all tests pass, 0 failures
    Evidence: .sisyphus/evidence/task-4-tests.txt
  ```

  **Commit**: YES
  - Message: `test(mcp): add transport layer TDD tests`
  - Files: `src/tests/mcp_registry/test_transport.py`

- [ ] 5. **结算异常导办 LangGraph 图**

  **What to do**:
  - 创建 `src/runtime/langgraph/settlement_exception.py`
  - 用 `StateGraph(SettlementState)` 构建图：
    - `validate_claim` node → 调用 `adapters.insurance_interface.query_claim()`, 把 `claim_detail` 写入 state
    - `check_high_risk` node → 检查 `blocked_actions`，如果是 HIGH 则走 `human_confirmation_node`
    - `query_error_knowledge` node → 调用 `knowledge_extension.knowledge.get_error_detail(state["error_code"])`
    - `build_recommendation` node → 组装最终推荐
    - `human_confirmation` node — 使用 `interrupt()` 暂停，等待 `/tasks/confirm`
    - 条件边：`check_high_risk` → 有 blocked_actions 则走 human_confirmation，否则走 query_error_knowledge
  - 导出 `settlement_exception_graph` 供编排层使用
  - 写 TDD 测试：`src/tests/langgraph/test_settlement_exception.py`

  **Must NOT do**:
  - 不在 node 中直接调用外部系统（必须通过 adapters/）
  - 不改变现有 adapters/insurance_interface 接口
  - 不改变现有 knowledge_extension 接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 需要理解 LangGraph 条件边、interrupt()、和现有业务场景的数据流

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 6, 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 8, 9
  - **Blocked By**: Task 2 (基础设施), Task 3 (State 类型)

  **References**:
  - `src/business_scenarios/settlement_exception_guide/service.py` — 现有结算异常导办的完整业务逻辑（4 个步骤），理解每个步骤的输入输出
  - `src/adapters/insurance_interface/` — 医保接口适配器，理解 query_claim 的调用方式
  - `src/knowledge_extension/knowledge/` — 错误码知识库，理解 get_error_detail 的调用方式
  - `src/security/risk_control/` — 高风险动作检测，理解 detect_blocked_actions 的调用方式
  - `src/runtime/langgraph/nodes.py` — 通用 node 实现，重用 adapter_call_node 和 human_confirmation_node

  **Acceptance Criteria**:
  - [ ] `settlement_exception_graph` 可编译（`.compile()`）
  - [ ] 输入 `{'intent': 'settlement', 'error_code': 'E001'}` → 走完整流程 → 输出含 `recommendation` 和 `citations`
  - [ ] 高风险场景 → `interrupt()` 触发 → state 含 `requires_confirmation=True`
  - [ ] TDD 测试：`python -m pytest src/tests/langgraph/test_settlement_exception.py -v` → PASS

  **QA Scenarios**:
  ```
  Scenario: Normal settlement flow
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests/langgraph/test_settlement_exception.py::test_normal_settlement_flow -v
    Expected Result: PASS, graph execution completes with recommendation
    Evidence: .sisyphus/evidence/task-5-normal.txt

  Scenario: High risk settlement flow
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests/langgraph/test_settlement_exception.py::test_high_risk_interrupt -v
    Expected Result: PASS, interrupt() triggered, state shows requires_confirmation=True
    Evidence: .sisyphus/evidence/task-5-highrisk.txt
  ```

  **Commit**: YES
  - Message: `feat(langgraph): implement settlement exception guidance state graph`
  - Files: `src/runtime/langgraph/settlement_exception.py`, `src/tests/langgraph/test_settlement_exception.py`

- [ ] 6. **出院前联合质控 LangGraph 图**

  **What to do**:
  - 创建 `src/runtime/langgraph/pre_discharge_qc.py`
  - 用 `StateGraph(PreDischargeState)` 构建图：
    - `get_patient_summary` node → 调用 `adapters.emr.get_summary()` 和 `adapters.his.get_encounter_info()`
    - `run_qc_rules` node → 调用 `knowledge_extension.knowledge.get_qc_rules()`, 结果写入 `rule_results`
    - `check_qc_issues` node → 检查 `quality_issues` 列表
    - `build_qc_report` node → 组装质控报告
    - `human_confirmation` node — 高风险问题使用 `interrupt()`
    - 条件边：`check_qc_issues` → 有 issues 则走 build_qc_report，否则直接返回
  - 导出 `pre_discharge_qc_graph`
  - 写 TDD 测试：`src/tests/langgraph/test_pre_discharge_qc.py`

  **Must NOT do**:
  - 不在 node 中直接调用外部系统
  - 不改变现有 adapters/emr、adapters/his 接口

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 出院前质控有 8 个步骤，LangGraph 图最复杂

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 5, 7)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 8, 9
  - **Blocked By**: Task 2, Task 3

  **References**:
  - `src/business_scenarios/pre_discharge_joint_qc/service.py` — 现有出院前质控的完整业务逻辑（8 个步骤）
  - `src/adapters/emr/` — EMR 适配器，理解 get_summary 调用
  - `src/adapters/his/` — HIS 适配器，理解 get_encounter_info 调用
  - `src/knowledge_extension/knowledge/` — 质控规则知识库
  - `src/runtime/langgraph/nodes.py` — 通用 node 实现

  **Acceptance Criteria**:
  - [ ] `pre_discharge_qc_graph` 可编译
  - [ ] 输入 `{'intent': 'pre_discharge', 'patient_id': 'P001'}` → 走完整流程 → 输出含 `qc_recommendation`
  - [ ] 存在质控问题时 → 条件边正确路由到 build_qc_report
  - [ ] TDD 测试：`python -m pytest src/tests/langgraph/test_pre_discharge_qc.py -v` → PASS

  **QA Scenarios**:
  ```
  Scenario: Normal QC flow
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests/langgraph/test_pre_discharge_qc.py::test_normal_qc_flow -v
    Expected Result: PASS, graph execution completes with qc_recommendation
    Evidence: .sisyphus/evidence/task-6-normal.txt

  Scenario: QC flow with quality issues
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests/langgraph/test_pre_discharge_qc.py::test_qc_issues_found -v
    Expected Result: PASS, quality_issues populated, report generated
    Evidence: .sisyphus/evidence/task-6-issues.txt
  ```

  **Commit**: YES
  - Message: `feat(langgraph): implement pre-discharge joint QC state graph`
  - Files: `src/runtime/langgraph/pre_discharge_qc.py`, `src/tests/langgraph/test_pre_discharge_qc.py`

- [ ] 7. **LangGraph interrupt + 人工确认模式**

  **What to do**:
  - 完善 `src/runtime/langgraph/nodes.py` 中的 `human_confirmation_node`
  - 实现 `interrupt()` 暂停 + checkpoint 保存
  - 实现 `POST /tasks/confirm` → `Command(resume=...)` 恢复执行
  - 修改 `src/runtime/api/routes.py` 中的 `/tasks/confirm` 端点：
    - 接收 `{task_id, action: "confirm"|"reject"}`
    - 调用 LangGraph 的 `Command(resume={"confirmed": True/False})`
    - 返回确认后的执行结果
  - 写 TDD 测试：`src/tests/langgraph/test_human_confirmation.py`

  **Must NOT do**:
  - 不改变 `/tasks/confirm` 的 URL 和请求体格式
  - 不改变现有 `waiting_human_confirmation` 响应结构

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 涉及 LangGraph interrupt/Command/resume 和 FastAPI 路由的联调

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 5, 6)
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 9
  - **Blocked By**: Task 2

  **References**:
  - `src/runtime/api/routes.py:confirm_task` — 现有 `/tasks/confirm` 实现
  - `src/security/risk_control/detector.py` — 高风险动作检测逻辑
  - LangGraph docs: `https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/` — interrupt() 和 Command(resume=...) 模式

  **Acceptance Criteria**:
  - [ ] `interrupt()` 能在高风险步骤暂停执行
  - [ ] `POST /tasks/confirm {"task_id": "..", "action": "confirm"}` → 恢复执行
  - [ ] `POST /tasks/confirm {"task_id": "..", "action": "reject"}` → 终止执行
  - [ ] checkpoint 保存暂停状态可恢复
  - [ ] TDD 测试：`python -m pytest src/tests/langgraph/test_human_confirmation.py -v` → PASS

  **QA Scenarios**:
  ```
  Scenario: Confirm high-risk action
    Tool: Bash (curl)
    Preconditions: 触发一个高风险 settlement 场景
    Steps:
      1. curl -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/chat -H "Content-Type: application/json" -d '{"message":"结算失败E001","role":"cashier","patient_id":"P001","encounter_id":"E001"}'
      2. 从响应中提取 task_id
      3. curl -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/tasks/confirm -H "Content-Type: application/json" -d '{"task_id":"<task_id>","action":"confirm"}'
    Expected Result: 第一步返回 requires_confirmation=true, 第二步返回 completed result
    Evidence: .sisyphus/evidence/task-7-confirm.txt
  ```

  **Commit**: YES
  - Message: `feat(langgraph): implement human-in-the-loop interrupt and resume`
  - Files: `src/runtime/langgraph/nodes.py`, `src/runtime/api/routes.py`, `src/tests/langgraph/test_human_confirmation.py`

- [ ] 8. **业务场景服务适配 LangGraph node**

  **What to do**:
  - 修改 `src/business_scenarios/settlement_exception_guide/service.py`：
    - 保留 `query_claim`、`get_error_detail`、`build_recommendation` 核心函数
    - 去掉 service 中的编排逻辑（哪个步骤先执行、条件判断）
    - 每个核心函数返回 dict（适配 LangGraph state update）
    - 添加 `settlement_nodes.py` — 将这些函数包装为 LangGraph `@task` 兼容的 node 函数
  - 修改 `src/business_scenarios/pre_discharge_joint_qc/service.py`：
    - 同样的处理：保留核心函数，去掉编排逻辑
    - 添加 `qc_nodes.py`
  - 写 TDD 测试：`src/tests/langgraph/test_scenario_nodes.py`

  **Must NOT do**:
  - 不删除 `service.py` 中的核心业务函数（只去掉编排逻辑）
  - 不改变 adapters/ 调用方式

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 需要理解现有 service.py 中哪些是核心业务逻辑、哪些是编排逻辑

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential due to dependency on graph definitions)
  - **Blocks**: Task 9
  - **Blocked By**: Task 5, 6

  **References**:
  - `src/business_scenarios/settlement_exception_guide/service.py` — 完整业务逻辑
  - `src/business_scenarios/pre_discharge_joint_qc/service.py` — 完整业务逻辑
  - `src/runtime/langgraph/settlement_exception.py` — 已定义的图结构
  - `src/runtime/langgraph/pre_discharge_qc.py` — 已定义的图结构

  **Acceptance Criteria**:
  - [ ] 每个核心函数返回 dict（非 AgentResponse）
  - [ ] node 函数签名匹配 LangGraph node 要求：(state) → dict
  - [ ] 去掉编排逻辑后，核心函数仍然可被独立调用
  - [ ] TDD 测试：`python -m pytest src/tests/langgraph/test_scenario_nodes.py -v` → PASS

  **QA Scenarios**:
  ```
  Scenario: Settlement node functions
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests/langgraph/test_scenario_nodes.py::test_settlement_nodes -v
    Expected Result: PASS, all node functions return correct dict shapes
    Evidence: .sisyphus/evidence/task-8-nodes.txt
  ```

  **Commit**: YES
  - Message: `refactor(scenarios): adapt business scenario services to LangGraph nodes`
  - Files: `src/business_scenarios/settlement_exception_guide/service.py`, `src/business_scenarios/pre_discharge_joint_qc/service.py`, `src/business_scenarios/settlement_exception_guide/settlement_nodes.py`, `src/business_scenarios/pre_discharge_joint_qc/qc_nodes.py`

- [ ] 9. **编排层统一：替换 route 中的两条调用链**

  **What to do**:
  - 修改 `src/runtime/orchestration/service.py` — 去掉 `execute_plan()` 中的 if/elif 链，改为：
    - `dispatch_to_langgraph(intent)` → 根据 intent 选择对应的 StateGraph
    - `execute_graph(graph, initial_state)` → 编译并执行图，返回最终 state
  - 修改 `src/runtime/api/routes.py` — 替换 `_try_skill_execution()` 为：
    - `_try_langgraph_execution()` → 先 @-mention（保留），再 intent→graph 匹配
  - 保留现有 API 响应格式（AgentResponse）
  - 添加 `_state_to_agent_response(final_state)` 转换函数
  - 写 TDD 测试：`src/tests/langgraph/test_orchestration_unified.py`

  **Must NOT do**:
  - 不改变 `/chat` 路由签名和响应格式
  - 不删除 `_try_skill_execution` 中的 @-mention 解析（保留）
  - 不在编排层中直接调用 adapters/

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 涉及编排层的核心变更，影响所有 /chat 请求的调用链

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 13, 14
  - **Blocked By**: Task 7, 8

  **References**:
  - `src/runtime/orchestration/service.py:execute_plan` — 现有硬编码 if/elif 链
  - `src/runtime/api/routes.py:process_chat_request` — /chat 入口
  - `src/runtime/api/routes.py:_try_skill_execution` — 现有 skill 路由逻辑
  - `src/shared/schemas/responses.py:AgentResponse` — 响应结构

  **Acceptance Criteria**:
  - [ ] `POST /chat` settlement 消息 → LangGraph 执行 → AgentResponse（格式不变）
  - [ ] `POST /chat` pre_discharge 消息 → LangGraph 执行 → AgentResponse（格式不变）
  - [ ] @-mention 技能调用 → 正常工作
  - [ ] 意图匹配 → 正确路由到对应 LangGraph 图
  - [ ] TDD 测试：`python -m pytest src/tests/langgraph/test_orchestration_unified.py -v` → PASS

  **QA Scenarios**:
  ```
  Scenario: Full chat flow with LangGraph
    Tool: Bash (curl)
    Steps:
      1. curl -X POST http://127.0.0.1:8000/api/v1/medical-insurance-ai-agent/chat -H "Content-Type: application/json" -d '{"message":"结算失败E001，请帮我看看","role":"cashier","patient_id":"P001","encounter_id":"E001"}'
    Expected Result: HTTP 200, response contains "recommendation", "citations", no "engine" reference
    Evidence: .sisyphus/evidence/task-9-chat-response.json
  ```

  **Commit**: YES
  - Message: `refactor(orchestration): unify execution through LangGraph dispatch`
  - Files: `src/runtime/orchestration/service.py`, `src/runtime/api/routes.py`

- [ ] 10. **Skill/Tool 领域模型简化**

  **What to do**:
  - 修改 `src/domain/skill/models.py`：
    - 移除 `ExecutionStrategy` 枚举（sequential/parallel/conditional → LangGraph 替代）
    - 移除 `SkillStep` 的 `input_mapping`、`output_mapping`、`condition` 字段（→ LangGraph state key 替代）
    - 保留 `SkillStep` 的 `step_id`、`tool_id`、`depends_on`
    - 保留 `Skill` 的 `skill_id`、`name`、`description`、`owner`、`intent_keywords`、`required_roles`、`enabled`、`risk_level`
    - 保留 `SkillMetadata`（author、version、category、tags）
    - 保留 `Tool` 模型不变（tool_id、name、description、owner、tool_type、capability_ref、risk_level、enabled、required_roles）
  - 修改 `src/domain/skill/__init__.py` 导出
  - 更新所有引用 ExecutionStrategy 和 input_mapping/output_mapping 的代码
  - 写 TDD 测试：`src/tests/domain/test_skill_model_simplified.py`

  **Must NOT do**:
  - 不删除 Skill 和 Tool 的 storage ports（保留 protocol 以供后续 PostgreSQL 实现）
  - 不删除 seed.py 中的种子数据定义
  - 不改变 SkillService 和 ToolService 的公开 API

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 领域模型变更影响范围大，需要追踪所有引用点

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 11, 12)
  - **Parallel Group**: Wave 4
  - **Blocks**: Task 14
  - **Blocked By**: Task 9 (确保新编排层不再依赖被删除的字段)

  **References**:
  - `src/domain/skill/models.py` — 完整领域模型
  - `src/domain/tool/models.py` — Tool 模型
  - `src/runtime/skill_registry/skill_service.py` — 引用 ExecutionStrategy 的地方
  - `src/data_platform/storage/skill/seed.py` — 种子数据中的 execution_strategy 引用
  - `src/runtime/api/schemas.py` — API schema 中的 SkillCreateRequest

  **Acceptance Criteria**:
  - [ ] `ExecutionStrategy` 枚举已从代码中完全移除
  - [ ] `input_mapping`、`output_mapping`、`condition` 已从 SkillStep 移除
  - [ ] `SkillStep.depends_on` 保留
  - [ ] SkillService.create_skill 不再要求 execution_strategy
  - [ ] 所有现有测试通过（已更新引用）
  - [ ] TDD 测试：`python -m pytest src/tests/domain/test_skill_model_simplified.py -v` → PASS

  **QA Scenarios**:
  ```
  Scenario: Skill model import without ExecutionStrategy
    Tool: Bash
    Steps:
      1. python -c "from src.domain.skill.models import Skill; print(hasattr(Skill, 'execution_strategy')); s = Skill(skill_id='s1', name='test', description='desc', owner='cashier', intent_keywords=['test'], required_roles=['cashier'], enabled=True); print(s.name)"
    Expected Result: stdout contains "False" then "test"
    Evidence: .sisyphus/evidence/task-10-model.txt
  ```

  **Commit**: YES
  - Message: `refactor(domain): simplify skill/tool model for LangGraph workflow templates`
  - Files: `src/domain/skill/models.py`, `src/domain/skill/__init__.py`, `src/runtime/skill_registry/skill_service.py`, `src/runtime/api/schemas.py`

- [ ] 11. **枚举去重 + 类型合并**

  **What to do**:
  - 审计并合并重复枚举：
    - `src/domain/skill/models.py` 中的 `ExecutionStrategy` → 删除（已在 Task 10 中移除）
    - `src/domain/tool/models.py` 中的 `ToolType` vs `src/domain/skill/models.py` 中的 `StepType` → 统一为 `ToolType`
    - `src/knowledge_extension/mcp_registry/models.py` 中的 `McpRiskLevel` vs `src/domain/tool/models.py` 中的 `RiskLevel` 无关 → 保留两者，因为语义不同（MCP 风险 vs 业务风险）
  - 更新所有 `StepType` 引用为 `ToolType`
  - 删除 `StepType` 枚举定义
  - 写 TDD 测试：`src/tests/domain/test_enum_dedup.py`

  **Must NOT do**:
  - 不合并 McpRiskLevel 和 RiskLevel（语义不同，分别用于 MCP 工具和业务工具）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: 枚举替换，涉及全局重命名但逻辑简单

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 10, 12)
  - **Parallel Group**: Wave 4
  - **Blocks**: None
  - **Blocked By**: Task 10

  **References**:
  - `src/domain/skill/models.py` — StepType 定义位置
  - `src/domain/tool/models.py` — ToolType 定义位置
  - LSP find references on `StepType` — 追踪所有引用点

  **Acceptance Criteria**:
  - [ ] `StepType` 枚举已完全从代码中移除
  - [ ] 所有之前用 `StepType` 的地方现在用 `ToolType`
  - [ ] `python -m pytest src/tests -v` 无 import error
  - [ ] TDD 测试通过

  **QA Scenarios**:
  ```
  Scenario: StepType removed
    Tool: Bash
    Steps:
      1. python -c "from src.domain.skill.models import StepType; print('FOUND')"
    Expected Result: ImportError (StepType should not exist)
    Failure Indicators: stdout contains "FOUND"
    Evidence: .sisyphus/evidence/task-11-steptype-removed.txt

  Scenario: ToolType still importable
    Tool: Bash
    Steps:
      1. python -c "from src.domain.tool.models import ToolType; print(ToolType.ADAPTER_CALL)"
    Expected Result: stdout contains "ADAPTER_CALL"
    Evidence: .sisyphus/evidence/task-11-tooltype.txt
  ```

  **Commit**: YES
  - Message: `refactor(domain): deduplicate StepType into ToolType`
  - Files: `src/domain/skill/models.py`, 所有引用 StepType 的文件

- [ ] 12. **种子数据迁移 + MCP 注册/发现架构参考重构**

  **What to do**:
  - 更新 `src/data_platform/storage/skill/seed.py`：
    - 移除 execution_strategy 字段
    - 移除 input_mapping/output_mapping/condition 字段
    - 保留 skill_id、tool_id、depends_on 元数据
    - 添加 `langgraph_graph` 引用字段（指向对应的 LangGraph 图名）
  - 更新 `src/data_platform/storage/tool/seed.py`（如存在）
  - 参考 MCP Gateway & Registry 架构，重构 `src/knowledge_extension/mcp_registry/`：
    - 保留 `McpRegistryService` 的注册/发现核心逻辑
    - 保留 `config_import.py` 的配置解析
    - 保留 `discovery.py` 的工具发现（用新的 mcp SDK transport）
    - 保留 `models.py` 的 McpServer、McpCapability 模型
    - 保留 `ports.py` 的 McpRegistry Protocol
    - 将 `service.py` 中的 capability 选择逻辑改为适配 LangGraph node 的模式
  - 写 TDD 测试：`src/tests/integration/test_seed_migration.py`

  **Must NOT do**:
  - 不删除 MCP 管理 API（`/api/v1/medical-insurance-ai-agent/mcp/*`）
  - 不改变 MCP 注册/发现的 API 请求/响应格式
  - 不引入外部 MCP Gateway 平台依赖

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 种子数据迁移 + MCP 注册架构重构，影响多个模块

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 10, 11)
  - **Parallel Group**: Wave 4
  - **Blocks**: Task 13
  - **Blocked By**: Task 9, 10

  **References**:
  - `src/data_platform/storage/skill/seed.py` — 种子数据（16 tools + 3 skills）
  - `src/knowledge_extension/mcp_registry/service.py` — McpRegistryService
  - `src/knowledge_extension/mcp_registry/discovery.py` — McpToolDiscoveryService
  - `src/knowledge_extension/mcp_registry/config_import.py` — config import
  - MCP Gateway & Registry: `https://github.com/agentic-community/mcp-gateway-registry` — 架构参考

  **Acceptance Criteria**:
  - [ ] 种子数据不含 execution_strategy、input_mapping、output_mapping、condition
  - [ ] 种子数据含 `langgraph_graph` 字段
  - [ ] MCP 注册/发现 API 正常工作
  - [ ] `POST /mcp/servers` → 注册 MCP server → 工具发现可用
  - [ ] TDD 测试通过

  **QA Scenarios**:
  ```
  Scenario: Seed data valid
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests/integration/test_seed_migration.py -v
    Expected Result: PASS, all seed data loads without error
    Evidence: .sisyphus/evidence/task-12-seed.txt
  ```

  **Commit**: YES
  - Message: `refactor: migrate seed data and MCP registry architecture`
  - Files: `src/data_platform/storage/skill/seed.py`, `src/knowledge_extension/mcp_registry/service.py`

- [ ] 13. **端到端集成测试 + API 契约验证**

  **What to do**:
  - 创建 `src/tests/langgraph/test_e2e_langgraph.py`：
    - 测试 1: `POST /chat` settlement → LangGraph 执行 → AgentResponse
    - 测试 2: `POST /chat` pre_discharge → LangGraph 执行 → AgentResponse
    - 测试 3: 高风险 → interrupt → `POST /tasks/confirm` → 恢复执行
    - 测试 4: @-mention 技能调用 → 正确路由
    - 测试 5: 意图匹配 → 正确路由
    - 测试 6: P002 降级路径 → 返回 uncertain 响应
    - 测试 7: API 响应结构不变（对比 AgentResponse schema）
  - 运行现有全量测试确保无回归

  **Must NOT do**:
  - 不创建新的测试 fixture 破坏现有测试
  - 不修改现有测试（除非受 Task 10-11 枚举变更影响）

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 端到端测试需要覆盖完整调用链

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 5 (sequential, depends on all previous waves)
  - **Blocks**: Task 14, 15
  - **Blocked By**: Task 9, 12

  **References**:
  - `src/tests/e2e/test_settlement_exception.py` — 现有 e2e 测试模式
  - `src/tests/integration/test_human_confirmation.py` — 人工确认测试模式
  - `src/tests/integration/test_intent_routing.py` — 意图路由测试模式
  - `src/shared/schemas/responses.py:AgentResponse` — 响应结构对比基准

  **Acceptance Criteria**:
  - [ ] 7 个 e2e 测试全部 PASS
  - [ ] `python -m pytest src/tests -v --ignore=src/tests/langgraph/test_e2e_langgraph.py` → 无新增失败
  - [ ] AgentResponse 结构验证通过

  **QA Scenarios**:
  ```
  Scenario: Full e2e LangGraph tests
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests/langgraph/test_e2e_langgraph.py -v
    Expected Result: 7 passed, 0 failures
    Evidence: .sisyphus/evidence/task-13-e2e.txt

  Scenario: Existing tests still pass
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests -v --ignore=src/tests/langgraph --ignore=src/tests/shared/skills
    Expected Result: all pass, no unexpected failures
    Evidence: .sisyphus/evidence/task-13-regression.txt
  ```

  **Commit**: YES
  - Message: `test: add end-to-end LangGraph integration tests`
  - Files: `src/tests/langgraph/test_e2e_langgraph.py`

- [ ] 14. **删除旧代码：engine.py 硬编码 + orchestration if/elif + InMemoryMcpClientGateway**

  **What to do**:
  - 删除 `src/runtime/skill_registry/engine.py` 中的硬编码部分：
    - 删除 `_execute_step` 中的 if/elif 链（`insurance_interface.*`、`knowledge.*`、`his.*`、`billing.*`）
    - 删除 `build_sample_store()` 函数
    - 保留 `SkillExecutionEngine` 类壳（作为 LangGraph 的 facade，如果还有引用）
  - 删除 `src/runtime/orchestration/service.py` 中的 `execute_plan()` if/elif 链
  - 删除 `src/knowledge_extension/mcp_registry/client_gateway.py` 中的 `InMemoryMcpClientGateway`
  - 确认删除后所有测试通过
  - 更新 imports

  **Must NOT do**:
  - 不删除 `adapters/` 层的任何代码
  - 不删除 `engine.py` 完全（保留类壳作为兼容层，打上 `@deprecated` 标记）
  - 不删除 `orchestration/service.py` 完全（保留 `create_workflow`、`get_workflow_status` 等非执行相关函数）

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: 删除为主，但需要确认依赖关系

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 5
  - **Blocks**: None
  - **Blocked By**: Task 13

  **References**:
  - `src/runtime/skill_registry/engine.py` — 定位硬编码部分
  - `src/runtime/orchestration/service.py` — 定位 if/elif 链
  - `src/knowledge_extension/mcp_registry/client_gateway.py` — 定位 InMemoryMcpClientGateway
  - LSP find references on deleted functions — 确保无残留引用

  **Acceptance Criteria**:
  - [ ] `_execute_step` 不含 if/elif 硬编码链
  - [ ] `build_sample_store()` 不再存在
  - [ ] `execute_plan()` 不含 if/elif 链
  - [ ] `InMemoryMcpClientGateway` 不再存在
  - [ ] `python -m pytest src/tests -v` 全部通过

  **QA Scenarios**:
  ```
  Scenario: Old code removed
    Tool: Bash (grep)
    Steps:
      1. python -c "from src.knowledge_extension.mcp_registry.client_gateway import InMemoryMcpClientGateway; print('FOUND')"
    Expected Result: ImportError (class removed)
    Evidence: .sisyphus/evidence/task-14-removed.txt
  ```

  **Commit**: YES
  - Message: `chore: remove deprecated engine hardcoded paths and mock gateway`
  - Files: `src/runtime/skill_registry/engine.py`, `src/runtime/orchestration/service.py`, `src/knowledge_extension/mcp_registry/client_gateway.py`

- [ ] 15. **全量回归测试**

  **What to do**:
  - 运行完整测试套件：`python -m pytest src/tests -v`
  - 验证所有 313+ 测试通过
  - 验证无 deprecation warning
  - 验证 import 无循环依赖
  - 验证 API 启动：`uvicorn src.runtime.api.app:create_app --factory`
  - 写回归测试报告

  **Must NOT do**:
  - 不修改任何测试来"凑通过"

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: 最终质量闸门

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 5 (final gate)
  - **Blocks**: None
  - **Blocked By**: Task 13, 14

  **Acceptance Criteria**:
  - [ ] `python -m pytest src/tests -v` → 全部 PASS
  - [ ] `python -c "from src.runtime.api.app import create_app; app = create_app(); print('OK')"` → OK
  - [ ] 无循环导入
  - [ ] AgentResponse 结构验证通过

  **QA Scenarios**:
  ```
  Scenario: Full test suite
    Tool: Bash (pytest)
    Steps:
      1. python -m pytest src/tests -v
    Expected Result: all tests pass, 0 failures, 0 errors
    Evidence: .sisyphus/evidence/task-15-full-tests.txt

  Scenario: App factory loads
    Tool: Bash
    Steps:
      1. python -c "from src.runtime.api.app import create_app; create_app(); print('APP_OK')"
    Expected Result: stdout contains "APP_OK", no import errors
    Evidence: .sisyphus/evidence/task-15-app-load.txt
  ```

  **Commit**: NO (final verification, no code changes)
  - Evidence only

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns. Check evidence files exist.

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest src/tests -v`. Review all changed files for code smells.

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute ALL QA scenarios from every task. Test cross-task integration.

- [ ] F4. **Scope Fidelity Check** — `deep`
  Verify 1:1 — everything in spec was built, nothing beyond spec. Check "Must NOT do" compliance.

---

## Commit Strategy

| Wave | Commit Message | Files |
|------|---------------|-------|
| 1 | `feat(mcp): introduce official mcp SDK transport layer` | transport.py, requirements |
| 2 | `feat(langgraph): add unified state graph infrastructure` | langgraph/__init__.py, states.py |
| 3 | `feat(langgraph): migrate settlement and pre-discharge scenarios` | settlement_exception.py, pre_discharge_qc.py |
| 4 | `refactor(domain): simplify skill/tool model, deduplicate enums` | domain/skill/models.py |
| 5 | `test: full integration tests and old code cleanup` | tests/ + deletions |

---

## Success Criteria

### Verification Commands
```bash
python -m pytest src/tests -v              # Expected: all pass, 0 failures
python -m pytest src/tests/langgraph -v    # Expected: all pass
python -c "from src.knowledge_extension.mcp_registry.transport import McpTransport; print('OK')"  # Expected: OK
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] AgentResponse 结构未变
- [ ] 两个业务场景端到端可用
- [ ] 高风险拦截 + 人工确认流程正常
- [ ] TDD 测试全部通过
