"""政策知识 Unit×Knowledge 三栏工作台 API。"""
from __future__ import annotations

import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from src.config import production as production_config
from src.data_platform.storage.postgresql.policy_quality_store import (
    PostgresPolicyQualityStore,
)
from src.data_platform.storage.postgresql.policy_answer_verification_gate_store import (
    PostgresAnswerVerificationGateStore,
)

from src.knowledge_extension.rule_explanation.change_set_models import KnowledgeChangeSet
from src.knowledge_extension.rule_explanation.decision_task_models import DecisionTask
from src.knowledge_extension.rule_explanation.knowledge_build_models import (
    CreateKnowledgeBuildTaskRequest,
    EligibleKnowledgeUnit,
    ExtractionOverride,
    KnowledgeBuildPreflight,
    KnowledgeBuildTask,
    PromptMode,
    ReextractReport,
)
from src.knowledge_extension.rule_explanation.knowledge_build_service import (
    KnowledgeBuildPreflightBlocked,
    KnowledgeExtractionFailed,
    KnowledgeBuildService,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
    KnowledgeBuildStore,
    PostgreSQLKnowledgeBuildStore,
    UnitRevisionClaimed,
)
from src.knowledge_extension.rule_explanation.knowledge_review_store import (
    InMemoryKnowledgeReviewStore,
    KnowledgeReview,
    KnowledgeReviewStore,
    stable_review_id,
)
from src.knowledge_extension.rule_explanation.published_snapshot_models import PublishedSnapshot
from src.knowledge_extension.rule_explanation.published_snapshot_store import PublishedSnapshotStore
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    KnowledgeWorkbenchDocument,
    WorkbenchDocumentList,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
    SemanticContractUnavailable,
)
from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
from src.knowledge_extension.rule_explanation.unit_med_type_store import (
    UnitMedTypeOverride,
)
from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
    PipelineOrchestrator,
)
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    RuleCompilationTraceResponse,
)
from src.knowledge_extension.rule_explanation.policy_extract.med_type_classifier import (
    VALID_MED_TYPES,
)
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
from src.knowledge_extension.rule_explanation.answer_verification.gate_models import (
    AnswerVerificationCaseResult,
    AnswerVerificationRun,
)
from src.knowledge_extension.rule_explanation.answer_verification.gate_service import (
    PolicyAnswerVerificationGateService,
)
from src.knowledge_extension.rule_explanation.answer_verification.gate_store import (
    AnswerVerificationGateStore,
    InMemoryAnswerVerificationGateStore,
)
from src.knowledge_extension.rule_explanation.answer_verification.milvus_port import (
    get_rule_knowledge_port_for_collection,
)
from src.knowledge_extension.rule_explanation.release_index import (
    KnowledgeWorkbenchReleaseSource,
    MilvusReleaseIndexBackend,
    ReleaseIndexBuilder,
)
from src.knowledge_extension.rule_explanation.policy_retrieval.applicability_backfill import (
    ApplicabilityBackfillService,
    BackfillApplication,
    BackfillProposal,
    MilvusRuleStore,
)
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    get_semantic_alignment_service,
)
from src.semantic_layer.registry import get_semantic_registry
from src.config.model_routing import MODEL_PARAMS, ROUTING_TABLE
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.knowledge_extension.rule_explanation.change_set_service import (
        ChangeSetService,
    )
    from src.knowledge_extension.rule_explanation.decision_task_service import (
        DecisionTaskService,
    )


router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/policy-workbench",
    tags=["policy-workbench"],
)

_service: KnowledgeWorkbenchService | None = None
_quality_store: PolicyQualityStore | None = None
_quality_service: PolicyQualityService | None = None
_answer_verification_gate_store: AnswerVerificationGateStore | None = None
_answer_verification_gate_service: PolicyAnswerVerificationGateService | None = None
_release_index_builder: ReleaseIndexBuilder | None = None
_release_content_source: KnowledgeWorkbenchReleaseSource | None = None
_review_store: KnowledgeReviewStore | None = None
_snapshot_store: PublishedSnapshotStore | None = None
_change_set_service: "ChangeSetService | None" = None
_decision_task_service: "DecisionTaskService | None" = None
_knowledge_build_store: KnowledgeBuildStore | None = None
_knowledge_build_service: KnowledgeBuildService | None = None
_unit_med_type_store: Any | None = None
_applicability_backfill_service: ApplicabilityBackfillService | None = None


def _get_unit_med_type_store():
    global _unit_med_type_store
    if _unit_med_type_store is None:
        from src.knowledge_extension.rule_explanation.unit_med_type_store import (
            InMemoryUnitMedTypeStore,
            PostgresUnitMedTypeStore,
        )
        _unit_med_type_store = (
            InMemoryUnitMedTypeStore()
            if os.environ.get("USE_MEMORY_STORAGE") == "1"
            else PostgresUnitMedTypeStore()
        )
    return _unit_med_type_store
_compilation_trace_store: Any | None = None


def _get_compilation_trace_store():
    global _compilation_trace_store
    if _compilation_trace_store is None:
        from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
            InMemoryCompilationTraceStore,
            PostgresCompilationTraceStore,
        )
        _compilation_trace_store = (
            InMemoryCompilationTraceStore()
            if os.environ.get("USE_MEMORY_STORAGE") == "1"
            else PostgresCompilationTraceStore()
        )
    return _compilation_trace_store


def _get_knowledge_build_store() -> KnowledgeBuildStore:
    global _knowledge_build_store
    if _knowledge_build_store is None:
        _knowledge_build_store = (
            InMemoryKnowledgeBuildStore()
            if os.environ.get("USE_MEMORY_STORAGE") == "1"
            else PostgreSQLKnowledgeBuildStore()
        )
    return _knowledge_build_store


def _get_knowledge_build_service() -> KnowledgeBuildService:
    global _knowledge_build_service
    if _knowledge_build_service is None:
        _knowledge_build_service = KnowledgeBuildService(
            _get_service(),
            _get_change_set_service(),
            _get_knowledge_build_store(),
            orchestrator=PipelineOrchestrator(PipelineStore()),
            med_type_store=_get_unit_med_type_store(),
        )
    return _knowledge_build_service


def _get_decision_task_service() -> "DecisionTaskService":
    global _decision_task_service
    if _decision_task_service is None:
        from src.knowledge_extension.rule_explanation.decision_task_service import (
            DecisionTaskService,
        )
        from src.knowledge_extension.rule_explanation.decision_task_store import (
            InMemoryDecisionTaskStore,
            PostgresDecisionTaskStore,
        )
        store = (
            InMemoryDecisionTaskStore()
            if os.environ.get("USE_MEMORY_STORAGE") == "1"
            else PostgresDecisionTaskStore()
        )
        _decision_task_service = DecisionTaskService(store)
    return _decision_task_service


def _get_change_set_service() -> "ChangeSetService":
    global _change_set_service
    if _change_set_service is None:
        from src.knowledge_extension.rule_explanation.change_set_service import (
            ChangeSetService,
        )
        from src.knowledge_extension.rule_explanation.change_set_store import (
            InMemoryChangeSetStore,
            PostgresChangeSetStore,
        )
        from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
            PolicyRuleCompiler,
        )
        from src.knowledge_extension.rule_explanation.policy_compiler.service import (
            PolicyCompilationService,
        )
        store = (
            InMemoryChangeSetStore()
            if os.environ.get("USE_MEMORY_STORAGE") == "1"
            else PostgresChangeSetStore()
        )
        pipeline_store = PipelineStore()
        _change_set_service = ChangeSetService(
            _get_service(),
            store,
            build_store=_get_knowledge_build_store(),
            compilation_service=PolicyCompilationService(
                pipeline_store,
                PolicyRuleCompiler(),
                _get_compilation_trace_store(),
            ),
        )
    return _change_set_service


def _get_snapshot_store() -> PublishedSnapshotStore:
    global _snapshot_store
    if _snapshot_store is None:
        if os.environ.get("USE_MEMORY_STORAGE") == "1":
            from src.knowledge_extension.rule_explanation.published_snapshot_store import (
                InMemoryPublishedSnapshotStore,
            )
            _snapshot_store = InMemoryPublishedSnapshotStore()
        else:
            from src.knowledge_extension.rule_explanation.published_snapshot_store import (
                PostgresPublishedSnapshotStore,
            )
            _snapshot_store = PostgresPublishedSnapshotStore()
    return _snapshot_store


