"""模型与提示词治理接口。"""

import os
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from src.data_platform.storage.model_governance.factory import (
    get_model_governance_storage,
)
from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceConflictError,
    ModelGovernanceNotFoundError,
)
from src.gateway.auth import authenticator
from src.model_service.governance import ModelGovernanceSnapshot, build_governance_snapshot
from src.model_service.governance_assets import GovernanceAssetType, GovernanceEnvironment
from src.model_service.governance_import import build_current_governance_assets
from src.model_service.governance_secrets import (
    GovernanceCredentialVault,
    GovernanceSecretError,
)
from src.model_service.governance_service import (
    ModelGovernanceGateError,
    ModelGovernanceService,
)
from src.runtime.api.model_governance_schemas import (
    ApproveGovernanceDraftRequest,
    CreateGovernanceDraftRequest,
    GovernanceAssetsResponse,
    GovernanceAssetsResult,
    GovernanceDraftResponse,
    GovernanceImportResponse,
    GovernancePreviewResponse,
    GovernanceReleaseResponse,
    GovernanceReleasesResponse,
    GovernanceReleasesResult,
    GovernanceRevisionRequest,
    GovernanceVersionsResponse,
    GovernanceVersionsResult,
    ModelGovernancePrincipal,
    PreviewGovernanceDraftRequest,
    PublishedGovernanceSnapshotResponse,
    PublishGovernanceDraftRequest,
    UpdateGovernanceDraftRequest,
)
from src.runtime.api.schemas import AgentResponse
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/model-governance",
    tags=["model-governance"],
)


class ModelGovernanceResponse(AgentResponse):
    scenario: Literal["model_governance"] = "model_governance"
    status: Literal["success"] = "success"
    result: ModelGovernanceSnapshot


@lru_cache(maxsize=1)
def get_model_governance_service() -> ModelGovernanceService:
    return ModelGovernanceService(get_model_governance_storage())


def require_model_governance_permission(
    required: str | None,
    authorization: str | None,
) -> ModelGovernancePrincipal:
    """当前仅允许显式开启的开发模式使用模拟 Token。"""
    if os.getenv("MODEL_GOVERNANCE_DEV_MODE", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise HTTPException(
            status_code=403,
            detail=error_detail(
                "MODEL_GOVERNANCE_DISABLED",
                "生产真实认证未接入，模型治理端点默认关闭；仅可在显式开发模式下启用",
            ),
        )
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth_result = authenticator.validate_token(authorization)
    if not auth_result.is_success:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_INVALID", auth_result.error_message or "凭据无效"),
        )
    if not auth_result.user_id:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_INVALID", "凭据缺少用户标识"),
        )
    if required:
        permission_result = authenticator.check_permission(auth_result, required)
        if not permission_result.is_success:
            raise HTTPException(
                status_code=403,
                detail=error_detail(
                    "AUTH_FORBIDDEN", permission_result.error_message or "权限不足"
                ),
            )
    return ModelGovernancePrincipal(
        user_id=auth_result.user_id,
        roles=auth_result.roles,
        permissions=auth_result.permissions,
    )


def require_model_governance_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> ModelGovernancePrincipal:
    return require_model_governance_permission(None, authorization)


