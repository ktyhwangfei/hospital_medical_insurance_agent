# Real MCP Tools AI Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 准备一个可在 AI 导办中真实体现的内置 MCP 演示服务，让“结算失败”和“出院前风险”两个导办问题自动调用 MCP tool 并展示结果。

**Architecture:** 在后端新增一个低风险内置 MCP 演示工具集，复用现有 MCP registry、capability selection 和 in-memory client gateway 模型，不引入外部进程依赖。业务场景服务在生成原有结果后调用 MCP 工具，将输出写入 `result.mcp_insights`、`citations` 和 `audit.mcp_tool_invocations`，前端已有人可读渲染可继续扩展展示 MCP 洞察。

**Tech Stack:** Python 3、FastAPI、Pydantic、pytest、现有 MCP Registry/Storage/ClientGateway、Next.js/React 前端展示。

---

## 文件结构与职责

- Create `src/knowledge_extension/mcp_registry/demo_tools.py`：定义内置 MCP demo server、两个 capability、tool 输出和调用服务。
- Modify `src/business_scenarios/settlement_exception_guide/service.py`：在结算异常导办中调用 `explain_settlement_error`，追加 MCP 洞察。
- Modify `src/business_scenarios/pre_discharge_joint_qc/service.py`：在出院前质控中调用 `pre_discharge_risk_supplement`，追加 MCP 洞察。
- Modify `prototype/src/components/settlement-chat.tsx`：在人可读导办文案中展示 `mcp_insights`。
- Test `src/tests/knowledge_extension/test_mcp_demo_tools.py`：覆盖 demo tool 定义与调用输出。
- Test `src/tests/integration/test_mcp_runtime_integration.py`：覆盖两个 AI 导办场景响应中出现 MCP 洞察、citations、audit。

---

### Task 1: 新增内置 MCP demo tools

**Files:**
- Create: `src/knowledge_extension/mcp_registry/demo_tools.py`
- Test: `src/tests/knowledge_extension/test_mcp_demo_tools.py`

- [ ] **Step 1: 写失败测试**

创建 `src/tests/knowledge_extension/test_mcp_demo_tools.py`：

```python
from src.knowledge_extension.mcp_registry.demo_tools import build_demo_mcp_tool_service


def test_demo_mcp_tool_service_explains_settlement_error():
    service = build_demo_mcp_tool_service()

    result = service.invoke_for_scenario(
        scenario="settlement_exception_guidance",
        role="medical_office",
        tool_name="explain_settlement_error",
        arguments={"patient_id": "P001", "encounter_id": "E001", "error_code": "E-UPLOAD-001"},
    )

    assert result["tool_name"] == "explain_settlement_error"
    assert result["source"] == "demo-mcp-medical-insurance"
    assert "费用明细未全部上传" in result["summary"]
    assert result["recommendations"]
    assert result["citations"][0]["source_type"] == "mcp_tool"


def test_demo_mcp_tool_service_supplements_pre_discharge_risks():
    service = build_demo_mcp_tool_service()

    result = service.invoke_for_scenario(
        scenario="pre_discharge_quality_control",
        role="medical_office",
        tool_name="pre_discharge_risk_supplement",
        arguments={"patient_id": "P001", "encounter_id": "E001"},
    )

    assert result["tool_name"] == "pre_discharge_risk_supplement"
    assert result["source"] == "demo-mcp-medical-insurance"
    assert result["risks"]
    assert result["risks"][0]["risk_type"] == "MCP补充风险"
    assert result["citations"][0]["source_id"] == "cap-pre-discharge-risk-supplement"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_demo_tools.py -v
```

Expected: FAIL，提示缺少 `src.knowledge_extension.mcp_registry.demo_tools`。

- [ ] **Step 3: 实现 demo tool 服务**

创建 `src/knowledge_extension/mcp_registry/demo_tools.py`：

