from pydantic import BaseModel, Field

from src.runtime.intent.registry import IntentEntry, get_intent_registry


class ScoredIntent(BaseModel):
    intent_id: str
    score: float = Field(ge=0, le=1)
    matched_keywords: list[str] = Field(default_factory=list)
    source: str = 'keyword'


class IntentKnowledgeStore:
    def __init__(self, registry: list[IntentEntry] | None = None):
        self._registry = registry or get_intent_registry()

    def search(self, query: str, role: str = '', top_k: int = 5) -> list[ScoredIntent]:
        query_lower = query.lower()
        candidates: list[ScoredIntent] = []

        for entry in self._registry:
            if entry.status != 'active':
                continue
            if role and role not in entry.allowed_roles:
                continue

            score = 0.0
            matched: list[str] = []

            for kw in entry.keywords:
                if kw.lower() in query_lower:
                    matched.append(kw)
                    score += 0.3

            for ex in entry.examples:
                if ex.lower() in query_lower or query_lower in ex.lower():
                    matched.append(ex)
                    score += 0.25

            if any(word in query_lower for word in entry.description.lower().split()):
                score += 0.1

            if score > 0:
                candidates.append(ScoredIntent(
                    intent_id=entry.intent_id,
                    score=min(score, 1.0),
                    matched_keywords=matched,
                    source='keyword',
                ))

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]

    def get_by_id(self, intent_id: str) -> IntentEntry | None:
        return next((e for e in self._registry if e.intent_id == intent_id), None)

    def get_active_intents_for_role(self, role: str) -> list[IntentEntry]:
        return [
            e for e in self._registry
            if e.status == 'active' and role in e.allowed_roles
        ]
