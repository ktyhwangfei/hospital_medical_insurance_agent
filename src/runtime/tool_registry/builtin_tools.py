"""内置 Tool 登记（数据-结算事实/退费记录/人员定位结算单）：包装既有能力，供 Workflow 编排调用。

Registry 只做登记与调用转发，具体实现均来自既有模块，不新写业务逻辑。
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

from src.runtime.policy_qa import settlement_record_lookup

TOOL_GET_SETTLEMENT_FACT = "tool_get_settlement_fact"
TOOL_GET_REFUND_RECORD = "tool_get_refund_record"
TOOL_RESOLVE_SETTLEMENT_BY_PERSON = "tool_resolve_settlement_by_person"


async def _get_settlement_fact(settlement_id: str) -> dict:
    """包装既有结算数据 provider，返回可序列化的结算事实。

    输出字段对齐下游需要：政策检索的适用性维度（险种/医疗类别/医院等级/人员类别）
    与对比计算需要的金额字段（统筹支付/医保内金额/统筹自付）。
    """
    from src.runtime.policy_qa.settlement_data_provider import (
        create_settlement_data_provider,
    )

    provider = create_settlement_data_provider()
    context = await provider.get_settlement_context(settlement_id)
    return {
        "settlement_id": context.settlement_id,
        "person_type": context.person_type,
        "insurance_type": context.insurance_type,
        "service_type": context.service_type,
        "hospital_level": context.hospital_level,
        "settlement_date": context.settlement_date,
        "total_amount": context.total_amount,
        "medical_insurance_inner_amount": context.medical_insurance_inner_amount,
        "basic_pooling_payment": context.basic_pooling_payment,
        "basic_pooling_self_pay": context.basic_pooling_self_pay,
        "large_amount_payment": context.large_amount_payment,
        "large_amount_self_pay": context.large_amount_self_pay,
        "personal_total_pay": context.personal_total_pay,
        "deductible": context.deductible,
        "coverage_status": context.coverage_status,
    }


def _get_refund_record(
    settlement_id: str = "", id_card: str = "", insurance_card_no: str = "", visit_date: str = ""
) -> dict:
    """包装退费记录查询能力：住院 djh→tflydjh 医保端链路；门诊人员标识→HIS o_Trade 链路。"""
    return settlement_record_lookup.get_refund_record(
        settlement_id=settlement_id,
        id_card=id_card,
        insurance_card_no=insurance_card_no,
        visit_date=visit_date,
    )


def _resolve_settlement_by_person(
    *,
    id_card: str = "",
    patient_id: str = "",
    insurance_card_no: str = "",
    visit_date: str = "",
) -> dict:
    """包装人员定位结算单能力：门诊 o_Trade（P_IDNo/P_ICNo）+ 住院 yb_brdjxx（sfz/kh）。"""
    return settlement_record_lookup.resolve_settlement_by_person(
        id_card=id_card,
        patient_id=patient_id,
        insurance_card_no=insurance_card_no,
        visit_date=visit_date,
    )


def register_builtin_tools(registry: ToolRegistryService) -> None:
    """登记内置 Tool。全部绑定真实实现（2026-09-16 盘点后退费/人员定位已接入数据源）。"""
    registry.register(
        ToolVersion(
            version_id="tv_settlement_fact_3",
            tool_id=TOOL_GET_SETTLEMENT_FACT,
            semantic_version="1.2.0",
            definition=ToolDefinition(
                tool_id=TOOL_GET_SETTLEMENT_FACT,
                name="查询结算事实",
                description="包装既有结算数据 provider，返回结算单的适用性维度与统筹/自付金额事实字段",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "结算事实"],
                input_schema={
                    "settlement_id": {
                        "type": "string",
                        "required": True,
                        "description": "结算单号，来自会话上下文或用户澄清补充",
                    },
                },
                output_schema={
                    "settlement_id": {"type": "string", "description": "结算单号"},
                    "person_type": {"type": "string", "description": "人员类别（退休人员等，政策适用性维度）"},
                    "insurance_type": {"type": "string", "description": "险种（城镇职工等，政策适用性维度）"},
                    "service_type": {"type": "string", "description": "医疗类别（门诊/住院，政策适用性维度）"},
                    "hospital_level": {"type": "string", "description": "医院等级（政策适用性维度）"},
                    "settlement_date": {"type": "string", "description": "结算日期（政策有效期过滤维度）"},
                    "total_amount": {"type": "number", "description": "总金额"},
                    "medical_insurance_inner_amount": {"type": "number", "description": "医保内金额（比例分母）"},
                    "basic_pooling_payment": {"type": "number", "description": "统筹支付（比例分子）"},
                    "basic_pooling_self_pay": {"type": "number", "description": "统筹自付"},
                    "large_amount_payment": {"type": "number", "description": "大额支付"},
                    "large_amount_self_pay": {"type": "number", "description": "大额自付"},
                    "personal_total_pay": {"type": "number", "description": "个人总负担"},
                    "deductible": {"type": "number", "description": "起付线"},
                    "coverage_status": {"type": "string", "description": "待遇享受状态"},
                },
                execution_detail=(
                    "执行链：SemanticQueryPlanner.compile → SQLAlchemy Core 组装 → 出口白名单断言（仅只读聚合 SELECT，禁止 DML/DDL/注释/多语句）→ SQL Server 执行\n"
                    "SQL 形态（按发布版本编译，运行时生成）：\n"
                    "  SELECT SUM(<指标字段表达式>) AS <metric_code>, COUNT(*) AS _anchor_count, ...\n"
                    "  FROM <object_code=inpatient_settlement 对应发布数据集@发布版本>\n"
                    "  WHERE <anchor 字段> = :anchor_value GROUP BY <数据集键>\n"
                    "数据集/字段表达式全部来自已发布语义模型，未发布即拒；\n"
                    "完整性闸门：_anchor_count≠1→unavailable；分段缺失/重复键→unavailable；关联不完整→partial"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_get_settlement_fact,
    )

    registry.register(
        ToolVersion(
            version_id="tv_resolve_settlement_by_person_3",
            tool_id=TOOL_RESOLVE_SETTLEMENT_BY_PERSON,
            semantic_version="1.2.0",
            definition=ToolDefinition(
                tool_id=TOOL_RESOLVE_SETTLEMENT_BY_PERSON,
                name="人员定位结算单",
                description=(
                    "按身份证/患者ID/医保卡号（三选一）+ 就诊日期定位结算单："
                    "唯一命中返回 settlement_id，多笔返回候选供澄清（不确定不执行）"
                ),
                contract_kind=ToolContractKind.ADAPTER_PORT,
                target_ref="src.adapters.ports.settlement_resolver_port",
                risk_level=ToolRiskLevel.MEDIUM,
                tags=["数据类", "人员定位"],
                input_schema={
                    "id_card": {
                        "type": "string",
                        "required": False,
                        "description": "身份证号（人员唯一标识三选一；输出不回显原文）",
                    },
                    "patient_id": {
                        "type": "string",
                        "required": False,
                        "description": "患者ID，HIS 内部主键（当前数据源未启用该标识，保留占位）",
                    },
                    "insurance_card_no": {
                        "type": "string",
                        "required": False,
                        "description": "医保卡/社保卡号（人员唯一标识三选一）",
                    },
                    "visit_date": {
                        "type": "string",
                        "required": True,
                        "description": "就诊日期 YYYY-MM-DD；住院落在入院-结算区间内即命中",
                    },
                },
                output_schema={
                    "match_status": {
                        "type": "string",
                        "description": "定位结果（unique_match 唯一命中 / multiple_candidates 多笔待澄清 / no_match 无命中）",
                    },
                    "settlement_candidates": {
                        "type": "array<object>",
                        "description": "结算单候选（settlement_id/settlement_date/total_amount/service_type）；多笔时供人工选择，禁止自动选定执行",
                    },
                    "resolve_note": {
                        "type": "string",
                        "description": "定位说明（含数据源可用性声明）",
                    },
                },
                execution_detail=(
                    "双源映射化查询（表/列可按数据源映射 record_query_mappings 配置；只读 SELECT，参数化，输出不含身份原文）：\n"
                    "  门诊（HIS 交易表）：SELECT 交易号, 交易日期, 总金额 WHERE 交易日期窗口 AND (身份证号 = :id_card OR 医保卡号 = :card)\n"
                    "  住院（医保端登记表）：登记号, 入院日期, 出院日期 LEFT JOIN 住院结算表取总金额\n"
                    "    WHERE 入院日期 <= :visit_date AND (出院日期 IS NULL OR 出院日期 >= :visit_date) AND (身份证号 = :id_card OR 卡号 = :card)\n"
                    "硬约束：多笔命中 → multiple_candidates 供澄清，禁止自动选定执行；输出不回显身份证原文。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_resolve_settlement_by_person,
    )

    registry.register(
        ToolVersion(
            version_id="tv_refund_record_5",
            tool_id=TOOL_GET_REFUND_RECORD,
            semantic_version="1.4.0",
            definition=ToolDefinition(
                tool_id=TOOL_GET_REFUND_RECORD,
                name="查询退费记录",
                description="按结算单（住院 djh→tflydjh / HIS 交易号→退费交易对）或人员身份+就诊日期（门诊 HIS）查询已发生退费/冲正记录；门诊医保结算无身份时显式声明不可核对，不偺无退费结论",
                contract_kind=ToolContractKind.ADAPTER_PORT,
                target_ref="src.adapters.ports.refund_record_port",
                risk_level=ToolRiskLevel.MEDIUM,
                tags=["数据类", "退费记录"],
                input_schema={
                    "settlement_id": {
                        "type": "string",
                        "required": False,
                        "description": "结算单号（djh）：走医保端退费链路（住院 tflydjh）",
                    },
                    "id_card": {
                        "type": "string",
                        "required": False,
                        "description": "身份证号：与就诊日期配合走门诊 HIS 退费链路（输出不回显原文）",
                    },
                    "insurance_card_no": {
                        "type": "string",
                        "required": False,
                        "description": "医保卡/社保卡号：与身份证二选一",
                    },
                    "visit_date": {
                        "type": "string",
                        "required": False,
                        "description": "就诊日期 YYYY-MM-DD，门诊链路的过滤窗口",
                    },
                },
                output_schema={
                    "records": {
                        "type": "array<object>",
                        "description": "退费/冲正记录列表（trade_no/trade_date/fee_all/original_trade_no/partial_return_flag/refund_side）",
                    },
                    "refunded_count": {"type": "integer", "description": "命中退费相关交易笔数"},
                    "conclusion": {"type": "string", "description": "确定性摘要（有/无退费记录）"},
                    "uncertainties": {
                        "type": "array<string>",
                        "description": "边界声明（退费重算规则未接入，仅陈述事实不做金额归因）",
                    },
                },
                execution_detail=(
                    "三链路按结算侧别路由（表/列可按数据源映射 record_query_mappings 配置，换院零代码）：\n"
                    "  住院（医保端 djh）：SELECT jylsh, jyrq, zje, tflydjh FROM <住院结算表>\n"
                    "    WHERE tflydjh = :settlement_id AND tflydjh <> 0\n"
                    "  HIS 交易号：SELECT r.交易号, r.金额, r.原交易号, o.起付线, o.年度累计 FROM <门诊交易表> r\n"
                    "    LEFT JOIN <门诊交易表> o ON o.交易号 = r.原交易号 WHERE r.原交易号 = :trade_no\n"
                    "    （关联原交易取起付线/年度累计，供退费结算架构核验）\n"
                    "  人员身份+日期（门诊）：同表按 P_IDNo/P_ICNo + 日期窗口过滤退费相关交易\n"
                    "  （退费条件带整体括号：OR 链不被后续 AND 过滤吞掉）\n"
                    "边界：门诊医保结算（djh 在门诊结算表）无身份时显式声明不可核对；\n"
                    "退费重算规则（T7）未接入，结论仅陈述退费事实，不做金额重算归因（uncertainties 声明）。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_get_refund_record,
    )
