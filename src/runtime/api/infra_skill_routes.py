import logging
import os
import time
import hashlib
import json
from dataclasses import dataclass
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Protocol, TypeVar, cast

import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ValidationError

from src.config.production import (
    SKILLS_DIR,
    SKILL_CANDIDATE_CPU_LIMIT,
    SKILL_CANDIDATE_MEMORY_LIMIT,
    SKILL_CANDIDATE_PIDS_LIMIT,
    SKILL_CANDIDATE_ROOT,
    SKILL_CANDIDATE_RUNNER_IMAGE,
    SKILL_CANDIDATE_SANDBOX_ENABLED,
    SKILL_CANDIDATE_TIMEOUT_SECONDS,
)
from src.data_platform.storage.skill.version_factory import get_skill_version_storage
from src.data_platform.storage.skill.version_ports import SkillVersionConflictError
from src.data_platform.storage.skill.draft_ports import (
    SkillDraftConflictError,
    SkillDraftNotFoundError,
)
from src.data_platform.storage.skill.governance_factory import (
    get_skill_governance_storage,
)
from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
    SkillGovernanceNotFoundError,
)
from src.data_platform.cache import create_cache_client
from src.data_platform.cache.ports import IdempotencyStore, ShortStateStore
from src.observability import metrics as observability_metrics

logger = logging.getLogger(__name__)
from src.runtime.api.schemas import (
    FieldMappingItem,
    FieldMappingResponse,
    InfraSkillCatalogResponse,
    InfraSkillOverviewItem,
    InfraSkillOverviewResponse,
    InfraSkillDetailResponse,
    InfraSkillFilesStructure,
    InfraSkillItem,
    SkillExecuteTestRequest,
    SkillExecuteTestResponse,
    SkillRefreshResponse,
    SkillRouteTestRequest,
    SkillRouteTestResponse,
    SkillVersionResponse,
    SkillVersionSyncRequest,
)
from src.runtime.skill_management.version_service import (
    SkillNotFoundError,
    SkillVersionService,
)
from src.runtime.skill_management.governance_service import (
    SkillGovernanceGateError,
    SkillGovernanceService,
)
from src.runtime.skill_management.workbench_service import (
    SkillGovernancePriority,
    SkillGovernanceStatus,
    SkillWorkbenchService,
)
from src.runtime.skill_management.draft_service import SkillDraftService
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationResponse,
    SkillAIOptimizationResponse,
)
from src.runtime.skill_management.ai_authoring.service import (
    SkillAIAuthoringError,
    SkillAIAuthoringService,
    SkillAIInputInvalidError,
    SkillAIMetricNotFoundError,
    SkillAIMetricNotPublishedError,
    SkillAIModelError,
    SkillAIOutputInvalidError,
    SkillAIRevisionConflictError,
    SkillAISecurityRejectedError,
)
from src.runtime.skill_management.draft_validator import SkillDraftValidator
from src.runtime.skill_management.package_generator import SkillPackageGenerator
from src.runtime.skill_management.ai_authoring.candidate_evaluation import (
    SkillCandidateArtifactError,
    SkillCandidateEvaluationService,
)
from src.runtime.skill_management.ai_authoring.candidate_execution_ports import (
    CandidateExecutionPort,
    DisabledCandidateExecutionAdapter,
)
from src.domain.skill.governance_models import SkillRelease
from src.runtime.api.skill_schemas import (
    SkillAIAcceptRequest,
    SkillAIGenerateRequest,
    SkillAIOptimizeRequest,
    SkillDraftCreateRequest,
    SkillDraftCopyRequest,
    SkillDraftListResponse,
    SkillDraftResponse,
    SkillDraftSaveRequest,
    SkillDraftValidationResponse,
    SkillMaterializeRequest,
    SkillMaterializeResponse,
    SkillDefinitionResponse,
    SkillLifecycleTransitionRequest,
    SkillPackageFileResponse,
    SkillPackagePreviewResponse,
    SkillCandidateBehaviorEvaluationResponse,
    SkillCandidateEvaluationRequest,
    SkillCandidateRouteEvaluationResponse,
    SkillValidationIssueResponse,
    SkillEvalCaseCreateRequest,
    SkillEvalCaseListResponse,
    SkillEvalCaseResponse,
    SkillEvalCaseUpdateRequest,
    SkillEvalRunCreateRequest,
    SkillEvalRunListResponse,
    SkillEvalRunResponse,
    SkillReleaseApproveRequest,
    SkillReleaseApprovalSummaryResponse,
    SkillReleaseCreateRequest,
    SkillReleaseListResponse,
    SkillReleaseResponse,
    SkillReleaseTransitionRequest,
    SkillWorkbenchResponse,
)
from src.shared.schemas.responses import error_detail
from src.gateway.auth import AuthStatus, authenticator
from src.skill_infra.artifact import SkillArtifactError
from src.skill_infra.skill_loader import get_loader, refresh_loader
from src.skill_infra.skill_router import get_assembler
from src.skill_infra.unified_router import route_question_ranked
from src.data_platform.storage.skill.regression_factory import (
    get_skill_regression_storage as _get_skill_regression_storage_factory,
)
from src.data_platform.storage.skill.regression_ports import SkillRegressionStorage
from src.runtime.api.policy_qa_routes import TaskBackedQASourceReader
from src.runtime.skill_management.regression_mining_service import (
    RegressionMiningService,
)
from src.runtime.api.skill_schemas import (
    EvalCasePoolConfirmRequest,
    EvalCasePoolConfirmResponse,
    EvalCasePoolFromHistoryRequest,
    EvalCasePoolFromHistoryResponse,
    EvalCasePoolItemResponse,
    EvalCasePoolListResponse,
    EvalCasePoolRejectRequest,
    EvalCasePoolTransformRequest,
    EvalCasePoolTransformResponse,
    HistoryMiningOutcomeResponse,
)

router = APIRouter()


def get_skill_version_service() -> SkillVersionService:
    return SkillVersionService(
        storage=get_skill_version_storage(),
        loader=get_loader(),
        skills_root=SKILLS_DIR,
    )


SkillVersionServiceDependency = Annotated[
    SkillVersionService, Depends(get_skill_version_service)
]


def get_skill_governance_service() -> SkillGovernanceService:
    return SkillGovernanceService(
        storage=get_skill_governance_storage(),
        version_storage=get_skill_version_storage(),
        loader=get_loader(),
    )


SkillGovernanceServiceDependency = Annotated[
    SkillGovernanceService, Depends(get_skill_governance_service)
]


def get_skill_draft_service() -> SkillDraftService:
    from src.data_platform.storage.skill.draft_factory import get_skill_draft_storage

    return SkillDraftService(
        storage=get_skill_draft_storage(),
        loader=get_loader(),
        skills_root=SKILLS_DIR,
    )


SkillDraftServiceDependency = Annotated[
    SkillDraftService, Depends(get_skill_draft_service)
]


def get_skill_workbench_service(
    version_service: SkillVersionServiceDependency,
    governance_service: SkillGovernanceServiceDependency,
    draft_service: SkillDraftServiceDependency,
) -> SkillWorkbenchService:
    return SkillWorkbenchService(
        version_service,
        governance_service,
        draft_service=draft_service,
    )


SkillWorkbenchServiceDependency = Annotated[
    SkillWorkbenchService, Depends(get_skill_workbench_service)
]


def get_skill_regression_storage_dep() -> SkillRegressionStorage:
    return _get_skill_regression_storage_factory()


SkillRegressionStorageDependency = Annotated[
    SkillRegressionStorage, Depends(get_skill_regression_storage_dep)
]


def get_regression_mining_service(
    storage: SkillRegressionStorageDependency,
) -> RegressionMiningService:
    return RegressionMiningService(
        storage=storage, qa_source_reader=TaskBackedQASourceReader()
    )


RegressionMiningServiceDependency = Annotated[
    RegressionMiningService, Depends(get_regression_mining_service)
]


@dataclass(frozen=True)
class SkillControlPrincipal:
    user_id: str
    roles: tuple[str, ...]


def _resolve_dev_principal(
    authorization: str | None,
    *,
    required_permission: str,
) -> SkillControlPrincipal:
    if os.getenv("SKILL_CONTROL_DEV_MODE", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(
            status_code=403,
            detail=error_detail(
                "SKILL_CONTROL_DISABLED",
                "Skill 治理写操作仅在显式开发模式下开放",
            ),
        )
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTHENTICATION_REQUIRED", "Skill 治理写操作需要登录凭证"),
        )
    auth_result = authenticator.validate_token(authorization)
    if not auth_result.is_success:
        raise HTTPException(
            status_code=401,
            detail=error_detail("INVALID_AUTHENTICATION", auth_result.error_message),
        )
    permitted = authenticator.check_permission(auth_result, required_permission)
    if permitted.status == AuthStatus.INSUFFICIENT_PERMISSION:
        raise HTTPException(
            status_code=403,
            detail=error_detail("SKILL_CONTROL_FORBIDDEN", permitted.error_message),
        )
    if not auth_result.user_id.strip():
        raise HTTPException(
            status_code=401,
            detail=error_detail("INVALID_AUTHENTICATION", "登录凭证缺少用户标识"),
        )
    return SkillControlPrincipal(
        user_id=auth_result.user_id.strip(),
        roles=tuple(auth_result.roles),
    )


