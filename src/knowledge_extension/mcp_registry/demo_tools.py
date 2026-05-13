from typing import Any

from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.ports import McpStorage
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


POLICY_KNOWLEDGE_MCP_SERVER_ID = "medical-insurance-policy-knowledge-mcp"
PRE_DISCHARGE_QC_MCP_SERVER_ID = "pre-discharge-qc-knowledge-mcp"


def demo_mcp_servers() -> list[McpServer]:
    return [
        McpServer(
            server_id=POLICY_KNOWLEDGE_MCP_SERVER_ID,
            name="医保政策知识 MCP",
            endpoint="memory://medical-insurance-policy-knowledge",
            transport=McpTransportType.STREAMABLE_HTTP,
            status=McpServerStatus.ENABLED,
            protocol_version="2025-03-26",
            metadata={"owner": "医保办", "domain": "policy_knowledge"},
        ),
        McpServer(
            server_id=PRE_DISCHARGE_QC_MCP_SERVER_ID,
            name="出院质控知识 MCP",
            endpoint="memory://pre-discharge-qc-knowledge",
            transport=McpTransportType.STREAMABLE_HTTP,
            status=McpServerStatus.ENABLED,
            protocol_version="2025-03-26",
            metadata={"owner": "医保办", "domain": "pre_discharge_qc"},
        ),
    ]


def demo_mcp_capabilities() -> list[McpCapability]:
    return [
        McpCapability(
            capability_id="cap-query-policy-by-error-code",
            server_id=POLICY_KNOWLEDGE_MCP_SERVER_ID,
            name="query_policy_by_error_code",
            capability_type=McpCapabilityType.TOOL,
            description="按医保错误码查询政策解释和处置提示",
            supported_scenarios={"settlement_exception_guidance"},
            required_roles={"medical_office", "cashier"},
            required_permissions={"mcp:invoke:read"},
            risk_level=McpRiskLevel.LOW,
            input_schema={"error_code": "string"},
            output_schema={"policy_explanation": "string", "handling_hints": "list[string]"},
        ),
        McpCapability(
            capability_id="cap-search-policy-clause",
            server_id=POLICY_KNOWLEDGE_MCP_SERVER_ID,
            name="search_policy_clause",
            capability_type=McpCapabilityType.TOOL,
            description="按关键词检索医保政策条款摘要",
            supported_scenarios={"settlement_exception_guidance", "pre_discharge_quality_control"},
            required_roles={"medical_office", "cashier", "medical_record_staff", "clinician"},
            required_permissions={"mcp:invoke:read"},
            risk_level=McpRiskLevel.LOW,
            input_schema={"keyword": "string", "scenario": "string"},
            output_schema={"clauses": "list[object]"},
        ),
        McpCapability(
            capability_id="cap-get-pre-discharge-checklist",
            server_id=PRE_DISCHARGE_QC_MCP_SERVER_ID,
            name="get_pre_discharge_checklist",
            capability_type=McpCapabilityType.TOOL,
            description="读取出院前医保质控检查项清单",
            supported_scenarios={"pre_discharge_quality_control"},
            required_roles={"medical_office", "medical_record_staff", "clinician"},
            required_permissions={"mcp:invoke:read"},
            risk_level=McpRiskLevel.LOW,
            input_schema={"patient_id": "string", "encounter_id": "string"},
            output_schema={"checklist": "list[object]"},
        ),
        McpCapability(
            capability_id="cap-match-drug-restriction",
            server_id=PRE_DISCHARGE_QC_MCP_SERVER_ID,
            name="match_drug_restriction",
            capability_type=McpCapabilityType.TOOL,
            description="匹配药品与诊断的医保限制条件",
            supported_scenarios={"pre_discharge_quality_control"},
            required_roles={"medical_office", "medical_record_staff", "clinician"},
            required_permissions={"mcp:invoke:read"},
            risk_level=McpRiskLevel.LOW,
            input_schema={"drug_name": "string", "diagnosis_code": "string"},
            output_schema={"matched": "boolean", "restriction_summary": "string"},
        ),
    ]


def bootstrap_demo_mcp_data(storage: McpStorage) -> None:
    registry = McpRegistryService(storage)
    for server in demo_mcp_servers():
        registry.register_server(server)
    for capability in demo_mcp_capabilities():
        registry.register_capability(capability)


