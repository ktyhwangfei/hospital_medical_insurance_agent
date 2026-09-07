"""治理 Flow API — Phase 1（Phase 0 契约冻结 §3.1 端点全集）。

前缀 /api/v1/medical-insurance-ai-agent/flow；错误统一走 error_detail()
映射 FLOW_* 冻结错误码：404 FLOW_NOT_FOUND / 409 乐观锁与状态机 /
422 校验阻断（携带完整校验报告，fail closed）。

服务通过 Depends(get_flow_service) 注入——API 测试 override 该依赖
即可注入内存存储（项目既有陷阱：直接调用工厂不响应 override）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.data_platform.storage.flow.flow_factory import get_governed_flow_storage
from src.domain.governed_flow.compiler import CompiledFlowArtifact
from src.domain.governed_flow.models import (
    FlowDefinition,
    FlowNotFoundError,
    FlowPublishedRevision,
    FlowRevisionConflictError,
    FlowStateInvalidError,
)
from src.domain.governed_flow.validation import FlowValidationReport
from src.runtime.flow.flow_service import FlowGovernanceService, FlowPublishBlockedError
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/flow",
    tags=["governed-flow"],
)


def get_flow_service() -> FlowGovernanceService:
    """依赖注入 seam：API 测试 override 此函数注入内存存储。"""
    return FlowGovernanceService(get_governed_flow_storage())


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FlowNotFoundError):
        return HTTPException(status_code=404, detail=error_detail(
            "FLOW_NOT_FOUND", str(exc), {},
        ))
    if isinstance(exc, FlowRevisionConflictError):
        return HTTPException(status_code=409, detail=error_detail(
            "FLOW_REVISION_CONFLICT", str(exc), {},
        ))
    if isinstance(exc, FlowStateInvalidError):
        return HTTPException(status_code=409, detail=error_detail(
            "FLOW_STATE_INVALID", str(exc), {},
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
