from src.runtime.api.schemas import AgentResponse


# ============================================================
# Settlement Core Business Functions
# ============================================================

class TestSettlementCoreFunctions:

    def test_query_claim_returns_dict_for_valid_patient(self):
        from src.business_scenarios.settlement_exception_guide.service import query_claim

        result = query_claim("P001", "E001")
        assert isinstance(result, dict)
        assert "data" in result
        assert result["data"]["error_code"] == "E-UPLOAD-001"

    def test_query_claim_returns_dict_for_invalid_patient(self):
        from src.business_scenarios.settlement_exception_guide.service import query_claim

        result = query_claim("UNKNOWN", "X001")
        assert isinstance(result, dict)
        assert "data" in result
        # Unknown patients return empty data without crashing
        assert result["data"] == {}

    def test_query_claim_includes_source_info(self):
        from src.business_scenarios.settlement_exception_guide.service import query_claim

        result = query_claim("P001", "E001")
        assert "source_system" in result
        assert "source_record_id" in result

    def test_get_error_detail_returns_dict_for_known_code(self):
        from src.business_scenarios.settlement_exception_guide.service import get_error_detail

        result = get_error_detail("E-UPLOAD-001")
        assert isinstance(result, dict)
        assert result["error_code"] == "E-UPLOAD-001"
        assert "exception_type" in result
        assert "error_explanation" in result

    def test_get_error_detail_returns_empty_dict_for_unknown_code(self):
        from src.business_scenarios.settlement_exception_guide.service import get_error_detail

        result = get_error_detail("UNKNOWN-ERR")
        assert isinstance(result, dict)
        assert result == {}

    def test_build_recommendation_returns_string(self):
        from src.business_scenarios.settlement_exception_guide.service import build_recommendation

        error_detail = {
            "error_code": "E-UPLOAD-001",
            "recommended_steps": ["请重新上传医保结算单据"],
        }
        result = build_recommendation(error_detail)
        assert isinstance(result, str)
        assert result == "请重新上传医保结算单据"

    def test_build_recommendation_returns_default_for_empty_detail(self):
        from src.business_scenarios.settlement_exception_guide.service import build_recommendation

        result = build_recommendation({})
        assert isinstance(result, str)
        assert result == "请咨询医保办获取详细指导"


# ============================================================
# Settlement Node Functions
# ============================================================