def _get_review_store() -> KnowledgeReviewStore:
    global _review_store
    if _review_store is None:
        if os.environ.get("USE_MEMORY_STORAGE") == "1":
            _review_store = InMemoryKnowledgeReviewStore()
        else:
            from src.knowledge_extension.rule_explanation.knowledge_review_store import (
                PostgresKnowledgeReviewStore,
            )
            _review_store = PostgresKnowledgeReviewStore()
    return _review_store


def _get_service() -> KnowledgeWorkbenchService:
    global _service
    if _service is None:
        _service = KnowledgeWorkbenchService(
            PipelineStore(),
            registry=get_semantic_registry(),
            alignment_service=get_semantic_alignment_service(),
            review_store=_get_review_store(),
        )
    return _service


def _get_quality_store() -> PolicyQualityStore:
    global _quality_store
    if _quality_store is None:
        _quality_store = PostgresPolicyQualityStore()
        _quality_store.ensure_default_test_cases()
    return _quality_store


def _get_quality_service() -> PolicyQualityService:
    global _quality_service
    if _quality_service is None:
        _quality_service = PolicyQualityService(
            _get_quality_store(), RulesReleaseSearcher()
        )
    return _quality_service


def get_answer_verification_gate_store() -> AnswerVerificationGateStore:
    """答案验证门禁存储依赖；API 测试可通过 dependency_overrides 注入。"""
    global _answer_verification_gate_store
    if _answer_verification_gate_store is None:
        _answer_verification_gate_store = (
            InMemoryAnswerVerificationGateStore()
            if os.environ.get("USE_MEMORY_STORAGE") == "1"
            else PostgresAnswerVerificationGateStore()
        )
    return _answer_verification_gate_store


def get_answer_verification_gate_service() -> PolicyAnswerVerificationGateService:
    """答案验证门禁服务依赖；保持 release 检索与质量门禁使用同一 store。"""
    global _answer_verification_gate_service
    if _answer_verification_gate_service is None:
        _answer_verification_gate_service = PolicyAnswerVerificationGateService(
            _get_quality_store(),
            get_answer_verification_gate_store(),
            RulesReleaseSearcher(),
            get_rule_knowledge_port_for_collection,
        )
    return _answer_verification_gate_service


def _get_release_index_builder() -> ReleaseIndexBuilder:
    global _release_index_builder
    if _release_index_builder is None:
        _release_index_builder = ReleaseIndexBuilder(
            _get_quality_store(),
            MilvusReleaseIndexBackend(),
            _get_compilation_trace_store(),
        )
    return _release_index_builder


def _get_applicability_backfill_service() -> ApplicabilityBackfillService:
    global _applicability_backfill_service
    if _applicability_backfill_service is None:
        from src.knowledge_extension.rule_explanation.release_resolver import (
            resolve_rules_collection,
        )

        # Issue #33：回填写入 Runtime 当前实际读的集合（active release 优先），
        # 禁止直写 policy_rules_v2（有 active release 时 Runtime 读不到）。
        _applicability_backfill_service = ApplicabilityBackfillService(
            MilvusRuleStore(
                collection_name=resolve_rules_collection(
                    production_config.MILVUS_HOST, str(production_config.MILVUS_PORT)
                )
            )
        )
    return _applicability_backfill_service


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
    source_change_set_id: str | None = None


class RunQualityRequest(BaseModel):
    repeat_count: int = Field(default=3, ge=3)
    minimum_quality: float = Field(default=0.8, ge=0, le=1)
    minimum_consistency: float = Field(default=0.9, ge=0, le=1)


class ReleaseReviewRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=128)


class KnowledgeReviewRequest(BaseModel):
    """中栏每组结构化知识的评审请求。"""

    doc_id: str = Field(min_length=1, max_length=128)
    unit_id: str = Field(min_length=1, max_length=128)
    knowledge_id: str = Field(min_length=1, max_length=128)
    extraction_id: str | None = None
    status: str
    reviewed_by: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=2000)


class BuildChangeSetRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=128)


class QualityRunReport(BaseModel):
    run: QualityRun
    case_results: list[QualityCaseResult]


class AnswerVerificationRunReport(BaseModel):
    run: AnswerVerificationRun
    case_results: list[AnswerVerificationCaseResult]


class ReleaseGateStatus(BaseModel):
    """只读门禁快照；POST 发布会重新执行权威校验，不能依赖此结果放行。"""

    release_id: str
    can_promote: bool
    current_case_set_version: int
    active_release_id: str | None = None
    latest_run: QualityRun | None = None
    latest_answer_verification_run: AnswerVerificationRun | None = None
    answer_verification_gate_enabled: bool = False
    answer_verification_blocked_reasons: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)
    sync_pending: bool = False
    sync_pending_reasons: list[str] = Field(default_factory=list)


class Issue25MetricsResponse(BaseModel):
    """Issue #25 专项检索指标（供 policy-knowledge/test 看板展示）。"""

    run_at: str
    embedding_kind: str
    corpus_size: int
    case_count: int
    text_only: dict[str, float]
    current_hybrid: dict[str, float]
    enhanced_hybrid: dict[str, float]
    broad_hybrid: dict[str, float]
    field_quality_score: float
    top_diff_cases: list[dict[str, Any]]


def _require_legacy_policy_releases_enabled() -> None:
    if production_config.ALLOW_LEGACY_POLICY_RELEASES:
        return
    raise HTTPException(
        status_code=403,
        detail=error_detail(
            "POLICY_LEGACY_RELEASE_DISABLED",
            "无来源旧版发布能力已由服务端关闭",
            {},
        ),
    )


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


def _raise_build_preflight_error(result: KnowledgeBuildPreflight) -> None:
    conflicts = [
        blocker
        for blocker in result.blockers
        if blocker.code
        in {
            "UNIT_REVISION_CHANGED",
            "UNIT_ALREADY_CLAIMED",
            "SEMANTIC_CONTRACT_MISMATCH",
        }
    ]
    primary = conflicts[0] if conflicts else result.blockers[0]
    audit_event: dict[str, Any] = {
        "blockers": [blocker.model_dump() for blocker in result.blockers]
    }
    if conflicts:
        audit_event.update(
            unit_revision_id=primary.unit_revision_id,
            task_id=primary.task_id,
            target_href=primary.target_href,
        )
    raise HTTPException(
        status_code=409 if conflicts else 422,
        detail=error_detail(primary.code, primary.message, audit_event),
    )


def _claimed_target_href(error: UnitRevisionClaimed) -> str:
    fallback = f"/policy-knowledge/knowledge/build?task_id={error.task_id}"
    try:
        target_href = next(
            (
                unit.target_href
                for unit in _get_knowledge_build_service().list_eligible_units()
                if unit.doc_id == error.doc_id
                and unit.unit_id == error.unit_id
                and unit.occupied_by == error.task_id
            ),
            None,
        )
        return target_href or fallback
    except Exception:
        # 目标链接是次要审计补全，查询失败不得覆盖已确认的原子占用主冲突。
        return fallback


@router.get(
    "/knowledge-build/eligible-units",
    response_model=list[EligibleKnowledgeUnit],
)
def list_eligible_knowledge_build_units() -> list[EligibleKnowledgeUnit]:
    try:
        return _get_knowledge_build_service().list_eligible_units()
    except SemanticContractUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail("SEMANTIC_CONTRACT_UNAVAILABLE", str(exc), {}),
        ) from exc


class UnitMedTypeRequest(BaseModel):
    """单元医疗类别人工修正请求。"""

    doc_id: str = Field(min_length=1, max_length=64)
    unit_id: str = Field(min_length=1, max_length=64)
    med_type: str = Field(min_length=1, max_length=64)

    @field_validator("med_type")
    @classmethod
    def _med_type_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("med_type 不能为空白")
        if stripped not in VALID_MED_TYPES:
            raise ValueError("med_type 不是受支持的医疗类别")
        return stripped


class UnitMedTypeResetResponse(BaseModel):
    reset: bool


def _require_policy_knowledge_reviewer(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str:
    from src.gateway.auth import authenticator

    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTHENTICATION_REQUIRED", "人工修正医疗类别需要登录凭证"),
        )
    auth_result = authenticator.validate_token(authorization)
    if not auth_result.is_success or not auth_result.user_id.strip():
        raise HTTPException(
            status_code=401,
            detail=error_detail("INVALID_AUTHENTICATION", auth_result.error_message),
        )
    permission = authenticator.check_permission(auth_result, "semantic:review")
    if not permission.is_success:
        raise HTTPException(
            status_code=403,
            detail=error_detail("POLICY_KNOWLEDGE_REVIEW_FORBIDDEN", permission.error_message),
        )
    return auth_result.user_id.strip()


