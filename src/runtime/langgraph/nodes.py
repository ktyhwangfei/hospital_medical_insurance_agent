from langgraph.types import Command, interrupt

from src.adapters.base import AdapterCallContext, AdapterCallResult, AdapterCallStatus, failed_result, successful_result
from src.adapters.base.service import adapter_citation
from src.adapters.billing.in_memory import InMemoryBillingAdapter
from src.adapters.his.in_memory import InMemoryHisAdapter
from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.knowledge_extension.knowledge.factory import create_knowledge_store
from src.runtime.api.schemas import AgentResponse
from src.runtime.langgraph.states import BaseAgentState

_insurance_adapter = InMemoryInsuranceInterfaceAdapter()
_his_adapter = InMemoryHisAdapter()
_billing_adapter = InMemoryBillingAdapter()


def adapter_call_node(state: BaseAgentState, capability_ref: str) -> dict:
    if capability_ref.startswith("insurance_interface."):
        result = _call_insurance_adapter(state, capability_ref)
    elif capability_ref.startswith("knowledge."):
        result = _call_knowledge_service(state, capability_ref)
    elif capability_ref.startswith("his."):
        result = _call_his_adapter(state, capability_ref)
    elif capability_ref.startswith("billing."):
        result = _call_billing_adapter(state, capability_ref)
    else:
        result = failed_result(
            context=AdapterCallContext(workflow_id=state.get("workflow_id")),
            source_system="unknown",
            capability=capability_ref,
            error_type="unknown_capability",
            message=f"unsupported capability_ref: {capability_ref}",
        )
    return _adapter_result_to_update(result, state)


def human_confirmation_node(state: BaseAgentState) -> dict:
    """LangGraph interrupt-based human confirmation node.

    Calls interrupt() with risk context to pause graph execution.
    When resumed via Command(resume=...), returns the resume value
    to drive conditional routing.
    """
    result = interrupt({
        "action": "human_confirmation_required",
        "workflow_id": state.get("workflow_id"),
        "intent": state.get("intent"),
        "blocked_actions": state.get("blocked_actions", []),
    })
    confirmed = isinstance(result, dict) and result.get("confirmed", False)
    return {
        "requires_confirmation": True,
        "human_confirmed": confirmed,
        "human_confirmation_result": result if isinstance(result, dict) else {},
    }


def after_human_confirmation(state: BaseAgentState) -> str:
    """Conditional edge router: routes to 'confirmed' or 'rejected' based on resume."""
    if state.get("human_confirmed", False):
        return "confirmed"
    return "rejected"


def response_build_node(state: BaseAgentState) -> dict:
    human_confirmed = state.get("human_confirmed", False)
    blocked_actions = state.get("blocked_actions", [])

    if human_confirmed:
        status = "completed"
        result = {
            "message": "高风险动作已确认，可继续执行",
            "confirmed_actions": blocked_actions,
        }
    else:
        status = "rejected"
        result = {
            "message": "高风险动作已被驳回，执行已终止",
            "blocked_actions": blocked_actions,
        }

    return {
        "response": AgentResponse(
            scenario=state.get("intent"),
            status=status,
            result=result,
            citations=state.get("citations", []),
            uncertainties=state.get("uncertainties", []),
        )
    }


def _call_insurance_adapter(state: BaseAgentState, ref: str) -> AdapterCallResult:
    return _insurance_adapter.query_transaction(
        patient_id=state.get("patient_id", ""),
        encounter_id=state.get("encounter_id", ""),
    )


def _call_knowledge_service(state: BaseAgentState, ref: str) -> AdapterCallResult:
    error_code = state.get("error_code", "")
    entry = create_knowledge_store().get_error_code(error_code) or {}
    return successful_result(
        context=AdapterCallContext(input_summary={"error_code": error_code}),
        source_system="knowledge_extension",
        source_record_id=error_code,
        capability="knowledge_lookup",
        data=entry,
    )


def _call_his_adapter(state: BaseAgentState, ref: str) -> AdapterCallResult:
    return _his_adapter.query_orders(
        patient_id=state.get("patient_id", ""),
        encounter_id=state.get("encounter_id", ""),
    )


def _call_billing_adapter(state: BaseAgentState, ref: str) -> AdapterCallResult:
    return _billing_adapter.query_billing_status(
        patient_id=state.get("patient_id", ""),
        encounter_id=state.get("encounter_id", ""),
    )


def _adapter_result_to_update(result: AdapterCallResult, state: BaseAgentState) -> dict:
    citations = list(state.get("citations", []))
    if result.status == AdapterCallStatus.SUCCESS:
        citations.append(adapter_citation(result).model_dump())
    return {
        "citations": citations,
        "_last_adapter_result": result.model_dump(),
    }
