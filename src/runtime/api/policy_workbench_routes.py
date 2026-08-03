"""政策知识 Unit×Knowledge 三栏工作台 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    KnowledgeWorkbenchDocument,
    WorkbenchDocumentList,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
    SemanticContractUnavailable,
)
from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    get_semantic_alignment_service,
)
from src.semantic_layer.registry import get_semantic_registry
from src.shared.schemas.responses import error_detail


router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/policy-workbench",
    tags=["policy-workbench"],
)

_service: KnowledgeWorkbenchService | None = None


def _get_service() -> KnowledgeWorkbenchService:
    global _service
    if _service is None:
        _service = KnowledgeWorkbenchService(
            PipelineStore(),
            registry=get_semantic_registry(),
            alignment_service=get_semantic_alignment_service(),
        )
    return _service


@router.get("/documents", response_model=WorkbenchDocumentList)
def list_workbench_documents() -> WorkbenchDocumentList:
    try:
        return _get_service().list_documents()
    except SemanticContractUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail("SEMANTIC_CONTRACT_UNAVAILABLE", str(exc), {}),
        ) from exc


@router.get("/documents/{doc_id}", response_model=KnowledgeWorkbenchDocument)
def get_workbench_document(doc_id: str) -> KnowledgeWorkbenchDocument:
    try:
        return _get_service().get_document(doc_id)
    except SemanticContractUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "SEMANTIC_CONTRACT_UNAVAILABLE",
                str(exc),
                {"doc_id": doc_id},
            ),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "POLICY_DOCUMENT_NOT_FOUND",
                str(exc),
                {"doc_id": doc_id},
            ),
        ) from exc
