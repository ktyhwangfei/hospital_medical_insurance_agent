"""Tool 可视化管理与 Workflow 编排 — 只读展示 API（不新增业务写路径）。

与 catalog_routes 同口径：开放 GET、无凭据泄露面、Depends 注入供测试 override。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.runtime.workflow.catalog_view import (
    ToolCatalog,
    WorkflowCatalog,
    build_tool_catalog,
    build_workflow_catalog,
)

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent",
    tags=["tool-workflow-catalog"],
)


def get_tool_catalog() -> ToolCatalog:
    return build_tool_catalog()


def get_workflow_catalog() -> WorkflowCatalog:
    return build_workflow_catalog()


@router.get("/tool-registry/tools", response_model=ToolCatalog)
def list_tools(catalog: ToolCatalog = Depends(get_tool_catalog)) -> ToolCatalog:
    return catalog


@router.get("/workflow-catalog/workflows", response_model=WorkflowCatalog)
def list_workflows(catalog: WorkflowCatalog = Depends(get_workflow_catalog)) -> WorkflowCatalog:
    return catalog
