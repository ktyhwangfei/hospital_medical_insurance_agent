"""数据类 Tool 登记：语义层受控查询，与已发布语义查询模型保持一致。

Tool 不绕过语义层直接出 SQL——查询能力受 SemanticQuery 契约约束
（object_code/metrics/scope anchor），只消费已发布查询模型，越界即拒。
"""

from __future__ import annotations

from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolRiskLevel,
    ToolStatus,
    ToolVersion,
)
from src.runtime.tool_registry.service import ToolRegistryService

TOOL_QUERY_SEMANTIC_METRICS = "tool_query_semantic_metrics"


async def _query_semantic_metrics(
    object_code: str,
    entity_code: str,
    anchor_field: str,
    anchor_value: str,
    metrics: list[str],
    query_scope: str = "whole_admission",
) -> dict:
    """包装 SemanticQueryService：按已发布语义模型查询业务对象指标。

    与 settlement_data_provider 同一组合根（registry + supply connect），
    输入不合法（对象/指标未发布、anchor 非法）由语义层 fail-closed 拒绝。
    """
    from src.runtime.policy_qa.settlement_data_provider import (
        create_settlement_data_provider,
    )
    from src.semantic_layer.query_planner import QueryAnchor, QueryScope, SemanticQuery

    provider = create_settlement_data_provider()
    query = SemanticQuery(
        object_code=object_code,
        scope=QueryScope(
            entity_code=entity_code,
            anchor=QueryAnchor(field_code=anchor_field, value=anchor_value),
            query_scope=query_scope,
        ),
        metrics=list(metrics),
    )
    result = await provider.run_semantic_query(query)
    return {
        "rows": result.rows,
        "quality_status": result.quality_status,
        "model_version": result.model_version,
        "metrics": list(metrics),
        "row_count": len(result.rows),
    }


def register_data_tools(registry: ToolRegistryService) -> None:
    registry.register(
        ToolVersion(
            version_id="tv_query_semantic_metrics_1",
            tool_id=TOOL_QUERY_SEMANTIC_METRICS,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_QUERY_SEMANTIC_METRICS,
                name="语义指标查询",
                description="走语义层已发布查询模型按对象+指标受控取数，禁止绕过语义层直连数据库",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.semantic_layer.query_planner.SemanticQueryService.execute",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "语义层查询"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_query_semantic_metrics,
    )
