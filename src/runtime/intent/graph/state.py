from typing import Any, TypedDict

from src.runtime.intent.models import IntentCandidate


class IntentGraphState(TypedDict, total=False):
    message: str
    role: str
    history: list[dict[str, Any]]
    candidates: list[IntentCandidate]
    rewritten_message: str | None
    rewrite_changes: list[str]
    intent_id: str | None
    confidence: float
    entities: dict[str, Any]
    missing_fields: list[str]
    clarification_needed: bool
    clarification_question: str | None
    status: str
    citations: list[str]
