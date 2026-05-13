from typing import Any

from pydantic import BaseModel, Field


class IntentCandidate(BaseModel):
    intent_id: str
    score: float = Field(ge=0, le=1)
    source: str = ''
    matched_keywords: list[str] = Field(default_factory=list)


class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    raw_message: str
    top_candidates: list[IntentCandidate] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None
    original_message: str | None = None
    rewrite_changes: list[str] = Field(default_factory=list)
    status: str = 'routed'