def _require_eligible_unit(doc_id: str, unit_id: str) -> None:
    if not any(
        unit.doc_id == doc_id and unit.unit_id == unit_id
        for unit in _get_knowledge_build_service().list_eligible_units()
    ):
        raise HTTPException(
            status_code=404,
            detail=error_detail("KNOWLEDGE_UNIT_NOT_FOUND", "政策单元不存在"),
        )


@router.post("/knowledge-build/unit-med-types", response_model=UnitMedTypeOverride)
def set_unit_med_type(
    request: UnitMedTypeRequest,
    actor: str = Depends(_require_policy_knowledge_reviewer),
) -> UnitMedTypeOverride:
    """人工修正单元医疗类别（覆盖自动分类；不影响其他单元）。"""
    _require_eligible_unit(request.doc_id, request.unit_id)
    return _get_unit_med_type_store().set(UnitMedTypeOverride(
        doc_id=request.doc_id,
        unit_id=request.unit_id,
        med_type=request.med_type,
        updated_by=actor,
    ))


@router.delete(
    "/knowledge-build/unit-med-types/{doc_id}/{unit_id}",
    response_model=UnitMedTypeResetResponse,
)
def reset_unit_med_type(
    doc_id: str,
    unit_id: str,
    _: str = Depends(_require_policy_knowledge_reviewer),
) -> UnitMedTypeResetResponse:
    """重置单元医疗类别为自动分类。"""
    _require_eligible_unit(doc_id, unit_id)
    reset = _get_unit_med_type_store().delete(doc_id, unit_id)
    return UnitMedTypeResetResponse(reset=reset)


@router.post(
    "/knowledge-build/preflight",
    response_model=KnowledgeBuildPreflight,
)
def preflight_knowledge_build(
    request: CreateKnowledgeBuildTaskRequest,
) -> KnowledgeBuildPreflight:
    try:
        return _get_knowledge_build_service().preflight(request)
    except SemanticContractUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail("SEMANTIC_CONTRACT_UNAVAILABLE", str(exc), {}),
        ) from exc


@router.get(
    "/knowledge-build/tasks",
    response_model=list[KnowledgeBuildTask],
)
def list_knowledge_build_tasks() -> list[KnowledgeBuildTask]:
    return _get_knowledge_build_store().list()


@router.get(
    "/knowledge-build/tasks/{task_id}",
    response_model=KnowledgeBuildTask,
)
def get_knowledge_build_task(task_id: str) -> KnowledgeBuildTask:
    task = _get_knowledge_build_store().get(task_id)
    if task is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "KNOWLEDGE_BUILD_TASK_NOT_FOUND",
                "知识构建任务不存在",
                {"task_id": task_id},
            ),
        )
    return task


@router.post(
    "/knowledge-build/tasks",
    response_model=KnowledgeBuildTask,
    status_code=201,
)
def create_knowledge_build_task(
    request: CreateKnowledgeBuildTaskRequest,
    background_tasks: BackgroundTasks,
) -> KnowledgeBuildTask:
    try:
        service = _get_knowledge_build_service()
        queued = service.enqueue_task(request)
        background_tasks.add_task(
            _run_knowledge_build_task,
            service,
            queued.task_id,
        )
        return queued
    except SemanticContractUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail("SEMANTIC_CONTRACT_UNAVAILABLE", str(exc), {}),
        ) from exc
    except KnowledgeExtractionFailed as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "KNOWLEDGE_EXTRACTION_FAILED",
                str(exc),
                {
                    "task_id": exc.task_id,
                    "doc_id": exc.doc_id,
                    "unit_id": exc.unit_id,
                },
            ),
        ) from exc
    except KnowledgeBuildPreflightBlocked as exc:
        _raise_build_preflight_error(exc.result)
    except UnitRevisionClaimed as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "UNIT_ALREADY_CLAIMED",
                str(exc),
                {
                    "unit_revision_id": exc.unit_revision_id,
                    "task_id": exc.task_id,
                    "target_href": _claimed_target_href(exc),
                },
            ),
        ) from exc


def _run_knowledge_build_task(service: KnowledgeBuildService, task_id: str) -> None:
    try:
        service.run_task(task_id)
    except Exception:
        # run_task 已将失败原因写回任务；这里只保留服务端堆栈，避免后台异常污染响应。
        logger.exception("知识构建后台任务失败 task_id=%s", task_id)


@router.get("/change-sets", response_model=list[KnowledgeChangeSet])
def list_change_sets(doc_id: str = "") -> list[KnowledgeChangeSet]:
    """知识变更集列表（V4.1 §11.1）；按文档批次聚合，可带 doc_id 过滤。"""
    return _get_change_set_service().list_change_sets(doc_id)


@router.get("/change-sets/{change_set_id}", response_model=KnowledgeChangeSet)
def get_change_set(change_set_id: str) -> KnowledgeChangeSet:
    change_set = _get_change_set_service().get_change_set(change_set_id)
    if change_set is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "CHANGE_SET_NOT_FOUND", "知识变更集不存在", {"change_set_id": change_set_id}
            ),
        )
    return change_set


@router.post("/change-sets/build-from-doc", response_model=KnowledgeChangeSet)
def build_change_set_from_document(request: BuildChangeSetRequest) -> KnowledgeChangeSet:
    """按文档批次生成（或重建）知识变更集（V4.1 §11：AI 产物聚合层）。"""
    return _get_change_set_service().build_for_document(request.doc_id)


class ChangeSetActionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=2000)


class LifecycleSyncPending(RuntimeError):
    """变更集与关联任务的原子迁移失败，可安全重试。"""

    def __init__(self, change_set_id: str, target_status: str) -> None:
        self.change_set_id = change_set_id
        self.target_status = target_status
        super().__init__(
            f"变更集 {change_set_id} 与关联任务迁移到 {target_status} 失败"
        )


def _apply_change_set_action(
    change_set_id: str,
    *,
    target_status: str,
    action: Callable[[], KnowledgeChangeSet],
) -> KnowledgeChangeSet:
    """执行服务层的双状态原子迁移；失败时两边均保持原状态。"""
    try:
        return action()
    except (HTTPException, ValueError, LifecycleSyncPending):
        raise
    except Exception as exc:
        raise LifecycleSyncPending(change_set_id, target_status) from exc


def _lifecycle_sync_pending_response(exc: LifecycleSyncPending) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_detail(
            "CHANGE_SET_LIFECYCLE_SYNC_PENDING",
            "知识变更集与构建任务状态均未变更，可安全重试",
            {
                "change_set_id": exc.change_set_id,
                "target_status": exc.target_status,
            },
        ),
    )


@router.post("/change-sets/{change_set_id}/submit-review", response_model=KnowledgeChangeSet)
def submit_change_set_review(change_set_id: str, request: ChangeSetActionRequest) -> KnowledgeChangeSet:
    try:
        return _get_change_set_service().submit_review(change_set_id, request.reviewer)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=error_detail("CHANGE_SET_STATE_INVALID", str(exc), {})) from exc


@router.post("/change-sets/{change_set_id}/approve", response_model=KnowledgeChangeSet)
def approve_change_set(change_set_id: str, request: ChangeSetActionRequest) -> KnowledgeChangeSet:
    try:
        service = _get_change_set_service()
        return _apply_change_set_action(
            change_set_id,
            target_status="APPROVED",
            action=lambda: service.approve(
                change_set_id, request.reviewer, request.note or ""
            ),
        )
    except LifecycleSyncPending as exc:
        raise _lifecycle_sync_pending_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=error_detail("CHANGE_SET_STATE_INVALID", str(exc), {})) from exc


@router.post("/change-sets/{change_set_id}/return", response_model=KnowledgeChangeSet)
def return_change_set(change_set_id: str, request: ChangeSetActionRequest) -> KnowledgeChangeSet:
    try:
        service = _get_change_set_service()
        return _apply_change_set_action(
            change_set_id,
            target_status="RETURNED",
            action=lambda: service.return_for_rebuild(
                change_set_id, request.reviewer, request.note or ""
            ),
        )
    except LifecycleSyncPending as exc:
        raise _lifecycle_sync_pending_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=error_detail("CHANGE_SET_STATE_INVALID", str(exc), {})) from exc


@router.post("/change-sets/{change_set_id}/reject", response_model=KnowledgeChangeSet)
def reject_change_set(change_set_id: str, request: ChangeSetActionRequest) -> KnowledgeChangeSet:
    try:
        service = _get_change_set_service()
        return _apply_change_set_action(
            change_set_id,
            target_status="REJECTED",
            action=lambda: service.reject(
                change_set_id, request.reviewer, request.note or ""
            ),
        )
    except LifecycleSyncPending as exc:
        raise _lifecycle_sync_pending_response(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=error_detail("CHANGE_SET_STATE_INVALID", str(exc), {})) from exc


