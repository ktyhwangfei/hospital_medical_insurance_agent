"""治理 Flow API — Phase 1（Phase 0 契约冻结 §3.1 端点全集）。

前缀 /api/v1/medical-insurance-ai-agent/flow；错误统一走 error_detail()
映射 FLOW_* 冻结错误码：404 FLOW_NOT_FOUND / 409 乐观锁与状态机 /
422 校验阻断（携带完整校验报告，fail closed）。

服务通过 Depends(get_flow_service) 注入——API 测试 override 该依赖
即可注入内存存储（项目既有陷阱：直接调用工厂不响应 override）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.data_platform.storage.flow.flow_factory import (
    get_flow_view_reader,
    get_flow_view_deployer,
    get_governed_flow_storage,
)
from src.domain.governed_flow.compiler import CompiledFlowArtifact
from src.domain.governed_flow.models import (
    FlowArtifactMismatchError,
    FlowDefinition,
    FlowNotFoundError,
    FlowPublishedRevision,
    FlowQueryResult,
    FlowRevisionConflictError,
    FlowStateInvalidError,
    FLOW_CALLER_ROLE_LEVELS,
    PermissionLevel,
)
from src.gateway.auth import authenticator
from src.domain.governed_flow.validation import FlowValidationReport
from src.runtime.flow.flow_query_service import (
    FlowConsumeAmbiguousError,
    FlowConsumeDimensionForbiddenError,
    FlowConsumeDimensionPermissionDeniedError,
    FlowConsumeMetricUnknownError,
    FlowQueryService,
)
from src.runtime.flow.flow_service import FlowGovernanceService, FlowPublishBlockedError
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/flow",
    tags=["governed-flow"],
)


def get_flow_service() -> FlowGovernanceService:
    """依赖注入 seam：API 测试 override 此函数注入内存存储。

    生产 wiring 一并注入视图部署器（publish/rollback 真部署 DDL）；
    API 测试 override 时自行决定是否携带部署器。
    """
    return FlowGovernanceService(get_governed_flow_storage(), get_flow_view_deployer())


def get_flow_query_service() -> FlowQueryService:
    """消费服务依赖注入 seam：API 测试 override 注入内存存储 + stub 读取器。"""
    return FlowQueryService(get_governed_flow_storage(), get_flow_view_reader())


def get_flow_caller_role(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> str | None:
    """校验 flow:read 后从签名主体读取查询角色。"""
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTH_INVALID", auth.error_message or "登录凭据无效"),
        )
    permitted = authenticator.check_permission(auth, "flow:read")
    if not permitted.is_success:
        raise HTTPException(
            status_code=403,
            detail=error_detail("AUTH_FORBIDDEN", "权限不足"),
        )
    # 多角色主体按最高已声明级别取值；未知角色不会获得权限。
    detail_roles = {
        role for role, level in FLOW_CALLER_ROLE_LEVELS.items()
        if level is PermissionLevel.DETAIL
    }
    return next((role for role in auth.roles if role in detail_roles), None)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FlowNotFoundError):
        return HTTPException(status_code=404, detail=error_detail(
            "FLOW_NOT_FOUND", str(exc), {},
        ))
    if isinstance(exc, FlowRevisionConflictError):
        return HTTPException(status_code=409, detail=error_detail(
            "FLOW_REVISION_CONFLICT", str(exc), {},
        ))
    # 子类先于父类 FlowStateInvalidError 判断（T8 防篡改专用码）
    if isinstance(exc, FlowArtifactMismatchError):
        return HTTPException(status_code=409, detail=error_detail(
            "FLOW_ARTIFACT_MISMATCH", str(exc), {},
        ))
    # 子类先于父类 FlowStateInvalidError 判断（多契约拒猜专用码）
    if isinstance(exc, FlowConsumeAmbiguousError):
        return HTTPException(status_code=409, detail=error_detail(
            "FLOW_CONSUME_AMBIGUOUS", str(exc), {},
        ))
    if isinstance(exc, FlowStateInvalidError):
        return HTTPException(status_code=409, detail=error_detail(
            "FLOW_STATE_INVALID", str(exc), {},
        ))
    if isinstance(exc, FlowConsumeMetricUnknownError):
        return HTTPException(status_code=422, detail=error_detail(
            "FLOW_CONSUMES_UNKNOWN_METRIC", str(exc), {},
        ))
    if isinstance(exc, FlowConsumeDimensionForbiddenError):
        return HTTPException(status_code=422, detail=error_detail(
            "FLOW_CONSUME_DIMENSION_FORBIDDEN", str(exc), {},
        ))
    # T11 消费侧强制：detail 级维度对 summary 调用方拒止
    if isinstance(exc, FlowConsumeDimensionPermissionDeniedError):
        return HTTPException(status_code=422, detail=error_detail(
            "FLOW_CONSUME_DIMENSION_PERMISSION_DENIED", str(exc), {},
        ))
    if isinstance(exc, FlowPublishBlockedError):
        blocking = [i.code for i in exc.report.issues if i.severity.value == "blocking"]
        return HTTPException(status_code=422, detail=error_detail(
            blocking[0] if blocking else "FLOW_STATE_INVALID",
            "校验阻断，发布 fail closed",
            {"issues": [i.model_dump(mode="json") for i in exc.report.issues]},
        ))
    logger.exception("governed flow api unexpected error")
    return HTTPException(status_code=500, detail=error_detail(
        "FLOW_STATE_INVALID", f"未预期错误: {exc}", {},
    ))


class FlowRevisionView(BaseModel):
    """发布版本 + 活跃标记（活跃指针是存储概念，不进领域模型）。"""

    revision: FlowPublishedRevision
    is_active: bool


class PublishRequest(BaseModel):
    published_by: str


class RollbackRequest(BaseModel):
    revision_id: str


class FlowQueryRequest(BaseModel):
    """受控问数请求：metrics/dimensions 为空 = 消费契约全量指标 / 无下钻。

    调用方角色从 Authorization 签名主体解析，不接受请求体自报角色。
    """

    metrics: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)


@router.post("", status_code=201)
def create_flow(
    definition: FlowDefinition, service: FlowGovernanceService = Depends(get_flow_service)
) -> FlowDefinition:
    try:
        return service.create_flow(definition)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("")
def list_flows(service: FlowGovernanceService = Depends(get_flow_service)) -> list[FlowDefinition]:
    return service.list_flows()


@router.get("/{flow_id}")
def get_flow(
    flow_id: str, service: FlowGovernanceService = Depends(get_flow_service)
) -> FlowDefinition:
    try:
        return service.get_flow(flow_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put("/{flow_id}")
def update_flow(
    flow_id: str,
    definition: FlowDefinition,
    expected_revision: int = Query(..., ge=1),
    service: FlowGovernanceService = Depends(get_flow_service),
) -> FlowDefinition:
    try:
        return service.update_flow(flow_id, definition, expected_revision)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/{flow_id}")
def delete_flow(
    flow_id: str,
    expected_revision: int = Query(..., ge=1),
    service: FlowGovernanceService = Depends(get_flow_service),
) -> dict:
    try:
        service.delete_flow(flow_id, expected_revision)
        return {"deleted": flow_id}
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{flow_id}/validate")
def validate_flow(
    flow_id: str, service: FlowGovernanceService = Depends(get_flow_service)
) -> FlowValidationReport:
    try:
        return service.validate_flow(flow_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{flow_id}/submit-review")
def submit_review(
    flow_id: str, service: FlowGovernanceService = Depends(get_flow_service)
) -> FlowDefinition:
    try:
        return service.submit_review(flow_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{flow_id}/publish", status_code=201)
def publish_flow(
    flow_id: str,
    request: PublishRequest,
    service: FlowGovernanceService = Depends(get_flow_service),
) -> FlowPublishedRevision:
    try:
        return service.publish_flow(flow_id, request.published_by)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{flow_id}/rollback")
def rollback_flow(
    flow_id: str,
    request: RollbackRequest,
    service: FlowGovernanceService = Depends(get_flow_service),
) -> FlowRevisionView:
    try:
        target = service.rollback_flow(flow_id, request.revision_id)
        active = service.get_active_revision(flow_id)
        return FlowRevisionView(
            revision=target,
            is_active=active is not None and active.revision_id == target.revision_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{flow_id}/deprecate")
def deprecate_flow(
    flow_id: str, service: FlowGovernanceService = Depends(get_flow_service)
) -> FlowDefinition:
    try:
        return service.deprecate_flow(flow_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/{flow_id}/revisions")
def list_revisions(
    flow_id: str, service: FlowGovernanceService = Depends(get_flow_service)
) -> list[FlowRevisionView]:
    try:
        revisions = service.list_revisions(flow_id)
        active = service.get_active_revision(flow_id)
        active_id = active.revision_id if active else None
        return [
            FlowRevisionView(revision=r, is_active=r.revision_id == active_id)
            for r in revisions
        ]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/{flow_id}/preview")
def preview_flow(
    flow_id: str, service: FlowGovernanceService = Depends(get_flow_service)
) -> CompiledFlowArtifact:
    try:
        return service.preview_flow(flow_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/{flow_id}/query")
def query_flow(
    flow_id: str,
    request: FlowQueryRequest,
    service: FlowQueryService = Depends(get_flow_query_service),
    caller_role: str | None = Depends(get_flow_caller_role),
) -> FlowQueryResult:
    """受控问数：只读已部署视图，携带发布证据与门禁评估（Phase 3）。"""
    try:
        return service.query(
            flow_id, request.metrics, request.dimensions,
            caller_role=caller_role,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/consume")
def consume_by_metrics(
    request: FlowQueryRequest,
    service: FlowQueryService = Depends(get_flow_query_service),
    caller_role: str | None = Depends(get_flow_caller_role),
) -> FlowQueryResult:
    """指标码驱动受控消费（query_planner / 问数层接入点）。

    消费方只知语义指标码、不感知 flow_id：解析已发布消费契约的唯一活跃
    版本后走既有 T8 / 白名单 / 勾稽门禁链路；无契约 422、多契约 409。
    """
    try:
        return service.query_by_metrics(
            request.metrics, request.dimensions,
            caller_role=caller_role,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
