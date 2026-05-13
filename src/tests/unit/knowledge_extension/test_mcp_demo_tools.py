from src.knowledge_extension.mcp_registry.demo_tools import build_demo_mcp_tool_service, demo_mcp_capabilities, demo_mcp_servers


def test_demo_mcp_tool_service_explains_settlement_error():
    service = build_demo_mcp_tool_service()

    result = service.invoke_for_scenario(
        scenario="settlement_exception_guidance",
        role="medical_office",
        tool_name="query_policy_by_error_code",
        arguments={"patient_id": "P001", "encounter_id": "E001", "error_code": "E-UPLOAD-001"},
    )

    assert result["tool_name"] == "query_policy_by_error_code"
    assert result["source"] == "medical-insurance-policy-knowledge-mcp"
    assert "错误码" in result["summary"]
    assert result["recommendations"]
    assert result["citations"][0]["source_type"] == "mcp_tool"


def test_demo_mcp_tool_service_supplements_pre_discharge_risks():
    service = build_demo_mcp_tool_service()

    result = service.invoke_for_scenario(
        scenario="pre_discharge_quality_control",
        role="medical_office",
        tool_name="get_pre_discharge_checklist",
        arguments={"patient_id": "P001", "encounter_id": "E001"},
    )

    assert result["tool_name"] == "get_pre_discharge_checklist"
    assert result["source"] == "pre-discharge-qc-knowledge-mcp"
    assert result["risks"]
    assert result["risks"][0]["risk_type"] == "MCP补充风险"
    assert result["citations"][0]["source_id"] == "cap-get-pre-discharge-checklist"


def test_demo_mcp_data_uses_two_servers_and_atomic_tools():
    servers = demo_mcp_servers()
    capabilities = demo_mcp_capabilities()

    assert {server.server_id for server in servers} == {"medical-insurance-policy-knowledge-mcp", "pre-discharge-qc-knowledge-mcp"}
    assert {capability.name for capability in capabilities} == {"query_policy_by_error_code", "search_policy_clause", "get_pre_discharge_checklist", "match_drug_restriction"}
    assert "explain_settlement_error" not in {capability.name for capability in capabilities}
    assert "pre_discharge_risk_supplement" not in {capability.name for capability in capabilities}
