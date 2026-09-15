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


def register_builtin_tools(registry: ToolRegistryService) -> None:
    """登记内置 Tool。`tool_get_refund_record` 无既有数据源，故意不绑定实现，
    调用时由 Registry 抛出 ToolInvocationError，交由 Workflow 层降级为 unavailable。
    """
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
            version_id="tv_resolve_settlement_by_person_1",
            tool_id=TOOL_RESOLVE_SETTLEMENT_BY_PERSON,
            semantic_version="1.0.0",
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
                        "description": "患者ID，HIS 内部主键（人员唯一标识三选一）",
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
                    "无执行语句（fail-closed）：平台数据模型现状盘点——\n"
                    "  门诊 mz_trade 84 列无人员身份字段（无身份证/姓名/患者ID，锚点为 T_TradeNo/T_SetTid）；\n"
                    "  住院语义模型锚点为登记号 djh，语义字段无患者身份；\n"
                    "  PostgreSQL patients 表仅 patient_id+name（样例），insurance_transactions 为上传事务表（无金额/结算日期）。\n"
                    "绑定路径：HIS 患者主索引或医保结算身份字段接入后，实现 SettlementResolverPort 并绑定，\n"
                    "  目标查询形态：SELECT 结算单号, 结算日期, 总金额 FROM <结算事实表>\n"
                    "               WHERE <人员身份字段> = :id AND <就诊日期> BETWEEN <入院-结算区间>；\n"
                    "  硬约束：多笔命中 → multiple_candidates 供澄清；输出不回显身份证原文（脱敏规范）。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        )
    )

    registry.register(
        ToolVersion(
            version_id="tv_refund_record_3",
            tool_id=TOOL_GET_REFUND_RECORD,
            semantic_version="1.2.0",
            definition=ToolDefinition(
                tool_id=TOOL_GET_REFUND_RECORD,
                name="查询退费记录",
                description="查询指定结算单的退费/冲正记录（当前无既有数据源接入，故意不绑定实现）",
                contract_kind=ToolContractKind.ADAPTER_PORT,
                target_ref="src.adapters.ports.refund_record_port",
                risk_level=ToolRiskLevel.MEDIUM,
                tags=["数据类", "退费记录"],
                input_schema={
                    "settlement_id": {
                        "type": "string",
                        "required": True,
                        "description": "结算单号，定位其退费/冲正记录",
                    },
                },
                output_schema={
                    "records": {
                        "type": "array<object>",
                        "description": "退费/冲正记录列表（含退费时间/金额/原因），未接入数据源前恒 unavailable",
                    },
                },
                execution_detail=(
                    "无执行语句：目标 Adapter Protocol（src.adapters.ports.refund_record_port）尚无真实数据源接入，"
                    "故意不绑定实现；调用即 ToolInvocationError，Workflow 层降级为 unavailable（fail-closed，不编造结果）。"
                    "接入后执行方式由该 Protocol 实现决定并在此补充。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
    )
