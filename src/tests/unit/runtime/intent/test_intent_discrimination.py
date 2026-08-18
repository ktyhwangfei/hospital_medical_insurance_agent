from unittest.mock import patch

import pytest

from src.model_service.governance_runtime import GovernanceRuntimeError
from src.runtime.intent.graph.nodes.discrimination import discrimination
from src.runtime.intent.models import IntentCandidate


def test_discrimination_propagates_governance_runtime_error():
    state = {
        'message': '结算失败怎么办',
        'candidates': [
            IntentCandidate(
                intent_id='settlement_exception_guidance',
                score=0.5,
                matched_keywords=['结算'],
            )
        ],
    }

    with patch(
        'src.runtime.intent.graph.nodes.discrimination.build_discrimination_prompt',
        side_effect=GovernanceRuntimeError('active prompt is corrupt'),
    ):
        with pytest.raises(GovernanceRuntimeError, match='active prompt is corrupt'):
            discrimination(state, gateway=object())
