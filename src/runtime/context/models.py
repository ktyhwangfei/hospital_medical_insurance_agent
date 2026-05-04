from typing import Any

from pydantic import BaseModel, Field


class RuntimeContext(BaseModel):
    request_id: str
    workflow_id: str
    user_id: str
    role: str
    message: str
    patient_id: str | None = None
    encounter_id: str | None = None
    intent: str
    intent_confidence: float
    intent_entities: dict[str, Any] = Field(default_factory=dict)
    intent_citations: list[str] = Field(default_factory=list)
    requested_at: str
