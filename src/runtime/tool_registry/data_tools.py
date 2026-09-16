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
from src.runtime.policy_qa import settlement_record_lookup
from src.runtime.policy_qa.data_query_intent_parser import parse_data_query_intent
from src.runtime.tool_registry.service import ToolRegistryService

TOOL_QUERY_SEMANTIC_METRICS = "tool_query_semantic_metrics"
TOOL_PARSE_DATA_QUERY_INTENT = "tool_parse_data_query_intent"
TOOL_GET_FEE_DETAIL = "tool_get_fee_detail"
TOOL_GET_BENEFIT_STACKING = "tool_get_benefit_stacking"


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
    registry.register(
        ToolVersion(
            version_id="tv_get_fee_detail_1",
            tool_id=TOOL_GET_FEE_DETAIL,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_GET_FEE_DETAIL,
                name="查询费用明细",
                description="按结算单号查询逐项目费用明细（含国标码/数量/单价/医保内外/先行自付），住院与门诊双链路",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.settlement_record_lookup.get_fee_detail",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "费用明细"],
                input_schema={
                    "settlement_id": {
                        "type": "string",
                        "required": True,
                        "description": "结算单号（djh）",
                    },
                },
                output_schema={
                    "items": {
                        "type": "array<object>",
                        "description": "明细项（item_code/nation_code/item_name/quantity/unit_price/total_amount/insurance_inner_amount/insurance_outer_amount/pre_self_pay_amount/individual_first_self_pay/service_type）",
                    },
                    "item_count": {"type": "integer", "description": "明细条数"},
                    "service_type": {"type": "string", "description": "医疗类别（门诊/普通住院，按命中链路判定）"},
                    "conclusion": {"type": "string", "description": "摘要"},
                },
                execution_detail=(
                    "双链路只读查询（参数化，djh 锚点，2026-09-16 盘点 NATION_CODE 100% 填充）：\n"
                    "  住院：SELECT xh, xmdm, xmmc, NATION_CODE, sflb, sl, dj, zje, ybnje, ybwje, txfy, grziftw\n"
                    "    FROM dbo.yb_zyfymx WHERE djh = :settlement_id ORDER BY xh\n"
                    "  门诊（住院未命中时）：SELECT xh, xmdm, xmmc, NATION_CODE, sflb, sl, dj, zje, ybnje, ybwje, grziftw\n"
                    "    FROM dbo.yb_mzfymx WHERE djh = :settlement_id ORDER BY xh\n"
                    "同药对齐键：NATION_CODE（国标码），回退 xmdm；不含患者身份输出。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=settlement_record_lookup.get_fee_detail,
    )
    registry.register(
        ToolVersion(
            version_id="tv_get_benefit_stacking_1",
            tool_id=TOOL_GET_BENEFIT_STACKING,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_GET_BENEFIT_STACKING,
                name="查询待遇叠加分摊",
                description="按结算单查询特病登记状态与逐笔分摊事实（特病/大病/民政救助金额），低保维度缺数据时如实声明",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.settlement_record_lookup.get_benefit_stacking",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "待遇叠加"],
                input_schema={
                    "settlement_id": {
                        "type": "string",
                        "required": True,
                        "description": "结算单号（djh）",
                    },
                },
                output_schema={
                    "special_disease_registered": {"type": "boolean", "description": "是否有特病登记（tsb1-3）"},
                    "special_disease_codes": {"type": "array<string>", "description": "特病登记代码"},
                    "special_disease_inner_amount": {"type": "number", "description": "特病医保内分摊金额（tsbybn）"},
                    "big_ill_pay": {"type": "number", "description": "大病支付金额"},
                    "civil_assistance_amount": {"type": "number", "description": "民政救助金额（CIVIL_IN）"},
                    "low_income_flag": {"type": "string", "description": "低保标识（dbzbs，当前数据源无数据）"},
                    "conclusion": {"type": "string", "description": "实际分摊确定性摘要"},
                    "uncertainties": {"type": "array<string>", "description": "低保维度边界声明"},
                },
                execution_detail=(
                    "三表只读查询（djh 锚点）：\n"
                    "  登记：SELECT tsb1, tsb2, tsb3, dbzbs, CIVIL_TYPE FROM dbo.yb_brdjxx WHERE djh = :settlement_id\n"
                    "  住院分摊：SELECT BIG_ILL_PAY, CIVIL_IN, DB_PAY_TRUE, MAF_PAY_TRUE FROM dbo.yb_zyjyxx WHERE djh = :settlement_id\n"
                    "  门诊分摊（住院未命中）：SELECT tsbybn, tsbybw, BIG_ILL_PAY, CIVIL_IN FROM dbo.yb_mzjyxx WHERE djh = :settlement_id\n"
                    "边界：叠加顺序规则（T8）无权威来源，仅陈述实际分摊金额不做顺序归因；\n"
                    "低保 dbzbs 测试库全空，低保维度缺失即声明 uncertainties。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=settlement_record_lookup.get_benefit_stacking,
    )
    registry.register(
        ToolVersion(
            version_id="tv_parse_data_query_intent_1",
            tool_id=TOOL_PARSE_DATA_QUERY_INTENT,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_PARSE_DATA_QUERY_INTENT,
                name="解析运营问数意图",
                description="将自然语言问数映射到已发布的语义指标查询参数，不在目录内则澄清",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.data_query_intent_parser.parse_data_query_intent",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "语义层查询", "意图解析"],
                input_schema={
                    "question": {
                        "type": "string",
                        "required": True,
                        "description": "用户自然语言问数问题",
                    },
                },
                output_schema={
                    "object_code": {"type": "string", "description": "解析出的语义对象编码，未命中为空"},
                    "entity_code": {"type": "string", "description": "数据集/实体编码"},
                    "anchor_field": {"type": "string", "description": "锚点字段编码"},
                    "anchor_value": {"type": "string", "description": "锚点值"},
                    "metrics": {"type": "array<string>", "description": "已发布指标编码列表"},
                    "query_scope": {"type": "string", "description": "查询范围"},
                    "clarify": {"type": "boolean", "description": "是否需要澄清（指标不在目录内）"},
                },
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_parse_data_query_intent,
    )
