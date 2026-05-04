from src.runtime.api.schemas import ChatRequest
from src.runtime.context.service import build_runtime_context
from src.runtime.intent.models import IntentResult
from src.runtime.planning.service import build_execution_plan


def test_build_runtime_context_preserves_intent_result():
    request = ChatRequest(user_id="U001", role="medical_office", message="医保结算失败", patient_id="P001", encounter_id="E001")
    intent = IntentResult(intent="settlement_exception_guidance", confidence=0.8, entities={"error_code": "ERR001"}, citations=["LLM意图识别"], raw_message=request.message)

    context = build_runtime_context(request, intent)

    assert context.user_id == "U001"
    assert context.intent == "settlement_exception_guidance"
    assert context.intent_confidence == 0.8
    assert context.intent_citations == ["LLM意图识别"]
    assert context.workflow_id.startswith("wf-")


def test_build_settlement_exception_plan():
    request = ChatRequest(user_id="U001", role="medical_office", message="医保结算失败", patient_id="P001", encounter_id="E001")
    intent = IntentResult(intent="settlement_exception_guidance", confidence=0.8, entities={}, citations=["关键词匹配降级"], raw_message=request.message)
    context = build_runtime_context(request, intent)

    plan = build_execution_plan(context)

    assert plan.scenario == "settlement_exception_guidance"
    assert [step.step_id for step in plan.steps] == ["query_transaction", "retrieve_error_code", "query_billing_status", "build_result"]


def test_build_high_risk_plan_requires_confirmation():
    request = ChatRequest(user_id="U001", role="medical_office", message="请退费", patient_id="P001", encounter_id="E001")
    intent = IntentResult(intent="high_risk_action_confirmation", confidence=1, entities={}, citations=["风控策略"], raw_message=request.message)
    context = build_runtime_context(request, intent)

    plan = build_execution_plan(context)

    assert plan.scenario == "high_risk_action_confirmation"
    assert plan.steps[-1].requires_human_confirmation is True