@router.post("/change-sets/{change_set_id}/reprocess", response_model=KnowledgeChangeSet)
def reprocess_change_set(change_set_id: str) -> KnowledgeChangeSet:
    """退回 AI 重处理：阶段一按原文档批次重建（差异分析放阶段二）。"""
    try:
        return _get_change_set_service().reprocess(change_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=error_detail("CHANGE_SET_STATE_INVALID", str(exc), {})) from exc


# ── 迭代 18：变更集重新提取（修改提示词 / 换大模型 / 单条·批量）──────────

class ReextractRequest(BaseModel):
    item_ids: list[str] | None = None
    override: ExtractionOverride | None = None


@router.post(
    "/change-sets/{change_set_id}/reextract",
    response_model=ReextractReport,
)
def reextract_change_set(change_set_id: str, request: ReextractRequest) -> ReextractReport:
    """对变更集重新提取（单条/批量统一入口，迭代 18）。"""
    try:
        return _get_change_set_service().reextract(
            change_set_id, request.item_ids, request.override
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "CHANGE_SET_REEXTRACT_INVALID",
                str(exc),
                {"change_set_id": change_set_id},
            ),
        ) from exc


class TestExtractRequest(BaseModel):
    item_id: str
    override: ExtractionOverride | None = None


@router.post("/change-sets/{change_set_id}/test-extract")
def test_extract_change_set_item(
    change_set_id: str, request: TestExtractRequest
) -> dict[str, Any]:
    """重提取前测试（迭代 19 修改2）：用当前单元 + 动态指标 + 所选提示词/模型
    跑一次提取并预览，**不写任何存储**；满意后再提交正式重提取。"""
    try:
        return _get_change_set_service().test_extract(
            change_set_id, request.item_id, request.override
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "CHANGE_SET_TEST_EXTRACT_INVALID",
                str(exc),
                {"change_set_id": change_set_id, "item_id": request.item_id},
            ),
        ) from exc


class MetricContractSummary(BaseModel):
    code: str
    name: str
    kind: str
    extraction_hint: str | None = None
    value_domain: str | None = None


class ExtractionConfigResponse(BaseModel):
    default_prompt_mode: PromptMode = "schema"
    default_model: str
    default_max_tokens: int = 8192
    schema_version: int
    metrics: list[MetricContractSummary]
    note: str


class ModelOption(BaseModel):
    model_name: str
    display_name: str
    available: bool


class PromptPreviewResponse(BaseModel):
    prompt: str
    schema_version: int
    field_count: int


def _build_extraction_metrics() -> tuple[int, list[MetricContractSummary]]:
    """读当前 published 指标契约，返回 (schema_version, metrics)。"""
    from src.semantic_layer.extraction_contract import build_extraction_schema
    from src.semantic_layer.registry import create_registry

    try:
        schema = build_extraction_schema(create_registry(), "zcgz")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail("SEMANTIC_CONTRACT_UNAVAILABLE", str(exc), {}),
        ) from exc
    metrics: list[MetricContractSummary] = []
    for f in schema.fields:
        metrics.append(MetricContractSummary(
            code=f.code, name=f.name, kind=f.kind,
            extraction_hint=f.extraction_hint, value_domain=f.value_domain,
        ))
    for e in schema.entities:
        metrics.append(MetricContractSummary(
            code=e.code, name=e.name, kind=e.kind,
            extraction_hint=e.extraction_hint, value_domain=e.value_domain,
        ))
    for r in schema.relations:
        hint = " / ".join(p for p in (r.subject_hint, r.predicate_hint, r.object_hint) if p)
        metrics.append(MetricContractSummary(
            code=r.code, name=r.name, kind=r.kind, extraction_hint=hint or None,
        ))
    return schema.schema_version, metrics


@router.get("/extraction-config", response_model=ExtractionConfigResponse)
def get_extraction_config() -> ExtractionConfigResponse:
    """查询当前提取配置：默认提示词模式、可用指标、契约版本、默认模型。"""
    schema_version, metrics = _build_extraction_metrics()
    return ExtractionConfigResponse(
        default_prompt_mode="schema",
        default_model=ROUTING_TABLE.get(("default", "llm"), ""),
        default_max_tokens=8192,
        schema_version=schema_version,
        metrics=metrics,
        note="schema 模式实时读语义层 published 指标；在语义层发布新指标后下次重提取立即生效。",
    )


@router.get("/extraction-config/models", response_model=list[ModelOption])
def list_extraction_models() -> list[ModelOption]:
    """列出可选 LLM 模型（排除 embedding）。"""
    embedding_models = {
        v for (scene, mt), v in ROUTING_TABLE.items() if mt == "embedding"
    }
    return [
        ModelOption(model_name=name, display_name=name, available=True)
        for name in MODEL_PARAMS
        if name not in embedding_models
    ]


@router.get(
    "/extraction-config/prompt-preview",
    response_model=PromptPreviewResponse,
)
def preview_extraction_prompt(
    prompt_mode: PromptMode = "schema",
    custom_prompt: str | None = None,
) -> PromptPreviewResponse:
    """实时预览最终提示词（schema 模式含指标注入，让用户看到指标确实生效）。"""
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        PipelineOrchestrator,
    )
    from src.semantic_layer.extraction_contract import build_extraction_schema
    from src.semantic_layer.registry import create_registry

    try:
        schema = build_extraction_schema(create_registry(), "zcgz")
        schema_version = schema.schema_version
        field_count = len(schema.fields) + len(schema.entities) + len(schema.relations)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail("SEMANTIC_CONTRACT_UNAVAILABLE", str(exc), {}),
        ) from exc

    override: ExtractionOverride | None
    if prompt_mode == "custom":
        if not (custom_prompt and custom_prompt.strip()):
            raise HTTPException(
                status_code=400,
                detail=error_detail(
                    "PROMPT_PREVIEW_INVALID",
                    "custom 模式需提供 custom_prompt",
                    {"prompt_mode": prompt_mode},
                ),
            )
        override = ExtractionOverride(prompt_mode="custom", custom_prompt=custom_prompt)
    else:
        override = ExtractionOverride(prompt_mode=prompt_mode)

    orch = PipelineOrchestrator()
    prompt = orch._build_fact_extraction_prompt(
        "（政策原文）", "（政策标题）", override
    )
    return PromptPreviewResponse(
        prompt=prompt, schema_version=schema_version, field_count=field_count
    )


class RuleDetail(BaseModel):
    rule: dict[str, Any]
    unit: dict[str, Any]
    document: dict[str, Any]
    change_set_id: str | None = None
    review_status: str | None = None


@router.get(
    "/rules/{rule_id}/trace",
    response_model=RuleCompilationTraceResponse,
)
def get_rule_compilation_trace(
    rule_id: str,
    run_id: str | None = None,
) -> RuleCompilationTraceResponse:
    trace = _get_compilation_trace_store().get_rule_trace(rule_id, run_id=run_id)
    if trace is None:
        audit_event = {"rule_id": rule_id}
        if run_id is not None:
            audit_event["run_id"] = run_id
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "RULE_TRACE_NOT_FOUND",
                "规则编译轨迹不存在",
                audit_event,
            ),
        )
    return trace


@router.get("/rules/{rule_id}", response_model=RuleDetail)
def get_rule_detail(rule_id: str) -> RuleDetail:
    """按 rule_id 定位规则详情：规则 + 所属单元原文 + 文档上下文 + 变更集归属。"""
    service = _get_service()
    for summary in service.list_documents().items:
        document = service.get_document(summary.doc_id)
        for unit in document.units:
            for knowledge in unit.knowledge:
                if knowledge.knowledge_id == rule_id:
                    change_sets = _get_change_set_service().list_change_sets(summary.doc_id)
                    return RuleDetail(
                        rule=knowledge.model_dump(),
                        unit={"unit_id": unit.unit_id, "path": unit.path, "source_text": unit.source_text, "status": unit.status},
                        document={"doc_id": document.doc_id, "doc_title": document.doc_title, "contract_version": document.contract_version},
                        change_set_id=change_sets[0].change_set_id if change_sets else None,
                        review_status=knowledge.review_status,
                    )
    raise HTTPException(
        status_code=404,
        detail=error_detail("RULE_NOT_FOUND", "规则不存在", {"rule_id": rule_id}),
    )


