from __future__ import annotations

from fastapi.testclient import TestClient

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeConfidence,
    KnowledgeItem,
    KnowledgeWorkbenchDocument,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    SemanticContractUnavailable,
)
from src.runtime.api.app import create_app


PREFIX = "/api/v1/medical-insurance-ai-agent/policy-workbench"


def _document() -> KnowledgeWorkbenchDocument:
    return KnowledgeWorkbenchDocument(
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        contract_version="2",
        units=[ApprovedUnit(
            unit_id="unit_1",
            doc_id="doc_1",
            doc_title="职工医保待遇政策",
            path=["第一条", "（一）"],
            source_text="在职职工住院费用",
            order_no=1,
            status="reviewed",
            knowledge_count=1,
            knowledge=[KnowledgeItem(
                knowledge_id="kn_1",
                unit_id="unit_1",
                extraction_id="ext_1",
                relationship_source="persisted",
                business_sentence="在职职工住院时，统筹基金支付比例为80%。",
                source_text="政策原文",
                fields=[],
                standardized_fields=[],
                confidence=KnowledgeConfidence(
                    completeness=1,
                    accuracy=None,
                    source_fidelity=1,
                    model_confidence=0.9,
                    value_domain_compliance=1,
                    overall=0.9667,
                    uncertainties=["准确性待经典用例验证"],
                ),
                citations=[],
            )],
        )],
    )


def test_get_typed_workbench_document(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    class Service:
        def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
            assert doc_id == "doc_1"
            return _document()

    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: Service())
    client = TestClient(create_app())

    response = client.get(f"{PREFIX}/documents/doc_1")

    assert response.status_code == 200
    assert response.json()["contract_version"] == "2"
    assert response.json()["units"][0]["knowledge_count"] == 1


def test_semantic_contract_failure_returns_503_not_empty_200(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    class Service:
        def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
            raise SemanticContractUnavailable("semantic registry unavailable")

    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: Service())
    client = TestClient(create_app())

    response = client.get(f"{PREFIX}/documents/doc_1")

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "SEMANTIC_CONTRACT_UNAVAILABLE"


def test_missing_document_returns_404(monkeypatch) -> None:
    from src.runtime.api import policy_workbench_routes

    class Service:
        def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
            raise ValueError(f"政策文档不存在: {doc_id}")

    monkeypatch.setattr(policy_workbench_routes, "_get_service", lambda: Service())
    client = TestClient(create_app())

    response = client.get(f"{PREFIX}/documents/missing")

    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "POLICY_DOCUMENT_NOT_FOUND"

