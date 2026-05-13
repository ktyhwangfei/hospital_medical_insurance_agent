import logging

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.adapters.base import AdapterCallStatus
from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.knowledge_extension.knowledge.factory import create_knowledge_store
from src.runtime.langgraph.settlement_state import SettlementState

_logger = logging.getLogger(__name__)
_insurance_adapter = InMemoryInsuranceInterfaceAdapter()

_HIGH_RISK_INDICATORS = {"refund", "reversal", "cancel", "退费", "冲正", "撤销结算"}


def validate_claim(state: SettlementState) -> dict:
    patient_id = state.get("patient_id", "")
    encounter_id = state.get("encounter_id", "")
    try:
        result = _insurance_adapter.query_transaction(
            patient_id=patient_id,
            encounter_id=encounter_id,
        )
        claim_detail = result.data if result.status == AdapterCallStatus.SUCCESS else {}
        citations = list(state.get("citations", []))
        if result.status == AdapterCallStatus.SUCCESS:
            citations.append({
                "source_type": result.source_system,
                "source_id": result.source_record_id or "",
                "summary": f"Claim query result for encounter {encounter_id}",
            })
        error_code = claim_detail.get("error_code") or state.get("error_code", "")
        return {
            "claim_detail": claim_detail,
            "error_code": error_code,
            "citations": citations,
        }
    except Exception:
        _logger.exception("Failed to query claim for %s/%s", patient_id, encounter_id)
        return {
            "claim_detail": {},
            "error_code": state.get("error_code", ""),
        }


def check_high_risk(state: SettlementState) -> dict:
    blocked = list(state.get("blocked_actions", []))
    error_code = state.get("error_code", "")
    for indicator in _HIGH_RISK_INDICATORS:
        if indicator.lower() in error_code.lower():
            if indicator not in blocked:
                blocked.append(indicator)
    claim_detail = state.get("claim_detail", {})
    risk_flags = claim_detail.get("risk_flags", [])
    for flag in risk_flags:
        if flag not in blocked:
            blocked.append(flag)
    return {"blocked_actions": blocked}


def route_after_high_risk_check(state: SettlementState) -> str:
    blocked = state.get("blocked_actions", [])
    if blocked:
        return "human_confirmation"
    return "query_error_knowledge"


def query_error_knowledge_node(state: SettlementState) -> dict:
    error_code = state.get("error_code", "")
    entry = create_knowledge_store().get_error_code(error_code) or {}
    citations = list(state.get("citations", []))
    if entry:
        citations.append({
            "source_type": "knowledge_error_code",
            "source_id": error_code,
            "summary": entry.get("description", f"Error code {error_code}"),
        })
    return {
        "error_detail": entry,
        "citations": citations,
    }


def human_confirmation_node(state: SettlementState) -> dict:
    interrupt({
        "action": "waiting_human_confirmation",
        "blocked_actions": state.get("blocked_actions", []),
        "workflow_id": state.get("workflow_id"),
        "intent": state.get("intent"),
    })
    return {"requires_confirmation": True}


def build_recommendation_node(state: SettlementState) -> dict:
    error_detail = state.get("error_detail", {})
    recommendation = error_detail.get("recommendation", "请咨询医保办获取详细指导")
    return {"recommendation": recommendation}


def build_settlement_exception_graph(checkpointer=None):
    builder = StateGraph(SettlementState)
    builder.add_node("validate_claim", validate_claim)
    builder.add_node("check_high_risk", check_high_risk)
    builder.add_node("query_error_knowledge", query_error_knowledge_node)
    builder.add_node("human_confirmation", human_confirmation_node)
    builder.add_node("build_recommendation", build_recommendation_node)
    builder.add_edge(START, "validate_claim")
    builder.add_edge("validate_claim", "check_high_risk")
    builder.add_conditional_edges(
        "check_high_risk",
        route_after_high_risk_check,
        {
            "human_confirmation": "human_confirmation",
            "query_error_knowledge": "query_error_knowledge",
        },
    )
    builder.add_edge("query_error_knowledge", "build_recommendation")
    builder.add_edge("human_confirmation", "build_recommendation")
    builder.add_edge("build_recommendation", END)
    return builder.compile(checkpointer=checkpointer)


from src.runtime.langgraph.checkpoint import get_checkpointer

settlement_exception_graph = build_settlement_exception_graph(checkpointer=get_checkpointer())