class TestSettlementNodeFunctions:

    def _make_state(self, **overrides) -> dict:
        defaults = {
            "intent": "settlement",
            "role": "cashier",
            "messages": [],
            "citations": [],
            "uncertainties": [],
            "requires_confirmation": False,
            "workflow_id": "wf-test",
            "patient_id": "P001",
            "encounter_id": "E001",
            "claim_detail": {},
            "error_code": "",
            "error_detail": {},
            "recommendation": "",
            "blocked_actions": [],
        }
        defaults.update(overrides)
        return defaults

    def test_query_claim_node_returns_dict_not_agent_response(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import query_claim_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = query_claim_node(state)
        assert isinstance(result, dict)
        assert not isinstance(result, AgentResponse)

    def test_query_claim_node_populates_claim_detail(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import query_claim_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = query_claim_node(state)
        assert "claim_detail" in result
        assert "error_code" in result
        assert result["error_code"] == "E-UPLOAD-001"

    def test_query_claim_node_adds_citations(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import query_claim_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = query_claim_node(state)
        assert "citations" in result
        assert len(result["citations"]) > 0

    def test_query_claim_node_handles_unknown_patient(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import query_claim_node

        state = self._make_state(patient_id="UNKNOWN", encounter_id="X001", error_code="UNKNOWN-ERR")
        result = query_claim_node(state)
        assert "claim_detail" in result
        # Should not crash, return state's error_code as fallback
        assert result.get("error_code") == "UNKNOWN-ERR"

    def test_get_error_detail_node_returns_dict_not_agent_response(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import get_error_detail_node

        state = self._make_state(error_code="E-UPLOAD-001")
        result = get_error_detail_node(state)
        assert isinstance(result, dict)
        assert not isinstance(result, AgentResponse)

    def test_get_error_detail_node_populates_error_detail(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import get_error_detail_node

        state = self._make_state(error_code="E-UPLOAD-001")
        result = get_error_detail_node(state)
        assert "error_detail" in result
        assert result["error_detail"]["error_code"] == "E-UPLOAD-001"

    def test_get_error_detail_node_adds_citations(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import get_error_detail_node

        state = self._make_state(error_code="E-UPLOAD-001")
        result = get_error_detail_node(state)
        assert len(result["citations"]) > 0

    def test_get_error_detail_node_handles_unknown_code(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import get_error_detail_node

        state = self._make_state(error_code="UNKNOWN-ERR")
        result = get_error_detail_node(state)
        assert result["error_detail"] == {}

    def test_build_recommendation_node_returns_dict_not_agent_response(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import build_recommendation_node

        state = self._make_state(
            error_detail={
                "error_code": "E-UPLOAD-001",
                "recommended_steps": ["请重新上传医保结算单据"],
            }
        )
        result = build_recommendation_node(state)
        assert isinstance(result, dict)
        assert not isinstance(result, AgentResponse)

    def test_build_recommendation_node_returns_recommendation(self):
        from src.business_scenarios.settlement_exception_guide.settlement_nodes import build_recommendation_node

        state = self._make_state(
            error_detail={
                "error_code": "E-UPLOAD-001",
                "recommended_steps": ["请重新上传医保结算单据"],
            }
        )
        result = build_recommendation_node(state)
        assert "recommendation" in result
        assert result["recommendation"] == "请重新上传医保结算单据"


# ============================================================
# QC Core Business Functions
# ============================================================

class TestQcCoreFunctions:

    def test_get_patient_summary_returns_dict(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import get_patient_summary

        result = get_patient_summary("P001", "E001")
        assert isinstance(result, dict)
        assert "emr" in result
        assert "his" in result

    def test_get_patient_summary_includes_source_info(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import get_patient_summary

        result = get_patient_summary("P001", "E001")
        assert "emr_source" in result
        assert "his_source" in result

    def test_run_qc_rules_returns_dict(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import run_qc_rules

        result = run_qc_rules("P001", "E001")
        assert isinstance(result, dict)
        assert "rule_results" in result
        assert "quality_issues" in result

    def test_run_qc_rules_returns_three_rules(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import run_qc_rules

        result = run_qc_rules("P001", "E001")
        assert len(result["rule_results"]) == 3

    def test_run_qc_rules_identifies_quality_issues(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import run_qc_rules

        result = run_qc_rules("P001", "E001")
        assert len(result["quality_issues"]) > 0

    def test_build_qc_report_returns_string_with_issues(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import build_qc_report

        issues = [
            {"rule": "PRE_AUDIT_RISK", "risk": "合规拒付风险", "responsible_role": "医保办"},
            {"rule": "DRG_LOSS_RISK", "risk": "亏损风险", "responsible_role": "科主任"},
        ]
        result = build_qc_report(issues)
        assert isinstance(result, str)
        assert "发现 2 个质控问题" in result
        assert "PRE_AUDIT_RISK" in result

    def test_build_qc_report_returns_no_issues_string(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import build_qc_report

        result = build_qc_report([])
        assert isinstance(result, str)
        assert "未发现质控问题" in result


# ============================================================
# QC Node Functions
# ============================================================

class TestQcNodeFunctions:

    def _make_state(self, **overrides) -> dict:
        defaults = {
            "intent": "pre_discharge",
            "role": "doctor",
            "messages": [],
            "citations": [],
            "uncertainties": [],
            "requires_confirmation": False,
            "workflow_id": "wf-qc-test",
            "patient_id": "P001",
            "encounter_id": "E001",
            "patient_summary": {},
            "quality_issues": [],
            "rule_results": [],
            "qc_recommendation": "",
        }
        defaults.update(overrides)
        return defaults

    def test_get_patient_summary_node_returns_dict_not_agent_response(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import get_patient_summary_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = get_patient_summary_node(state)
        assert isinstance(result, dict)
        assert not isinstance(result, AgentResponse)

    def test_get_patient_summary_node_populates_patient_summary(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import get_patient_summary_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = get_patient_summary_node(state)
        assert "patient_summary" in result
        assert "emr" in result["patient_summary"]
        assert "his" in result["patient_summary"]

    def test_get_patient_summary_node_adds_citations(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import get_patient_summary_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = get_patient_summary_node(state)
        assert "citations" in result
        assert len(result["citations"]) >= 2

    def test_run_qc_rules_node_returns_dict_not_agent_response(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import run_qc_rules_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = run_qc_rules_node(state)
        assert isinstance(result, dict)
        assert not isinstance(result, AgentResponse)

    def test_run_qc_rules_node_populates_rule_results(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import run_qc_rules_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = run_qc_rules_node(state)
        assert "rule_results" in result
        assert len(result["rule_results"]) == 3
        assert "quality_issues" in result

    def test_run_qc_rules_node_adds_citations(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import run_qc_rules_node

        state = self._make_state(patient_id="P001", encounter_id="E001")
        result = run_qc_rules_node(state)
        assert len(result["citations"]) >= 3

    def test_build_qc_report_node_returns_dict_not_agent_response(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import build_qc_report_node

        state = self._make_state(
            quality_issues=[
                {"rule": "PRE_AUDIT_RISK", "risk": "合规拒付风险", "responsible_role": "医保办"},
            ]
        )
        result = build_qc_report_node(state)
        assert isinstance(result, dict)
        assert not isinstance(result, AgentResponse)

    def test_build_qc_report_node_returns_report(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import build_qc_report_node

        state = self._make_state(
            quality_issues=[
                {"rule": "PRE_AUDIT_RISK", "risk": "合规拒付风险", "responsible_role": "医保办"},
            ]
        )
        result = build_qc_report_node(state)
        assert "qc_recommendation" in result
        assert isinstance(result["qc_recommendation"], str)
        assert "发现 1 个质控问题" in result["qc_recommendation"]

    def test_build_qc_report_node_no_issues(self):
        from src.business_scenarios.pre_discharge_joint_qc.qc_nodes import build_qc_report_node

        state = self._make_state(quality_issues=[])
        result = build_qc_report_node(state)
        assert "qc_recommendation" in result
        assert "未发现质控问题" in result["qc_recommendation"]


# ============================================================
# Core Functions Independence
# ============================================================

class TestCoreFunctionsIndependence:

    def test_settlement_core_functions_callable_independently(self):
        from src.business_scenarios.settlement_exception_guide.service import (
            build_recommendation,
            get_error_detail,
            query_claim,
        )

        claim = query_claim("P001", "E001")
        assert isinstance(claim, dict)

        detail = get_error_detail("E-UPLOAD-001")
        assert isinstance(detail, dict)

        rec = build_recommendation(detail)
        assert isinstance(rec, str)

    def test_qc_core_functions_callable_independently(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import (
            build_qc_report,
            get_patient_summary,
            run_qc_rules,
        )

        summary = get_patient_summary("P001", "E001")
        assert isinstance(summary, dict)

        rules = run_qc_rules("P001", "E001")
        assert isinstance(rules, dict)

        report = build_qc_report(rules["quality_issues"])
        assert isinstance(report, str)

    def test_backward_compat_settlement_still_returns_agent_response(self):
        from src.business_scenarios.settlement_exception_guide.service import guide_settlement_exception

        result = guide_settlement_exception("P001", "E001")
        assert isinstance(result, AgentResponse)

    def test_backward_compat_qc_still_returns_agent_response(self):
        from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc

        result = run_pre_discharge_qc("P001", "E001")
        assert isinstance(result, AgentResponse)

    def test_degraded_path_still_works_for_p002(self):
        from src.business_scenarios.settlement_exception_guide.service import guide_settlement_exception

        result = guide_settlement_exception("P002", "E002")
        assert isinstance(result, AgentResponse)
        assert result.status == "degraded"
