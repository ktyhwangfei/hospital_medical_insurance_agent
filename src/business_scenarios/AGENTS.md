# business_scenarios/ — 医保业务场景

## OVERVIEW

Three self-contained business scenarios dispatched by `runtime/scenario_executor.UnifiedScenarioExecutor` — each is an independent module with service.py + optional LangGraph nodes.

## STRUCTURE

- **settlement_exception_guide/** — 结算异常导办
  - `service.py`: SettlementExceptionGuideService — orchestrates error_code lookup, adapter calls, return guidance.
  - `settlement_nodes.py`: LangGraph nodes for settlement flow (error analysis, resolution path selection, human confirmation branch).
  - Graph defined in `runtime/langgraph/settlement_exception.py`.

- **pre_discharge_joint_qc/** — 出院前联合质控
  - `service.py`: PreDischargeJointQCService — orchestrates QC checks, risk scoring, summary generation.
  - `qc_nodes.py`: LangGraph nodes for QC flow (admission review, order compliance, DRG prediction, report).
  - Graph defined in `runtime/langgraph/pre_discharge_qc.py`.

- **mcp_tool_invocation/** — MCP 工具调用
  - `service.py`: McpToolInvocationService — routes tool calls through MCP registry → client_gateway.
  - No custom LangGraph graph — uses generic tool execution path.

## SCENARIO→ADAPTER MAPPING

| Scenario | Adapters Used |
|---|---|
| settlement_exception_guide | `adapters/insurance_interface`, `adapters/billing` |
| pre_discharge_joint_qc | `adapters/pre_audit`, `adapters/drg_dip`, `adapters/his`, `adapters/emr`, `adapters/medical_record` |
| mcp_tool_invocation | `knowledge_extension/mcp_registry` (registry lookup), `runtime/capability_nodes/client_gateway` (execution) |

All adapters are currently in-memory stubs — replace by implementing adapter ports.

## ANTI-PATTERNS

- **Do NOT import scenario service directly in routes.** Always go through UnifiedScenarioExecutor.
- **Do NOT put adapter calls in scenario service constructors.** Inject via constructor or use lazy init.
- **Do NOT duplicate LangGraph graph definitions here.** Graphs live in `runtime/langgraph/`, nodes live here.
- **Do NOT put business logic in LangGraph node files.** Nodes should be thin wrappers calling service methods.
- **Do NOT create interdependencies between scenarios.** Each scenario is independent — share via domain models, not direct imports.
- **Do NOT hardcode adapter choices.** Let scenario config or UnifiedScenarioExecutor decide which adapter profile to load.

Tests: `src/tests/integration/flow/` — test_settlement_exception_flow, test_pre_discharge_qc_flow, test_mcp_runtime_integration.