def get_skill_control_principal(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> SkillControlPrincipal:
    return _resolve_dev_principal(
        authorization, required_permission="skill:release:test"
    )


def get_skill_evaluation_principal(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> SkillControlPrincipal:
    return _resolve_dev_principal(
        authorization, required_permission="skill:evaluate"
    )


SkillControlPrincipalDependency = Annotated[
    SkillControlPrincipal, Depends(get_skill_control_principal)
]
SkillEvaluationPrincipalDependency = Annotated[
    SkillControlPrincipal, Depends(get_skill_evaluation_principal)
]


def get_skill_approval_principal(
    principal: SkillControlPrincipalDependency,
) -> SkillControlPrincipal:
    if "information_department" not in principal.roles:
        raise HTTPException(
            status_code=403,
            detail=error_detail(
                "SKILL_APPROVAL_ROLE_FORBIDDEN", "只有信息科角色可以审批 test 发布"
            ),
        )
    return principal


SkillApprovalPrincipalDependency = Annotated[
    SkillControlPrincipal, Depends(get_skill_approval_principal)
]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
]


class SkillIdempotencyStore(IdempotencyStore, ShortStateStore, Protocol):
    def get_json(self, key: str) -> dict[str, object] | None: ...

    def set_json(
        self, key: str, value: dict[str, object], ttl_seconds: int
    ) -> None: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...


@lru_cache(maxsize=1)
def get_skill_idempotency_store() -> SkillIdempotencyStore:
    if os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes"):
        from src.data_platform.cache.in_memory import InMemoryCacheClient

        return InMemoryCacheClient()
    return cast(SkillIdempotencyStore, create_cache_client())


SkillIdempotencyStoreDependency = Annotated[
    SkillIdempotencyStore, Depends(get_skill_idempotency_store)
]

_TResponse = TypeVar("_TResponse", bound=BaseModel)


def _idempotent_mutation(
    *,
    store: SkillIdempotencyStore,
    scope: str,
    idempotency_key: str,
    request_payload: dict[str, object],
    operation: Callable[[], object],
    response_model: type[_TResponse],
    recovery: Callable[[], object | None] | None = None,
    result_metadata: Callable[[_TResponse], dict[str, object]] | None = None,
    replay: Callable[[dict[str, object]], object | None] | None = None,
) -> _TResponse:
    scoped_key = f"skill-governance:{scope}:{idempotency_key}"
    cache_key = f"idempotency:{scoped_key}"
    reservation_acquired = False
    serialized = json.dumps(
        request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    request_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    try:
        existing = store.get_result(scoped_key)
        if existing is not None:
            if existing.get("_request_hash") != request_hash:
                raise HTTPException(
                    status_code=409,
                    detail=error_detail(
                        "IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key 已用于不同请求",
                    ),
                )
            if replay is not None:
                replayed = replay(existing)
                if replayed is None:
                    raise HTTPException(
                        status_code=409,
                        detail=error_detail(
                            "IDEMPOTENCY_RESULT_UNAVAILABLE",
                            "幂等结果关联资源不存在",
                        ),
                    )
                return response_model.model_validate(replayed.model_dump())
            return response_model.model_validate(existing)
        reservation = store.get_json(cache_key)
        if (
            reservation is not None
            and reservation.get("request_hash") not in (None, request_hash)
        ):
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency-Key 已用于不同请求",
                ),
            )
        if reservation is not None and recovery is not None:
            recovered = recovery()
            if recovered is not None:
                response = response_model.model_validate(recovered.model_dump())
                stored = {
                    **(
                        result_metadata(response)
                        if result_metadata is not None
                        else response.model_dump(mode="json")
                    ),
                    "_request_hash": request_hash,
                }
                try:
                    store.complete(scoped_key, stored, ttl_seconds=86400)
                except Exception:
                    logger.exception(
                        "Failed to complete recovered Skill idempotency key: %s",
                        scoped_key,
                    )
                return response
        if not store.reserve(scoped_key, ttl_seconds=86400):
            raise HTTPException(
                status_code=409,
                detail=error_detail(
                    "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                    "相同 Idempotency-Key 的请求正在处理中",
                ),
            )
        reservation_acquired = True
        store.set_json(
            cache_key,
            {"status": "reserved", "request_hash": request_hash},
            ttl_seconds=86400,
        )
    except HTTPException:
        if reservation_acquired:
            try:
                store.delete(cache_key)
            except Exception:
                logger.exception(
                    "Failed to release initialized Skill idempotency key: %s",
                    scoped_key,
                )
        raise
    except Exception as exc:
        if reservation_acquired:
            try:
                store.delete(cache_key)
            except Exception:
                logger.exception(
                    "Failed to release initialized Skill idempotency key: %s",
                    scoped_key,
                )
        raise HTTPException(
            status_code=503,
            detail=error_detail("IDEMPOTENCY_STORE_UNAVAILABLE", "幂等存储不可用"),
        ) from exc

    try:
        response = response_model.model_validate(operation().model_dump())
    except Exception:
        try:
            store.delete(f"idempotency:{scoped_key}")
        except Exception:
            logger.exception("Failed to release Skill idempotency key: %s", scoped_key)
        raise
    stored = {
        **(
            result_metadata(response)
            if result_metadata is not None
            else response.model_dump(mode="json")
        ),
        "_request_hash": request_hash,
    }
    try:
        store.complete(scoped_key, stored, ttl_seconds=86400)
    except Exception:
        logger.exception("Failed to complete Skill idempotency key: %s", scoped_key)
    return response


def _idempotent_release_id(scope: str, idempotency_key: str) -> str:
    return hashlib.sha256(f"{scope}:{idempotency_key}".encode("utf-8")).hexdigest()[:32]


def _recover_release_status(
    service: SkillGovernanceService,
    *,
    skill_id: str,
    release_id: str,
    status_value: str,
    expected_revision: int,
) -> SkillRelease | None:
    release = service.find_release(skill_id, release_id)
    if (
        release is None
        or release.status.value != status_value
        or release.revision != expected_revision + 1
    ):
        return None
    return release


@router.get("/infra-skills", response_model=list[InfraSkillItem])
def list_infra_skills(
    business_action: str = Query(default="", description="按业务动作筛选（explain/query/guide/verify/compare/evaluate/analyze）"),
    business_object: str = Query(default="", description="按业务对象筛选（settlement/benefit/policy/directory/...）"),
) -> list[InfraSkillItem]:
    loader = get_loader()
    skills = loader.get_all()
    result = []
    for s_id, s in skills.items():
        if business_action and s.business_action != business_action:
            continue
        if business_object and s.business_object != business_object:
            continue
        result.append(
            InfraSkillItem(
                skill_id=s.skill_id,
                skill_name=s.skill_name,
                business_action=s.business_action,
                business_object=s.business_object,
                include_keywords=s.include_keywords,
                excluded_intents=s.excluded_intents,
            )
        )
    return result


@router.get("/infra-skills/catalog", response_model=InfraSkillCatalogResponse)
def list_infra_skill_catalog(
    service: SkillVersionServiceDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    business_action: str = Query(default=""),
    business_object: str = Query(default=""),
    artifact_status: str = Query(default=""),
    query: str = Query(default="", max_length=128),
) -> InfraSkillCatalogResponse:
    catalog = service.list_catalog(
        page=page,
        page_size=page_size,
        business_action=business_action,
        business_object=business_object,
        artifact_status=artifact_status,
        query=query,
    )
    return InfraSkillCatalogResponse.model_validate(catalog.model_dump())


@router.get("/infra-skills/workbench", response_model=SkillWorkbenchResponse)
def get_infra_skill_workbench(
    service: SkillWorkbenchServiceDependency,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    business_action: str = Query(default=""),
    business_object: str = Query(default=""),
    artifact_status: str = Query(default=""),
    governance_status: SkillGovernanceStatus | None = Query(default=None),
    priority: SkillGovernancePriority | None = Query(default=None),
    query: str = Query(default="", max_length=128),
) -> SkillWorkbenchResponse:
    workbench = service.list_workbench(
        page=1 if priority is not None else page,
        page_size=10_000 if priority is not None else page_size,
        business_action=business_action,
        business_object=business_object,
        artifact_status=artifact_status,
        governance_status=governance_status,
        query=query,
    )
    if priority is not None:
        filtered = [item for item in workbench.items if item.priority == priority]
        start = (page - 1) * page_size
        workbench = workbench.model_copy(
            update={
                "items": filtered[start : start + page_size],
                "total": len(filtered),
                "page": page,
                "page_size": page_size,
            }
        )
    return SkillWorkbenchResponse.model_validate(workbench.model_dump())


def _governance_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SkillGovernanceNotFoundError):
        return HTTPException(
            status_code=404,
            detail=error_detail("SKILL_GOVERNANCE_NOT_FOUND", str(exc)),
        )
    if isinstance(exc, SkillGovernanceGateError):
        return HTTPException(
            status_code=409,
            detail=error_detail(
                "SKILL_RELEASE_GATE_FAILED",
                str(exc),
                {"gate_failures": exc.gate_failures},
            ),
        )
    return HTTPException(
        status_code=409,
        detail=error_detail("SKILL_GOVERNANCE_CONFLICT", str(exc)),
    )


@router.get(
    "/infra-skills/eval-cases",
    response_model=SkillEvalCaseListResponse,
)
def list_skill_eval_cases(
    service: SkillGovernanceServiceDependency,
    enabled_only: bool = Query(default=False),
) -> SkillEvalCaseListResponse:
    cases = service.list_cases(enabled_only=enabled_only)
    return SkillEvalCaseListResponse(
        items=[SkillEvalCaseResponse.model_validate(case.model_dump()) for case in cases],
        suite_version=service.current_suite_version(),
        total=len(cases),
    )