```python
from typing import Any

from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.client_gateway import InMemoryMcpClientGateway
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilitySelectionRequest,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)
from src.knowledge_extension.mcp_registry.service import McpRegistryService


DEMO_MCP_SERVER_ID = "demo-mcp-medical-insurance"


class DemoMcpToolService:
    def __init__(self) -> None:
        self._storage = InMemoryMcpStorage()
        self._registry = McpRegistryService(self._storage)
        self._gateway = InMemoryMcpClientGateway(tool_results=self._tool_results())
        self._bootstrap()

    def invoke_for_scenario(self, scenario: str, role: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        capability_type = McpCapabilityType.TOOL
        selection = self._registry.select_capabilities(
            McpCapabilitySelectionRequest(
                scenario=scenario,
                role=role,
                permissions={"mcp:invoke:read"},
                capability_type=capability_type,
                max_risk_level=McpRiskLevel.LOW,
            )
        )
        if selection.status is not KnowledgeExtensionStatus.SUCCESS:
            return {
                "tool_name": tool_name,
                "source": DEMO_MCP_SERVER_ID,
                "status": selection.status.value,
                "summary": "未选中可用 MCP 工具",
                "recommendations": [],
                "risks": [],
                "citations": [],
                "audit_events": [event.model_dump(mode="json") for event in selection.audit_events],
            }

        capability = next((item for item in selection.selected_capabilities if item.name == tool_name), None)
        if capability is None:
            return {
                "tool_name": tool_name,
                "source": DEMO_MCP_SERVER_ID,
                "status": "no_hit",
                "summary": "未找到指定 MCP 工具",
                "recommendations": [],
                "risks": [],
                "citations": [],
                "audit_events": [event.model_dump(mode="json") for event in selection.audit_events],
            }

        server = self._storage.get_server(capability.server_id)
        if server is None:
            return {
                "tool_name": tool_name,
                "source": DEMO_MCP_SERVER_ID,
                "status": "server_missing",
                "summary": "MCP 服务未注册",
                "recommendations": [],
                "risks": [],
                "citations": [],
                "audit_events": [event.model_dump(mode="json") for event in selection.audit_events],
            }

        invocation = self._gateway.invoke_tool(server, capability, arguments)
        output = invocation.output
        return {
            **output,
            "status": invocation.status.value,
            "audit_events": [
                *[event.model_dump(mode="json") for event in selection.audit_events],
                *[event.model_dump(mode="json") for event in invocation.audit_events],
            ],
        }

    def _bootstrap(self) -> None:
        server = McpServer(
            server_id=DEMO_MCP_SERVER_ID,
            name="院端医保 MCP 演示服务",
            endpoint="memory://demo-medical-insurance",
            transport=McpTransportType.STREAMABLE_HTTP,
            status=McpServerStatus.ENABLED,
            protocol_version="2025-03-26",
            metadata={"owner": "医保办", "purpose": "ai_guide_demo"},
        )
        self._registry.register_server(server)
        for capability in self._capabilities():
            self._registry.register_capability(capability)

    def _capabilities(self) -> list[McpCapability]:
        return [
            McpCapability(
                capability_id="cap-explain-settlement-error",
                server_id=DEMO_MCP_SERVER_ID,
                name="explain_settlement_error",
                capability_type=McpCapabilityType.TOOL,
                description="解释医保结算错误码并给出处置建议",
                supported_scenarios={"settlement_exception_guidance"},
                required_roles={"medical_office", "cashier"},
                required_permissions={"mcp:invoke:read"},
                risk_level=McpRiskLevel.LOW,
                input_schema={"patient_id": "string", "encounter_id": "string", "error_code": "string"},
                output_schema={"summary": "string", "recommendations": "list[string]"},
            ),
            McpCapability(
                capability_id="cap-pre-discharge-risk-supplement",
                server_id=DEMO_MCP_SERVER_ID,
                name="pre_discharge_risk_supplement",
                capability_type=McpCapabilityType.TOOL,
                description="补充出院前医保风险提示",
                supported_scenarios={"pre_discharge_quality_control"},
                required_roles={"medical_office", "medical_record_staff", "clinician"},
                required_permissions={"mcp:invoke:read"},
                risk_level=McpRiskLevel.LOW,
                input_schema={"patient_id": "string", "encounter_id": "string"},
                output_schema={"risks": "list[object]"},
            ),
        ]

    def _tool_results(self) -> dict[str, dict[str, Any]]:
        return {
            "cap-explain-settlement-error": {
                "tool_name": "explain_settlement_error",
                "source": DEMO_MCP_SERVER_ID,
                "summary": "MCP 工具提示：费用明细未全部上传会导致医保预结算失败，应先补传失败明细后重新预结算。",
                "recommendations": [
                    "核对收费系统费用上传状态",
                    "补传失败费用明细",
                    "重新发起医保预结算并保留接口返回流水号",
                ],
                "risks": [],
                "citations": [
                    {"source_type": "mcp_tool", "source_id": "cap-explain-settlement-error", "summary": "院端医保 MCP 错误码解释工具"}
                ],
            },
            "cap-pre-discharge-risk-supplement": {
                "tool_name": "pre_discharge_risk_supplement",
                "source": DEMO_MCP_SERVER_ID,
                "summary": "MCP 工具补充：出院前应同步检查费用上传、限制用药、病案首页一致性。",
                "recommendations": ["优先处理高风险费用上传和病案首页一致性问题"],
                "risks": [
                    {
                        "risk_type": "MCP补充风险",
                        "risk_level": "medium",
                        "responsible_role": "医保办",
                        "recommendation": "核对医保目录限制条件与费用上传完成状态",
                    }
                ],
                "citations": [
                    {"source_type": "mcp_tool", "source_id": "cap-pre-discharge-risk-supplement", "summary": "院端医保 MCP 出院前风险补充工具"}
                ],
            },
        }


def build_demo_mcp_tool_service() -> DemoMcpToolService:
    return DemoMcpToolService()
```

