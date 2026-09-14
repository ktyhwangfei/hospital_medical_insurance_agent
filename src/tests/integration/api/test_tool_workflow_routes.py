import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_list_tools_exposes_builtin_tools_with_binding_status():
    response = _client().get("/api/v1/medical-insurance-ai-agent/tool-registry/tools")

    assert response.status_code == 200
    items = {item["tool_id"]: item for item in response.json()["items"]}
    assert items["tool_get_settlement_fact"]["bound"] is True
    assert items["tool_get_refund_record"]["bound"] is False


def test_list_tools_covers_data_knowledge_and_calc_categories():
    response = _client().get("/api/v1/medical-insurance-ai-agent/tool-registry/tools")

    assert response.status_code == 200
    items = {item["tool_id"]: item for item in response.json()["items"]}
    # 数据类（语义层对齐）、知识类（向量/结构化）、对比计算类均登记且已绑定实现。
    for tool_id in (
        "tool_query_semantic_metrics",
        "tool_retrieve_policy_evidence",
        "tool_match_trusted_question",
        "tool_compare_settlement_vs_policy",
    ):
        assert tool_id in items, f"{tool_id} 未登记"
        assert items[tool_id]["bound"] is True, f"{tool_id} 未绑定实现"
        assert items[tool_id]["status"] == "materialized"


def test_list_workflows_exposes_refund_verification_with_step_binding():
    response = _client().get("/api/v1/medical-insurance-ai-agent/workflow-catalog/workflows")

    assert response.status_code == 200
    workflows = {item["workflow_id"]: item for item in response.json()["items"]}
    wf = workflows["wf_refund_verification"]
    steps = {step["step_id"]: step for step in wf["steps"]}
    assert steps["fetch_settlement"]["tool_bound"] is True
    assert steps["fetch_refund_record"]["tool_bound"] is False
    assert wf["missing_evidence_rules"][0]["field_name"] == "settlement_id"


def test_list_workflows_exposes_settlement_explain_chain_with_input_mapping():
    response = _client().get("/api/v1/medical-insurance-ai-agent/workflow-catalog/workflows")

    assert response.status_code == 200
    workflows = {item["workflow_id"]: item for item in response.json()["items"]}
    wf = workflows["wf_outpatient_settlement_explain"]
    steps = {step["step_id"]: step for step in wf["steps"]}

    assert [step["step_id"] for step in wf["steps"]] == [
        "fetch_settlement",
        "retrieve_policy_evidence",
        "compare_settlement_vs_policy",
    ]
    assert steps["retrieve_policy_evidence"]["input_mapping"] == {
        "settlement_fact": "fetch_settlement"
    }
    assert steps["compare_settlement_vs_policy"]["input_mapping"] == {
        "settlement_fact": "fetch_settlement",
        "policy_evidence": "retrieve_policy_evidence",
    }
    assert all(step["tool_bound"] is True for step in wf["steps"])