@router.post(
    "/infra-skills/eval-cases",
    response_model=SkillEvalCaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_skill_eval_case(
    request: SkillEvalCaseCreateRequest,
    service: SkillGovernanceServiceDependency,
    principal: SkillEvaluationPrincipalDependency,
) -> SkillEvalCaseResponse:
    try:
        case = service.create_case(
            **request.model_dump(), created_by=principal.user_id
        )
    except (
        SkillGovernanceConflictError,
        SkillGovernanceGateError,
        SkillGovernanceNotFoundError,
    ) as exc:
        raise _governance_error(exc) from exc
    return SkillEvalCaseResponse.model_validate(case.model_dump())


@router.put(
    "/infra-skills/eval-cases/{case_id}",
    response_model=SkillEvalCaseResponse,
)
def update_skill_eval_case(
    case_id: str,
    request: SkillEvalCaseUpdateRequest,
    service: SkillGovernanceServiceDependency,
    _principal: SkillEvaluationPrincipalDependency,
) -> SkillEvalCaseResponse:
    try:
        case = service.update_case(case_id, **request.model_dump())
    except (
        SkillGovernanceConflictError,
        SkillGovernanceGateError,
        SkillGovernanceNotFoundError,
    ) as exc:
        raise _governance_error(exc) from exc
    return SkillEvalCaseResponse.model_validate(case.model_dump())


@router.delete(
    "/infra-skills/eval-cases/{case_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_skill_eval_case(
    case_id: str,
    service: SkillGovernanceServiceDependency,
    _principal: SkillEvaluationPrincipalDependency,
) -> None:
    try:
        service.delete_case(case_id)
    except SkillGovernanceNotFoundError as exc:
        raise _governance_error(exc) from exc


@router.post(
    "/infra-skills/eval-cases/dedupe",
    response_model=SkillEvalCaseListResponse,
)
def dedupe_skill_eval_cases(
    service: SkillGovernanceServiceDependency,
    _principal: SkillEvaluationPrincipalDependency,
) -> SkillEvalCaseListResponse:
    service.dedupe_cases()
    cases = service.list_cases()
    return SkillEvalCaseListResponse(
        items=[SkillEvalCaseResponse.model_validate(case.model_dump()) for case in cases],
        suite_version=service.current_suite_version(),
        total=len(cases),
    )


@router.post(
    "/infra-skills/eval-cases/seed-golden",
    response_model=SkillEvalCaseListResponse,
)
def seed_golden_skill_eval_cases(
    service: SkillGovernanceServiceDependency,
    _principal: SkillEvaluationPrincipalDependency,
) -> SkillEvalCaseListResponse:
    """灌入预置黄金 routing 用例（幂等：自动去重）。"""
    service.seed_golden_cases()
    cases = service.list_cases()
    return SkillEvalCaseListResponse(
        items=[SkillEvalCaseResponse.model_validate(case.model_dump()) for case in cases],
        suite_version=service.current_suite_version(),
        total=len(cases),
    )


@router.get(
    "/infra-skills/eval-runs",
    response_model=SkillEvalRunListResponse,
)
def list_all_skill_eval_runs(
    service: SkillGovernanceServiceDependency,
    skill_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> SkillEvalRunListResponse:
    """跨 Skill 汇总评测运行（评测中心首页）。可选 skill_id 过滤。"""
    runs = service.list_eval_runs(skill_id)[:limit]
    return SkillEvalRunListResponse(
        items=[SkillEvalRunResponse.model_validate(run.model_dump()) for run in runs],
        total=len(runs),
    )


@router.get(
    "/infra-skills/{skill_id}/eval-runs",
    response_model=SkillEvalRunListResponse,
)
def list_skill_eval_runs(
    skill_id: str,
    service: SkillGovernanceServiceDependency,
) -> SkillEvalRunListResponse:
    runs = service.list_eval_runs(skill_id)
    return SkillEvalRunListResponse(
        items=[SkillEvalRunResponse.model_validate(run.model_dump()) for run in runs],
        total=len(runs),
    )


@router.post(
    "/infra-skills/{skill_id}/eval-runs",
    response_model=SkillEvalRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_skill_eval_run(
    skill_id: str,
    request: SkillEvalRunCreateRequest,
    service: SkillGovernanceServiceDependency,
    principal: SkillEvaluationPrincipalDependency,
) -> SkillEvalRunResponse:
    try:
        run = service.create_eval_run(
            skill_id, **request.model_dump(), created_by=principal.user_id
        )
    except (
        SkillGovernanceConflictError,
        SkillGovernanceGateError,
        SkillGovernanceNotFoundError,
    ) as exc:
        raise _governance_error(exc) from exc
    return SkillEvalRunResponse.model_validate(run.model_dump())


@router.get(
    "/infra-skills/{skill_id}/eval-runs/{run_id}",
    response_model=SkillEvalRunResponse,
)
def get_skill_eval_run(
    skill_id: str,
    run_id: str,
    service: SkillGovernanceServiceDependency,
) -> SkillEvalRunResponse:
    try:
        run = service.get_eval_run(skill_id, run_id)
    except SkillGovernanceNotFoundError as exc:
        raise _governance_error(exc) from exc
    return SkillEvalRunResponse.model_validate(run.model_dump())


@router.get(
    "/infra-skills/{skill_id}/releases",
    response_model=SkillReleaseListResponse,
)
def list_skill_releases(
    skill_id: str,
    service: SkillGovernanceServiceDependency,
    environment: str | None = Query(default=None, pattern=r"^(dev|test)$"),
) -> SkillReleaseListResponse:
    releases = service.list_releases(skill_id, environment)
    return SkillReleaseListResponse(
        items=[_release_response(service, item) for item in releases],
        total=len(releases),
    )


def _release_response(
    service: SkillGovernanceService,
    release: SkillRelease | SkillReleaseResponse,
) -> SkillReleaseResponse:
    approval = service.get_release_approval(release.release_id)
    payload = release.model_dump()
    if approval is not None:
        payload["approval"] = SkillReleaseApprovalSummaryResponse(
            approved_by=approval.approved_by,
            approver_role=approval.approver_role,
            approved_at=approval.approved_at,
        )
    return SkillReleaseResponse.model_validate(payload)


@router.post(
    "/infra-skills/{skill_id}/releases",
    response_model=SkillReleaseResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_skill_release(
    skill_id: str,
    request: SkillReleaseCreateRequest,
    service: SkillGovernanceServiceDependency,
    principal: SkillControlPrincipalDependency,
    idempotency_key: IdempotencyKey,
    idempotency_store: SkillIdempotencyStoreDependency,
) -> SkillReleaseResponse:
    scope = f"{skill_id}:candidate"
    release_id = _idempotent_release_id(scope, idempotency_key)
    try:
        release = _idempotent_mutation(
            store=idempotency_store,
            scope=scope,
            idempotency_key=idempotency_key,
            request_payload={
                **request.model_dump(mode="json"),
                "created_by": principal.user_id,
            },
            response_model=SkillReleaseResponse,
            operation=lambda: service.create_candidate(
                skill_id,
                **request.model_dump(),
                created_by=principal.user_id,
                release_id=release_id,
            ),
            recovery=lambda: service.create_candidate(
                skill_id,
                **request.model_dump(),
                created_by=principal.user_id,
                release_id=release_id,
            ),
        )
        return _release_response(service, release)
    except (
        SkillGovernanceConflictError,
        SkillGovernanceGateError,
        SkillGovernanceNotFoundError,
    ) as exc:
        raise _governance_error(exc) from exc


@router.post(
    "/infra-skills/{skill_id}/releases/{release_id}/request-approval",
    response_model=SkillReleaseResponse,
)
def request_skill_release_approval(
    skill_id: str,
    release_id: str,
    request: SkillReleaseTransitionRequest,
    service: SkillGovernanceServiceDependency,
    _principal: SkillControlPrincipalDependency,
    idempotency_key: IdempotencyKey,
    idempotency_store: SkillIdempotencyStoreDependency,
) -> SkillReleaseResponse:
    try:
        release = _idempotent_mutation(
            store=idempotency_store,
            scope=f"{skill_id}:{release_id}:request-approval",
            idempotency_key=idempotency_key,
            request_payload=request.model_dump(mode="json"),
            response_model=SkillReleaseResponse,
            operation=lambda: service.request_approval(
                skill_id, release_id, expected_revision=request.expected_revision
            ),
            recovery=lambda: _recover_release_status(
                service,
                skill_id=skill_id,
                release_id=release_id,
                status_value="approval_pending",
                expected_revision=request.expected_revision,
            ),
        )
        return _release_response(service, release)
    except (
        SkillGovernanceConflictError,
        SkillGovernanceGateError,
        SkillGovernanceNotFoundError,
    ) as exc:
        raise _governance_error(exc) from exc


@router.post(
    "/infra-skills/{skill_id}/releases/{release_id}/approve",
    response_model=SkillReleaseResponse,
)
def approve_skill_release(
    skill_id: str,
    release_id: str,
    request: SkillReleaseApproveRequest,
    service: SkillGovernanceServiceDependency,
    principal: SkillApprovalPrincipalDependency,
    idempotency_key: IdempotencyKey,
    idempotency_store: SkillIdempotencyStoreDependency,
) -> SkillReleaseResponse:
    try:
        release = _idempotent_mutation(
            store=idempotency_store,
            scope=f"{skill_id}:{release_id}:approve",
            idempotency_key=idempotency_key,
            request_payload={
                **request.model_dump(mode="json"),
                "approved_by": principal.user_id,
            },
            response_model=SkillReleaseResponse,
            operation=lambda: service.approve_release(
                skill_id,
                release_id,
                expected_revision=request.expected_revision,
                approved_by=principal.user_id,
                approver_role="information_department",
                reason=request.reason,
            ),
            recovery=lambda: _recover_release_status(
                service,
                skill_id=skill_id,
                release_id=release_id,
                status_value="approved",
                expected_revision=request.expected_revision,
            ),
        )
        return _release_response(service, release)
    except (
        SkillGovernanceConflictError,
        SkillGovernanceGateError,
        SkillGovernanceNotFoundError,
    ) as exc:
        raise _governance_error(exc) from exc


@router.post(
    "/infra-skills/{skill_id}/releases/{release_id}/activate",
    response_model=SkillReleaseResponse,
)
def activate_skill_release(
    skill_id: str,
    release_id: str,
    request: SkillReleaseTransitionRequest,
    service: SkillGovernanceServiceDependency,
    _principal: SkillControlPrincipalDependency,
    idempotency_key: IdempotencyKey,
    idempotency_store: SkillIdempotencyStoreDependency,
) -> SkillReleaseResponse:
    try:
        release = _idempotent_mutation(
            store=idempotency_store,
            scope=f"{skill_id}:{release_id}:activate",
            idempotency_key=idempotency_key,
            request_payload=request.model_dump(mode="json"),
            response_model=SkillReleaseResponse,
            operation=lambda: service.activate_release(
                skill_id, release_id, expected_revision=request.expected_revision
            ),
            recovery=lambda: _recover_release_status(
                service,
                skill_id=skill_id,
                release_id=release_id,
                status_value="active",
                expected_revision=request.expected_revision,
            ),
        )
        return _release_response(service, release)
    except (
        SkillGovernanceConflictError,
        SkillGovernanceGateError,
        SkillGovernanceNotFoundError,
    ) as exc:
        raise _governance_error(exc) from exc


def _list_files_in_dir(base_dir: Path, sub_dir: str) -> list[str]:
    target_dir = base_dir / sub_dir
    if not target_dir.exists() or not target_dir.is_dir():
        return []
    
    files = []
    for item in target_dir.iterdir():
        if item.name.startswith("__"):
            continue
        if item.is_dir():
            files.append(f"{item.name}/")
        else:
            files.append(item.name)
    return sorted(files)


def _read_field_mapping(skill_dir: Path) -> FieldMappingResponse | None:
    """读取技能包的 field_mapping.yaml，返回结构化字段映射数据。"""
    field_mapping_path = skill_dir / "field_mapping.yaml"
    if not field_mapping_path.exists():
        return None

    try:
        raw = yaml.safe_load(field_mapping_path.read_text(encoding="utf-8"))
        if not raw:
            return None

        target_field = raw.get("target_field", {})

        settlement_fields: dict[str, FieldMappingItem] = {}
        raw_settlement = raw.get("settlement_fields", {})
        if isinstance(raw_settlement, dict):
            for field_name, field_data in raw_settlement.items():
                if isinstance(field_data, dict):
                    settlement_fields[field_name] = FieldMappingItem(
                        label=field_data.get("label", ""),
                        description=field_data.get("description", ""),
                        db_source=field_data.get("db_source", ""),
                    )

        defaults = raw.get("defaults", {})

        return FieldMappingResponse(
            target_field=target_field,
            settlement_fields=settlement_fields,
            defaults=defaults,
        )
    except Exception:
        logger.exception("Failed to parse field_mapping.yaml for skill: %s", skill_dir.name)
        return None





# ── Skill 草稿管理（P1+）──────────────────────────────────────────


def get_skill_materializer() -> "SkillMaterializer":
    from src.data_platform.storage.skill.draft_factory import (
        get_skill_draft_storage,
    )
    from src.runtime.skill_management.materializer import SkillMaterializer
    from src.skill_infra.skill_loader import get_loader

    draft_storage = get_skill_draft_storage()
    return SkillMaterializer(
        draft_service=get_skill_draft_service(),
        draft_storage=draft_storage,
        version_service=get_skill_version_service(),
        skills_root=SKILLS_DIR,
        loader=get_loader(),
    )


SkillMaterializerDependency = Annotated[
    "SkillMaterializer", Depends(get_skill_materializer)
]


def get_skill_lifecycle_service() -> "SkillLifecycleService":
    from src.data_platform.storage.skill.draft_factory import (
        get_skill_draft_storage,
    )
    from src.runtime.skill_management.lifecycle_service import SkillLifecycleService

    return SkillLifecycleService(
        definition_storage=get_skill_draft_storage(),
        governance_service=get_skill_governance_service(),
    )


SkillLifecycleServiceDependency = Annotated[
    "SkillLifecycleService", Depends(get_skill_lifecycle_service)
]


def get_skill_draft_validator() -> SkillDraftValidator:
    return SkillDraftValidator()


SkillDraftValidatorDependency = Annotated[
    SkillDraftValidator, Depends(get_skill_draft_validator)
]


def get_skill_package_generator() -> SkillPackageGenerator:
    return SkillPackageGenerator()


SkillPackageGeneratorDependency = Annotated[
    SkillPackageGenerator, Depends(get_skill_package_generator)
]


def get_skill_candidate_evaluation_service(
    generator: SkillPackageGeneratorDependency,
) -> SkillCandidateEvaluationService:
    executor: CandidateExecutionPort = DisabledCandidateExecutionAdapter(
        "sandbox_unavailable"
    )
    if SKILL_CANDIDATE_SANDBOX_ENABLED:
        from src.runtime.skill_management.ai_authoring.candidate_execution_docker import (
            DockerCandidateExecutionAdapter,
        )

        executor = DockerCandidateExecutionAdapter(
            image=SKILL_CANDIDATE_RUNNER_IMAGE,
            timeout_seconds=SKILL_CANDIDATE_TIMEOUT_SECONDS,
            memory_limit=SKILL_CANDIDATE_MEMORY_LIMIT,
            cpu_limit=SKILL_CANDIDATE_CPU_LIMIT,
            pids_limit=SKILL_CANDIDATE_PIDS_LIMIT,
        )
    return SkillCandidateEvaluationService(
        package_generator=generator,
        candidate_root=SKILL_CANDIDATE_ROOT,
        runtime_skills_root=SKILLS_DIR,
        executor=executor,
    )


SkillCandidateEvaluationServiceDependency = Annotated[
    SkillCandidateEvaluationService,
    Depends(get_skill_candidate_evaluation_service),
]


def get_skill_ai_authoring_service() -> SkillAIAuthoringService:
    """AI 编写服务组装点；模型与指标注册表均显式注入。"""

    from src.model_service.gateway import ModelGateway
    from src.runtime.skill_management.skill_input_service import SkillInputService
    from src.semantic_layer.registry import get_semantic_registry

    registry = get_semantic_registry()
    return SkillAIAuthoringService(
        gateway=ModelGateway(),
        input_service=SkillInputService(registry),
        metric_registry=registry,
    )


SkillAIAuthoringServiceDependency = Annotated[
    SkillAIAuthoringService, Depends(get_skill_ai_authoring_service)
]

_AI_EVIDENCE_NAMESPACE = "skill-ai-authoring"
_AI_EVIDENCE_TTL_SECONDS = 15 * 60


def _ai_authoring_error(exc: SkillAIAuthoringError) -> HTTPException:
    if isinstance(exc, SkillAIModelError):
        status_code = 503 if exc.category in {
            "timeout",
            "rate_limit",
            "exhausted",
        } else 502
        return HTTPException(
            status_code=status_code,
            detail=error_detail(
                "SKILL_AI_MODEL_FAILED",
                "Skill AI 模型生成失败",
                {"category": exc.category, "error_hash": exc.error_hash},
            ),
        )
    if isinstance(exc, SkillAISecurityRejectedError):
        return HTTPException(
            status_code=422,
            detail=error_detail(
                "SKILL_AI_SECURITY_REJECTED",
                str(exc),
                {
                    "issues": [
                        {
                            "code": issue.code,
                            "message": issue.message,
                            "path": issue.path,
                        }
                        for issue in exc.issues
                    ]
                },
            ),
        )
    if isinstance(exc, SkillAIMetricNotFoundError):
        code = "SKILL_AI_METRIC_NOT_FOUND"
    elif isinstance(exc, SkillAIMetricNotPublishedError):
        code = "SKILL_AI_METRIC_NOT_PUBLISHED"
    elif isinstance(exc, SkillAIInputInvalidError):
        code = "SKILL_AI_INPUT_INVALID"
    else:
        code = "SKILL_AI_OUTPUT_INVALID"
    return HTTPException(status_code=422, detail=error_detail(code, str(exc)))


def _skill_ai_metric_reason(exc: SkillAIAuthoringError) -> str:
    if isinstance(exc, SkillAISecurityRejectedError):
        return "unsafe_code"
    if isinstance(exc, SkillAIOutputInvalidError):
        return exc.reason_code
    if isinstance(exc, SkillAIInputInvalidError):
        return "input_invalid"
    if isinstance(exc, SkillAIMetricNotFoundError):
        return "metric_not_found"
    if isinstance(exc, SkillAIMetricNotPublishedError):
        return "metric_not_published"
    if isinstance(exc, SkillAIRevisionConflictError):
        return "revision_conflict"
    if isinstance(exc, SkillAIModelError):
        return "model_error"
    return "other"


@router.post(
    "/infra-skills/ai-generate",
    response_model=SkillAIGenerationResponse,
)
def generate_skill_ai_proposal(
    request: SkillAIGenerateRequest,
    service: SkillAIAuthoringServiceDependency,
    _principal: SkillControlPrincipalDependency,
    evidence_store: SkillIdempotencyStoreDependency,
) -> SkillAIGenerationResponse:
    observability_metrics.record_skill_ai_generation_started()
    try:
        generated = service.generate_with_evidence(request)
        proposal = generated.proposal
        evidence_store.save_state(
            _AI_EVIDENCE_NAMESPACE,
            proposal.generation_id,
            {
                "proposal": proposal.model_dump(mode="json"),
                "metric_snapshot_hash": generated.metric_snapshot_hash,
            },
            _AI_EVIDENCE_TTL_SECONDS,
        )
        observability_metrics.record_skill_ai_generation_success()
        return proposal
    except SkillAIAuthoringError as exc:
        observability_metrics.record_skill_ai_generation_rejected(
            _skill_ai_metric_reason(exc)
        )
        raise _ai_authoring_error(exc) from exc
    except Exception as exc:
        observability_metrics.record_skill_ai_generation_rejected(
            "evidence_unavailable"
        )
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "SKILL_AI_EVIDENCE_STORE_UNAVAILABLE", "AI proposal 证据存储不可用"
            ),
        ) from exc


@router.post(
    "/infra-skills/drafts/{draft_id}/ai-optimize",
    response_model=SkillAIOptimizationResponse,
)
def optimize_skill_ai_draft(
    draft_id: str,
    request: SkillAIOptimizeRequest,
    authoring_service: SkillAIAuthoringServiceDependency,
    draft_service: SkillDraftServiceDependency,
    _principal: SkillControlPrincipalDependency,
) -> SkillAIOptimizationResponse:
    draft = draft_service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", f"草稿不存在: {draft_id}"),
        )
    if request.expected_revision != draft.revision:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "SKILL_DRAFT_CONFLICT",
                f"草稿 revision 冲突: expected={request.expected_revision}, actual={draft.revision}",
            ),
        )
    observability_metrics.record_skill_ai_generation_started()
    try:
        proposal = authoring_service.optimize(draft, request)
        observability_metrics.record_skill_ai_generation_success()
        return proposal
    except SkillAIRevisionConflictError as exc:
        observability_metrics.record_skill_ai_generation_rejected(
            "revision_conflict"
        )
        raise HTTPException(
            status_code=409,
            detail=error_detail("SKILL_DRAFT_CONFLICT", str(exc)),
        ) from exc
    except SkillAIAuthoringError as exc:
        observability_metrics.record_skill_ai_generation_rejected(
            _skill_ai_metric_reason(exc)
        )
        raise _ai_authoring_error(exc) from exc


