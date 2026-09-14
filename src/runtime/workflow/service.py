"""Workflow 层对外统一入口：意图路由 + 执行 + 结果映射。"""

from __future__ import annotations

from functools import lru_cache

from src.domain.workflow.models import WorkflowDefinition, WorkflowExecutionResult
from src.runtime.policy_qa.public_contract import PolicyQAPublicResult
from src.runtime.tool_registry.factory import get_tool_registry
from src.runtime.workflow.definitions import ALL_WORKFLOWS
from src.runtime.workflow.executor import WorkflowExecutor
from src.runtime.workflow.public_result import build_workflow_public_result
from src.runtime.workflow.router import WorkflowRouter


@lru_cache(maxsize=1)
def _get_router() -> WorkflowRouter:
    return WorkflowRouter(ALL_WORKFLOWS)


@lru_cache(maxsize=1)
def _get_executor() -> WorkflowExecutor:
    return WorkflowExecutor(get_tool_registry())


def route_workflow_question(question: str) -> WorkflowDefinition | None:
    """一次性关键词分类：命中则返回对应 Workflow，否则返回 None（不介入原有流程）。"""
    return _get_router().route(question)


async def execute_workflow(
    definition: WorkflowDefinition, *, settlement_id: str | None
) -> WorkflowExecutionResult:
    return await _get_executor().execute(definition, context={"settlement_id": settlement_id})


async def run_workflow_for_question(
    question: str, *, settlement_id: str | None
) -> PolicyQAPublicResult | None:
    """供 API 层调用的一站式入口：未命中 Workflow 返回 None，命中则返回公开结果。"""
    definition = route_workflow_question(question)
    if definition is None:
        return None
    result = await execute_workflow(definition, settlement_id=settlement_id)
    return build_workflow_public_result(result)