class DemoMcpToolService:
    def __init__(self, storage: McpStorage | None = None) -> None:
        self._storage = storage or InMemoryMcpStorage()
        self._registry = McpRegistryService(self._storage)
        self._gateway = InMemoryMcpClientGateway(tool_results=self._tool_results())
        bootstrap_demo_mcp_data(self._storage)

    def invoke_for_scenario(self, scenario: str, role: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        selection = self._registry.select_capabilities(
            McpCapabilitySelectionRequest(
                scenario=scenario,
                role=role,
                permissions={"mcp:invoke:read"},
                capability_type=McpCapabilityType.TOOL,
                max_risk_level=McpRiskLevel.LOW,
            )
        )
        if selection.status is not KnowledgeExtensionStatus.SUCCESS:
            return self._empty_result(tool_name, "未选中可用 MCP 工具", selection.status.value, [event.model_dump(mode="json") for event in selection.audit_events])

        capability = next((item for item in selection.selected_capabilities if item.name == tool_name), None)
        if capability is None:
            return self._empty_result(tool_name, "未找到指定 MCP 工具", "no_hit", [event.model_dump(mode="json") for event in selection.audit_events])

        server = self._storage.get_server(capability.server_id)
        if server is None:
            return self._empty_result(tool_name, "MCP 服务未注册", "server_missing", [event.model_dump(mode="json") for event in selection.audit_events])

        invocation = self._gateway.invoke_tool(server, capability, arguments)
        output = invocation.output
        return {
            **output,
            "status": invocation.status.value,
            "server_id": capability.server_id,
            "audit_events": [
                *[event.model_dump(mode="json") for event in selection.audit_events],
                *[event.model_dump(mode="json") for event in invocation.audit_events],
            ],
        }

    def _empty_result(self, tool_name: str, summary: str, status: str, audit_events: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "tool_name": tool_name,
            "source": "mcp_registry",
            "status": status,
            "summary": summary,
            "recommendations": [],
            "risks": [],
            "citations": [],
            "audit_events": audit_events,
        }

    def _tool_results(self) -> dict[str, dict[str, Any]]:
        return {
            "cap-query-policy-by-error-code": {
                "tool_name": "query_policy_by_error_code",
                "source": POLICY_KNOWLEDGE_MCP_SERVER_ID,
                "server_id": POLICY_KNOWLEDGE_MCP_SERVER_ID,
                "summary": "MCP 工具提示：错误码对应费用明细未全部上传，应先补传失败明细后重新预结算。",
                "policy_explanation": "费用上传完整性是医保预结算前置条件，缺失费用明细会导致结算校验失败。",
                "recommendations": ["核对收费系统费用上传状态", "补传失败费用明细", "重新发起医保预结算并保留接口返回流水号"],
                "risks": [],
                "citations": [
                    {"source_type": "mcp_tool", "source_id": "cap-query-policy-by-error-code", "summary": "医保政策知识 MCP 错误码查询工具"}
                ],
            },
            "cap-search-policy-clause": {
                "tool_name": "search_policy_clause",
                "source": POLICY_KNOWLEDGE_MCP_SERVER_ID,
                "server_id": POLICY_KNOWLEDGE_MCP_SERVER_ID,
                "summary": "MCP 工具提示：已命中费用上传完整性相关政策条款。",
                "clauses": [{"clause_id": "POLICY-UPLOAD-001", "summary": "医保结算前应完成费用明细上传与校验。"}],
                "recommendations": ["将政策条款作为导办解释来源，不替代医保正式审核结论"],
                "risks": [],
                "citations": [
                    {"source_type": "mcp_tool", "source_id": "cap-search-policy-clause", "summary": "医保政策知识 MCP 条款检索工具"}
                ],
            },
            "cap-get-pre-discharge-checklist": {
                "tool_name": "get_pre_discharge_checklist",
                "source": PRE_DISCHARGE_QC_MCP_SERVER_ID,
                "server_id": PRE_DISCHARGE_QC_MCP_SERVER_ID,
                "summary": "MCP 工具补充：出院前应检查费用上传、限制用药、病案首页一致性。",
                "checklist": [
                    {"item": "费用上传完整性", "risk_level": "medium"},
                    {"item": "限制用药适应症", "risk_level": "medium"},
                    {"item": "病案首页诊断一致性", "risk_level": "medium"},
                ],
                "recommendations": ["优先处理费用上传和病案首页一致性问题"],
                "risks": [
                    {"risk_type": "MCP补充风险", "risk_level": "medium", "responsible_role": "医保办", "recommendation": "核对医保目录限制条件与费用上传完成状态"}
                ],
                "citations": [
                    {"source_type": "mcp_tool", "source_id": "cap-get-pre-discharge-checklist", "summary": "出院质控知识 MCP 检查清单工具"}
                ],
            },
            "cap-match-drug-restriction": {
                "tool_name": "match_drug_restriction",
                "source": PRE_DISCHARGE_QC_MCP_SERVER_ID,
                "server_id": PRE_DISCHARGE_QC_MCP_SERVER_ID,
                "summary": "MCP 工具补充：存在限制用药条件匹配风险，需人工核对诊断和适应症。",
                "matched": True,
                "restriction_summary": "限制用药需匹配诊断与医保目录限定条件。",
                "recommendations": ["核对诊断编码和药品适应症是否一致"],
                "risks": [
                    {"risk_type": "限制用药匹配风险", "risk_level": "medium", "responsible_role": "临床科室", "recommendation": "补充适应症依据或调整医嘱说明"}
                ],
                "citations": [
                    {"source_type": "mcp_tool", "source_id": "cap-match-drug-restriction", "summary": "出院质控知识 MCP 限制用药匹配工具"}
                ],
            },
        }


def build_demo_mcp_tool_service() -> DemoMcpToolService:
    return DemoMcpToolService()