def _ai_evidence_conflict(message: str, *, code: str) -> HTTPException:
    return HTTPException(status_code=409, detail=error_detail(code, message))


@router.post(
    "/infra-skills/drafts/from-ai",
    response_model=SkillDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def accept_skill_ai_proposal(
    request: SkillAIAcceptRequest,
    authoring_service: SkillAIAuthoringServiceDependency,
    draft_service: SkillDraftServiceDependency,
    principal: SkillControlPrincipalDependency,
    idempotency_key: IdempotencyKey,
    evidence_store: SkillIdempotencyStoreDependency,
) -> SkillDraftResponse:
    canonical_client = json.dumps(
        {
            "structured_config": request.structured_config.model_dump(mode="json"),
            "raw_files": request.raw_files,
            "provenance": (
                request.provenance.model_dump(mode="json")
                if request.provenance is not None
                else None
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(canonical_client.encode("utf-8")).hexdigest()
    scope = f"ai-draft:{request.generation_id}"
    draft_id = draft_service.ai_draft_id(request.generation_id)

    def create_first_draft() -> SkillDraftResponse:
        try:
            state = evidence_store.load_state(
                _AI_EVIDENCE_NAMESPACE, request.generation_id
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=error_detail(
                    "SKILL_AI_EVIDENCE_STORE_UNAVAILABLE",
                    "AI proposal 证据存储不可用",
                ),
            ) from exc
        if state is None or not isinstance(state.get("proposal"), dict):
            raise _ai_evidence_conflict(
                "AI proposal 证据已过期或不存在",
                code="SKILL_AI_EVIDENCE_INVALID",
            )
        metric_snapshot_hash = state.get("metric_snapshot_hash")
        if not isinstance(metric_snapshot_hash, str) or len(metric_snapshot_hash) != 64:
            raise _ai_evidence_conflict(
                "AI proposal 服务端证据无效",
                code="SKILL_AI_EVIDENCE_INVALID",
            )
        try:
            proposal = SkillAIGenerationResponse.model_validate(state["proposal"])
        except (ValidationError, ValueError) as exc:
            raise _ai_evidence_conflict(
                "AI proposal 服务端证据无效",
                code="SKILL_AI_EVIDENCE_INVALID",
            ) from exc

        request_provenance = (
            request.provenance.model_dump(mode="json")
            if request.provenance is not None
            else proposal.provenance.model_dump(mode="json")
        )
        basic = proposal.structured_config.basic
        if (
            request.proposal_hash != proposal.proposal_hash
            or request.skill_id != basic.skill_id
            or request.skill_name != basic.skill_name
            or request.structured_config.model_dump(mode="json")
            != proposal.structured_config.model_dump(mode="json")
            or request.raw_files != dict(proposal.raw_files)
            or request_provenance != proposal.provenance.model_dump(mode="json")
        ):
            raise _ai_evidence_conflict(
                "客户端 proposal 与服务端证据不一致",
                code="SKILL_AI_EVIDENCE_CONFLICT",
            )
        try:
            authoring_service.verify_for_accept(
                proposal,
                metric_snapshot_hash=metric_snapshot_hash,
            )
        except (SkillAIMetricNotFoundError, SkillAIMetricNotPublishedError) as exc:
            raise _ai_evidence_conflict(
                str(exc), code="SKILL_AI_EVIDENCE_STALE"
            ) from exc
        except (SkillAIOutputInvalidError, SkillAISecurityRejectedError) as exc:
            raise _ai_evidence_conflict(
                str(exc), code="SKILL_AI_EVIDENCE_CONFLICT"
            ) from exc
        created = draft_service.create_from_ai(
            proposal=proposal,
            created_by=principal.user_id,
            draft_id=draft_id,
        )
        observability_metrics.record_skill_ai_manual_accept()
        return created

    try:
        return _idempotent_mutation(
            store=evidence_store,
            scope=scope,
            idempotency_key=idempotency_key,
            request_payload={
                "generation_id": request.generation_id,
                "proposal_hash": request.proposal_hash,
                "content_hash": content_hash,
                "created_by": principal.user_id,
            },
            response_model=SkillDraftResponse,
            operation=create_first_draft,
            recovery=lambda: draft_service.get_draft(draft_id),
            result_metadata=lambda response: {"draft_id": response.draft_id},
            replay=lambda stored: draft_service.get_draft(
                str(stored.get("draft_id", ""))
            ),
        )
    except SkillDraftConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail("SKILL_DRAFT_CONFLICT", str(exc)),
        ) from exc


@router.post(
    "/infra-skills/drafts",
    response_model=SkillDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_skill_draft(
    request: SkillDraftCreateRequest,
    service: SkillDraftServiceDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillDraftResponse:
    try:
        draft = service.create_from_template(
            skill_id=request.skill_id,
            skill_name=request.skill_name,
            created_by=principal.user_id,
            description=request.description,
            owner=request.owner,
            business_action=request.business_action,
            business_object=request.business_object,
            include_keywords=request.include_keywords,
            excluded_intents=request.excluded_intents,
        )
    except SkillDraftConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail("SKILL_DRAFT_CONFLICT", str(exc)),
        ) from exc
    return SkillDraftResponse.from_model(draft)


@router.post(
    "/infra-skills/drafts/import",
    response_model=SkillDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_skill_draft(
    request: Request,
    principal: SkillControlPrincipalDependency,
    draft_service: SkillDraftServiceDependency,
    source: str = Query(default="zip", pattern=r"^(zip|git|dir)$"),
    git_url: str = Query(default=""),
    dir_path: str = Query(default=""),
) -> SkillDraftResponse:
    from src.runtime.skill_management.import_service import (
        SkillImportError,
        SkillImportService,
    )

    service = SkillImportService(draft_service=draft_service)
    try:
        if source == "zip":
            upload = await request.body()
            draft = service.import_from_zip(
                upload_bytes=upload,
                filename=request.headers.get("filename", "upload.zip"),
                created_by=principal.user_id,
            )
        elif source == "git":
            if not git_url:
                raise HTTPException(
                    status_code=422,
                    detail=error_detail("MISSING_GIT_URL", "git 导入需要 git_url 参数"),
                )
            draft = service.import_from_git(
                url=git_url, created_by=principal.user_id
            )
        else:
            if not dir_path:
                raise HTTPException(
                    status_code=422,
                    detail=error_detail("MISSING_DIR_PATH", "dir 导入需要 dir_path 参数"),
                )
            draft = service.import_from_controlled_dir(
                relative_path=dir_path, created_by=principal.user_id
            )
    except SkillImportError as exc:
        raise HTTPException(
            status_code=422,
            detail=error_detail("SKILL_IMPORT_REJECTED", str(exc)),
        ) from exc
    return SkillDraftResponse.from_model(draft)


@router.post(
    "/infra-skills/{skill_id}/copy",
    response_model=SkillDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
def copy_skill_to_draft(
    skill_id: str,
    request: SkillDraftCopyRequest,
    service: SkillDraftServiceDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillDraftResponse:
    try:
        draft = service.copy_skill(
            source_skill_id=skill_id,
            new_skill_id=request.new_skill_id,
            created_by=principal.user_id,
        )
    except SkillDraftNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_SOURCE_NOT_FOUND", str(exc)),
        ) from exc
    except SkillDraftConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail("SKILL_DRAFT_CONFLICT", str(exc)),
        ) from exc
    return SkillDraftResponse.from_model(draft)


@router.get("/infra-skills/drafts", response_model=SkillDraftListResponse)
def list_skill_drafts(
    service: SkillDraftServiceDependency,
    include_deleted: bool = Query(default=False),
    skill_id: str = Query(default=""),
    status_filter: str = Query(default="", alias="status"),
) -> SkillDraftListResponse:
    from src.domain.skill.draft_models import SkillDraftStatus

    status_enum = None
    if status_filter:
        try:
            status_enum = SkillDraftStatus(status_filter)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=error_detail(
                    "INVALID_STATUS", f"非法草稿状态: {status_filter}"
                ),
            )
    drafts = service.list_drafts(
        include_deleted=include_deleted,
        skill_id=skill_id or None,
        status=status_enum,
    )
    return SkillDraftListResponse(
        items=[SkillDraftResponse.from_model(d) for d in drafts],
        total=len(drafts),
    )


@router.get(
    "/infra-skills/drafts/{draft_id}", response_model=SkillDraftResponse
)
def get_skill_draft(
    draft_id: str,
    service: SkillDraftServiceDependency,
) -> SkillDraftResponse:
    draft = service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", f"草稿不存在: {draft_id}"),
        )
    return SkillDraftResponse.from_model(draft)


@router.patch(
    "/infra-skills/drafts/{draft_id}", response_model=SkillDraftResponse
)
def save_skill_draft(
    draft_id: str,
    request: SkillDraftSaveRequest,
    service: SkillDraftServiceDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillDraftResponse:
    from src.domain.skill.draft_models import SkillDraftStatus

    status_enum = None
    if request.status:
        try:
            status_enum = SkillDraftStatus(request.status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=error_detail(
                    "INVALID_STATUS", f"非法草稿状态: {request.status}"
                ),
            )
    try:
        draft = service.save_draft(
            draft_id=draft_id,
            structured_config=request.structured_config,
            expected_revision=request.expected_revision,
            raw_files=request.raw_files,
            status=status_enum,
        )
    except SkillDraftNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", str(exc)),
        ) from exc
    except SkillDraftConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail("SKILL_DRAFT_CONFLICT", str(exc)),
        ) from exc
    return SkillDraftResponse.from_model(draft)


@router.delete(
    "/infra-skills/drafts/{draft_id}", response_model=SkillDraftResponse
)
def delete_skill_draft(
    draft_id: str,
    service: SkillDraftServiceDependency,
    principal: SkillControlPrincipalDependency,
    expected_revision: int = Query(..., ge=1, alias="expected_revision"),
) -> SkillDraftResponse:
    try:
        draft = service.delete_draft(
            draft_id=draft_id, expected_revision=expected_revision
        )
    except SkillDraftNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", str(exc)),
        ) from exc
    except SkillDraftConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail("SKILL_DRAFT_CONFLICT", str(exc)),
        ) from exc
    return SkillDraftResponse.from_model(draft)