def require_model_governance_write(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> ModelGovernancePrincipal:
    return require_model_governance_permission(
        "model_governance:write", authorization
    )


def require_model_governance_review(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> ModelGovernancePrincipal:
    return require_model_governance_permission(
        "model_governance:review", authorization
    )


def require_model_governance_publish(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> ModelGovernancePrincipal:
    return require_model_governance_permission(
        "model_governance:publish", authorization
    )


def _raise_domain_error(exc: Exception) -> None:
    if isinstance(exc, ModelGovernanceConflictError):
        status_code, code = 409, "MODEL_GOVERNANCE_CONFLICT"
    elif isinstance(exc, ModelGovernanceNotFoundError):
        status_code, code = 404, "MODEL_GOVERNANCE_NOT_FOUND"
    else:
        status_code, code = 422, "MODEL_GOVERNANCE_VALIDATION_FAILED"
    raise HTTPException(
        status_code=status_code,
        detail=error_detail(code, str(exc)),
    ) from exc


def _audit(principal: ModelGovernancePrincipal, action: str) -> dict[str, str]:
    return {"actor": principal.user_id, "action": action, "mode": "development"}


def _put_credential(request, *, actor: str) -> None:
    if request.credential is None:
        return
    GovernanceCredentialVault(get_model_governance_storage()).put(
        request.credential.credential_id,
        request.credential.api_key.get_secret_value(),
        actor=actor,
    )


_PENDING_RUNTIME = ["治理库已发布配置尚未接入当前运行时"]


@router.get("/snapshot", response_model=ModelGovernanceResponse)
def get_model_governance_snapshot(
    _: ModelGovernancePrincipal = Depends(require_model_governance_read),
) -> ModelGovernanceResponse:
    snapshot = build_governance_snapshot()
    return ModelGovernanceResponse(
        result=snapshot,
        citations=[
            {
                "source_type": "code",
                "source_id": source_path,
                "summary": "模型治理快照来源",
            }
            for source_path in snapshot.citations
        ],
        uncertainties=snapshot.uncertainties,
        audit={"mode": "read_only"},
    )


@router.get("/assets", response_model=GovernanceAssetsResponse)
def list_governance_assets(
    asset_type: GovernanceAssetType | None = None,
    environment: GovernanceEnvironment = GovernanceEnvironment.DEV,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_read),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceAssetsResponse:
    snapshot = service.published_snapshot(environment)
    return GovernanceAssetsResponse(
        result=GovernanceAssetsResult(
            baselines=[
                item
                for item in build_current_governance_assets()
                if asset_type is None or item.asset_type == asset_type
            ],
            drafts=service.list_drafts(asset_type),
            published=[
                item
                for item in snapshot.assets
                if asset_type is None or item.asset_type == asset_type
            ],
        ),
        uncertainties=_PENDING_RUNTIME,
        audit=_audit(principal, "list_assets"),
    )


@router.get(
    "/assets/{asset_id}/versions",
    response_model=GovernanceVersionsResponse,
)
def list_governance_versions(
    asset_id: str,
    environment: GovernanceEnvironment = GovernanceEnvironment.DEV,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_read),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceVersionsResponse:
    return GovernanceVersionsResponse(
        result=GovernanceVersionsResult(
            versions=service.list_versions(asset_id),
            releases=service.list_releases(asset_id, environment),
        ),
        uncertainties=_PENDING_RUNTIME,
        audit=_audit(principal, "list_versions"),
    )


@router.post(
    "/assets/{asset_id}/versions",
    response_model=GovernanceDraftResponse,
    status_code=201,
)
def create_next_governance_version(
    asset_id: str,
    environment: GovernanceEnvironment = GovernanceEnvironment.DEV,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        draft = service.create_next_version(
            asset_id,
            actor=principal.user_id,
            environment=environment,
        )
    except (ModelGovernanceNotFoundError, ModelGovernanceGateError) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft,
        uncertainties=_PENDING_RUNTIME,
        audit=_audit(principal, "create_next_version"),
    )


@router.post("/drafts", response_model=GovernanceDraftResponse, status_code=201)
def create_governance_draft(
    request: CreateGovernanceDraftRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        draft = service.create_draft(request.content, actor=principal.user_id)
        try:
            _put_credential(request, actor=principal.user_id)
        except Exception:
            service.delete_draft(draft.draft_id, expected_revision=draft.revision)
            raise
    except (
        ModelGovernanceConflictError,
        ModelGovernanceGateError,
        GovernanceSecretError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "create_draft")
    )


@router.post(
    "/import-current", response_model=GovernanceImportResponse, status_code=201
)
def import_current_governance_assets(
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceImportResponse:
    try:
        result = service.import_current_assets(actor=principal.user_id)
    except (ModelGovernanceConflictError, ModelGovernanceGateError) as exc:
        _raise_domain_error(exc)
    return GovernanceImportResponse(
        result=result,
        uncertainties=_PENDING_RUNTIME,
        audit=_audit(principal, "import_current_assets"),
    )


@router.patch("/drafts/{draft_id}", response_model=GovernanceDraftResponse)
def update_governance_draft(
    draft_id: str,
    request: UpdateGovernanceDraftRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        draft = service.save_draft(
            draft_id,
            request.content,
            expected_revision=request.expected_revision,
            actor=principal.user_id,
        )
        _put_credential(request, actor=principal.user_id)
    except (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
        ModelGovernanceGateError,
        GovernanceSecretError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "update_draft")
    )


@router.delete("/drafts/{draft_id}", response_model=GovernanceDraftResponse)
def delete_governance_draft(
    draft_id: str,
    expected_revision: int = Query(ge=1),
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        draft = service.delete_draft(
            draft_id, expected_revision=expected_revision
        )
    except (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
        ModelGovernanceGateError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft,
        uncertainties=_PENDING_RUNTIME,
        audit=_audit(principal, "delete_draft"),
    )


@router.post("/drafts/{draft_id}/validate", response_model=GovernanceDraftResponse)
def validate_governance_draft(
    draft_id: str,
    request: GovernanceRevisionRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        draft = service.validate_draft(
            draft_id, expected_revision=request.expected_revision
        )
    except (ModelGovernanceConflictError, ModelGovernanceNotFoundError) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "validate_draft")
    )


@router.post("/drafts/{draft_id}/preview", response_model=GovernancePreviewResponse)
def preview_governance_draft(
    draft_id: str,
    request: PreviewGovernanceDraftRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_read),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernancePreviewResponse:
    try:
        preview = service.preview(draft_id, request.variables)
    except (ModelGovernanceNotFoundError, ModelGovernanceGateError, ValueError) as exc:
        _raise_domain_error(exc)
    return GovernancePreviewResponse(
        result=preview, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "preview_draft")
    )


@router.post("/drafts/{draft_id}/request-review", response_model=GovernanceDraftResponse)
def request_governance_review(
    draft_id: str,
    request: GovernanceRevisionRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        draft = service.request_review(
            draft_id,
            expected_revision=request.expected_revision,
            actor=principal.user_id,
        )
    except (ModelGovernanceConflictError, ModelGovernanceNotFoundError, ModelGovernanceGateError) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "request_review")
    )


@router.post("/drafts/{draft_id}/approve", response_model=GovernanceDraftResponse)
def approve_governance_draft(
    draft_id: str,
    request: ApproveGovernanceDraftRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_review),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        draft = service.approve(
            draft_id,
            expected_revision=request.expected_revision,
            actor=principal.user_id,
            reason=request.reason,
        )
    except (ModelGovernanceConflictError, ModelGovernanceNotFoundError, ModelGovernanceGateError) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "approve_draft")
    )


