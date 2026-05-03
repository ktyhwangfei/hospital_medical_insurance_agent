from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc
from src.business_scenarios.settlement_exception_guide.service import guide_settlement_exception
from src.runtime.api.schemas import AgentResponse
from src.runtime.context.models import RuntimeContext
from src.runtime.planning.models import ExecutionPlan
from src.runtime.runtime_state.models import StepState, WorkflowInstance
from src.runtime.runtime_state.store import runtime_state_store
from src.security.audit.service import record_audit_event
from src.security.risk_control.service import build_human_confirmation_response, detect_blocked_actions


def execute_plan(context: RuntimeContext, plan: ExecutionPlan) -> AgentResponse:
    steps = [StepState(step_id=step.step_id, status="completed") for step in plan.steps]
    if plan.scenario == "settlement_exception_guidance":
        response = guide_settlement_exception(context.patient_id, context.encounter_id)
    elif plan.scenario == "pre_discharge_quality_control":
        response = run_pre_discharge_qc(context.patient_id, context.encounter_id)
    elif plan.scenario == "high_risk_action_confirmation":
        response = build_human_confirmation_response(detect_blocked_actions(context.message))
    else:
        response = AgentResponse(status="not_implemented", uncertainties=[f"未识别的意图: {context.message}"])
    workflow = WorkflowInstance(workflow_id=context.workflow_id, scenario=plan.scenario, status=response.status, current_step=steps[-1].step_id if steps else None, steps=steps)
    runtime_state_store.save_workflow(workflow)
    record_audit_event('workflow_executed', context.workflow_id, payload={'scenario': plan.scenario, 'status': response.status})
    for step in steps:
        record_audit_event('workflow_step_completed', context.workflow_id, step.step_id)
    response.audit["workflow_id"] = context.workflow_id
    response.audit["steps"] = [step.step_id for step in steps]
    return response