@router.post(
    "/infra-skills/drafts/{draft_id}/validate",
    response_model=SkillDraftValidationResponse,
)
def validate_skill_draft(
    draft_id: str,
    service: SkillDraftServiceDependency,
    validator: SkillDraftValidatorDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillDraftValidationResponse:
    draft = service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", f"草稿不存在: {draft_id}"),
        )
    report = validator.validate(draft)
    # 记录校验结果到草稿（状态随 blocking_ok 推进）
    updated = service.record_validation(
        draft_id=draft_id,
        validation_report=report.model_dump(mode="json"),
        expected_revision=draft.revision,
        blocking_ok=report.blocking_ok,
    )
    return SkillDraftValidationResponse(
        draft_id=draft_id,
        issues=[
            SkillValidationIssueResponse(**issue.model_dump())
            for issue in report.issues
        ],
        has_blocking=report.has_blocking,
        blocking_ok=report.blocking_ok,
        revision=updated.revision,
    )


@router.get(
    "/infra-skills/drafts/{draft_id}/package-preview",
    response_model=SkillPackagePreviewResponse,
)
def preview_skill_draft_package(
    draft_id: str,
    service: SkillDraftServiceDependency,
    generator: SkillPackageGeneratorDependency,
) -> SkillPackagePreviewResponse:
    draft = service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", f"草稿不存在: {draft_id}"),
        )
    package = generator.generate(draft)
    return SkillPackagePreviewResponse(
        draft_id=draft_id,
        files=[
            SkillPackageFileResponse(path=p, content=c)
            for p, c in package.files.items()
        ],
        file_count=len(package.files),
        revision=draft.revision,
    )


