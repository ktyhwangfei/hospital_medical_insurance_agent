"""健康运营 API — issue #45 P0（问题库 + 手动巡检）+ #50（详情与生命周期）。

前缀 /api/v1/medical-insurance-ai-agent/ops；鉴权走签名 JWT 的
ops:read / ops:write 权限（与 data-governance 同模式）。

服务通过 Depends(get_ops_service) 注入——API 测试 override 该依赖
即可注入内存存储（项目既有陷阱：直接调用工厂不响应 override）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.data_platform.storage.ops.ops_factory import get_ops_finding_storage
from src.domain.ops.models import (
    FindingRevisionConflictError,
    InvalidFindingTransitionError,
    OpsAssetType,
    OpsFindingDetail,
    OpsFindingNotFoundError,
    OpsFindingPage,
    OpsFindingStatus,
    OpsSeverity,
)
from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
from src.runtime.ops.service import OpsHealthService, OpsInspectionResult
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/ops",
    tags=["ops-health"],
)


def get_ops_service() -> OpsHealthService:
    """依赖注入 seam：API 测试 override 此函数注入内存存储与假读取面。"""
    # 巡检读取面复用治理控制面服务（lru_cache 单例，密钥缺失时端点 503）
    from src.runtime.api.data_governance_routes import get_data_governance_service

    return OpsHealthService(get_ops_finding_storage(), get_data_governance_service)


def _require_permission(permission: str, authorization: str | None):
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success or not auth.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_INVALID", auth.error_message or "登录凭据无效"),
        )
    permitted = authenticator.check_permission(auth, permission)
    if not permitted.is_success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("AUTH_FORBIDDEN", "权限不足"),
        )
    return DataGovernancePrincipal(
        user_id=auth.user_id,
        roles=auth.roles,
        permissions=auth.permissions,
    )


def require_ops_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    return _require_permission("ops:read", authorization)


def require_ops_write(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    return _require_permission("ops:write", authorization)


@router.post(
    "/inspections",
    response_model=OpsInspectionResult,
)
def run_inspection(
    _principal=Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsInspectionResult:
    """手动触发一次巡检：全部检查器只读取数，问题按 fingerprint 去重落库。"""
    return service.run_inspection()


@router.get(
    "/findings",
    response_model=OpsFindingPage,
)
def list_findings(
    status_filter: OpsFindingStatus | None = Query(default=None, alias="status"),
    severity: OpsSeverity | None = Query(default=None),
    asset_type: OpsAssetType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _principal=Depends(require_ops_read),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingPage:
    """开放问题列表：severity / asset_type 过滤 + 分页，severity 与最近发现排序。"""
    return service.list_findings(
        status=status_filter,
        severity=severity,
        asset_type=asset_type,
        page=page,
        page_size=page_size,
    )


class IgnoreFindingRequest(BaseModel):
    """忽略原因（必填，写入事件留痕）。"""

    reason: str = Field(min_length=1, max_length=500)


def _raise_lifecycle_error(exc: Exception) -> None:
    """生命周期异常 → HTTP 映射：404 不存在 / 409 非法流转或版本冲突。"""
    if isinstance(exc, OpsFindingNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("FINDING_NOT_FOUND", str(exc)),
        ) from exc
    if isinstance(exc, InvalidFindingTransitionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("FINDING_TRANSITION_INVALID", str(exc)),
        ) from exc
    if isinstance(exc, FindingRevisionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("FINDING_REVISION_CONFLICT", str(exc)),
        ) from exc
    raise exc


@router.get(
    "/findings/{finding_id}",
    response_model=OpsFindingDetail,
)
def get_finding(
    finding_id: str,
    _principal=Depends(require_ops_read),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingDetail:
    """单条问题详情：证据快照 + 生命周期事件时间线。"""
    try:
        return service.get_finding_detail(finding_id)
    except OpsFindingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("FINDING_NOT_FOUND", str(exc)),
        ) from exc


@router.post(
    "/findings/{finding_id}/ignore",
    response_model=OpsFindingDetail,
)
def ignore_finding(
    finding_id: str,
    request: IgnoreFindingRequest,
    expected_revision: int = Query(ge=1),
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingDetail:
    """忽略开放问题（open → ignored）：必填原因，乐观锁 expected_revision。"""
    try:
        return service.ignore_finding(
            finding_id,
            expected_revision=expected_revision,
            reason=request.reason,
            actor=principal.user_id,
        )
    except (OpsFindingNotFoundError, InvalidFindingTransitionError, FindingRevisionConflictError) as exc:
        _raise_lifecycle_error(exc)


@router.post(
    "/findings/{finding_id}/reopen",
    response_model=OpsFindingDetail,
)
def reopen_finding(
    finding_id: str,
    expected_revision: int = Query(ge=1),
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingDetail:
    """重开已忽略/已解决问题（ignored|resolved → open）：乐观锁 expected_revision。"""
    try:
        return service.reopen_finding(
            finding_id,
            expected_revision=expected_revision,
            actor=principal.user_id,
        )
    except (OpsFindingNotFoundError, InvalidFindingTransitionError, FindingRevisionConflictError) as exc:
        _raise_lifecycle_error(exc)
