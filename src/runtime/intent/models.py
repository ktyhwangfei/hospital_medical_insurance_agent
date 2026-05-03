from typing import Any

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    intent: str
    confidence: float = Field(ge=0, le=1)
    entities: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    raw_message: str