def _candidate_case_selection[T](
    cases: list[T], case_ids: list[str]
) -> list[T]:
    by_id = {getattr(case, "case_id"): case for case in cases}
    if case_ids:
        unknown = sorted(set(case_ids).difference(by_id))
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=error_detail(
                    "SKILL_CANDIDATE_CASE_NOT_FOUND",
                    f"候选评测用例不存在: {', '.join(unknown)}",
                ),
            )
        selected = [by_id[case_id] for case_id in dict.fromkeys(case_ids)]
    else:
        selected = list(cases)
    if not selected:
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                "SKILL_CANDIDATE_CASES_EMPTY", "没有可执行的候选评测用例"
            ),
        )
    return selected


@router.post(
    "/infra-skills/drafts/{draft_id}/candidate-evaluations/routes",
    response_model=SkillCandidateRouteEvaluationResponse,
)
def evaluate_skill_candidate_routes(
    draft_id: str,
    request: SkillCandidateEvaluationRequest,
    draft_service: SkillDraftServiceDependency,
    governance_service: SkillGovernanceServiceDependency,
    candidate_service: SkillCandidateEvaluationServiceDependency,
    principal: SkillEvaluationPrincipalDependency,
) -> SkillCandidateRouteEvaluationResponse:
    del principal
    draft = draft_service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", f"草稿不存在: {draft_id}"),
        )
    cases = _candidate_case_selection(
        governance_service.list_cases(enabled_only=True), request.case_ids
    )
    try:
        result = candidate_service.evaluate_routes(draft, cases)
    except SkillCandidateArtifactError as exc:
        raise HTTPException(
            status_code=422,
            detail=error_detail("SKILL_CANDIDATE_REJECTED", str(exc)),
        ) from exc
    return SkillCandidateRouteEvaluationResponse.model_validate(
        result.model_dump(mode="json")
    )


@router.post(
    "/infra-skills/drafts/{draft_id}/candidate-evaluations/behavior",
    response_model=SkillCandidateBehaviorEvaluationResponse,
)
def evaluate_skill_candidate_behavior(
    draft_id: str,
    request: SkillCandidateEvaluationRequest,
    draft_service: SkillDraftServiceDependency,
    regression_storage: SkillRegressionStorageDependency,
    candidate_service: SkillCandidateEvaluationServiceDependency,
    principal: SkillEvaluationPrincipalDependency,
) -> SkillCandidateBehaviorEvaluationResponse:
    del principal
    draft = draft_service.get_draft(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_DRAFT_NOT_FOUND", f"草稿不存在: {draft_id}"),
        )
    cases = _candidate_case_selection(
        regression_storage.list_cases(
            target_skill_id=draft.skill_id, enabled_only=True
        ),
        request.case_ids,
    )
    try:
        result = candidate_service.evaluate_behavior(draft, cases)
    except SkillCandidateArtifactError as exc:
        raise HTTPException(
            status_code=422,
            detail=error_detail("SKILL_CANDIDATE_REJECTED", str(exc)),
        ) from exc
    return SkillCandidateBehaviorEvaluationResponse.model_validate(
        result.model_dump(mode="json")
    )


@router.post(
    "/infra-skills/drafts/{draft_id}/materialize",
    response_model=SkillMaterializeResponse,
    status_code=status.HTTP_201_CREATED,
)
def materialize_skill_draft(
    draft_id: str,
    request: SkillMaterializeRequest,
    materializer: SkillMaterializerDependency,
    service: SkillDraftServiceDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillMaterializeResponse:
    from src.runtime.skill_management.materializer import SkillMaterializeError

    try:
        result = materializer.materialize(
            draft_id=draft_id,
            expected_revision=request.expected_revision,
            created_by=principal.user_id,
            reason=request.reason,
            source_commit=request.source_commit,
        )
    except SkillMaterializeError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail("SKILL_MATERIALIZE_FAILED", str(exc)),
        ) from exc
    updated_draft = service.get_draft(draft_id)
    return SkillMaterializeResponse(
        skill_id=result.skill_id,
        version_id=result.version_id,
        semantic_version=result.semantic_version,
        lifecycle_status=result.definition.lifecycle_status.value,
        artifact_written=result.artifact_written,
        draft_revision=updated_draft.revision if updated_draft else 0,
    )


@router.get(
    "/infra-skills/definitions/{skill_id}",
    response_model=SkillDefinitionResponse,
)
def get_skill_definition(
    skill_id: str,
    service: SkillLifecycleServiceDependency,
) -> SkillDefinitionResponse:
    from src.data_platform.storage.skill.draft_ports import (
        SkillDefinitionNotFoundError,
    )
    try:
        definition = service._storage.get_definition(skill_id)  # noqa: SLF001
    except SkillDefinitionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=error_detail("SKILL_DEFINITION_NOT_FOUND", str(exc))) from exc
    if definition is None:
        raise HTTPException(status_code=404, detail=error_detail("SKILL_DEFINITION_NOT_FOUND", f"定义不存在: {skill_id}"))
    return SkillDefinitionResponse.from_model(definition)


@router.post(
    "/infra-skills/{skill_id}/disable",
    response_model=SkillDefinitionResponse,
)
def disable_skill(
    skill_id: str,
    request: SkillLifecycleTransitionRequest,
    service: SkillLifecycleServiceDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillDefinitionResponse:
    from src.data_platform.storage.skill.draft_ports import (
        SkillDefinitionNotFoundError,
    )
    from src.runtime.skill_management.lifecycle_service import SkillLifecycleError
    try:
        definition = service.disable(
            skill_id=skill_id,
            reason=request.reason,
            actor=principal.user_id,
            expected_revision=request.expected_revision,
        )
    except SkillDefinitionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=error_detail("SKILL_DEFINITION_NOT_FOUND", str(exc))) from exc
    except SkillLifecycleError as exc:
        raise HTTPException(status_code=409, detail=error_detail("SKILL_LIFECYCLE_CONFLICT", str(exc))) from exc
    return SkillDefinitionResponse.from_model(definition)


