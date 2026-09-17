"""Tool 可视化管理与 Workflow 编排 — 目录只读展示 + Workflow 治理配置写入。

目录沿 catalog_routes 同口径：开放 GET、无凭据泄露面、Depends 注入供测试 override。
配置写入走签名 JWT 的 workflow:write 权限（与 ops / question_library 同模式）——
院区个性化只落配置层，不改代码即可调关键词与启停。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
from src.runtime.workflow import config_service as workflow_config
from src.runtime.workflow.catalog_view import (
    ToolCatalog,
    WorkflowCatalog,
    build_tool_catalog,
    build_workflow_catalog,
)
from src.runtime.workflow.config_service import (
    EffectiveWorkflowConfig,
    UnknownWorkflowError,
    WorkflowConfigService,
)
from src.runtime.workflow.service import invalidate_workflow_caches
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent",
    tags=["tool-workflow-catalog"],
)


def get_tool_catalog() -> ToolCatalog:
    return build_tool_catalog()


def get_workflow_catalog() -> WorkflowCatalog:
    return build_workflow_catalog()


def get_workflow_config_service() -> WorkflowConfigService:
    """依赖注入 seam：测试 override 此函数注入内存存储。"""
    return workflow_config.get_workflow_config_service()


@router.get("/tool-registry/tools", response_model=ToolCatalog)
def list_tools(catalog: ToolCatalog = Depends(get_tool_catalog)) -> ToolCatalog:
    return catalog


@router.get("/workflow-catalog/workflows", response_model=WorkflowCatalog)
def list_workflows(catalog: WorkflowCatalog = Depends(get_workflow_catalog)) -> WorkflowCatalog:
    return catalog


class WorkflowConfigRequest(BaseModel):
    """治理配置写入体。

    `intent_keywords` 省略 = 保持该行已有词表（只改启停不会清掉院区关键词）；
    显式传 null = 清除本行覆盖、回落代码声明默认；传列表 = 存为该行词表。
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    intent_keywords: list[str] | None = None
    hospital_code: str = ""
    updated_by: str = Field(default="", max_length=128)


def require_workflow_write(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> DataGovernancePrincipal:
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
    permitted = authenticator.check_permission(auth, "workflow:write")
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


@router.put(
    "/workflow-catalog/workflows/{workflow_id}/config",
    response_model=EffectiveWorkflowConfig,
)
def upsert_workflow_config(
    workflow_id: str,
    payload: WorkflowConfigRequest,
    principal: DataGovernancePrincipal = Depends(require_workflow_write),
    service: WorkflowConfigService = Depends(get_workflow_config_service),
) -> EffectiveWorkflowConfig:
    """写入启停/关键词覆盖；同进程内立即生效（缓存失效，无需重启）。"""
    if "intent_keywords" in payload.model_fields_set:
        keywords = payload.intent_keywords
    else:
        # 未提供关键词：保持该行已有词表，避免“只改启停”误清关键词
        existing = service.get_override(payload.hospital_code, workflow_id)
        keywords = existing.intent_keywords if existing is not None else None
    try:
        service.set_override(
            workflow_id,
            enabled=payload.enabled,
            intent_keywords=keywords,
            hospital_code=payload.hospital_code,
            updated_by=payload.updated_by or principal.user_id,
        )
    except UnknownWorkflowError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("WORKFLOW_NOT_FOUND", f"未登记的工作流：{workflow_id}"),
        )
    invalidate_workflow_caches()
    effective = service.effective(payload.hospital_code).get(workflow_id)
    if effective is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("WORKFLOW_NOT_FOUND", f"未登记的工作流：{workflow_id}"),
        )
    return effective
