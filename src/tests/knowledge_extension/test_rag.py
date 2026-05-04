from src.knowledge_extension.assets.in_memory import build_default_asset_repository
from src.knowledge_extension.rag.in_memory import InMemoryHybridRetriever
from src.knowledge_extension.rag.models import RetrievalFilter, RetrievalRequest


def test_retrieves_settlement_policy_with_citation():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="医保结算异常错误码", filters=RetrievalFilter(role="medical_insurance_officer", scenario="settlement_exception")))

    assert result.status.value == "success"
    assert result.citations
    assert result.citations[0].source_id == "asset-policy-001"


def test_retrieval_no_hit_returns_uncertainty():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="完全不存在的罕见政策", filters=RetrievalFilter(role="doctor", scenario="settlement_exception")))

    assert result.status.value == "no_hit"
    assert result.uncertainties


def test_context_budget_trims_results():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="医保 出院 审核 DRG DIP 病案", filters=RetrievalFilter(role="doctor", scenario="pre_discharge_qc"), context_budget=12))

    assert result.context.truncated_count >= 0
    assert len(result.context.context_text) <= 12


def test_public_citation_hides_locator():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="医保结算异常", filters=RetrievalFilter(role="doctor", scenario="settlement_exception")))

    public = result.citations[0].to_public_dict()

    assert "internal_locator" not in public
