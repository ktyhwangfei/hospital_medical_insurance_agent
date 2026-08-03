"""政策知识 Unit×Knowledge 三栏工作台 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.data_platform.storage.postgresql.policy_quality_store import (
    PostgresPolicyQualityStore,
)

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    KnowledgeWorkbenchDocument,
    WorkbenchDocumentList,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
    SemanticContractUnavailable,
)
from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
    QualityCaseResult,
    QualityRun,
)
from src.knowledge_extension.rule_explanation.quality_service import (
    PolicyQualityService,
    RulesReleaseSearcher,
)
from src.knowledge_extension.rule_explanation.quality_store import PolicyQualityStore
from src.knowledge_extension.rule_explanation.release_index import (
    KnowledgeWorkbenchReleaseSource,
    MilvusReleaseIndexBackend,
    ReleaseIndexBuilder,
)
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
_quality_store: PolicyQualityStore | None = None
_quality_service: PolicyQualityService | None = None
_release_index_builder: ReleaseIndexBuilder | None = None
_release_content_source: KnowledgeWorkbenchReleaseSource | None = None


def _get_service() -> KnowledgeWorkbenchService:
    global _service
    if _service is None:
        _service = KnowledgeWorkbenchService(
            PipelineStore(),
            registry=get_semantic_registry(),
            alignment_service=get_semantic_alignment_service(),
        )
    return _service


def _get_quality_store() -> PolicyQualityStore:
    global _quality_store
    if _quality_store is None:
        _quality_store = PostgresPolicyQualityStore()
    return _quality_store


def _get_quality_service() -> PolicyQualityService:
    global _quality_service
    if _quality_service is None:
        _quality_service = PolicyQualityService(
            _get_quality_store(), RulesReleaseSearcher()
        )
    return _quality_service


def _get_release_index_builder() -> ReleaseIndexBuilder:
    global _release_index_builder
    if _release_index_builder is None:
        _release_index_builder = ReleaseIndexBuilder(
            _get_quality_store(), MilvusReleaseIndexBackend()
        )
    return _release_index_builder


def _get_release_content_source() -> KnowledgeWorkbenchReleaseSource:
    global _release_content_source
    if _release_content_source is None:
        from src.knowledge_extension.rule_explanation.policy_retrieval.embedding_provider import (
            get_embedding_provider,
        )

        _release_content_source = KnowledgeWorkbenchReleaseSource(
            _get_service(), get_embedding_provider()
        )
    return _release_content_source


class CreateReleaseRequest(BaseModel):
    release_id: str = Field(pattern=r"^[A-Za-z0-9_]+$", min_length=1, max_length=64)
    contract_version: str
    config_hash: str


class RunQualityRequest(BaseModel):
    repeat_count: int = Field(default=3, ge=3)
    minimum_quality: float = Field(default=0.8, ge=0, le=1)
    minimum_consistency: float = Field(default=0.9, ge=0, le=1)


class ReleaseReviewRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=128)


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


@router.post("/test-cases", response_model=PolicyQATestCase, status_code=201)
def save_test_case(request: PolicyQATestCase) -> PolicyQATestCase:
    return _get_quality_store().save_test_case(request)


@router.get("/test-cases", response_model=list[PolicyQATestCase])
def list_test_cases() -> list[PolicyQATestCase]:
    return _get_quality_store().list_test_cases(active_only=False)


@router.post("/releases", response_model=KnowledgeRelease, status_code=201)
def create_candidate_release(request: CreateReleaseRequest) -> KnowledgeRelease:
    store = _get_quality_store()
    if store.get_release(request.release_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_EXISTS", "候选版本已存在", {"release_id": request.release_id}
            ),
        )
    release = KnowledgeRelease(
        release_id=request.release_id,
        facts_collection=f"policy_facts_{request.release_id}",
        rules_collection=f"policy_rules_{request.release_id}",
        contract_version=request.contract_version,
        case_set_version=store.current_case_set_version(),
        config_hash=request.config_hash,
    )
    return store.save_release(release)


@router.get("/releases", response_model=list[KnowledgeRelease])
def list_releases() -> list[KnowledgeRelease]:
    return _get_quality_store().list_releases()


@router.post("/releases/{release_id}/build", response_model=KnowledgeRelease)
def build_candidate_release(release_id: str) -> KnowledgeRelease:
    try:
        facts, rules = _get_release_content_source().records()
        return _get_release_index_builder().build(
            release_id, facts=facts, rules=rules
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_BUILD_BLOCKED", str(exc), {"release_id": release_id}
            ),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "POLICY_RELEASE_INDEX_UNAVAILABLE", str(exc), {"release_id": release_id}
            ),
        ) from exc


@router.get("/releases/active", response_model=KnowledgeRelease)
def get_active_release() -> KnowledgeRelease:
    release = _get_quality_store().get_active_release()
    if release is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("POLICY_ACTIVE_RELEASE_NOT_FOUND", "尚无活动版本", {}),
        )
    return release


@router.post("/releases/{release_id}/test", response_model=QualityRun)
def run_release_quality(release_id: str, request: RunQualityRequest) -> QualityRun:
    try:
        return _get_quality_service().run_release(
            release_id,
            repeat_count=request.repeat_count,
            minimum_quality=request.minimum_quality,
            minimum_consistency=request.minimum_consistency,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_QUALITY_RUN_BLOCKED", str(exc), {"release_id": release_id}
            ),
        ) from exc


@router.get("/quality-runs/{run_id}", response_model=QualityRun)
def get_quality_run(run_id: str) -> QualityRun:
    run = _get_quality_store().get_run(run_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "POLICY_QUALITY_RUN_NOT_FOUND",
                "质量运行不存在",
                {"run_id": run_id},
            ),
        )
    return run


@router.get("/quality-runs/{run_id}/case-results", response_model=list[QualityCaseResult])
def list_quality_case_results(run_id: str) -> list[QualityCaseResult]:
    if _get_quality_store().get_run(run_id) is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("POLICY_QUALITY_RUN_NOT_FOUND", "质量运行不存在", {"run_id": run_id}),
        )
    return _get_quality_store().list_case_results(run_id)


@router.post("/releases/{release_id}/promote", response_model=KnowledgeRelease)
def promote_release(
    release_id: str, request: ReleaseReviewRequest
) -> KnowledgeRelease:
    try:
        return _get_quality_store().promote_release(release_id, request.reviewed_by)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_GATE_BLOCKED", str(exc), {"release_id": release_id}
            ),
        ) from exc


@router.post("/releases/{release_id}/rollback", response_model=KnowledgeRelease)
def rollback_release(
    release_id: str, request: ReleaseReviewRequest
) -> KnowledgeRelease:
    try:
        return _get_quality_store().rollback_release(release_id, request.reviewed_by)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_ROLLBACK_BLOCKED", str(exc), {"release_id": release_id}
            ),
        ) from exc