- [ ] **Step 4: 运行测试验证通过**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_demo_tools.py -v
```

Expected: PASS。

---

### Task 2: 将 MCP 洞察接入两个 AI 导办场景

**Files:**
- Modify: `src/business_scenarios/settlement_exception_guide/service.py`
- Modify: `src/business_scenarios/pre_discharge_joint_qc/service.py`
- Test: `src/tests/integration/test_mcp_runtime_integration.py`

- [ ] **Step 1: 写场景集成失败测试**

在 `src/tests/integration/test_mcp_runtime_integration.py` 追加：

```python
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_settlement_exception_chat_includes_demo_mcp_insight():
    client = TestClient(create_app())

    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001',
        'role': 'medical_office',
        'message': '为什么这个患者结算失败',
        'patient_id': 'P001',
        'encounter_id': 'E001',
    })

    body = response.json()
    assert response.status_code == 200
    assert body['result']['mcp_insights'][0]['tool_name'] == 'explain_settlement_error'
    assert body['result']['mcp_insights'][0]['source'] == 'demo-mcp-medical-insurance'
    assert any(citation['source_type'] == 'mcp_tool' for citation in body['citations'])
    assert body['audit']['mcp_tool_invocations']


def test_pre_discharge_chat_includes_demo_mcp_insight():
    client = TestClient(create_app())

    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001',
        'role': 'medical_office',
        'message': '这个患者出院前还有哪些风险',
        'patient_id': 'P001',
        'encounter_id': 'E001',
    })

    body = response.json()
    assert response.status_code == 200
    assert body['result']['mcp_insights'][0]['tool_name'] == 'pre_discharge_risk_supplement'
    assert body['result']['mcp_insights'][0]['risks'][0]['risk_type'] == 'MCP补充风险'
    assert any(citation['source_id'] == 'cap-pre-discharge-risk-supplement' for citation in body['citations'])
    assert body['audit']['mcp_tool_invocations']
```

- [ ] **Step 2: 运行集成测试确认失败**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_runtime_integration.py::test_settlement_exception_chat_includes_demo_mcp_insight src/tests/integration/test_mcp_runtime_integration.py::test_pre_discharge_chat_includes_demo_mcp_insight -v
```

Expected: FAIL，响应中缺少 `result.mcp_insights`。

- [ ] **Step 3: 接入结算异常 MCP 工具**

在 `src/business_scenarios/settlement_exception_guide/service.py` 增加导入：

```python
from src.knowledge_extension.mcp_registry.demo_tools import build_demo_mcp_tool_service
```

在 `guide_settlement_exception()` 的 `response = AgentResponse(...)` 后、`ext_knowledge = ...` 前加入：

```python
    mcp_insight = build_demo_mcp_tool_service().invoke_for_scenario(
        scenario="settlement_exception_guidance",
        role="medical_office",
        tool_name="explain_settlement_error",
        arguments={"patient_id": patient_id, "encounter_id": encounter_id, "error_code": error_code},
    )
    response.result["mcp_insights"] = [mcp_insight]
    response.citations.extend(mcp_insight["citations"])
    response.audit["mcp_tool_invocations"] = mcp_insight["audit_events"]
```

- [ ] **Step 4: 接入出院前质控 MCP 工具**

