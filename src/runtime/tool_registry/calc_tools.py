"""对比计算类 Tool 登记：包装 policy_qa 内的确定性对比计算，无外部数据源依赖。

输入全部来自上游步骤输出（结算事实 + 政策证据），输出结构化对比结论，
计算过程可复现、结论可溯源到 rule_id，不引入 LLM 推断。
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

TOOL_COMPARE_SETTLEMENT_VS_POLICY = "tool_compare_settlement_vs_policy"


def _compare_settlement_vs_policy(settlement_fact: dict, policy_evidence: dict) -> dict:
    """包装 policy_qa 确定性对比：结算事实 vs 政策分段支付比例。"""
    from src.runtime.policy_qa.settlement_policy_compare import (
        compare_settlement_vs_policy,
    )

    return compare_settlement_vs_policy(settlement_fact, policy_evidence)


def register_calc_tools(registry: ToolRegistryService) -> None:
    registry.register(
        ToolVersion(
            version_id="tv_compare_settlement_vs_policy_1",
            tool_id=TOOL_COMPARE_SETTLEMENT_VS_POLICY,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_COMPARE_SETTLEMENT_VS_POLICY,
                name="结算政策对比",
                description="确定性对比结算事实与政策证据的分段支付比例，输出结构化差异与结论（纯计算，无外部依赖）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.settlement_policy_compare.compare_settlement_vs_policy",
                risk_level=ToolRiskLevel.LOW,
                tags=["对比计算类", "比例核验"],
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_compare_settlement_vs_policy,
    )
