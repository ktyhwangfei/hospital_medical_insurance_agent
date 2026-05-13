from typing import Any

from src.runtime.langgraph.base_state import BaseAgentState


class PreDischargeState(BaseAgentState):
    patient_id: str
    encounter_id: str
    patient_summary: dict[str, Any]
    quality_issues: list[dict[str, Any]]
    rule_results: list[dict[str, Any]]
    qc_recommendation: str
