"""UnifiedScenarioExecutor 的 Policy QA 单答案出口契约。"""

from src.data_platform.storage.skill.in_memory import InMemorySkillStorage
from src.runtime.context.models import RuntimeContext
from src.runtime.policy_qa.models import PolicyQAResponse
from src.runtime.scenario_executor import UnifiedScenarioExecutor


def _context() -> RuntimeContext:
    return RuntimeContext(
        request_id="req-1",
        workflow_id="wf-1",
        user_id="u-1",
        role="patient",
        message="为什么这次统筹自付这么多？",
        encounter_id="1671213",
        intent="policy_qa_fee_decomposition",
        intent_confidence=1.0,
        requested_at="2026-08-05T00:00:00+08:00",
    )


def _patch_policy_qa_pipeline(monkeypatch, events):
    import src.model_service.gateway as gateway_module
    import src.runtime.policy_qa.explanation_generator as generator_module
    import src.runtime.policy_qa.orchestrator as orchestrator_module
    import src.runtime.policy_qa.sql_data_fetcher as fetcher_module

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            pass

        async def process(self, request):
            for event in events:
                yield event

    monkeypatch.setattr(orchestrator_module, "PolicyQAOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(fetcher_module, "SQLDataFetcher", lambda: object())
    monkeypatch.setattr(generator_module, "ExplanationGenerator", lambda **kwargs: object())
    monkeypatch.setattr(gateway_module, "ModelGateway", lambda: object())


def test_policy_qa_complete_answer_preserves_status_and_citations(monkeypatch):
    policy_card = {
        "title": "城镇职工医保办法",
        "clause": "第十条",
        "evidence_text": "起付线以上费用按规定比例支付。",
        "matched_reason": "险种与人员类别匹配",
    }
    _patch_policy_qa_pipeline(
        monkeypatch,
        [
            PolicyQAResponse(step="policy_rule_search", status="done", policy_cards=[policy_card]),
            PolicyQAResponse(
                step="answer_generation",
                status="done",
                answer="根据第十条，本次统筹自付为100元。",
                answer_status="complete",
            ),
        ],
    )
    executor = UnifiedScenarioExecutor(InMemorySkillStorage(), {})

    response = executor._execute_policy_qa(_context())

    assert response.result["answer_status"] == "complete"
    assert response.citations
    assert response.citations[0]["summary"] == policy_card["evidence_text"]
    assert response.uncertainties == []


def test_policy_qa_unavailable_answer_preserves_uncertainty(monkeypatch):
    _patch_policy_qa_pipeline(
        monkeypatch,
        [
            PolicyQAResponse(
                step="answer_generation",
                status="skipped",
                answer="未检索到可核验政策，无法可靠确认，建议核对结算单。",
                answer_status="unavailable",
            ),
        ],
    )
    executor = UnifiedScenarioExecutor(InMemorySkillStorage(), {})

    response = executor._execute_policy_qa(_context())

    assert response.status == "completed"
    assert response.result["answer_status"] == "unavailable"
    assert response.uncertainties