@router.post("/change-sets/{change_set_id}/generate-tasks", response_model=list[DecisionTask])
def generate_decision_tasks(change_set_id: str) -> list[DecisionTask]:
    """从变更集生成人工决策任务（证据不足/值域未映射/低置信）。"""
    change_set = _get_change_set_service().get_change_set(change_set_id)
    if change_set is None:
        raise HTTPException(status_code=404, detail=error_detail("CHANGE_SET_NOT_FOUND", "变更集不存在", {}))
    return _get_decision_task_service().generate_for_change_set(change_set)


class ResolveTaskRequest(BaseModel):
    decision: dict[str, Any]


@router.post("/decision-tasks/{task_id}/resolve", response_model=DecisionTask)
def resolve_decision_task(task_id: str, request: ResolveTaskRequest) -> DecisionTask:
    try:
        return _get_decision_task_service().resolve(task_id, request.decision)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=error_detail("DECISION_TASK_INVALID", str(exc), {})) from exc


@router.get("/decision-tasks", response_model=list[DecisionTask])
def list_decision_tasks(status: str = "", task_type: str = "", scope: str = "") -> list[DecisionTask]:
    return _get_decision_task_service().list_tasks(status=status, task_type=task_type, scope=scope)


class GovernanceDashboard(BaseModel):
    documents_total: int
    change_sets_total: int
    knowledge_total: int
    rules_total: int
    rules_pending_review: int
    rules_approved: int
    compilation_by_status: dict[str, int]
    tasks_pending: int
    tasks_by_type: dict[str, int]
    change_sets_by_status: dict[str, int]
    risk_summary: dict[str, int]
    avg_source_fidelity: float | None = None
    avg_completeness: float | None = None


@router.get("/governance/dashboard", response_model=GovernanceDashboard)
def get_governance_dashboard() -> GovernanceDashboard:
    """AI 治理驾驶舱聚合（V4.1 §9）。"""
    service = _get_service()
    documents = service.list_documents()
    change_sets = _get_change_set_service().list_change_sets()
    rules_total = 0
    rules_pending = 0
    rules_approved = 0
    fidelity: list[float] = []
    completeness: list[float] = []
    compilation_by_status: dict[str, int] = {}
    risk: dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for change_set in change_sets:
        for key, value in (change_set.risk_summary or {}).items():
            risk[key] = risk.get(key, 0) + value
        for item in change_set.items:
            rules_total += 1
            if item.compilation_status:
                compilation_by_status[item.compilation_status] = (
                    compilation_by_status.get(item.compilation_status, 0) + 1
                )
            after = item.after or {}
            confidence = after.get("confidence") or {}
            if confidence.get("overall"):
                fidelity.append(float(confidence.get("source_fidelity") or 0))
                completeness.append(float(confidence.get("completeness") or 0))
            review = after.get("review_status") or "pending"
            if review == "approved":
                rules_approved += 1
            elif review in ("pending", "rejected"):
                rules_pending += 1
    tasks = _get_decision_task_service().list_tasks(status="PENDING")
    tasks_by_type: dict[str, int] = {}
    for task in tasks:
        tasks_by_type[task.task_type] = tasks_by_type.get(task.task_type, 0) + 1
    return GovernanceDashboard(
        documents_total=documents.total,
        change_sets_total=len(change_sets),
        knowledge_total=sum(item.knowledge_count for item in documents.items),
        rules_total=rules_total,
        rules_pending_review=rules_pending,
        rules_approved=rules_approved,
        compilation_by_status=compilation_by_status,
        tasks_pending=len(tasks),
        tasks_by_type=tasks_by_type,
        change_sets_by_status={status: sum(1 for cs in change_sets if cs.status == status) for status in {cs.status for cs in change_sets}},
        risk_summary=risk,
        avg_source_fidelity=round(sum(fidelity) / len(fidelity), 4) if fidelity else None,
        avg_completeness=round(sum(completeness) / len(completeness), 4) if completeness else None,
    )


@router.post(
    "/knowledge/{knowledge_id}/review",
    response_model=KnowledgeReview,
    status_code=201,
)
def review_knowledge(knowledge_id: str, request: KnowledgeReviewRequest) -> KnowledgeReview:
    """记录一组知识的评审结论（通过 / 驳回），落库以便追溯。"""
    if knowledge_id != request.knowledge_id:
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                "KNOWLEDGE_REVIEW_ID_MISMATCH",
                "路径 knowledge_id 与请求体不一致",
                {"path": knowledge_id, "body": request.knowledge_id},
            ),
        )
    if request.status not in ("approved", "rejected"):
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                "KNOWLEDGE_REVIEW_STATUS_INVALID",
                "评审状态只能为 approved / rejected",
                {"status": request.status},
            ),
        )
    review = KnowledgeReview(
        review_id=stable_review_id(request.doc_id, request.knowledge_id),
        doc_id=request.doc_id,
        unit_id=request.unit_id,
        knowledge_id=request.knowledge_id,
        extraction_id=request.extraction_id,
        status=request.status,  # type: ignore[arg-type]
        reviewed_by=request.reviewed_by,
        note=request.note,
    )
    return _get_review_store().save(review)


class CreateTestCaseRequest(BaseModel):
    case_id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["precise", "semantic", "hybrid"] = "semantic"
    expected_knowledge_ids: list[str] = Field(default_factory=list)
    required: bool = True
    active: bool = True


@router.post("/test-cases", response_model=PolicyQATestCase, status_code=201)
def save_test_case(request: CreateTestCaseRequest) -> PolicyQATestCase:
    case = PolicyQATestCase(
        case_id=request.case_id or f"tc_{uuid4().hex[:12]}",
        name=request.name,
        query=request.query,
        mode=request.mode,
        expected_knowledge_ids=request.expected_knowledge_ids,
        required=request.required,
        active=request.active,
    )
    return _get_quality_store().save_test_case(case)


@router.get("/test-cases", response_model=list[PolicyQATestCase])
def list_test_cases() -> list[PolicyQATestCase]:
    return _get_quality_store().list_test_cases(active_only=False)


@router.post("/releases", response_model=KnowledgeRelease, status_code=201)
def create_candidate_release(request: CreateReleaseRequest) -> KnowledgeRelease:
    if request.source_change_set_id is None:
        _require_legacy_policy_releases_enabled()
    store = _get_quality_store()
    release = KnowledgeRelease(
        release_id=request.release_id,
        facts_collection=f"policy_facts_{request.release_id}",
        rules_collection=f"policy_rules_{request.release_id}",
        contract_version=request.contract_version,
        case_set_version=store.current_case_set_version(),
        config_hash=request.config_hash,
        source_change_set_id=request.source_change_set_id,
    )
    if request.source_change_set_id is not None:
        try:
            _validate_governed_release_source_before_promote(
                release,
                active_retry=False,
                require_lineage=False,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "POLICY_RELEASE_LINEAGE_INVALID",
                    str(exc),
                    {
                        "release_id": request.release_id,
                        "source_change_set_id": request.source_change_set_id,
                    },
                ),
            ) from exc
        except Exception as exc:
            raise _release_source_unavailable_response(
                request.release_id,
                request.source_change_set_id,
            ) from exc
    try:
        return store.create_release(release)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_EXISTS", str(exc), {"release_id": request.release_id}
            ),
        ) from exc


@router.get("/releases", response_model=list[KnowledgeRelease])
def list_releases() -> list[KnowledgeRelease]:
    return _get_quality_store().list_releases()


