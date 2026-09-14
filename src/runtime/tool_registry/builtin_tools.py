"""内置 Tool 登记（数据-结算事实/退费记录）：包装既有能力，供 Workflow 编排调用。

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
            version_id="tv_settlement_fact_2",
            tool_id=TOOL_GET_SETTLEMENT_FACT,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_GET_SETTLEMENT_FACT,
                name="查询结算事实",
                description="包装既有结算数据 provider，返回结算单的适用性维度与统筹/自付金额事实字段",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
                risk_level=ToolRiskLevel.LOW,
                tags=["数据类", "结算事实"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_get_settlement_fact,
    )

    registry.register(
        ToolVersion(
            version_id="tv_refund_record_2",
            tool_id=TOOL_GET_REFUND_RECORD,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_GET_REFUND_RECORD,
                name="查询退费记录",
                description="查询指定结算单的退费/冲正记录（当前无既有数据源接入，故意不绑定实现）",
                contract_kind=ToolContractKind.ADAPTER_PORT,
                target_ref="src.adapters.ports.refund_record_port",
                risk_level=ToolRiskLevel.MEDIUM,
                tags=["数据类", "退费记录"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
    )
