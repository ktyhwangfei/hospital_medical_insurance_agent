from unittest.mock import patch

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.runtime.langgraph.pre_discharge_qc import (
    build_pre_discharge_qc_graph,
    pre_discharge_qc_graph,
    route_qc_issues,
)


def _make_input(
    patient_id: str = "",
    encounter_id: str = "",
) -> dict:
    return {
        "intent": "pre_discharge",
        "role": "doctor",
        "messages": [],
        "citations": [],
        "uncertainties": [],
        "requires_confirmation": False,
        "human_confirmed": False,
        "workflow_id": "wf-qc-test",
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "patient_summary": {},
        "quality_issues": [],
        "rule_results": [],
        "qc_recommendation": "",
    }


class TestPreDischargeQcGraph:

    def test_graph_compile_succeeds(self):
        graph = build_pre_discharge_qc_graph()
        assert graph is not None

    def test_exported_graph_is_compiled(self):
        assert hasattr(pre_discharge_qc_graph, "invoke")

    def test_normal_flow_returns_qc_recommendation_with_citations(self):
        memory = MemorySaver()
        graph = build_pre_discharge_qc_graph(checkpointer=memory)
        inputs = _make_input(patient_id="P001", encounter_id="E001")
        thread = {"configurable": {"thread_id": "normal-1"}}

        # First invoke: runs through check_qc_issues, hits interrupt at human_confirmation
        graph.invoke(inputs, thread)

        # Resume with Command: continues past human_confirmation to build_qc_report
        result = graph.invoke(Command(resume={"confirmed": True}), thread)

        assert result["qc_recommendation"] != ""
        assert len(result["citations"]) > 0
        source_types = {c["source_type"] for c in result["citations"]}
        assert "emr" in source_types
        assert "his" in source_types

    def test_normal_flow_populates_quality_issues(self):
        memory = MemorySaver()
        graph = build_pre_discharge_qc_graph(checkpointer=memory)
        inputs = _make_input(patient_id="P001", encounter_id="E001")
        thread = {"configurable": {"thread_id": "normal-2"}}

        graph.invoke(inputs, thread)
        result = graph.invoke(Command(resume={"confirmed": True}), thread)

        assert len(result["quality_issues"]) > 0
        assert len(result["rule_results"]) > 0

    def test_normal_flow_populates_patient_summary(self):
        memory = MemorySaver()
        graph = build_pre_discharge_qc_graph(checkpointer=memory)
        inputs = _make_input(patient_id="P001", encounter_id="E001")
        thread = {"configurable": {"thread_id": "normal-3"}}

        graph.invoke(inputs, thread)
        result = graph.invoke(Command(resume={"confirmed": True}), thread)

        assert result["patient_summary"] != {}
        assert "emr" in result["patient_summary"]
        assert "his" in result["patient_summary"]

    def test_no_issues_early_termination(self):
        memory = MemorySaver()
        graph = build_pre_discharge_qc_graph(checkpointer=memory)
        inputs = _make_input(patient_id="P001", encounter_id="E001")

        from src.adapters.base import AdapterCallContext, successful_result
        from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
        from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
        from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter

        empty_result = successful_result(
            context=AdapterCallContext(input_summary={}),
            source_system="pre_audit",
            source_record_id="P001:E001",
            capability="query_audit_result",
            data={"risk": "", "patient_id": "P001", "encounter_id": "E001"},
        )

        with patch.object(
            InMemoryPreAuditAdapter, "query_audit_result", return_value=empty_result
        ), patch.object(
            InMemoryDrgDipAdapter, "query_group_result", return_value=empty_result
        ), patch.object(
            InMemoryMedicalRecordAdapter, "query_homepage", return_value=empty_result
        ):
            result = graph.invoke(
                inputs, {"configurable": {"thread_id": "no-issues-1"}}
            )
            assert len(result.get("quality_issues", [])) == 0


class TestRouteQcIssues:

    def test_has_issues_returns_has_issues(self):
        state = _make_input()
        state["quality_issues"] = [{"rule": "PRE_AUDIT_RISK", "risk": "合规拒付风险"}]
        assert route_qc_issues(state) == "has_issues"

    def test_no_issues_returns_no_issues(self):
        state = _make_input()
        state["quality_issues"] = []
        assert route_qc_issues(state) == "no_issues"

    def test_empty_quality_issues_returns_no_issues(self):
        state = _make_input()
        assert route_qc_issues(state) == "no_issues"
