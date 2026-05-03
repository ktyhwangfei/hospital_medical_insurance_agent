from src.runtime.context.models import RuntimeContext
from src.runtime.planning.models import ExecutionPlan, PlanStep, RiskLevel, StepType


def build_execution_plan(context: RuntimeContext) -> ExecutionPlan:
    if context.intent == "settlement_exception_guidance":
        steps = [
            PlanStep(step_id="query_transaction", step_type=StepType.ADAPTER_CALL, capability="insurance_interface.query_transaction"),
            PlanStep(step_id="retrieve_error_code", step_type=StepType.KNOWLEDGE_RETRIEVAL, capability="knowledge.error_code", depends_on=["query_transaction"]),
            PlanStep(step_id="query_billing_status", step_type=StepType.ADAPTER_CALL, capability="billing.query_billing_status", depends_on=["query_transaction"]),
            PlanStep(step_id="build_result", step_type=StepType.RESULT_BUILDING, capability="settlement_exception.build_result", depends_on=["retrieve_error_code", "query_billing_status"]),
        ]
    elif context.intent == "pre_discharge_quality_control":
        steps = [
            PlanStep(step_id="query_orders", step_type=StepType.ADAPTER_CALL, capability="his.query_orders"),
            PlanStep(step_id="query_insurance_status", step_type=StepType.ADAPTER_CALL, capability="insurance_interface.query_status"),
            PlanStep(step_id="query_pre_audit", step_type=StepType.ADAPTER_CALL, capability="pre_audit.query_audit_result"),
            PlanStep(step_id="query_drg_dip", step_type=StepType.ADAPTER_CALL, capability="drg_dip.query_group_result"),
            PlanStep(step_id="query_medical_record", step_type=StepType.ADAPTER_CALL, capability="medical_record.query_homepage"),
            PlanStep(step_id="retrieve_rule_explanation", step_type=StepType.KNOWLEDGE_RETRIEVAL, capability="knowledge.rule_explanation"),
            PlanStep(step_id="build_risk_list", step_type=StepType.RESULT_BUILDING, capability="pre_discharge_qc.build_risk_list"),
            PlanStep(step_id="create_tasks", step_type=StepType.TASK_CREATION, capability="task_closure.create_tasks"),
        ]
    elif context.intent == "high_risk_action_confirmation":
        steps = [
            PlanStep(step_id="detect_high_risk_action", step_type=StepType.RESULT_BUILDING, capability="risk_control.detect"),
            PlanStep(step_id="create_human_confirmation_task", step_type=StepType.HUMAN_CONFIRMATION, capability="task_closure.human_confirmation", risk_level=RiskLevel.HIGH, requires_human_confirmation=True),
        ]
    else:
        steps = [PlanStep(step_id="build_unknown_intent_response", step_type=StepType.RESULT_BUILDING, capability="response.unknown_intent")]
    return ExecutionPlan(workflow_id=context.workflow_id, scenario=context.intent, goal=context.message, steps=steps, output_requirements=["citations_or_uncertainties"])
