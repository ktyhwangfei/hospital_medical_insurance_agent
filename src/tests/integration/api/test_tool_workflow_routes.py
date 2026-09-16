"""Tool / Workflow 可视化 API 测试（含 #72 节点模型与真实数据源绑定）。"""

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
    # 2026-09-16 盘点后：退费记录/人员定位均已接入真实数据源并绑定实现。
    assert items["tool_get_settlement_fact"]["bound"] is True
    assert items["tool_get_refund_record"]["bound"] is True
    assert items["tool_resolve_settlement_by_person"]["bound"] is True


def test_list_tools_exposes_input_and_output_schemas():
    """输入/输出字段契约必须随清单返回，供 Portal 优先展示字段信息。"""
    response = _client().get("/api/v1/medical-insurance-ai-agent/tool-registry/tools")

    assert response.status_code == 200
    items = {item["tool_id"]: item for item in response.json()["items"]}

    fact = items["tool_get_settlement_fact"]
    assert fact["input_schema"]["settlement_id"]["required"] is True
    assert "basic_pooling_payment" in fact["output_schema"]
    assert fact["output_schema"]["basic_pooling_payment"]["type"] == "number"

    # 费用明细支持单笔与批量双入口（同药跨单对比的上游取数）。
    fee = items["tool_get_fee_detail"]
    assert set(fee["input_schema"]) == {"settlement_id", "settlement_ids"}
    assert fee["input_schema"]["settlement_id"]["required"] is False
    assert fee["input_schema"]["settlement_ids"]["type"] == "array<string>"

    # 退费记录：真实双链路 SQL（医保端 tflydjh + HIS 端退费交易）。
    detail = items["tool_get_refund_record"]["execution_detail"]
    assert "tflydjh" in detail
    assert "o_Trade" in detail
    assert "T_HasRefundmented" in detail

    # 所有已登记 Tool 均应声明非空输入/输出契约。
    for tool_id, tool in items.items():
        assert tool["input_schema"], f"{tool_id} 缺输入字段契约"
        assert tool["output_schema"], f"{tool_id} 缺输出字段契约"


def test_list_tools_registers_person_settlement_resolver_with_real_sources():
    """人员定位结算单 Tool：双源真实查询 + 敏感字段脱敏约束（2026-09-16 盘点后接入）。"""
    response = _client().get("/api/v1/medical-insurance-ai-agent/tool-registry/tools")

    assert response.status_code == 200
    items = {item["tool_id"]: item for item in response.json()["items"]}
    tool = items["tool_resolve_settlement_by_person"]

    assert tool["bound"] is True
    assert tool["risk_level"] == "medium"
    assert tool["target_ref"] == "src.adapters.ports.settlement_resolver_port"

    # 输出契约：三态定位 + 候选列表。
    assert "match_status" in tool["output_schema"]
    assert "settlement_candidates" in tool["output_schema"]

    # 执行细节：双源 SQL（门诊 HIS + 住院医保端）+ 不回显身份证。
    detail = tool["execution_detail"]
    assert "o_Trade" in detail
    assert "yb_brdjxx" in detail
    assert "multiple_candidates" in detail
    assert "不回显身份证" in detail


def test_list_tools_exposes_only_independently_invokable_capabilities():
    response = _client().get("/api/v1/medical-insurance-ai-agent/tool-registry/tools")

    assert response.status_code == 200
    items = {item["tool_id"]: item for item in response.json()["items"]}
    # 数据类和知识类继续作为可独立调用 Tool；内部确定性计算改由 DomainNode 承载。
    for tool_id in (
        "tool_query_semantic_metrics",
        "tool_get_fee_detail",
        "tool_get_benefit_stacking",
        "tool_retrieve_policy_evidence",
        "tool_match_trusted_question",
    ):
        assert tool_id in items, f"{tool_id} 未登记"
        assert items[tool_id]["bound"] is True, f"{tool_id} 未绑定实现"
        assert items[tool_id]["status"] == "materialized"
    # 对比计算已下沉为领域节点，不再作为 Tool 登记。
    assert "tool_compare_settlement_vs_policy" not in items
    assert "tool_compare_same_drug_across_settlements" not in items


