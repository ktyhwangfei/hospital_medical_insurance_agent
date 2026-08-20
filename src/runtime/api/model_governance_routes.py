"""模型与提示词治理接口。"""

import ipaddress
import os
import socket
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceConflictError,
    ModelGovernanceNotFoundError,
)
from src.gateway.auth import authenticator
from src.model_service.governance import ModelGovernanceSnapshot, build_governance_snapshot
from src.model_service.governance_assets import (
    GovernanceAssetContent,
    GovernanceAssetType,
    GovernanceEnvironment,
    ModelProfileAssetContent,
    PromptAssetContent,
    RouteRuleAssetContent,
)
from src.model_service.governance_import import build_current_governance_assets
from src.model_service.governance_factory import get_model_governance_service
from src.model_service.governance_secrets import GovernanceSecretError
from src.model_service.governance_service import (
    ModelGovernanceGateError,
    ModelGovernanceService,
)
from src.model_service.exceptions import (
    ModelAuthError,
    ModelRateLimitError,
    ModelServerError,
    ModelTimeoutError,
)
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider
from src.runtime.api.model_governance_schemas import (
    ApproveGovernanceDraftRequest,
    CreateGovernanceDraftRequest,
    GovernanceAssetsResponse,
    GovernanceAssetsResult,
    GovernanceBaseline,
    GovernanceConnectionTestResponse,
    GovernanceConnectionTestResult,
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
    ModelListProbeRequest,
    ModelListProbeResponse,
    ModelListProbeResult,
    ModelProfileGovernanceBaseline,
    PreviewGovernanceDraftRequest,
    PromptGovernanceBaseline,
    PublishedGovernanceSnapshotResponse,
    PublishGovernanceDraftRequest,
    RouteRuleGovernanceBaseline,
    UpdateGovernanceDraftRequest,
)
from src.runtime.api.schemas import AgentResponse
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/model-governance",
    tags=["model-governance"],
)


def _baseline_projection(content: GovernanceAssetContent) -> GovernanceBaseline:
    if isinstance(content, PromptAssetContent):
        return PromptGovernanceBaseline.model_validate(content.model_dump())
    if isinstance(content, ModelProfileAssetContent):
        return ModelProfileGovernanceBaseline.model_validate(content.model_dump())
    if isinstance(content, RouteRuleAssetContent):
        return RouteRuleGovernanceBaseline.model_validate(content.model_dump())
    raise TypeError(f"不支持的基线资产类型: {type(content).__name__}")


class ModelGovernanceResponse(AgentResponse):
    scenario: Literal["model_governance"] = "model_governance"
    status: Literal["success"] = "success"
    result: ModelGovernanceSnapshot


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
    if isinstance(exc, GovernanceSecretError):
        status_code, code = 503, "MODEL_GOVERNANCE_SECRET_UNAVAILABLE"
        message = "模型治理凭据暂不可用"
    elif isinstance(exc, ModelGovernanceConflictError):
        status_code, code = 409, "MODEL_GOVERNANCE_CONFLICT"
        message = str(exc)
    elif isinstance(exc, ModelGovernanceNotFoundError):
        status_code, code = 404, "MODEL_GOVERNANCE_NOT_FOUND"
        message = str(exc)
    else:
        status_code, code = 422, "MODEL_GOVERNANCE_VALIDATION_FAILED"
        message = str(exc)
    raise HTTPException(
        status_code=status_code,
        detail=error_detail(code, message),
    ) from exc


def _audit(principal: ModelGovernancePrincipal, action: str) -> dict[str, str]:
    return {"actor": principal.user_id, "action": action, "mode": "development"}


def _model_probe_audit(
    principal: ModelGovernancePrincipal, base_url: str, result: str
) -> dict[str, str]:
    return {
        **_audit(principal, "model_list_probe"),
        "endpoint_host": urlsplit(base_url).hostname or "",
        "result": result,
    }


