from typing import Any

from typing_extensions import NotRequired

from src.runtime.langgraph.base_state import BaseAgentState


class SettlementState(BaseAgentState):
    claim_detail: dict[str, Any]
    error_code: str
    error_detail: dict[str, Any]
    recommendation: str
    blocked_actions: list[str]
    patient_id: NotRequired[str]
    encounter_id: NotRequired[str]
