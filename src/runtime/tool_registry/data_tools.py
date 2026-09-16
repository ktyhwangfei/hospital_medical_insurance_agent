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
from src.runtime.policy_qa.data_query_intent_parser import parse_data_query_intent
from src.runtime.tool_registry.service import ToolRegistryService

TOOL_QUERY_SEMANTIC_METRICS = "tool_query_semantic_metrics"
TOOL_PARSE_DATA_QUERY_INTENT = "tool_parse_data_query_intent"
TOOL_QUERY_FLOW_METRICS = "tool_query_flow_metrics"


def _flow_query_service():
    """Flow 消费查询服务工厂 seam（测试 monkeypatch 此函数注入 stub）。"""
    from src.data_platform.storage.flow.flow_factory import (
        get_flow_view_reader,
        get_governed_flow_storage,
    )
    from src.runtime.flow.flow_query_service import FlowQueryService

    return FlowQueryService(get_governed_flow_storage(), get_flow_view_reader())


def _query_flow_metrics(
    metric_codes: list[str],
    dimensions: list[str] | None = None,
    caller_role: str | None = None,
    clarification_needed: bool = False,
    clarification_message: str | None = None,
) -> dict:
    """运营问数执行面：指标码 → Flow 已发布消费契约 → 受控视图（勾稽门禁在内）。

    与单笔锚点查询（SemanticQuery）不同，运营聚合问法无 anchor；
    消费契约白名单 + T8 防篡改 + 勾稽恒等门由 FlowQueryService 强制。
    上游澄清场景（无指标码）直接透传澄清话术为结论，诚实降级不猜数。
    """
    if not metric_codes:
        return {
            "rows": [],
            "metrics": [],
            "quality_status": "unavailable",
            "conclusion": clarification_message or "未能识别要查询的运营指标，请换一种方式提问。",
            "citations": [],
        }
    result = _flow_query_service().query_by_metrics(
        metric_codes, dimensions=dimensions, caller_role=caller_role,
    )
    payload = result.model_dump(mode="json")
    rows = payload.get("rows") or []
    first = rows[0] if rows else {}
    # 指标中文名映射（flow 定义的 metric_outputs），答案对用户可读
    names: dict[str, str] = {}
    try:
        from src.data_platform.storage.flow.flow_factory import get_governed_flow_storage

        flow = get_governed_flow_storage().get_flow(payload.get("flow_id") or "")
        if flow is not None:
            names = {m.metric_code: m.name for m in flow.metric_outputs}
    except Exception:
        pass
    # conclusion 供 workflow public_result 渲染为答案文本；citations 携带发布证据
    parts = [
        f"{names.get(code, code)}：{first.get(code)}"
        for code in payload.get("metrics", []) if code in first
    ]
    payload["conclusion"] = (
        f"{"、".join(parts)}（来源：{payload.get('view_name')}，质量 {payload.get('quality_status')}）"
        if parts else "查询完成，但结果为空。"
    )
    payload["citations"] = [{
        "flow_id": payload.get("flow_id"),
        "revision_id": payload.get("revision_id"),
        "artifact_hash": payload.get("artifact_hash"),
        "published_by": payload.get("published_by"),
        "published_at": payload.get("published_at"),
    }]
    return payload


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
            query_scope=query_scope,  # type: ignore[arg-type]
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


async def _parse_data_query_intent(question: str) -> dict:
    """包装 data_query_intent_parser：NL → 已发布语义指标参数。

    LLM 只做意图到受治理指标的映射；指标不在已发布目录内即返回澄清。
    """
    return await parse_data_query_intent(question)


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
    registry.register(
        ToolVersion(
            version_id="tv_parse_data_query_intent_2",
            tool_id=TOOL_PARSE_DATA_QUERY_INTENT,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_PARSE_DATA_QUERY_INTENT,
                name="解析运营问数意图",
                description="将自然语言问数映射到已发布的消费契约指标码，不在目录内则澄清",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.data_query_intent_parser.parse_data_query_intent",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "语义层查询", "意图解析"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_parse_data_query_intent,
    )
    registry.register(
        ToolVersion(
            version_id="tv_query_flow_metrics_1",
            tool_id=TOOL_QUERY_FLOW_METRICS,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_QUERY_FLOW_METRICS,
                name="运营指标受控查询",
                description="按 Flow 已发布消费契约指标码查询运营聚合结果（受控视图+勾稽门禁），禁止绕过 Flow 直连数据库",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.flow.flow_query_service.FlowQueryService.query_by_metrics",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "运营问数", "Flow消费"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_query_flow_metrics,
    )