def _model_probe_connect_ip(
    principal: ModelGovernancePrincipal, base_url: str
) -> str:
    """所有主机解析后固定 IP；内网主机还需服务端显式授权。"""
    parsed = urlsplit(base_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = {
        item.strip().lower().rstrip(".")
        for item in os.getenv("MODEL_GOVERNANCE_PROBE_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }
    try:
        addresses = list(dict.fromkeys(
            item[4][0]
            for item in socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        ))
    except OSError as exc:
        raise ModelServerError("Model list network error") from exc
    if (
        not addresses
        or not all(ipaddress.ip_address(address).is_global for address in addresses)
        and host not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail=error_detail(
                "MODEL_LIST_PROBE_HOST_FORBIDDEN",
                "该模型主机不是可直接探测的公网地址",
                _model_probe_audit(principal, base_url, "host_forbidden"),
            ),
        )
    return addresses[0]


def _validate_credential_reference(
    request: CreateGovernanceDraftRequest | UpdateGovernanceDraftRequest,
) -> None:
    if request.credential is None:
        return
    if not isinstance(request.content, ModelProfileAssetContent):
        raise ModelGovernanceGateError("只有模型资产可以提交凭据")
    if request.content.credential_ref != request.credential.credential_id:
        raise ModelGovernanceGateError(
            "credential_ref 必须与 credential_id 一致"
        )
    api_key_length = len(request.credential.api_key.get_secret_value())
    if not 1 <= api_key_length <= 4096:
        raise ModelGovernanceGateError("API Key 长度必须在 1 到 4096 之间")


@router.post("/models/probe-list", response_model=ModelListProbeResponse)
def probe_model_list(
    request: ModelListProbeRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
) -> ModelListProbeResponse:
    audit = _model_probe_audit(principal, request.base_url, "success")
    try:
        connect_ip = _model_probe_connect_ip(principal, request.base_url)
        provider = OpenAICompatibleProvider(
            request.base_url,
            request.api_key.get_secret_value(),
            timeout=request.timeout_seconds,
        )
        models = provider.list_models(connect_ip=connect_ip)
    except ModelAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=error_detail(
                "MODEL_LIST_PROBE_AUTH_FAILED",
                "认证失败：检查 API Key",
                _model_probe_audit(principal, request.base_url, "auth_failed"),
            ),
        ) from exc
    except ModelTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=error_detail(
                "MODEL_LIST_PROBE_TIMEOUT",
                "连接超时：检查 API 访问地址",
                _model_probe_audit(principal, request.base_url, "timeout"),
            ),
        ) from exc
    except ModelRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=error_detail(
                "MODEL_LIST_PROBE_RATE_LIMITED",
                "请求过于频繁，请稍后重试",
                _model_probe_audit(principal, request.base_url, "rate_limited"),
            ),
        ) from exc
    except ModelServerError as exc:
        message = str(exc)
        unsupported = "HTTP 404" in message or "HTTP 405" in message
        safe_message = (
            "该端点不支持模型列表接口，请手动输入模型名"
            if unsupported
            else "端点返回格式无法识别，请手动输入模型名"
            if "invalid payload" in message or "no models" in message
            else "获取模型列表失败：检查 API 访问地址"
        )
        raise HTTPException(
            status_code=502,
            detail=error_detail(
                "MODEL_LIST_PROBE_UNSUPPORTED"
                if unsupported
                else "MODEL_LIST_PROBE_FAILED",
                safe_message,
                _model_probe_audit(principal, request.base_url, "failed"),
            ),
        ) from exc
    return ModelListProbeResponse(
        result=ModelListProbeResult(
            models=models, safe_message=f"成功获取 {len(models)} 个模型"
        ),
        uncertainties=[],
        audit=audit,
    )


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
                _baseline_projection(item)
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
        uncertainties=[],
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
        uncertainties=[],
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
        uncertainties=[],
        audit=_audit(principal, "create_next_version"),
    )


@router.post("/drafts", response_model=GovernanceDraftResponse, status_code=201)
def create_governance_draft(
    request: CreateGovernanceDraftRequest,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceDraftResponse:
    try:
        _validate_credential_reference(request)
        if request.credential is None:
            draft = service.create_draft(request.content, actor=principal.user_id)
        else:
            draft = service.create_draft_with_credential(
                request.content,
                request.credential.credential_id,
                request.credential.api_key.get_secret_value(),
                actor=principal.user_id,
            )
    except (
        ModelGovernanceConflictError,
        ModelGovernanceGateError,
        GovernanceSecretError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft, uncertainties=[], audit=_audit(principal, "create_draft")
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
        uncertainties=[],
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
        _validate_credential_reference(request)
        if request.credential is None:
            draft = service.save_draft(
                draft_id,
                request.content,
                expected_revision=request.expected_revision,
                actor=principal.user_id,
            )
        else:
            draft = service.save_draft_with_credential(
                draft_id,
                request.content,
                request.credential.credential_id,
                request.credential.api_key.get_secret_value(),
                expected_revision=request.expected_revision,
                actor=principal.user_id,
            )
    except (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
        ModelGovernanceGateError,
        GovernanceSecretError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceDraftResponse(
        result=draft, uncertainties=[], audit=_audit(principal, "update_draft")
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
        uncertainties=[],
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
        result=draft, uncertainties=[], audit=_audit(principal, "validate_draft")
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
        result=preview, uncertainties=[], audit=_audit(principal, "preview_draft")
    )


@router.post(
    "/drafts/{draft_id}/test-connection",
    response_model=GovernanceConnectionTestResponse,
)
def test_governance_model_connection(
    draft_id: str,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_write),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> GovernanceConnectionTestResponse:
    try:
        tested = service.test_connection(draft_id, actor=principal.user_id)
    except (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
        ModelGovernanceGateError,
        GovernanceSecretError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceConnectionTestResponse(
        result=GovernanceConnectionTestResult(
            status="success" if tested.succeeded else "failure",
            latency_ms=tested.latency_ms,
            safe_message=tested.safe_message,
            tested_at=tested.tested_at,
            content_hash=tested.content_hash,
        ),
        uncertainties=[],
        audit=_audit(principal, "test_connection"),
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
        result=draft, uncertainties=[], audit=_audit(principal, "request_review")
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
        result=draft, uncertainties=[], audit=_audit(principal, "approve_draft")
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
    except (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
        ModelGovernanceGateError,
        GovernanceSecretError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceReleaseResponse(
        result=release, uncertainties=[], audit=_audit(principal, "publish_draft")
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
        uncertainties=[],
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
    except (
        ModelGovernanceConflictError,
        ModelGovernanceNotFoundError,
        ModelGovernanceGateError,
        GovernanceSecretError,
    ) as exc:
        _raise_domain_error(exc)
    return GovernanceReleaseResponse(
        result=release, uncertainties=[], audit=_audit(principal, "rollback_release")
    )


@router.get("/published-snapshot", response_model=PublishedGovernanceSnapshotResponse)
def get_published_governance_snapshot(
    environment: GovernanceEnvironment = GovernanceEnvironment.DEV,
    principal: ModelGovernancePrincipal = Depends(require_model_governance_read),
    service: ModelGovernanceService = Depends(get_model_governance_service),
) -> PublishedGovernanceSnapshotResponse:
    return PublishedGovernanceSnapshotResponse(
        result=service.published_snapshot(environment),
        uncertainties=[],
        audit=_audit(principal, "published_snapshot"),
    )
