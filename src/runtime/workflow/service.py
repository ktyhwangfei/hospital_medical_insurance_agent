"""Workflow 层对外统一入口：意图路由 + 执行 + 结果映射。"""

from __future__ import annotations

import os
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


def _disabled_workflow_ids() -> set[str]:
    """运维停用开关：WORKFLOW_DISABLED=wf_a,wf_b（逗号分隔，无需改代码即可下线单条）。

    ponytail: 环境变量级开关；PG 化的治理启停（发布/版本）留待编排发布阶段。
    """
    raw = os.getenv("WORKFLOW_DISABLED", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _enabled(definition: WorkflowDefinition) -> bool:
    return definition.workflow_id not in _disabled_workflow_ids()


def is_workflow_enabled(workflow_id: str) -> bool:
    """目录/路由统一查询停用状态。"""
    return workflow_id not in _disabled_workflow_ids()


@lru_cache(maxsize=1)
def _get_router() -> WorkflowRouter:
    return WorkflowRouter([d for d in KEYWORD_ROUTED_WORKFLOWS if _enabled(d)])


@lru_cache(maxsize=1)
def _get_executor() -> WorkflowExecutor:
    return WorkflowExecutor(get_tool_registry(), domain_handlers=DOMAIN_HANDLERS)


def route_workflow_question(question: str) -> WorkflowDefinition | None:
    """窄场景关键词 fallback；政策问答和运营问数不参与，避免重叠词误路由。"""
    return _get_router().route(question)


def get_workflow_by_mode(mode: PolicyQAMode) -> WorkflowDefinition | None:
    """按三态入口模式返回对应 Workflow；未知/停用返回 None（外层走既有 Skill pipeline）。"""
    definition = _WORKFLOW_BY_MODE.get(mode)
    if definition is None or not _enabled(definition):
        return None
    return definition


async def execute_workflow(
    definition: WorkflowDefinition, *, context: dict[str, Any]
) -> WorkflowExecutionResult:
    return await _get_executor().execute(definition, context=context)


def _build_context(
    *,
    question: str,
    settlement_id: str | None,
    settlement_ids: list[str] | None,
    id_card: str,
    visit_date: str,
) -> dict[str, Any]:
    """执行上下文：可选字段全部默认值化，避免 input_mapping 引用缺失降级。

    id_card 仅在进程内传给工具做查询过滤，不进轨迹/日志（脱敏硬约束）。
    """
    return {
        "question": question,
        "settlement_id": settlement_id or "",
        "settlement_ids": list(settlement_ids or []),
        "id_card": id_card or "",
        "visit_date": visit_date or "",
    }


async def run_workflow_for_question(
    question: str,
    *,
    settlement_id: str | None = None,
    settlement_ids: list[str] | None = None,
    id_card: str = "",
    visit_date: str = "",
) -> PolicyQAPublicResult | None:
    """供 API 层调用的一站式入口：未命中 Workflow 返回 None，命中则返回公开结果。"""
    definition = route_workflow_question(question)
    if definition is None:
        return None
    result = await execute_workflow(
        definition,
        context=_build_context(
            question=question,
            settlement_id=settlement_id,
            settlement_ids=settlement_ids,
            id_card=id_card,
            visit_date=visit_date,
        ),
    )
    return build_workflow_public_result(result)


async def run_workflow_by_mode(
    mode: PolicyQAMode,
    *,
    question: str,
    settlement_id: str | None = None,
    settlement_ids: list[str] | None = None,
    id_card: str = "",
    visit_date: str = "",
) -> PolicyQAPublicResult | None:
    """按显式 mode 执行 Workflow；mode 未映射/停用（含 policy_chat）时返回 None，让外层走既有 Skill pipeline。"""
    definition = get_workflow_by_mode(mode)
    if definition is None:
        return None
    result = await execute_workflow(
        definition,
        context=_build_context(
            question=question,
            settlement_id=settlement_id,
            settlement_ids=settlement_ids,
            id_card=id_card,
            visit_date=visit_date,
        ),
    )
    return build_workflow_public_result(result)