@router.post(
    "/infra-skills/{skill_id}/restore",
    response_model=SkillDefinitionResponse,
)
def restore_skill(
    skill_id: str,
    request: SkillLifecycleTransitionRequest,
    service: SkillLifecycleServiceDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillDefinitionResponse:
    from src.data_platform.storage.skill.draft_ports import (
        SkillDefinitionNotFoundError,
    )
    from src.runtime.skill_management.lifecycle_service import SkillLifecycleError
    try:
        definition = service.restore(
            skill_id=skill_id,
            reason=request.reason,
            actor=principal.user_id,
            expected_revision=request.expected_revision,
        )
    except SkillDefinitionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=error_detail("SKILL_DEFINITION_NOT_FOUND", str(exc))) from exc
    except SkillLifecycleError as exc:
        raise HTTPException(status_code=409, detail=error_detail("SKILL_LIFECYCLE_CONFLICT", str(exc))) from exc
    return SkillDefinitionResponse.from_model(definition)


@router.post(
    "/infra-skills/{skill_id}/archive",
    response_model=SkillDefinitionResponse,
)
def archive_skill(
    skill_id: str,
    request: SkillLifecycleTransitionRequest,
    service: SkillLifecycleServiceDependency,
    principal: SkillControlPrincipalDependency,
) -> SkillDefinitionResponse:
    from src.data_platform.storage.skill.draft_ports import (
        SkillDefinitionNotFoundError,
    )
    from src.runtime.skill_management.lifecycle_service import SkillLifecycleError
    try:
        definition = service.archive(
            skill_id=skill_id,
            reason=request.reason,
            actor=principal.user_id,
            expected_revision=request.expected_revision,
        )
    except SkillDefinitionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=error_detail("SKILL_DEFINITION_NOT_FOUND", str(exc))) from exc
    except SkillLifecycleError as exc:
        raise HTTPException(status_code=409, detail=error_detail("SKILL_LIFECYCLE_CONFLICT", str(exc))) from exc
    return SkillDefinitionResponse.from_model(definition)


@router.get("/infra-skills/overview", response_model=InfraSkillOverviewResponse)
def get_infra_skills_overview_early() -> InfraSkillOverviewResponse:
    return get_infra_skills_overview()


# ── Skill 错误挖掘：案例池查询与历史批量入池 ──────────────────────


@router.get(
    "/infra-skills/eval-case-pool",
    response_model=EvalCasePoolListResponse,
)
def list_eval_case_pool(
    principal: SkillEvaluationPrincipalDependency,
    storage: SkillRegressionStorageDependency,
    status: str | None = Query(default=None),
    error_dimension: str | None = Query(default=None),
    target_skill_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EvalCasePoolListResponse:
    """查询案例池（仅 skill:evaluate）。始终附加调用方租户条件。"""
    tenant_id = getattr(principal, "tenant_id", None)
    items = storage.list_pool_items(
        tenant_id=tenant_id,
        status=status,
        error_dimension=error_dimension,
        target_skill_id=target_skill_id,
        limit=limit,
        offset=offset,
    )
    responses = [_pool_item_to_response(item) for item in items]
    return EvalCasePoolListResponse(
        items=responses,
        total=len(responses),
        limit=limit,
        offset=offset,
    )


def _pool_item_to_response(item) -> EvalCasePoolItemResponse:
    return EvalCasePoolItemResponse(
        pool_id=item.pool_id,
        tenant_id=item.tenant_id,
        source_qa_turn_id=item.source_qa_turn_id,
        source_user_id=item.source_user_id,
        reason_code=item.reason_code.value,
        error_dimension=item.error_dimension.value,
        initial_dimension=item.error_dimension.value,
        transformed_dimension=(
            item.transformed_dimension.value if item.transformed_dimension else None
        ),
        target_skill_id=item.source_selected_skill_id,
        question_excerpt=item.question_excerpt,
        answer_excerpt=item.answer_excerpt,
        comment=item.comment,
        status=item.status.value,
        revision=item.revision,
        eval_case_ref=(
            item.eval_case_ref.model_dump() if item.eval_case_ref else None
        ),
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post(
    "/infra-skills/eval-case-pool/from-history",
    response_model=EvalCasePoolFromHistoryResponse,
)
def create_eval_case_pool_from_history(
    request: EvalCasePoolFromHistoryRequest,
    principal: SkillEvaluationPrincipalDependency,
    service: RegressionMiningServiceDependency,
) -> EvalCasePoolFromHistoryResponse:
    """评测者从历史批量入池（仅 skill:evaluate）。逐项返回结果。"""
    mining_principal = _to_mining_principal(principal)
    results = service.collect_from_history(
        principal=mining_principal,
        qa_turn_ids=request.qa_turn_ids,
        reason_code=request.reason_code,
        comment=request.comment,
    )
    return EvalCasePoolFromHistoryResponse(
        outcomes=[
            HistoryMiningOutcomeResponse(
                qa_turn_id=r.qa_turn_id, status=r.status.value, pool_id=r.pool_id
            )
            for r in results
        ]
    )


def _to_mining_principal(principal: SkillControlPrincipal):
    from src.runtime.skill_management.regression_mining_service import (
        RegressionPrincipal as _RegressionPrincipal,
    )

    return _RegressionPrincipal(
        user_id=principal.user_id,
        tenant_id=getattr(principal, "tenant_id", None) or "default",
        roles=principal.roles,
    )


def get_regression_transform_service(
    storage: SkillRegressionStorageDependency,
) -> "RegressionTransformService":
    from src.runtime.skill_management.regression_transform_service import (
        RegressionTransformService,
        GatewayTransformModelProvider,
    )

    return RegressionTransformService(
        storage=storage, model_provider=GatewayTransformModelProvider()
    )


RegressionTransformServiceDependency = Annotated[
    "RegressionTransformService", Depends(get_regression_transform_service)
]


@router.post(
    "/infra-skills/eval-case-pool/{pool_id}/transform",
    response_model=EvalCasePoolTransformResponse,
)
def transform_eval_case_pool_item(
    pool_id: str,
    request: EvalCasePoolTransformRequest,
    principal: SkillEvaluationPrincipalDependency,
    service: RegressionTransformServiceDependency,
) -> EvalCasePoolTransformResponse:
    """AI 转换案例池条目为类型化 proposal（仅 skill:evaluate）。失败不改状态。"""
    from src.data_platform.storage.skill.regression_ports import (
        SkillRegressionConflictError,
        SkillRegressionNotFoundError,
    )
    from src.runtime.skill_management.regression_transform_service import (
        SkillRegressionTransformError,
    )

    tenant_id = getattr(principal, "tenant_id", None) or "default"
    try:
        result = service.transform(
            pool_id,
            expected_revision=request.expected_revision,
            tenant_id=tenant_id,
        )
    except SkillRegressionNotFoundError:
        raise HTTPException(status_code=404, detail=error_detail("EVAL_CASE_POOL_NOT_FOUND", "案例不存在"))
    except SkillRegressionConflictError:
        raise HTTPException(status_code=409, detail=error_detail("EVAL_CASE_POOL_REVISION_CONFLICT", "案例已被修改，请刷新"))
    except SkillRegressionTransformError as exc:
        raise HTTPException(status_code=422, detail=error_detail("EVAL_CASE_TRANSFORM_INVALID", str(exc)))
    return EvalCasePoolTransformResponse(
        pool_id=result.pool_id,
        transformed_dimension=result.transformed_dimension.value,
        case_proposal=result.case_proposal.model_dump() if result.case_proposal else None,
        root_cause=result.root_cause,
        citations=result.citations,
        uncertainties=result.uncertainties,
        revision=result.revision,
    )


def get_regression_confirm_service(
    storage: SkillRegressionStorageDependency,
):
    from src.runtime.skill_management.regression_confirm_service import (
        RegressionConfirmService,
    )

    return RegressionConfirmService(
        regression_storage=storage,
        governance_storage=get_skill_governance_storage(),
    )


RegressionConfirmServiceDependency = Annotated[
    "RegressionConfirmService", Depends(get_regression_confirm_service)
]


@router.post(
    "/infra-skills/eval-case-pool/{pool_id}/confirm",
    response_model=EvalCasePoolConfirmResponse,
)
def confirm_eval_case_pool_item(
    pool_id: str,
    request: EvalCasePoolConfirmRequest,
    principal: SkillEvaluationPrincipalDependency,
    service: RegressionConfirmServiceDependency,
) -> EvalCasePoolConfirmResponse:
    """人工确认案例，投影到对应评测资产（仅 skill:evaluate）。重复请求返回同一资产。"""
    from src.runtime.skill_management.regression_confirm_service import (
        SkillRegressionCaseNotExecutableError,
    )
    from src.data_platform.storage.skill.regression_ports import (
        SkillRegressionConflictError,
        SkillRegressionNotFoundError,
    )

    confirm_principal = _to_mining_principal(principal)
    try:
        result = service.confirm(
            pool_id,
            request=request,
            confirmed_by=confirm_principal.user_id,
            tenant_id=confirm_principal.tenant_id,
        )
    except SkillRegressionNotFoundError:
        raise HTTPException(status_code=404, detail=error_detail("EVAL_CASE_POOL_NOT_FOUND", "案例不存在"))
    except SkillRegressionConflictError:
        raise HTTPException(status_code=409, detail=error_detail("EVAL_CASE_POOL_REVISION_CONFLICT", "案例已被修改，请刷新"))
    except SkillRegressionCaseNotExecutableError:
        raise HTTPException(status_code=422, detail=error_detail("EVAL_CASE_NOT_EXECUTABLE", "该维度不可确认，请重新分型或拒绝"))
    return EvalCasePoolConfirmResponse(
        pool_id=result.pool_id,
        case_type=result.case_type,
        case_id=result.case_id,
        revision=result.revision,
    )


@router.post(
    "/infra-skills/eval-case-pool/{pool_id}/reject",
    response_model=EvalCasePoolItemResponse,
)
def reject_eval_case_pool_item(
    pool_id: str,
    request: EvalCasePoolRejectRequest,
    principal: SkillEvaluationPrincipalDependency,
    storage: SkillRegressionStorageDependency,
) -> EvalCasePoolItemResponse:
    """拒绝案例（仅 skill:evaluate）。"""
    from src.data_platform.storage.skill.regression_ports import (
        SkillRegressionConflictError,
        SkillRegressionNotFoundError,
    )

    tenant_id = getattr(principal, "tenant_id", None) or "default"
    try:
        updated = storage.reject_pool_item(
            pool_id,
            tenant_id=tenant_id,
            reason=request.rejection_reason,
            expected_revision=request.expected_revision,
        )
    except SkillRegressionNotFoundError:
        raise HTTPException(status_code=404, detail=error_detail("EVAL_CASE_POOL_NOT_FOUND", "案例不存在"))
    except SkillRegressionConflictError:
        raise HTTPException(status_code=409, detail=error_detail("EVAL_CASE_POOL_REVISION_CONFLICT", "案例已被修改，请刷新"))
    return _pool_item_to_response(updated)


@router.get("/infra-skills/{skill_id}", response_model=InfraSkillDetailResponse)
def get_infra_skill_details(skill_id: str) -> InfraSkillDetailResponse:
    loader = get_loader()
    skill = loader.get(skill_id)
    if not skill:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_NOT_FOUND", "未找到该 Skill 包", {"skill_id": skill_id}),
        )

    skill_dir = Path(SKILLS_DIR) / skill_id
    readme_content = ""
    readme_path = skill_dir / "SKILL.md"
    if readme_path.exists():
        readme_content = readme_path.read_text(encoding="utf-8")

    files_struct = InfraSkillFilesStructure(
        agents=_list_files_in_dir(skill_dir, "agents"),
        schemas=_list_files_in_dir(skill_dir, "schemas"),
        templates=_list_files_in_dir(skill_dir, "templates"),
        scripts=_list_files_in_dir(skill_dir, "scripts"),
        references=_list_files_in_dir(skill_dir, "references"),
        tests=_list_files_in_dir(skill_dir, "tests"),
        strategies=_list_files_in_dir(skill_dir, "strategies"),
    )

    # 读取 field_mapping.yaml（语义层字段映射）
    field_mapping = _read_field_mapping(skill_dir)

    return InfraSkillDetailResponse(
        skill_id=skill.skill_id,
        skill_name=skill.skill_name,
        business_action=skill.business_action,
        business_object=skill.business_object,
        include_keywords=skill.include_keywords,
        excluded_intents=skill.excluded_intents,
        manifest=skill.manifest,
        readme=readme_content,
        files_structure=files_struct,
        field_mapping=field_mapping,
    )


@router.get(
    "/infra-skills/{skill_id}/versions",
    response_model=list[SkillVersionResponse],
)
def list_infra_skill_versions(
    skill_id: str,
    service: SkillVersionServiceDependency,
) -> list[SkillVersionResponse]:
    return [
        SkillVersionResponse.model_validate(version.model_dump())
        for version in service.list_versions(skill_id)
    ]


@router.get(
    "/infra-skills/{skill_id}/versions/{version_id}",
    response_model=SkillVersionResponse,
)
def get_infra_skill_version(
    skill_id: str,
    version_id: str,
    service: SkillVersionServiceDependency,
) -> SkillVersionResponse:
    try:
        version = service.get_version(skill_id, version_id)
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "SKILL_VERSION_NOT_FOUND",
                str(exc),
                {"skill_id": skill_id, "version_id": version_id},
            ),
        ) from exc
    return SkillVersionResponse.model_validate(version.model_dump())


