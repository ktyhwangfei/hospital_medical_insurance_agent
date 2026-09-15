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
            version_id="tv_query_semantic_metrics_2",
            tool_id=TOOL_QUERY_SEMANTIC_METRICS,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_QUERY_SEMANTIC_METRICS,
                name="语义指标查询",
                description="走语义层已发布查询模型按对象+指标受控取数，禁止绕过语义层直连数据库",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.semantic_layer.query_planner.SemanticQueryService.execute",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "语义层查询"],
                input_schema={
                    "object_code": {
                        "type": "string",
                        "required": True,
                        "description": "语义对象编码（仅限已发布查询模型）",
                    },
                    "entity_code": {
                        "type": "string",
                        "required": True,
                        "description": "数据集/实体编码（数据源路由依据）",
                    },
                    "anchor_field": {
                        "type": "string",
                        "required": True,
                        "description": "锚点字段编码（如结算单号字段）",
                    },
                    "anchor_value": {
                        "type": "string",
                        "required": True,
                        "description": "锚点值（如具体结算单号）",
                    },
                    "metrics": {
                        "type": "array<string>",
                        "required": True,
                        "description": "指标编码列表（仅限已发布指标）",
                    },
                    "query_scope": {
                        "type": "string",
                        "required": False,
                        "description": "查询范围，默认 whole_admission（全就诊口径）",
                    },
                },
                output_schema={
                    "rows": {"type": "array<object>", "description": "按指标聚合的查询结果行"},
                    "row_count": {"type": "integer", "description": "结果行数"},
                    "quality_status": {"type": "string", "description": "数据质量状态（complete/partial/unavailable）"},
                    "model_version": {"type": "string", "description": "发布版本，结果可溯源"},
                    "metrics": {"type": "array<string>", "description": "实际返回的指标编码列表"},
                },
                execution_detail=(
                    "执行链：SemanticQueryPlanner.compile → SQLAlchemy Core 组装 → 出口白名单断言（仅只读聚合 SELECT）→ SQL Server 执行\n"
                    "SQL 形态（按发布版本编译，运行时生成）：\n"
                    "  SELECT <指标聚合表达式> AS <metric_code>, COUNT(*) AS _anchor_count, ...\n"
                    "  FROM <object_code 对应发布数据集@发布版本>\n"
                    "  WHERE <anchor_field> = :anchor_value GROUP BY <数据集键>\n"
                    "数据集/字段表达式全部来自已发布语义模型，禁止绕过语义层直连出 SQL；\n"
                    "越界（对象/指标未发布、anchor 非法）由语义层 fail-closed 拒绝。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_query_semantic_metrics,
    )