@router.post("/releases/{release_id}/build", response_model=KnowledgeRelease)
def build_candidate_release(release_id: str) -> KnowledgeRelease:
    store = _get_quality_store()
    release: KnowledgeRelease | None = None
    try:
        release = store.get_release(release_id)
        if release is None:
            raise ValueError(f"候选版本不存在: {release_id}")
        if release.source_change_set_id is None:
            raise ValueError("候选版本缺少来源知识变更集")
        change_set = _get_change_set_service().get_change_set(
            release.source_change_set_id
        )
        if change_set is None:
            raise ValueError(
                f"来源知识变更集不存在: {release.source_change_set_id}"
            )
        facts, rules, publications = _get_release_content_source().records(change_set)
        return _get_release_index_builder().build(
            release_id,
            facts=facts,
            rules=rules,
            publications=publications,
        )
    except Exception as exc:
        if release is not None:
            try:
                store.save_release(release.model_copy(update={"build_error": str(exc)}))
            except Exception:
                pass
        blocked = isinstance(exc, ValueError)
        raise HTTPException(
            status_code=409 if blocked else 503,
            detail=error_detail(
                "POLICY_RELEASE_BUILD_BLOCKED" if blocked else "POLICY_RELEASE_INDEX_UNAVAILABLE",
                str(exc),
                {"release_id": release_id},
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


@router.get("/releases/{release_id}/quality/latest", response_model=QualityRunReport)
def get_latest_release_quality(release_id: str) -> QualityRunReport:
    run = _get_quality_store().get_latest_run(release_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "POLICY_QUALITY_RUN_NOT_FOUND",
                "候选版本尚无质量运行",
                {"release_id": release_id},
            ),
        )
    return QualityRunReport(
        run=run,
        case_results=_get_quality_store().list_case_results(run.run_id),
    )


_issue25_evaluation_runner: Callable[[str], dict[str, Any]] | None = None


def _load_issue25_evaluation_runner() -> Callable[[str], dict[str, Any]]:
    """动态加载 Issue #25 评估脚本中的 run_issue25_evaluation 函数。"""
    global _issue25_evaluation_runner
    if _issue25_evaluation_runner is not None:
        return _issue25_evaluation_runner

    script_path = Path(__file__).resolve().parents[3] / "scripts" / "eval" / "issue25_retrieval_baseline.py"
    if not script_path.exists():
        raise RuntimeError(f"Issue #25 评估脚本不存在: {script_path}")

    spec = importlib.util.spec_from_file_location("issue25_retrieval_baseline", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 Issue #25 评估脚本: {script_path}")

    module = importlib.util.module_from_spec(spec)
    # 评估脚本依赖 PROJECT_ROOT 在 sys.path 中，先注入
    project_root = str(script_path.resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    # 必须先注册到 sys.modules，否则脚本内 dataclass 装饰器会报 NoneType.__dict__ 错误
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    runner = getattr(module, "run_issue25_evaluation", None)
    if runner is None or not callable(runner):
        raise RuntimeError("Issue #25 评估脚本未导出 run_issue25_evaluation 函数")

    _issue25_evaluation_runner = runner
    return runner


@router.get("/quality/issue25-metrics", response_model=Issue25MetricsResponse)
def get_issue25_metrics(
    embedding_kind: str = "hash",
) -> Issue25MetricsResponse:
    """Issue #25 专项检索指标：对跑 text_only / current_hybrid / enhanced_hybrid / broad_hybrid 四条基线。

    默认使用 hash embedding 快速返回；生产环境可传 `sentence_transformer` 获取真实 bge 结果，
    但首次调用需加载模型，耗时较长。

    ⚠️ 评估脚本使用内存 fake Milvus 客户端，会临时替换模块级 MilvusClient 引用，
    调用前后自动恢复，不影响生产检索。
    """
    if embedding_kind not in ("hash", "sentence_transformer"):
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                "ISSUE25_METRICS_INVALID_KIND",
                "embedding_kind 必须是 hash 或 sentence_transformer",
                {"embedding_kind": embedding_kind},
            ),
        )

    # 保存原 MilvusClient，评估后恢复
    from src.runtime.policy_qa import structured_policy_retriever as _spr_module
    from src.runtime.policy_qa import broad_policy_retriever as _bpr_module

    _original_structured_client = getattr(_spr_module, "MilvusClient", None)
    _original_broad_client = getattr(_bpr_module, "MilvusClient", None)

    try:
        runner = _load_issue25_evaluation_runner()
        result = runner(embedding_kind=embedding_kind)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "ISSUE25_EVALUATION_UNAVAILABLE",
                str(exc),
                {"embedding_kind": embedding_kind},
            ),
        ) from exc
    except Exception as exc:
        logger.exception("Issue #25 评估执行失败")
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "ISSUE25_EVALUATION_FAILED",
                f"评估执行失败: {exc}",
                {"embedding_kind": embedding_kind},
            ),
        ) from exc
    finally:
        if _original_structured_client is not None:
            _spr_module.MilvusClient = _original_structured_client
        if _original_broad_client is not None:
            _bpr_module.MilvusClient = _original_broad_client

    return Issue25MetricsResponse(
        run_at=datetime.now().isoformat(),
        embedding_kind=result.get("embedding_kind", embedding_kind),
        corpus_size=result.get("corpus_size", 0),
        case_count=result.get("case_count", 0),
        text_only=result.get("text_only", {}),
        current_hybrid=result.get("current_hybrid", {}),
        enhanced_hybrid=result.get("enhanced_hybrid", {}),
        broad_hybrid=result.get("broad_hybrid", {}),
        field_quality_score=result.get("field_quality_score", 0.0),
        top_diff_cases=result.get("top_diff_cases", []),
    )


@router.post(
    "/releases/{release_id}/answer-verification/test",
    response_model=AnswerVerificationRun,
)
def run_release_answer_verification(
    release_id: str,
    service: PolicyAnswerVerificationGateService = Depends(
        get_answer_verification_gate_service
    ),
) -> AnswerVerificationRun:
    """触发候选 release 的夹具驱动答案验证门禁运行。"""
    try:
        return service.run_release(release_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_ANSWER_VERIFICATION_RUN_BLOCKED",
                str(exc),
                {"release_id": release_id},
            ),
        ) from exc


@router.get(
    "/releases/{release_id}/answer-verification/latest",
    response_model=AnswerVerificationRunReport,
)
def get_latest_release_answer_verification(
    release_id: str,
    store: AnswerVerificationGateStore = Depends(get_answer_verification_gate_store),
) -> AnswerVerificationRunReport:
    """读取最新答案验证门禁报告及逐用例结果。"""
    run = store.get_latest_run(release_id)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "POLICY_ANSWER_VERIFICATION_RUN_NOT_FOUND",
                "候选版本尚无答案验证门禁运行",
                {"release_id": release_id},
            ),
        )
    return AnswerVerificationRunReport(
        run=run,
        case_results=store.list_case_results(run.run_id),
    )


def _release_sync_pending_response(
    release_id: str,
    source_change_set_id: str | None,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_detail(
            "POLICY_RELEASE_SYNC_PENDING",
            "发布已生效，血缘与构建任务状态尚待重试收口",
            {
                "release_id": release_id,
                "source_change_set_id": source_change_set_id,
            },
        ),
    )


def _release_source_unavailable_response(
    release_id: str,
    source_change_set_id: str | None,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_detail(
            "POLICY_RELEASE_SOURCE_UNAVAILABLE",
            "发布来源状态暂不可用，请稍后重试",
            {
                "release_id": release_id,
                "source_change_set_id": source_change_set_id,
            },
        ),
    )


def _release_gate_unavailable_response(release_id: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_detail(
            "POLICY_RELEASE_GATE_UNAVAILABLE",
            "发布门禁状态暂不可用，请稍后重试",
            {"release_id": release_id},
        ),
    )


def _release_promotion_unavailable_response(release_id: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_detail(
            "POLICY_RELEASE_PROMOTION_UNAVAILABLE",
            "发布存储暂不可用，release 尚未确认生效",
            {"release_id": release_id},
        ),
    )


def _release_state_unknown_response(release_id: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=error_detail(
            "POLICY_RELEASE_STATE_UNKNOWN",
            "发布调用失败且无法回读 release 状态，请稍后查询后再重试",
            {"release_id": release_id},
        ),
    )


def _validate_release_source_before_promote(
    release: KnowledgeRelease,
    *,
    active_retry: bool,
) -> None:
    source_change_set_id = release.source_change_set_id
    if source_change_set_id is None:
        return
    change_set = _get_change_set_service().get_change_set(source_change_set_id)
    if change_set is None:
        raise ValueError(f"来源知识变更集不存在: {source_change_set_id}")
    allowed_change_set_statuses = (
        {"APPROVED", "PUBLISHED"} if active_retry else {"APPROVED"}
    )
    if change_set.status not in allowed_change_set_statuses:
        raise ValueError(
            f"来源知识变更集 {source_change_set_id} 状态为 {change_set.status}，"
            "不满足发布条件"
        )
    if change_set.semantic_contract_version != release.contract_version:
        raise ValueError(
            f"来源知识变更集 {source_change_set_id} 的语义契约版本"
            f" {change_set.semantic_contract_version} 与 release"
            f" {release.contract_version} 不一致"
        )
    if not change_set.build_task_id:
        raise ValueError(
            f"来源知识变更集 {source_change_set_id} 未关联构建任务"
        )
    task = _get_knowledge_build_store().get(change_set.build_task_id)
    if task is None:
        raise ValueError(f"构建任务不存在: {change_set.build_task_id}")
    if task.result_change_set_id != source_change_set_id:
        raise ValueError(
            f"构建任务 {task.task_id} 的结果与来源变更集"
            f" {source_change_set_id} 不一致"
        )
    allowed_task_statuses = (
        {"APPROVED_PENDING_RELEASE", "PUBLISHED"}
        if active_retry
        else {"APPROVED_PENDING_RELEASE"}
    )
    if task.status not in allowed_task_statuses:
        raise ValueError(
            f"构建任务 {task.task_id} 状态为 {task.status}，不满足发布条件"
        )
    if (
        task.semantic_contract_version != release.contract_version
        or task.semantic_contract_version
        != change_set.semantic_contract_version
    ):
        raise ValueError(
            f"构建任务 {task.task_id}、来源变更集 {source_change_set_id}"
            f" 与 release 的语义契约版本不一致"
        )


