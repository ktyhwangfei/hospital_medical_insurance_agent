"""TDD tests for unified orchestration layer.

Tests that:
- POST /chat settlement → LangGraph → AgentResponse (format unchanged)
- POST /chat pre_discharge → LangGraph → AgentResponse (format unchanged)
- @-mention skill call still works
- Intent matching routes to correct graph
- execute_plan() dispatches via graph for settlement/pre_discharge
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.runtime.api.app import create_app
from src.runtime.api.schemas import AgentResponse
from src.runtime.intent.models import IntentResult
from src.runtime.langgraph.pre_discharge_qc import build_pre_discharge_qc_graph
from src.runtime.langgraph.settlement_exception import build_settlement_exception_graph
from src.runtime.orchestration.service import execute_plan
from src.runtime.planning.models import ExecutionPlan, PlanStep, StepType


def _make_settlement_state(**kwargs) -> dict:
    base = {
        "intent": "settlement",
        "role": "medical_office",
        "messages": [],
        "citations": [],
        "uncertainties": [],
        "requires_confirmation": False,
        "human_confirmed": False,
        "workflow_id": "wf-orch-test",
        "patient_id": "P001",
        "encounter_id": "E001",
        "claim_detail": {},
        "error_code": "E-UPLOAD-001",
        "error_detail": {},
        "recommendation": "",
        "blocked_actions": [],
    }
    base.update(kwargs)
    return base


def _make_qc_state(**kwargs) -> dict:
    base = {
        "intent": "pre_discharge",
        "role": "doctor",
        "messages": [],
        "citations": [],
        "uncertainties": [],
        "requires_confirmation": False,
        "human_confirmed": False,
        "workflow_id": "wf-orch-test-qc",
        "patient_id": "P001",
        "encounter_id": "E001",
        "patient_summary": {},
        "quality_issues": [],
        "rule_results": [],
        "qc_recommendation": "",
    }
    base.update(kwargs)
    return base


# ====================================================================
# Unit tests: execute_plan() graph dispatch
# ====================================================================


class TestExecutePlanGraphDispatch:

    def test_execute_plan_settlement_dispatches_to_graph(self):
        """execute_plan with settlement scenario executes LangGraph."""
        from src.runtime.context.models import RuntimeContext

        context = RuntimeContext(
            request_id="req-test",
            workflow_id="wf-test",
            user_id="U001",
            role="medical_office",
            message="医保结算失败",
            patient_id="P001",
            encounter_id="E001",
            intent="settlement_exception_guidance",
            intent_confidence=0.9,
            intent_entities={},
            intent_citations=[],
            requested_at="2026-05-09T00:00:00Z",
        )
        plan = ExecutionPlan(
            workflow_id="wf-test",
            scenario="settlement_exception_guidance",
            goal="医保结算失败",
            steps=[PlanStep(step_id="run", step_type=StepType.ADAPTER_CALL, capability="insurance_interface.query_transaction")],
            output_requirements=["citations_or_uncertainties"],
        )

        response = execute_plan(context, plan)
        assert isinstance(response, AgentResponse)
        assert response.scenario == "settlement_exception_guidance"
        assert response.status == "completed"
        assert len(response.citations) > 0

    def test_execute_plan_pre_discharge_dispatches_to_graph(self):
        """execute_plan with qc scenario dispatches to LangGraph."""
        from src.runtime.context.models import RuntimeContext

        context = RuntimeContext(
            request_id="req-test",
            workflow_id="wf-test",
            user_id="U001",
            role="doctor",
            message="检查出院前风险",
            patient_id="P001",
            encounter_id="E001",
            intent="pre_discharge_quality_control",
            intent_confidence=0.9,
            intent_entities={},
            intent_citations=[],
            requested_at="2026-05-09T00:00:00Z",
        )
        plan = ExecutionPlan(
            workflow_id="wf-test",
            scenario="pre_discharge_quality_control",
            goal="检查出院前风险",
            steps=[PlanStep(step_id="run_qc", step_type=StepType.ADAPTER_CALL, capability="pre_audit.query_audit_result")],
            output_requirements=["citations_or_uncertainties"],
        )

        response = execute_plan(context, plan)
        assert isinstance(response, AgentResponse)
        assert response.scenario == "pre_discharge_quality_control"
        assert response.status == "completed"

    def test_execute_plan_unknown_scenario_falls_back(self):
        """execute_plan with unknown scenario returns not_implemented."""
        from src.runtime.context.models import RuntimeContext

        context = RuntimeContext(
            request_id="req-test",
            workflow_id="wf-test",
            user_id="U001",
            role="doctor",
            message="未知请求",
            patient_id="P001",
            encounter_id="E001",
            intent="unknown",
            intent_confidence=0.5,
            intent_entities={},
            intent_citations=[],
            requested_at="2026-05-09T00:00:00Z",
        )
        plan = ExecutionPlan(
            workflow_id="wf-test",
            scenario="unknown",
            goal="未知请求",
            steps=[],
            output_requirements=[],
        )

        response = execute_plan(context, plan)
        assert response.status == "not_implemented"


# ====================================================================
# Unit tests: intent → graph routing
# ====================================================================


class TestIntentToGraphRouting:

    def test_settlement_graph_compiles_and_runs(self):
        """Settlement graph runs to completion with normal input."""
        graph = build_settlement_exception_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            _make_settlement_state(),
            {"configurable": {"thread_id": "unit-settle-1"}},
        )
        assert result.get("recommendation") != ""
        assert result.get("claim_detail") != {}
        assert result["requires_confirmation"] is False

    def test_pre_discharge_graph_compiles_and_runs(self):
        """PreDischarge graph runs to completion via confirmed path."""
        graph = build_pre_discharge_qc_graph(checkpointer=MemorySaver())
        thread = {"configurable": {"thread_id": "unit-qc-1"}}
        graph.invoke(_make_qc_state(), thread)
        result = graph.invoke(Command(resume={"confirmed": True}), thread)
        assert result.get("qc_recommendation") != ""
        assert len(result.get("quality_issues", [])) > 0

    def test_normal_settlement_graph_completes_without_interrupt(self):
        """Normal settlement (no high-risk) runs through all nodes without interrupt."""
        graph = build_settlement_exception_graph(checkpointer=MemorySaver())
        result = graph.invoke(
            _make_settlement_state(error_code="E-UPLOAD-001"),
            {"configurable": {"thread_id": "unit-settle-2"}},
        )
        # Should have gone through validate_claim -> check_high_risk -> query_error_knowledge -> build_recommendation
        assert result["recommendation"] != ""
        assert result["requires_confirmation"] is False

    def test_settlement_high_risk_hits_interrupt(self):
        """Settlement with high-risk actions hits human_confirmation interrupt."""
        from src.adapters.base import AdapterCallContext, successful_result
        from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter

        mock_result = successful_result(
            context=AdapterCallContext(input_summary={}),
            source_system="insurance_interface",
            source_record_id="P003:E003",
            capability="query_transaction",
            data={"error_code": "E-REFUND-001", "settlement_status": "failed"},
        )
        graph = build_settlement_exception_graph(checkpointer=MemorySaver())
        with patch.object(InMemoryInsuranceInterfaceAdapter, "query_transaction", return_value=mock_result):
            result = graph.invoke(
                _make_settlement_state(patient_id="P003", encounter_id="E003"),
                {"configurable": {"thread_id": "unit-settle-highrisk"}},
            )
            assert len(result.get("blocked_actions", [])) > 0


# ====================================================================
# Integration tests: /chat endpoint through LangGraph path
# ====================================================================


class TestChatSettlementLangGraph:

    @patch("src.runtime.scenario_executor.match_skill_by_intent", return_value=None)
    @patch("src.runtime.api.routes.parse_intent")
    def test_settlement_chat_returns_agent_response_via_graph(self, mock_parse, mock_match):
        """POST /chat settlement (no-skill-match) returns AgentResponse from LangGraph."""
        mock_parse.return_value = IntentResult(
            intent="settlement_exception_guidance",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="医保结算情况怎么样",
        )
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "medical_office",
                "message": "医保结算情况怎么样",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        )
        body = response.json()
        assert response.status_code == 200
        assert body["scenario"] == "settlement_exception_guidance"
        assert body["status"] == "completed"
        assert "workflow_id" in body["audit"]
        assert "steps" in body["audit"]
        AgentResponse(**body)

    @patch("src.runtime.scenario_executor.match_skill_by_intent", return_value=None)
    @patch("src.runtime.api.routes.parse_intent")
    def test_settlement_chat_includes_result_fields(self, mock_parse, mock_match):
        """Settlement AgentResponse from graph includes expected result fields."""
        mock_parse.return_value = IntentResult(
            intent="settlement_exception_guidance",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="医保结算情况怎么样",
        )
        client = TestClient(create_app())
        body = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "medical_office",
                "message": "医保结算情况怎么样",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        ).json()

        result = body["result"]
        assert "exception_type" in result
        assert "error_code" in result
        assert "error_explanation" in result
        assert "responsible_role" in result
        assert "recommended_steps" in result

    @patch("src.runtime.scenario_executor.match_skill_by_intent", return_value=None)
    @patch("src.runtime.api.routes.parse_intent")
    def test_settlement_chat_includes_citations(self, mock_parse, mock_match):
        """Settlement response from graph includes citations."""
        mock_parse.return_value = IntentResult(
            intent="settlement_exception_guidance",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="医保结算情况怎么样",
        )
        client = TestClient(create_app())
        body = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "medical_office",
                "message": "医保结算情况怎么样",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        ).json()

        assert len(body["citations"]) > 0
        source_types = {c["source_type"] for c in body["citations"]}
        assert "insurance_interface" in source_types
        assert "knowledge_error_code" in source_types


class TestChatPreDischargeLangGraph:

    @patch("src.runtime.langgraph.pre_discharge_qc.InMemoryPreAuditAdapter.query_audit_result")
    @patch("src.runtime.langgraph.pre_discharge_qc.InMemoryDrgDipAdapter.query_group_result")
    @patch("src.runtime.langgraph.pre_discharge_qc.InMemoryMedicalRecordAdapter.query_homepage")
    @patch("src.runtime.scenario_executor.match_skill_by_intent", return_value=None)
    @patch("src.runtime.api.routes.parse_intent")
    def test_pre_discharge_chat_returns_agent_response(self, mock_parse, mock_match, mock_mr, mock_drg, mock_pre):
        """POST /chat pre_discharge (no-skill-match) returns AgentResponse from LangGraph."""
        from src.adapters.base import AdapterCallContext, successful_result
        no_risk = successful_result(
            context=AdapterCallContext(input_summary={}),
            source_system="pre_audit",
            source_record_id="P001:E001",
            capability="query_audit_result",
            data={"risk": "", "patient_id": "P001", "encounter_id": "E001"},
        )
        mock_pre.return_value = no_risk
        mock_drg.return_value = no_risk
        mock_mr.return_value = no_risk
        mock_parse.return_value = IntentResult(
            intent="pre_discharge_quality_control",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="出院前检查医保情况",
        )
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "medical_office",
                "message": "出院前检查医保情况",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        )
        body = response.json()
        assert response.status_code == 200
        assert body["scenario"] == "pre_discharge_quality_control"
        assert body["status"] == "completed"
        assert "workflow_id" in body["audit"]
        AgentResponse(**body)

    @patch("src.runtime.langgraph.pre_discharge_qc.InMemoryPreAuditAdapter.query_audit_result")
    @patch("src.runtime.langgraph.pre_discharge_qc.InMemoryDrgDipAdapter.query_group_result")
    @patch("src.runtime.langgraph.pre_discharge_qc.InMemoryMedicalRecordAdapter.query_homepage")
    @patch("src.runtime.scenario_executor.match_skill_by_intent", return_value=None)
    @patch("src.runtime.api.routes.parse_intent")
    def test_pre_discharge_chat_includes_result_fields(self, mock_parse, mock_match, mock_mr, mock_drg, mock_pre):
        """QC response from graph includes risks field."""
        from src.adapters.base import AdapterCallContext, successful_result
        no_risk = successful_result(
            context=AdapterCallContext(input_summary={}),
            source_system="pre_audit",
            source_record_id="P001:E001",
            capability="query_audit_result",
            data={"risk": "", "patient_id": "P001", "encounter_id": "E001"},
        )
        mock_pre.return_value = no_risk
        mock_drg.return_value = no_risk
        mock_mr.return_value = no_risk
        mock_parse.return_value = IntentResult(
            intent="pre_discharge_quality_control",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="出院前检查医保情况",
        )
        client = TestClient(create_app())
        body = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "medical_office",
                "message": "出院前检查医保情况",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        ).json()

        assert "risks" in body["result"]
        assert isinstance(body["result"]["risks"], list)

    @patch("src.runtime.scenario_executor.match_skill_by_intent", return_value=None)
    @patch("src.runtime.api.routes.parse_intent")
    def test_pre_discharge_chat_includes_citations(self, mock_parse, mock_match):
        """QC response includes citations."""
        mock_parse.return_value = IntentResult(
            intent="pre_discharge_quality_control",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="出院前检查医保情况",
        )
        client = TestClient(create_app())
        body = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "medical_office",
                "message": "出院前检查医保情况",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        ).json()

        assert len(body["citations"]) > 0


# ====================================================================
# Tests: @-mention and skill matching still work
# ====================================================================


class TestMentionSkillCallWorks:

    @patch("src.runtime.api.routes.parse_intent")
    def test_mention_skill_settlement(self, mock_parse):
        """@-mention skill call still works via _try_langgraph_execution."""
        from src.runtime.intent.models import IntentResult
        mock_parse.return_value = IntentResult(
            intent="settlement_exception_guidance",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="医保结算失败",
        )
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "cashier",
                "message": "@settlement_exception_guidance 医保结算失败",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        )
        body = response.json()
        assert response.status_code == 200
        assert body["status"] in ("completed", "not_implemented")


class TestSkillMatchStillWorks:

    @patch("src.runtime.api.routes.parse_intent")
    def test_keyword_skill_match_settlement(self, mock_parse):
        """Keyword-matched skill resolution still works for settlement."""
        from src.runtime.intent.models import IntentResult
        mock_parse.return_value = IntentResult(
            intent="settlement_exception_guidance",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="医保结算失败",
        )
        # "医保结算失败" matches skill intent_keywords=["结算失败",...]
        client = TestClient(create_app())
        response = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "cashier",
                "message": "医保结算失败",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        )
        body = response.json()
        assert response.status_code == 200
        assert body["status"] in ("completed", "not_implemented")


# ====================================================================
# Tests: API response shape contract
# ====================================================================


class TestAgentResponseShape:

    @patch("src.runtime.api.routes.parse_intent")
    def test_response_has_expected_keys(self, mock_parse):
        """AgentResponse from /chat has all required fields."""
        from src.runtime.intent.models import IntentResult
        mock_parse.return_value = IntentResult(
            intent="settlement_exception_guidance",
            confidence=0.8,
            entities={},
            citations=[],
            raw_message="医保结算失败",
        )
        client = TestClient(create_app())
        body = client.post(
            "/api/v1/medical-insurance-ai-agent/chat",
            json={
                "user_id": "U001",
                "role": "medical_office",
                "message": "医保结算失败",
                "patient_id": "P001",
                "encounter_id": "E001",
            },
        ).json()

        expected_keys = {
            "scenario", "status", "result", "citations", "tasks",
            "missing_fields", "uncertainties", "blocked_actions", "audit",
        }
        assert set(body.keys()) == expected_keys