def test_list_workflows_exposes_refund_verification_with_step_binding():
    response = _client().get("/api/v1/medical-insurance-ai-agent/workflow-catalog/workflows")

    assert response.status_code == 200
    workflows = {item["workflow_id"]: item for item in response.json()["items"]}
    wf = workflows["wf_refund_verification"]
    steps = {step["step_id"]: step for step in wf["steps"]}
    assert [step["step_id"] for step in wf["steps"]] == [
        "fetch_settlement",
        "fetch_fee_detail",
        "fetch_refund_record",
        "public_result",
    ]
    assert steps["fetch_settlement"]["input_mapping"] == {
        "settlement_id": "context.settlement_id"
    }
    assert all(step["bound"] is True for step in wf["steps"])
    assert steps["public_result"]["node_type"] == "output"
    assert steps["public_result"]["source_ref"] == "fetch_refund_record"
    assert wf["missing_evidence_rules"][0]["field_name"] == "settlement_id"


def test_list_workflows_exposes_reimbursement_diff_and_benefit_stacking():
    """Issue #68 问题 1/3 的两条 Workflow：Tool 取数 + 领域节点对比 + 输出节点。"""
    response = _client().get("/api/v1/medical-insurance-ai-agent/workflow-catalog/workflows")

    assert response.status_code == 200
    workflows = {item["workflow_id"]: item for item in response.json()["items"]}

    diff = workflows["wf_settlement_reimbursement_diff"]
    assert diff["missing_evidence_rules"][0]["field_name"] == "settlement_ids"
    steps = {step["step_id"]: step for step in diff["steps"]}
    assert steps["fetch_fee_details"]["node_type"] == "tool"
    assert steps["fetch_fee_details"]["input_mapping"] == {
        "settlement_ids": "context.settlement_ids"
    }
    assert steps["same_drug_compare"]["node_type"] == "domain"
    assert steps["same_drug_compare"]["handler_id"] == "same_drug_compare"
    assert steps["public_result"]["source_ref"] == "same_drug_compare"
    assert all(step["bound"] is True for step in diff["steps"])

    benefit = workflows["wf_benefit_stacking_attribution"]
    assert [step["tool_id"] for step in benefit["steps"] if step["tool_id"]] == [
        "tool_get_settlement_fact",
        "tool_get_benefit_stacking",
    ]
    assert benefit["steps"][-1]["node_type"] == "output"
    assert benefit["steps"][-1]["source_ref"] == "fetch_benefit_stacking"
    assert all(step["bound"] is True for step in benefit["steps"])


def test_list_workflows_exposes_settlement_explain_chain_with_input_mapping():
    response = _client().get("/api/v1/medical-insurance-ai-agent/workflow-catalog/workflows")

    assert response.status_code == 200
    workflows = {item["workflow_id"]: item for item in response.json()["items"]}
    wf = workflows["wf_outpatient_settlement_explain"]
    steps = {step["step_id"]: step for step in wf["steps"]}

    assert [step["step_id"] for step in wf["steps"]] == [
        "fetch_settlement",
        "retrieve_policy_evidence",
        "check_evidence",
        "compare_settlement_vs_policy",
        "merge_evidence",
        "public_result",
    ]
    assert steps["retrieve_policy_evidence"]["input_mapping"] == {
        "settlement_fact": "fetch_settlement"
    }
    assert steps["fetch_settlement"]["input_mapping"] == {
        "settlement_id": "context.settlement_id"
    }
    assert steps["compare_settlement_vs_policy"]["input_mapping"] == {
        "settlement_fact": "fetch_settlement",
        "policy_evidence": "retrieve_policy_evidence",
    }
    assert steps["fetch_settlement"]["node_type"] == "tool"
    assert steps["compare_settlement_vs_policy"]["node_type"] == "domain"
    assert steps["compare_settlement_vs_policy"]["handler_id"] == "settlement_policy_compare"
    assert steps["public_result"]["node_type"] == "output"
    assert steps["public_result"]["source_ref"] == "merge_evidence"
    assert all(step["bound"] is True for step in wf["steps"])
