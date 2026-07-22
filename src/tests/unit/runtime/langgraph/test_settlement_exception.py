from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.adapters.base import AdapterCallContext, successful_result
from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.knowledge_extension.knowledge_stub import create_knowledge_store
from src.runtime.langgraph.settlement_exception import (
    build_settlement_exception_graph,
    check_high_risk,
    route_after_high_risk_check,
    settlement_exception_graph,
)


def _make_input(
    patient_id: str = "",
    encounter_id: str = "",
    error_code: str = "",
    blocked_actions: list | None = None,
) -> dict:
    return {
        "intent": "settlement",
        "role": "cashier",
        "messages": [],
        "citations": [],
        "uncertainties": [],
        "requires_confirmation": False,
        "workflow_id": "wf-test",
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "claim_detail": {},
        "error_code": error_code,
        "error_detail": {},
        "recommendation": "",
        "blocked_actions": blocked_actions or [],
    }


class TestSettlementExceptionGraph:

    def test_graph_compile_succeeds(self):
        graph = build_settlement_exception_graph()
        assert graph is not None

    def test_settlement_exception_graph_export_is_compiled(self):
        assert hasattr(settlement_exception_graph, "invoke")

    def test_normal_flow_returns_recommendation_with_citations(self):
        memory = MemorySaver()
        graph = build_settlement_exception_graph(checkpointer=memory)
        inputs = _make_input(patient_id="P001", encounter_id="E001")
        result = graph.invoke(inputs, {"configurable": {"thread_id": "normal-1"}})

        assert result["recommendation"] != ""
        assert len(result["citations"]) > 0
        source_types = {c["source_type"] for c in result["citations"]}
        assert "insurance_interface" in source_types
        assert "knowledge_error_code" in source_types
        assert result["requires_confirmation"] is False

    def test_normal_flow_populates_claim_detail(self):
        memory = MemorySaver()
        graph = build_settlement_exception_graph(checkpointer=memory)
        inputs = _make_input(patient_id="P001", encounter_id="E001")
        result = graph.invoke(inputs, {"configurable": {"thread_id": "normal-2"}})

        assert result["claim_detail"] != {}
        assert result["error_code"] == "E-UPLOAD-001"
        expected = create_knowledge_store().get_error_code("E-UPLOAD-001") or {}
        assert result["error_detail"] == expected

    def test_high_risk_triggers_human_confirmation_interrupt(self):
        mock_result = successful_result(
            context=AdapterCallContext(input_summary={}),
            source_system="insurance_interface",
            source_record_id="P003:E003",
            capability="query_transaction",
            data={"error_code": "E-REFUND-001", "settlement_status": "failed"},
        )
        memory = MemorySaver()
        graph = build_settlement_exception_graph(checkpointer=memory)

        with patch.object(
            InMemoryInsuranceInterfaceAdapter,
            "query_transaction",
            return_value=mock_result,
        ):
            result = graph.invoke(
                _make_input(patient_id="P003", encounter_id="E003"),
                {"configurable": {"thread_id": "high-risk-1"}},
            )

            assert len(result.get("blocked_actions", [])) > 0

            final = graph.invoke(
                Command(resume={"confirmed": True}),
                {"configurable": {"thread_id": "high-risk-1"}},
            )
            assert final["recommendation"] != ""
            assert final["requires_confirmation"] is True

    def test_high_risk_detected_by_risk_flags_in_claim(self):
        mock_result = successful_result(
            context=AdapterCallContext(input_summary={}),
            source_system="insurance_interface",
            source_record_id="P004:E004",
            capability="query_transaction",
            data={"error_code": "E-OTHER-001", "settlement_status": "failed", "risk_flags": ["退费"]},
        )
        memory = MemorySaver()
        graph = build_settlement_exception_graph(checkpointer=memory)

        with patch.object(
            InMemoryInsuranceInterfaceAdapter,
            "query_transaction",
            return_value=mock_result,
        ):
            result = graph.invoke(
                _make_input(patient_id="P004", encounter_id="E004"),
                {"configurable": {"thread_id": "high-risk-2"}},
            )

            assert "退费" in result.get("blocked_actions", [])


class TestCheckHighRisk:

    def test_no_high_risk_returns_empty_blocked(self):
        state = _make_input(error_code="E-UPLOAD-001")
        result = check_high_risk(state)
        assert result["blocked_actions"] == []

    def test_high_risk_error_code_detected(self):
        state = _make_input(error_code="E-REFUND-001")
        result = check_high_risk(state)
        assert len(result["blocked_actions"]) > 0

    def test_high_risk_detected_preserves_existing_blocked(self):
        state = _make_input(error_code="E-REFUND-001", blocked_actions=["退费"])
        result = check_high_risk(state)
        assert "退费" in result["blocked_actions"]

    def test_risk_flags_in_claim_detail_detected(self):
        state = _make_input(error_code="E-OTHER-001")
        state["claim_detail"] = {"risk_flags": ["冲正"]}
        result = check_high_risk(state)
        assert "冲正" in result["blocked_actions"]

    def test_multiple_high_risk_indicators(self):
        state = _make_input(error_code="E-REFUND-CANCEL-001")
        result = check_high_risk(state)
        assert "refund" in result["blocked_actions"]
        assert "cancel" in result["blocked_actions"]


class TestRouteAfterHighRiskCheck:

    def test_blocked_actions_routes_to_human_confirmation(self):
        state = _make_input(blocked_actions=["退费"])
        assert route_after_high_risk_check(state) == "human_confirmation"

    def test_no_blocked_actions_routes_to_query_error_knowledge(self):
        state = _make_input()
        assert route_after_high_risk_check(state) == "query_error_knowledge"

    def test_empty_blocked_list_routes_to_knowledge(self):
        state = _make_input(blocked_actions=[])
        assert route_after_high_risk_check(state) == "query_error_knowledge"


class TestValidateClaim:

    def test_populates_claim_detail_for_valid_patient(self):
        from src.runtime.langgraph.settlement_exception import validate_claim

        state = _make_input(patient_id="P001", encounter_id="E001")
        result = validate_claim(state)
        assert result["claim_detail"] != {}
        assert result["error_code"] == "E-UPLOAD-001"

    def test_handles_missing_patient_gracefully(self):
        from src.runtime.langgraph.settlement_exception import validate_claim

        state = _make_input(patient_id="UNKNOWN", encounter_id="X001", error_code="UNKNOWN-ERR")
        result = validate_claim(state)
        assert result["claim_detail"] == {}
        assert result.get("error_code") == "UNKNOWN-ERR"