def _validate_applicability_gate_for_release(release: KnowledgeRelease) -> None:
    """Issue #25：在 release promote 前校验候选 collection 的适用性字段质量门禁。

    若候选 collection 尚未构建（如测试环境未执行 build），则跳过强门禁，
    由 `/backfill-applicability/validate-gate` 端点提供显式检查。
    """
    from pymilvus.exceptions import MilvusException

    try:
        store = MilvusRuleStore(collection_name=release.rules_collection)
        if not store.client.has_collection(store.collection_name):
            return
        service = ApplicabilityBackfillService(store)
        passed, missing = service.validate_gate()
    except MilvusException:
        # collection 不存在或 Milvus 瞬时不可用：不在 promote 路径强阻断
        return

    if not passed:
        summary = ", ".join(f"{m.rule_id}.{m.field_name}" for m in missing[:10])
        raise ValueError(
            f"适用性字段质量门禁未通过: {summary} (共 {len(missing)} 条)"
        )


def _validate_governed_release_source_before_promote(
    release: KnowledgeRelease,
    *,
    active_retry: bool,
    require_lineage: bool = True,
) -> None:
    if release.source_change_set_id is None:
        raise ValueError("缺少正式来源知识变更集")
    _validate_release_source_before_promote(
        release,
        active_retry=active_retry,
    )
    change_set = _get_change_set_service().get_change_set(
        release.source_change_set_id
    )
    if change_set is None:
        raise ValueError(f"来源知识变更集不存在: {release.source_change_set_id}")
    # 发布门禁必须精确匹配本变更集的规则与编译运行，旧运行不能顶替。
    expected_rule_runs: list[tuple[str, str]] = []
    for item in change_set.items:
        if (
            item.canonical_rule is None
            or item.compile_run_id is None
            or item.compilation_status not in {"PASS", "WARN"}
        ):
            raise ValueError(f"变更项 {item.item_id} 缺少可发布规范规则")
        expected_rule_runs.append((item.canonical_rule.rule_id, item.compile_run_id))
    if require_lineage and not _get_compilation_trace_store().has_release_lineage(
        release.release_id, expected_rule_runs
    ):
        raise ValueError(f"release {release.release_id} 编译血缘不完整")
    # Issue #25：适用性字段质量门禁
    _validate_applicability_gate_for_release(release)


def _release_sync_pending_reasons(release: KnowledgeRelease) -> list[str]:
    reasons: list[str] = []
    if _get_snapshot_store().get(release.release_id) is None:
        reasons.append("发布快照尚未落库")

    source_change_set_id = release.source_change_set_id
    if source_change_set_id is None:
        reasons.append("缺少正式来源知识变更集")
        return reasons

    change_set = _get_change_set_service().get_change_set(source_change_set_id)
    if change_set is None:
        reasons.append(f"来源知识变更集不存在: {source_change_set_id}")
        return reasons
    if change_set.status != "PUBLISHED":
        reasons.append(
            f"来源知识变更集 {source_change_set_id} 尚未同步为 PUBLISHED"
        )

    if change_set.build_task_id is None:
        reasons.append("来源知识变更集未关联构建任务")
        return reasons
    task = _get_knowledge_build_store().get(change_set.build_task_id)
    if task is None:
        reasons.append(f"构建任务不存在: {change_set.build_task_id}")
    elif task.status != "PUBLISHED":
        reasons.append(f"构建任务 {task.task_id} 尚未同步为 PUBLISHED")
    return reasons


@router.get(
    "/releases/{release_id}/gate-status",
    response_model=ReleaseGateStatus,
)
def get_release_gate_status(
    release_id: str,
    answer_gate_store: AnswerVerificationGateStore = Depends(
        get_answer_verification_gate_store
    ),
) -> ReleaseGateStatus:
    """返回观察性快照；真正发布仍由 POST 接口在事务前重新校验。"""
    try:
        store = _get_quality_store()
        release = store.get_release(release_id)
        current_case_set_version = store.current_case_set_version()
        active = store.get_active_release()
        latest_run = store.get_latest_run(release_id)
        latest_answer_verification_run = answer_gate_store.get_latest_run(release_id)
    except Exception as exc:
        raise _release_gate_unavailable_response(release_id) from exc

    active_release_id = active.release_id if active is not None else None
    blocked_reasons: list[str] = []
    answer_verification_blocked_reasons: list[str] = []
    sync_pending_reasons: list[str] = []
    if release is None:
        blocked_reasons.append("release 不存在")
    else:
        if release.status == "active":
            blocked_reasons.append("该 release 已是活动版本，仅允许通过发布接口重试同步收口")
        elif release.status != "passed":
            blocked_reasons.append(f"release 状态为 {release.status}，尚未通过质量门禁")

        if latest_run is None:
            blocked_reasons.append("缺少质量运行")
        else:
            if latest_run.status != "passed":
                blocked_reasons.append("最新质量运行未通过")
            if latest_run.case_set_version != current_case_set_version:
                blocked_reasons.append("最新质量运行未使用当前用例集")
            if latest_run.config_hash != release.config_hash:
                blocked_reasons.append("release 测试配置与最新质量运行不一致")
            if latest_run.baseline_release_id != active_release_id:
                blocked_reasons.append("最新质量运行的活动基线已过期")

        answer_gate_enabled = (
            production_config.POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED
        )
        if not answer_gate_enabled:
            answer_verification_blocked_reasons.append("skipped: 答案验证门禁未启用")
        elif latest_answer_verification_run is None:
            answer_verification_blocked_reasons.append("缺少答案验证门禁运行")
        elif latest_answer_verification_run.status != "passed":
            answer_verification_blocked_reasons.extend(
                latest_answer_verification_run.blocked_reasons
                or ["最新答案验证门禁运行未通过"]
            )
        if answer_gate_enabled:
            blocked_reasons.extend(answer_verification_blocked_reasons)

        try:
            _validate_governed_release_source_before_promote(
                release,
                active_retry=release.status == "active",
            )
        except ValueError as exc:
            blocked_reasons.append(str(exc))
        except Exception as exc:
            raise _release_source_unavailable_response(
                release_id,
                release.source_change_set_id,
            ) from exc

        if release.status == "active":
            try:
                sync_pending_reasons = _release_sync_pending_reasons(release)
            except Exception as exc:
                raise _release_gate_unavailable_response(release_id) from exc

    return ReleaseGateStatus(
        release_id=release_id,
        can_promote=not blocked_reasons,
        current_case_set_version=current_case_set_version,
        active_release_id=active_release_id,
        latest_run=latest_run,
        latest_answer_verification_run=latest_answer_verification_run,
        answer_verification_gate_enabled=production_config.POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED,
        answer_verification_blocked_reasons=answer_verification_blocked_reasons,
        blocked_reasons=blocked_reasons,
        sync_pending=bool(sync_pending_reasons),
        sync_pending_reasons=sync_pending_reasons,
    )


def _validate_answer_verification_gate_before_promote(
    release: KnowledgeRelease,
    gate_store: AnswerVerificationGateStore,
) -> None:
    """发布前第二道答案验证门禁；开关关闭时明确跳过且不阻断。"""
    if not production_config.POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED:
        return
    latest = gate_store.get_latest_run(release.release_id)
    if latest is None:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_BLOCKED",
                "缺少答案验证门禁运行",
                {"release_id": release.release_id},
            ),
        )
    if latest.status != "passed":
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_BLOCKED",
                "最新答案验证门禁运行未通过",
                {
                    "release_id": release.release_id,
                    "run_id": latest.run_id,
                    "blocked_reasons": latest.blocked_reasons,
                },
            ),
        )