@router.post("/drafts/{draft_id}/publish", response_model=GovernanceReleaseResponse)
def publish_governance_draft(
    draft_id: str,
    request: PublishGovernanceDraftRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_publish),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceReleaseResponse:
    try:
        release = service.publish(
            draft_id,
            expected_revision=request.expected_revision,
            actor=principal.user_id,
            environment=request.environment,
        )
    except (ModelGovernanceConflictError, ModelGovernanceNotFoundError, ModelGovernanceGateError) as exc:
        _raise_domain_error(exc)
    return GovernanceReleaseResponse(
        result=release, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "publish_draft")
    )


@router.get("/releases", response_model=GovernanceReleasesResponse)
def list_governance_releases(
    asset_id: str | None = None,
    environment: GovernanceEnvironment | None = None,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_read),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceReleasesResponse:
    return GovernanceReleasesResponse(
        result=GovernanceReleasesResult(
            releases=service.list_releases(asset_id, environment)
        ),
        uncertainties=_PENDING_RUNTIME,
        audit=_audit(principal, "list_releases"),
    )


@router.post("/releases/{release_id}/rollback", response_model=GovernanceReleaseResponse)
def rollback_governance_release(
    release_id: str,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_publish),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceReleaseResponse:
    try:
        release = service.rollback(release_id, actor=principal.user_id)
    except (ModelGovernanceConflictError, ModelGovernanceNotFoundError, ModelGovernanceGateError) as exc:
        _raise_domain_error(exc)
    return GovernanceReleaseResponse(
        result=release, uncertainties=_PENDING_RUNTIME, audit=_audit(principal, "rollback_release")
    )


@router.get("/published-snapshot", response_model=PublishedGovernanceSnapshotResponse)
def get_published_governance_snapshot(
    environment: GovernanceEnvironment = GovernanceEnvironment.DEV,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_read),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> PublishedGovernanceSnapshotResponse:
    return PublishedGovernanceSnapshotResponse(
        result=service.published_snapshot(environment),
        uncertainties=_PENDING_RUNTIME,
        audit=_audit(principal, "published_snapshot"),
    )
