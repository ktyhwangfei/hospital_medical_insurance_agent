import logging
import os
import time
import hashlib
import json
from dataclasses import dataclass
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Protocol, cast

import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from src.config.production import SKILLS_DIR
from src.data_platform.storage.skill.version_factory import get_skill_version_storage
from src.data_platform.storage.skill.version_ports import SkillVersionConflictError
from src.data_platform.storage.skill.governance_factory import (
    get_skill_governance_storage,
)
from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
    SkillGovernanceNotFoundError,
)
from src.data_platform.cache import create_cache_client
from src.data_platform.cache.ports import IdempotencyStore

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
    SkillGovernanceStatus,
    SkillWorkbenchService,
)
from src.domain.skill.governance_models import SkillRelease
from src.runtime.api.skill_schemas import (
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


def get_skill_workbench_service(
    version_service: SkillVersionServiceDependency,
    governance_service: SkillGovernanceServiceDependency,
) -> SkillWorkbenchService:
    return SkillWorkbenchService(version_service, governance_service)


SkillWorkbenchServiceDependency = Annotated[
    SkillWorkbenchService, Depends(get_skill_workbench_service)
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


class SkillIdempotencyStore(IdempotencyStore, Protocol):
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


def _idempotent_release_mutation(
    *,
    store: SkillIdempotencyStore,
    scope: str,
    idempotency_key: str,
    request_payload: dict[str, object],
    operation: Callable[[], SkillRelease],
    recovery: Callable[[], SkillRelease | None] | None = None,
) -> SkillReleaseResponse:
    scoped_key = f"skill-governance:{scope}:{idempotency_key}"
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
            return SkillReleaseResponse.model_validate(existing)
        cache_key = f"idempotency:{scoped_key}"
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
                response = SkillReleaseResponse.model_validate(recovered.model_dump())
                stored = {
                    **response.model_dump(mode="json"),
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
        store.set_json(
            cache_key,
            {"status": "reserved", "request_hash": request_hash},
            ttl_seconds=86400,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail("IDEMPOTENCY_STORE_UNAVAILABLE", "幂等存储不可用"),
        ) from exc

    try:
        response = SkillReleaseResponse.model_validate(operation().model_dump())
    except Exception:
        try:
            store.delete(f"idempotency:{scoped_key}")
        except Exception:
            logger.exception("Failed to release Skill idempotency key: %s", scoped_key)
        raise
    stored = {**response.model_dump(mode="json"), "_request_hash": request_hash}
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
    query: str = Query(default="", max_length=128),
) -> SkillWorkbenchResponse:
    workbench = service.list_workbench(
        page=page,
        page_size=page_size,
        business_action=business_action,
        business_object=business_object,
        artifact_status=artifact_status,
        governance_status=governance_status,
        query=query,
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
        release = _idempotent_release_mutation(
            store=idempotency_store,
            scope=scope,
            idempotency_key=idempotency_key,
            request_payload={
                **request.model_dump(mode="json"),
                "created_by": principal.user_id,
            },
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
        release = _idempotent_release_mutation(
            store=idempotency_store,
            scope=f"{skill_id}:{release_id}:request-approval",
            idempotency_key=idempotency_key,
            request_payload=request.model_dump(mode="json"),
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
        release = _idempotent_release_mutation(
            store=idempotency_store,
            scope=f"{skill_id}:{release_id}:approve",
            idempotency_key=idempotency_key,
            request_payload={
                **request.model_dump(mode="json"),
                "approved_by": principal.user_id,
            },
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
        release = _idempotent_release_mutation(
            store=idempotency_store,
            scope=f"{skill_id}:{release_id}:activate",
            idempotency_key=idempotency_key,
            request_payload=request.model_dump(mode="json"),
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


@router.get("/infra-skills/overview", response_model=InfraSkillOverviewResponse)
def get_infra_skills_overview_early() -> InfraSkillOverviewResponse:
    return get_infra_skills_overview()


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