def _promote_release(
    release_id: str,
    request: ReleaseReviewRequest,
    *,
    legacy: bool,
    answer_gate_store: AnswerVerificationGateStore | None = None,
) -> KnowledgeRelease:
    if legacy:
        _require_legacy_policy_releases_enabled()
    try:
        quality_store = _get_quality_store()
        release = quality_store.get_release(release_id)
    except Exception as exc:
        raise _release_promotion_unavailable_response(release_id) from exc
    if release is None:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_GATE_BLOCKED",
                f"release 不存在: {release_id}",
                {"release_id": release_id},
            ),
        )
    active_retry = release.status == "active"
    if legacy:
        if release.source_change_set_id is not None:
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "POLICY_RELEASE_LEGACY_BLOCKED",
                    "正式来源 release 不允许使用 legacy 发布入口",
                    {
                        "release_id": release_id,
                        "source_change_set_id": release.source_change_set_id,
                    },
                ),
            )
    else:
        try:
            _validate_governed_release_source_before_promote(
                release,
                active_retry=active_retry,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "POLICY_RELEASE_LINEAGE_INVALID",
                    str(exc),
                    {
                        "release_id": release_id,
                        "source_change_set_id": release.source_change_set_id,
                    },
                ),
            ) from exc
        except Exception as exc:
            raise _release_source_unavailable_response(
                release_id, release.source_change_set_id
            ) from exc
    if active_retry:
        promoted_release = release
    else:
        if not legacy:
            _validate_answer_verification_gate_before_promote(
                release,
                answer_gate_store or get_answer_verification_gate_store(),
            )
        try:
            promoted_release = quality_store.promote_release(
                release_id, request.reviewed_by
            )
        except ValueError as exc:
            # 并发 promote 已提交时，继续从刚切换的 active 版本收口。
            try:
                current = quality_store.get_release(release_id)
            except Exception as read_exc:
                raise _release_state_unknown_response(release_id) from read_exc
            if current is not None and current.status == "active":
                promoted_release = current
            else:
                raise HTTPException(
                    status_code=409,
                    detail=error_detail(
                        "POLICY_RELEASE_GATE_BLOCKED",
                        str(exc),
                        {"release_id": release_id},
                    ),
                ) from exc
        except Exception as exc:
            try:
                current = quality_store.get_release(release_id)
            except Exception as read_exc:
                raise _release_state_unknown_response(release_id) from read_exc
            if current is not None and current.status == "active":
                raise _release_sync_pending_response(
                    release_id, current.source_change_set_id
                ) from exc
            raise _release_promotion_unavailable_response(release_id) from exc
    release = promoted_release
    # 从这里起 active 已切换；任一后置 store 失败都只能等待幂等重试收口。
    try:
        _get_snapshot_store().save(PublishedSnapshot(
            snapshot_id=release.release_id,
            semantic_contract_version=release.contract_version,
            rules_collection=release.rules_collection,
            facts_collection=release.facts_collection,
            source_change_set_id=release.source_change_set_id,
            published_by=release.promoted_by or request.reviewed_by,
        ))
        if release.source_change_set_id is not None:
            service = _get_change_set_service()
            _apply_change_set_action(
                release.source_change_set_id,
                target_status="PUBLISHED",
                action=lambda: service.mark_published(
                    release.source_change_set_id or ""
                ),
            )
    except Exception as exc:
        raise _release_sync_pending_response(
            release_id, release.source_change_set_id
        ) from exc
    return release


@router.post("/releases/{release_id}/promote", response_model=KnowledgeRelease)
def promote_release(
    release_id: str,
    request: ReleaseReviewRequest,
    answer_gate_store: AnswerVerificationGateStore = Depends(
        get_answer_verification_gate_store
    ),
) -> KnowledgeRelease:
    return _promote_release(
        release_id,
        request,
        legacy=False,
        answer_gate_store=answer_gate_store,
    )


@router.post(
    "/releases/{release_id}/promote-legacy",
    response_model=KnowledgeRelease,
    deprecated=True,
)
def promote_release_legacy(
    release_id: str, request: ReleaseReviewRequest
) -> KnowledgeRelease:
    """Deprecated：仅供旧测试页发布无来源候选，正式链路不得调用。"""
    return _promote_release(release_id, request, legacy=True)


@router.get("/published", response_model=list[PublishedSnapshot])
def list_published_snapshots() -> list[PublishedSnapshot]:
    """已发布知识快照列表（V4.1 §12）。"""
    return _get_snapshot_store().list()


@router.get("/published/active", response_model=PublishedSnapshot)
def get_active_snapshot() -> PublishedSnapshot:
    """当前活动快照（Agent 运行时的知识版本）。"""
    release = _get_quality_store().get_active_release()
    if release is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("POLICY_ACTIVE_RELEASE_NOT_FOUND", "尚无活动版本", {}),
        )
    snapshot = _get_snapshot_store().get(release.release_id)
    if snapshot is None:
        snapshot = PublishedSnapshot(
            snapshot_id=release.release_id,
            semantic_contract_version=release.contract_version,
            rules_collection=release.rules_collection,
            facts_collection=release.facts_collection,
            source_change_set_id=release.source_change_set_id,
            published_by=release.promoted_by or "",
        )
    return snapshot


@router.post("/releases/{release_id}/rollback", response_model=KnowledgeRelease)
def rollback_release(
    release_id: str, request: ReleaseReviewRequest
) -> KnowledgeRelease:
    store = _get_quality_store()
    release = store.get_release(release_id)
    if release is not None and release.source_change_set_id is None:
        _require_legacy_policy_releases_enabled()
    try:
        return store.rollback_release(release_id, request.reviewed_by)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "POLICY_RELEASE_ROLLBACK_BLOCKED", str(exc), {"release_id": release_id}
            ),
        ) from exc


# ── Issue #25：适用性字段存量回填（提议者-审核者模型）──────────────


class _BackfillProposalItem(BaseModel):
    rule_id: str
    field_name: str
    old_value: Any
    proposed_value: Any
    confidence: str
    reason: str


class _BackfillApplicationItem(BaseModel):
    rule_id: str
    field_name: str
    applied_value: Any
    reviewed_by: str
    reviewed_at: str


class ProposeBackfillResponse(BaseModel):
    proposals: list[_BackfillProposalItem]
    total_rules: int
    missing_count: int


class ApplyBackfillRequest(BaseModel):
    proposals: list[_BackfillProposalItem]
    reviewed_by: str


class ApplyBackfillResponse(BaseModel):
    applications: list[_BackfillApplicationItem]
    updated_count: int


class ValidateBackfillGateResponse(BaseModel):
    passed: bool
    missing: list[_BackfillProposalItem]


def _proposal_item(p: BackfillProposal) -> _BackfillProposalItem:
    return _BackfillProposalItem(
        rule_id=p.rule_id,
        field_name=p.field_name,
        old_value=p.old_value,
        proposed_value=p.proposed_value,
        confidence=p.confidence,
        reason=p.reason,
    )


def _application_item(a: BackfillApplication) -> _BackfillApplicationItem:
    return _BackfillApplicationItem(
        rule_id=a.rule_id,
        field_name=a.field_name,
        applied_value=a.applied_value,
        reviewed_by=a.reviewed_by,
        reviewed_at=a.reviewed_at,
    )


@router.get("/backfill-applicability/propose", response_model=ProposeBackfillResponse)
def propose_applicability_backfill() -> ProposeBackfillResponse:
    """扫描当前 policy_rules_v2，返回缺失适用性字段的回填提议。"""
    service = _get_applicability_backfill_service()
    proposals = service.propose()
    rules = service._store.list_rules()
    return ProposeBackfillResponse(
        proposals=[_proposal_item(p) for p in proposals],
        total_rules=len(rules),
        missing_count=len(proposals),
    )


@router.post("/backfill-applicability/apply", response_model=ApplyBackfillResponse)
def apply_applicability_backfill(request: ApplyBackfillRequest) -> ApplyBackfillResponse:
    """人工确认后应用回填提议。reviewed_by 必填。"""
    service = _get_applicability_backfill_service()
    domain_proposals = [
        BackfillProposal(
            rule_id=p.rule_id,
            field_name=p.field_name,
            old_value=p.old_value,
            proposed_value=p.proposed_value,
            confidence=p.confidence,
            reason=p.reason,
        )
        for p in request.proposals
    ]
    try:
        applications, updated_count = service.apply(domain_proposals, request.reviewed_by)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=error_detail("BACKFILL_REVIEW_REQUIRED", str(exc), {}),
        ) from exc
    return ApplyBackfillResponse(
        applications=[_application_item(a) for a in applications],
        updated_count=updated_count,
    )


@router.get("/backfill-applicability/validate-gate", response_model=ValidateBackfillGateResponse)
def validate_applicability_backfill_gate() -> ValidateBackfillGateResponse:
    """质量门禁：检查 published 规则是否仍缺失关键适用性字段。"""
    service = _get_applicability_backfill_service()
    passed, missing = service.validate_gate()
    return ValidateBackfillGateResponse(
        passed=passed,
        missing=[_proposal_item(p) for p in missing],
    )
