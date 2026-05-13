from src.runtime.intent.graph.state import IntentGraphState
from src.runtime.intent.knowledge import IntentKnowledgeStore
from src.runtime.intent.models import IntentCandidate


def candidate_retrieval(
    state: IntentGraphState,
    knowledge_store: IntentKnowledgeStore | None = None,
) -> dict:
    store = knowledge_store or IntentKnowledgeStore()
    message = state.get('rewritten_message') or state['message']
    role = state.get('role', '')

    scored = store.search(message, role=role, top_k=5)
    candidates = [
        IntentCandidate(
            intent_id=s.intent_id,
            score=s.score,
            source=s.source,
            matched_keywords=s.matched_keywords,
        )
        for s in scored
    ]

    return {'candidates': candidates}
