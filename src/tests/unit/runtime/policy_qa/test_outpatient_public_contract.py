from src.runtime.api.policy_qa_routes import _build_public_result


def _build(**kwargs):
    return _build_public_result(
        answer="已完成门诊结算核验。",
        can_answer=True,
        partial_answer=False,
        policy_status="no_policy_matched",
        policy_evidence=[],
        calculation_steps=[],
        definition=None,
        warnings=[],
        case_context={"total_amount": 100},
        is_overview=False,
        **kwargs,
    )


def test_outpatient_extension_is_whitelisted_without_changing_legacy_shape():
    legacy = _build().model_dump(mode="json")
    outpatient = _build(outpatient_result={
        "scenario_id": "overall-settlement-verification",
        "context_checks": [{"name": "险种", "value": "职工", "status": "present"}],
        "amount_checks": [{
            "name": "总费用勾稽", "equation": "总费用 = 医保内 + 医保外",
            "actual": 100, "expected": 100, "difference": 0, "tolerance": 0.01,
            "status": "passed",
        }],
        "field_explanations": [{
            "field_name": "现金支付", "value": 0, "state": "reported_zero",
            "applicable": None, "explanation": "结算数据明确记录现金支付为 0 元。",
            "citations": ["settlement-data"],
        }],
        "anomalies": [],
        "next_actions": [],
    }).model_dump(mode="json")

    assert "scenario_id" not in legacy
    assert outpatient["scenario_id"] == "overall-settlement-verification"
    assert outpatient["field_explanations"][0]["state"] == "reported_zero"
    assert outpatient["field_explanations"][0]["citations"] == ["settlement-data"]


def test_non_amount_outpatient_scenario_can_verify_settlement_facts():
    result = _build_public_result(
        answer="交易状态为已结算。",
        can_answer=True,
        partial_answer=False,
        policy_status="full_policy_matched",
        policy_evidence=[{"title": "结算规则", "source_text": "结算状态规则"}],
        calculation_steps=[],
        definition=None,
        warnings=[],
        case_context={"query_scope": "whole_settlement"},
        outpatient_result={
            "scenario_id": "transaction-status-and-refund",
            "context_checks": [
                {"name": "交易状态", "value": "已结算", "status": "present"}
            ],
        },
    )

    assert result.answer_status == "complete"
    assert result.verification_summary.settlement_checked is True
    assert result.verification_summary.calculation_checked is False


def test_broad_question_with_zero_policy_evidence_is_unavailable():
    """Issue #33 P1-5：宽泛问题零政策证据 → 诚实拒答 unavailable，禁止低置信 partial。"""
    result = _build_public_result(
        answer="未检索到与您问题相关的政策依据。",
        can_answer=True,
        partial_answer=True,  # broad 路径现行行为：有无证据都标 partial_answer
        policy_status="no_policy_matched",
        policy_evidence=[],
        calculation_steps=[],
        definition=None,
        warnings=[],
        case_context=None,
        is_overview=False,
        is_broad=True,
    )

    assert result.answer_status == "unavailable"
    assert "未检索到足以回答该问题的政策依据" in result.answer
    assert any("现有信息不足" in item for item in result.uncertainties)


def test_broad_question_with_evidence_remains_partial():
    """宽泛问题有政策证据时维持 partial（不被零证据规则误伤）。"""
    result = _build_public_result(
        answer="退休人员门诊起付线为 1300 元。",
        can_answer=True,
        partial_answer=True,
        policy_status="partial_policy_matched",
        policy_evidence=[{"title": "门诊起付线", "source_text": "门诊起付标准为 1300 元。"}],
        calculation_steps=[],
        definition=None,
        warnings=[],
        case_context=None,
        is_overview=False,
        is_broad=True,
    )

    assert result.answer_status == "partial"