@router.post(
    "/infra-skills/{skill_id}/versions/sync",
    response_model=SkillVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def sync_infra_skill_version(
    skill_id: str,
    request: SkillVersionSyncRequest,
    service: SkillVersionServiceDependency,
) -> SkillVersionResponse:
    try:
        version = service.sync_version(
            skill_id,
            source_commit=request.source_commit,
            created_by=request.created_by,
        )
    except SkillNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "SKILL_NOT_FOUND", str(exc), {"skill_id": skill_id}
            ),
        ) from exc
    except SkillVersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "SKILL_VERSION_CONFLICT", str(exc), {"skill_id": skill_id}
            ),
        ) from exc
    except (SkillArtifactError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                "SKILL_VERSION_INVALID", str(exc), {"skill_id": skill_id}
            ),
        ) from exc
    return SkillVersionResponse.model_validate(version.model_dump())


@router.post("/infra-skills/route-test", response_model=SkillRouteTestResponse)
def test_infra_skill_routing(request: SkillRouteTestRequest) -> SkillRouteTestResponse:
    matches = route_question_ranked(request.question, min_confidence=0.1)
    top = matches[0] if matches else None
    return SkillRouteTestResponse(
        question=request.question,
        matched_skill_id=top.skill_id if top else None,
        confidence=top.confidence if top else 0.0,
        match_method=top.match_method if top else "none",
        matched_keywords=top.matched_keywords if top else [],
        candidates=[match.to_dict() for match in matches[:5]],
    )


def _safe_input_summary(request: SkillExecuteTestRequest) -> dict[str, object]:
    """只返回调试所需的非敏感上下文摘要，不回显原始患者数据。"""
    context = request.context or {}
    return {
        "context_keys": sorted(context.keys()),
        "patient_id": context.get("patient_id"),
        "encounter_id": context.get("encounter_id"),
        "target_fee_item": request.target_fee_item,
    }


def _result_diagnostics(result: object) -> tuple[list[str], list[dict], list[str], list[dict]]:
    if not isinstance(result, dict):
        return [], [], [], []
    return (
        list(result.get("warnings", []) or []),
        list(result.get("citations", []) or []),
        list(result.get("uncertainties", []) or []),
        list(result.get("trace", []) or []),
    )


@router.post("/infra-skills/{skill_id}/test", response_model=SkillExecuteTestResponse)
def test_infra_skill_execution(
    skill_id: str, request: SkillExecuteTestRequest
) -> SkillExecuteTestResponse:
    assembler = get_assembler(skill_id)
    if not assembler:
        raise HTTPException(
            status_code=404,
            detail=error_detail("SKILL_NOT_FOUND", "未找到该 Skill 包", {"skill_id": skill_id}),
        )

    try:
        # Check if the assembler expects 'target_fee_item' or just standard kwargs
        # This is a generic test execution wrapper, we pass available args.
        # It's assumed the assembler handles these inputs or ignores unknown kwargs.
        
        # Policy Fee Explanation specific signature:
        # execute(self, context, evidence, status, target_fee_item=None)
        
        import inspect
        from types import SimpleNamespace
        sig = inspect.signature(assembler.execute)
        kwargs = {}
        # 将 dict 转为 SimpleNamespace 以支持 getattr 访问
        ctx_obj = SimpleNamespace(**request.context) if request.context else SimpleNamespace()
        if "settlement_context" in sig.parameters or "context" in sig.parameters:
            kwargs["settlement_context"] = ctx_obj
        if "policy_evidence" in sig.parameters or "evidence" in sig.parameters:
            kwargs["policy_evidence"] = request.evidence
        if "policy_status" in sig.parameters or "status" in sig.parameters:
            kwargs["policy_status"] = request.status
        if "target_fee_item" in sig.parameters and request.target_fee_item:
            kwargs["target_fee_item"] = request.target_fee_item

        started = time.perf_counter()
        result = assembler.execute(**kwargs)
        warnings, citations, uncertainties, trace = _result_diagnostics(result)
        
        return SkillExecuteTestResponse(
            skill_id=skill_id,
            status="success",
            result=result,
            warnings=warnings,
            citations=citations,
            uncertainties=uncertainties,
            trace=trace,
            input_summary=_safe_input_summary(request),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_detail("SKILL_EXECUTION_FAILED", str(e), {"skill_id": skill_id}),
        )


@router.get("/infra-skills/overview", response_model=InfraSkillOverviewResponse)
def get_infra_skills_overview() -> InfraSkillOverviewResponse:
    """返回管理页面使用的 Skill 健康摘要。"""
    loader = get_loader()
    items: list[InfraSkillOverviewItem] = []
    for skill_id, skill in loader.get_all().items():
        skill_dir = Path(SKILLS_DIR) / skill_id
        manifest_path = skill_dir / "skill_manifest.yaml"
        warnings: list[str] = []
        manifest_valid = manifest_path.exists()
        if not manifest_valid:
            warnings.append("缺少 skill_manifest.yaml")
        field_mapping_configured = (skill_dir / "field_mapping.yaml").exists()
        metric_count = sum(
            len(declaration.get("metrics", []))
            for declaration in (skill.manifest.get("needed_objects", []) or [])
            if isinstance(declaration, dict)
        )
        items.append(InfraSkillOverviewItem(
            skill_id=skill_id,
            skill_name=skill.skill_name,
            business_action=skill.business_action,
            business_object=skill.business_object,
            manifest_valid=manifest_valid,
            field_mapping_configured=field_mapping_configured,
            metric_count=metric_count,
            warnings=warnings,
        ))
    return InfraSkillOverviewResponse(skill_count=len(items), skills=items)


@router.post("/infra-skills/refresh", response_model=SkillRefreshResponse)
def refresh_infra_skills() -> SkillRefreshResponse:
    """热重载：重新扫描 skills/ 目录，发现新增或移除的 skill 包。

    无需重启服务即可加载新创建的 skill 目录。
    """
    try:
        new_registry = refresh_loader()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=error_detail("SKILL_REFRESH_FAILED", str(e), {}),
        )

    skills = []
    for s_id, s in new_registry.items():
        skills.append(
            InfraSkillItem(
                skill_id=s.skill_id,
                skill_name=s.skill_name,
                include_keywords=s.include_keywords,
                excluded_intents=s.excluded_intents,
            )
        )

    return SkillRefreshResponse(
        skill_count=len(skills),
        skills=skills,
        message=f"热重载完成，已发现 {len(skills)} 个 skill",
    )
