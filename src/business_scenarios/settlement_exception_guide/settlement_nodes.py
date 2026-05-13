import logging

from src.adapters.base import AdapterCallStatus
from src.business_scenarios.settlement_exception_guide.service import (
    build_recommendation,
    get_error_detail,
    query_claim,
)

_logger = logging.getLogger(__name__)


def query_claim_node(state: dict) -> dict:
    patient_id = state.get("patient_id", "")
    encounter_id = state.get("encounter_id", "")
    citations = list(state.get("citations", []))
    try:
        claim = query_claim(patient_id, encounter_id)
        tx_data = claim["data"]
        error_code = tx_data.get("error_code", state.get("error_code", ""))
        status = claim.get("status")
        if status == AdapterCallStatus.SUCCESS:
            citations.append({
                "source_type": claim["source_system"],
                "source_id": claim["source_record_id"] or "",
                "summary": f"Claim query result for encounter {encounter_id}",
            })
        return {
            "claim_detail": tx_data,
            "error_code": error_code,
            "citations": citations,
        }
    except Exception:
        _logger.exception("Failed to query claim for %s/%s", patient_id, encounter_id)
        return {
            "claim_detail": {},
            "error_code": state.get("error_code", ""),
        }


def get_error_detail_node(state: dict) -> dict:
    error_code = state.get("error_code", "")
    error_detail = get_error_detail(error_code)
    citations = list(state.get("citations", []))
    if error_detail:
        citations.append({
            "source_type": "knowledge_error_code",
            "source_id": error_code,
            "summary": error_detail.get("error_explanation", f"Error code {error_code}"),
        })
    return {
        "error_detail": error_detail,
        "citations": citations,
    }


def build_recommendation_node(state: dict) -> dict:
    error_detail = state.get("error_detail", {})
    recommendation = build_recommendation(error_detail)
    return {"recommendation": recommendation}