在 `src/business_scenarios/pre_discharge_joint_qc/service.py` 增加导入：

```python
from src.knowledge_extension.mcp_registry.demo_tools import build_demo_mcp_tool_service
```

在 `run_pre_discharge_qc()` 的 `response = AgentResponse(...)` 后、`knowledge = ...` 前加入：

```python
    mcp_insight = build_demo_mcp_tool_service().invoke_for_scenario(
        scenario="pre_discharge_quality_control",
        role="medical_office",
        tool_name="pre_discharge_risk_supplement",
        arguments={"patient_id": patient_id, "encounter_id": encounter_id},
    )
    response.result["mcp_insights"] = [mcp_insight]
    response.citations.extend(mcp_insight["citations"])
    response.audit["mcp_tool_invocations"] = mcp_insight["audit_events"]
```

- [ ] **Step 5: 运行集成测试验证通过**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_demo_tools.py src/tests/integration/test_mcp_runtime_integration.py -v
```

Expected: PASS。

---

### Task 3: 前端对话显示 MCP 洞察

**Files:**
- Modify: `prototype/src/components/settlement-chat.tsx`

- [ ] **Step 1: 修改 `extractContent()` 支持 `mcp_insights`**

在 `prototype/src/components/settlement-chat.tsx` 的 `extractContent()` 中，在最终 `return JSON.stringify(result, null, 2)` 前加入：

```tsx
  const mcpInsights = recordList(result.mcp_insights)
  if (mcpInsights.length > 0) {
    return [
      '已获得 MCP 工具补充洞察：',
      ...mcpInsights.map((insight, index) => {
        const toolName = stringValue(insight.tool_name) ?? 'unknown_tool'
        const summary = stringValue(insight.summary) ?? '无摘要'
        const recommendations = stringList(insight.recommendations)
        const risks = recordList(insight.risks)
        const recommendationText = recommendations.length > 0 ? `\n   建议：${recommendations.join('；')}` : ''
        const riskText = risks.length > 0 ? `\n   补充风险：${risks.map((risk) => stringValue(risk.risk_type) ?? '未命名风险').join('、')}` : ''
        return `${index + 1}. ${toolName}\n   ${summary}${recommendationText}${riskText}`
      }),
    ].join('\n')
  }
```

然后在结算异常分支和风险清单分支中也拼接 MCP 段落：

```tsx
  const mcpInsights = recordList(result.mcp_insights)
  const mcpText = mcpInsights.length > 0
    ? `\n\nMCP 工具补充：\n${mcpInsights.map((insight, index) => `${index + 1}. ${stringValue(insight.summary) ?? '无摘要'}`).join('\n')}`
    : ''
```

在结算异常返回末尾加 `+ mcpText`；在风险清单返回末尾加 `+ mcpText`。

- [ ] **Step 2: 前端 lint**

Run:

```bash
npm run lint
```

Working directory: `prototype`

Expected: 退出码 0；允许既有 warning。

---

### Task 4: 验证与交付

**Files:**
- No required production file changes.

- [ ] **Step 1: 运行后端目标测试**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_demo_tools.py src/tests/integration/test_mcp_runtime_integration.py src/tests/integration/test_full_mvp_contract.py -v
```

Expected: PASS。

- [ ] **Step 2: 运行前端 lint**

Run:

```bash
npm run lint
```

Working directory: `prototype`

Expected: 退出码 0；允许既有 warning。

- [ ] **Step 3: 手动页面验证流程**

启动后端：

```bash
uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory --reload
```

启动前端：

```bash
npm run dev
```

Working directory: `prototype`

浏览器验证：

1. 打开 AI 导办对话。
2. 选择医保办。
3. 点击“为什么这个患者结算失败”。
4. 预期回复包含 `MCP 工具补充` 和费用上传补充建议。
5. 点击“这个患者出院前还有哪些风险”。
6. 预期回复包含 `MCP 工具补充` 和 `MCP补充风险`。

- [ ] **Step 4: 查看 diff**

Run:

```bash
git diff --check
```

Expected: 无空白错误。

---

## 自检清单

- MCP demo tools 是低风险读工具，不触发人工确认。
- 两个 AI 导办问题都能看到 MCP 结果。
- MCP 输出带 `mcp_tool` citation，满足可追溯要求。
- 不依赖外部 MCP 进程，演示可稳定运行。
- 不修改正式医保结算、退费、冲正等高风险动作。
