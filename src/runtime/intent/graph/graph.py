import logging

from src.runtime.intent.graph.config import DEFAULT_CONFIG, IntentGraphConfig
from src.runtime.intent.graph.nodes.candidate_retrieval import candidate_retrieval
from src.runtime.intent.graph.nodes.decision import decision
from src.runtime.intent.graph.nodes.discrimination import discrimination
from src.runtime.intent.graph.nodes.validation import validation
from src.runtime.intent.graph.state import IntentGraphState
from src.runtime.intent.knowledge import IntentKnowledgeStore
from src.runtime.intent.models import IntentResult

logger = logging.getLogger(__name__)


class IntentGraph:
    def __init__(
        self,
        config: IntentGraphConfig | None = None,
        knowledge_store: IntentKnowledgeStore | None = None,
    ):
        self._config = config or DEFAULT_CONFIG
        self._knowledge_store = knowledge_store or IntentKnowledgeStore()

    def run(self, message: str, role: str = '', history: list | None = None) -> IntentResult:
        state: IntentGraphState = {
            'message': message,
            'role': role,
            'history': history or [],
            'candidates': [],
            'rewrite_changes': [],
            'intent_id': None,
            'confidence': 0.0,
            'entities': {},
            'missing_fields': [],
            'clarification_needed': False,
            'clarification_question': None,
            'status': 'unknown',
            'citations': [],
        }

        state.update(candidate_retrieval(state, self._knowledge_store))
        state.update(discrimination(state, self._config))
        state.update(validation(state, self._config))

        route = decision(state)
        if route == 'clarify':
            state['status'] = 'needs_clarification'
        elif route == 'unknown':
            state['status'] = 'unknown'
        else:
            if state.get('status') not in ('routed', 'fallback_keyword', 'needs_clarification'):
                state['status'] = 'routed'

        return IntentResult(
            intent=state.get('intent_id') or 'unknown',
            confidence=state.get('confidence', 0.0),
            entities=state.get('entities', {}),
            citations=state.get('citations', []),
            raw_message=message,
            top_candidates=state.get('candidates', []),
            missing_fields=state.get('missing_fields', []),
            clarification_needed=state.get('clarification_needed', False),
            clarification_question=state.get('clarification_question'),
            original_message=message,
            rewrite_changes=state.get('rewrite_changes', []),
            status=state.get('status', 'unknown'),
        )
