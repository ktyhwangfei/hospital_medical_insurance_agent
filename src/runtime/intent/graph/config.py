from pydantic import BaseModel


class IntentGraphConfig(BaseModel):
    confidence_threshold: float = 0.7
    gap_threshold: float = 0.15
    max_candidates: int = 5
    enable_clarification: bool = True
    keyword_fallback_enabled: bool = True
    llm_discrimination_enabled: bool = True


DEFAULT_CONFIG = IntentGraphConfig()
