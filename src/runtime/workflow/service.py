"""Workflow 层对外统一入口：意图路由 + 执行 + 结果映射。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.domain.workflow.models import WorkflowDefinition, WorkflowExecutionResult
from src.runtime.policy_qa.models import PolicyQAMode
from src.runtime.policy_qa.public_contract import PolicyQAPublicResult
from src.runtime.tool_registry.factory import get_tool_registry
from src.runtime.workflow.definitions import (
    KEYWORD_ROUTED_WORKFLOWS,
    WF_DATA_QUERY,
    WF_OUTPATIENT_SETTLEMENT_EXPLAIN,
    WF_POLICY_CHAT,
)
from src.runtime.workflow.domain_nodes import DOMAIN_HANDLERS
from src.runtime.workflow.executor import WorkflowExecutor
from src.runtime.workflow.public_result import build_workflow_public_result
from src.runtime.workflow.router import WorkflowRouter


_WORKFLOW_BY_MODE: dict[PolicyQAMode, WorkflowDefinition] = {
    # PolicyChat 当前仍由既有 Skill pipeline 承载，待 WF_POLICY_CHAT 实现后再接入
    PolicyQAMode.SETTLEMENT_EXPLAIN: WF_OUTPATIENT_SETTLEMENT_EXPLAIN,
    PolicyQAMode.DATA_QUERY: WF_DATA_QUERY,
}


@lru_cache(maxsize=1)
def _get_router() -> WorkflowRouter:
    return WorkflowRouter(KEYWORD_ROUTED_WORKFLOWS)


@lru_cache(maxsize=1)
def _get_executor() -> WorkflowExecutor:
    return WorkflowExecutor(get_tool_registry(), domain_handlers=DOMAIN_HANDLERS)


def route_workflow_question(question: str) -> WorkflowDefinition | None:
    """窄场景关键词 fallback；政策问答和运营问数不参与，避免重叠词误路由。"""
    return _get_router().route(question)


def get_workflow_by_mode(mode: PolicyQAMode) -> WorkflowDefinition | None:
    """按三态入口模式返回对应 Workflow；未知模式返回 None。"""
    return _WORKFLOW_BY_MODE.get(mode)


async def execute_workflow(
    definition: WorkflowDefinition, *, context: dict[str, Any]
) -> WorkflowExecutionResult:
    return await _get_executor().execute(definition, context=context)


async def run_workflow_for_question(
    question: str, *, settlement_id: str | None
) -> PolicyQAPublicResult | None:
    """供 API 层调用的一站式入口：未命中 Workflow 返回 None，命中则返回公开结果。"""
    definition = route_workflow_question(question)
    if definition is None:
        return None
    result = await execute_workflow(
        definition, context={"question": question, "settlement_id": settlement_id}
    )
    return build_workflow_public_result(result)


async def run_workflow_by_mode(
    mode: PolicyQAMode,
    *,
    question: str,
    settlement_id: str | None,
) -> PolicyQAPublicResult | None:
    """按显式 mode 执行 Workflow；mode 未映射（含 policy_chat）时返回 None，让外层走既有 Skill pipeline。"""
    definition = get_workflow_by_mode(mode)
    if definition is None:
        return None
    result = await execute_workflow(
        definition, context={"question": question, "settlement_id": settlement_id}
    )
    return build_workflow_public_result(result)
