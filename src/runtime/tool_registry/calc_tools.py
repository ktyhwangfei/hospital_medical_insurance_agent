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
from src.runtime.policy_qa import settlement_record_lookup
from src.runtime.tool_registry.service import ToolRegistryService

TOOL_COMPARE_SETTLEMENT_VS_POLICY = "tool_compare_settlement_vs_policy"
TOOL_COMPARE_SAME_DRUG_ACROSS_SETTLEMENTS = "tool_compare_same_drug_across_settlements"


def _compare_settlement_vs_policy(settlement_fact: dict, policy_evidence: dict) -> dict:
    """包装 policy_qa 确定性对比：结算事实 vs 政策分段支付比例。"""
    from src.runtime.policy_qa.settlement_policy_compare import (
        compare_settlement_vs_policy,
    )

    return compare_settlement_vs_policy(settlement_fact, policy_evidence)


def register_calc_tools(registry: ToolRegistryService) -> None:
    registry.register(
        ToolVersion(
            version_id="tv_compare_settlement_vs_policy_2",
            tool_id=TOOL_COMPARE_SETTLEMENT_VS_POLICY,
            semantic_version="1.1.0",
            definition=ToolDefinition(
                tool_id=TOOL_COMPARE_SETTLEMENT_VS_POLICY,
                name="结算政策对比",
                description="确定性对比结算事实与政策证据的分段支付比例，输出结构化差异与结论（纯计算，无外部依赖）",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.settlement_policy_compare.compare_settlement_vs_policy",
                risk_level=ToolRiskLevel.LOW,
                tags=["对比计算类", "比例核验"],
                input_schema={
                    "settlement_fact": {
                        "type": "object",
                        "required": True,
                        "description": "结算事实（上游 tool_get_settlement_fact 输出），取统筹支付/医保内金额",
                    },
                    "policy_evidence": {
                        "type": "object",
                        "required": True,
                        "description": "政策证据（上游 tool_retrieve_policy_evidence 输出），取分段支付比例",
                    },
                },
                output_schema={
                    "comparisons": {"type": "array<object>", "description": "逐项对比明细（item/actual/expected/rule_ids/match/note）"},
                    "all_match": {"type": "boolean", "description": "全部对比项是否一致"},
                    "conclusion": {"type": "string", "description": "确定性对比结论（一致/差异待人工复核/字段缺失）"},
                    "comparison_count": {"type": "integer", "description": "对比项数"},
                },
                execution_detail=(
                    "核心公式（纯函数，无数据源、无 LLM，结论可溯源到 rule_id）：\n"
                    "  实际比例 actual = basic_pooling_payment / medical_insurance_inner_amount（统筹支付 ÷ 医保内金额）\n"
                    "  政策期望 expected = parse(payment_ratio)（'0.85'/'85%' → 0~1 浮点）\n"
                    "  一致判定 match = |actual - expected| <= 0.02（容差 RATIO_TOLERANCE = ±2%）\n"
                    "  all_match = 所有对比项均 match；无可用比例 → match=false（证据不足，不误报 complete）\n"
                    "结论三态：一致 / 差异或证据不足待人工复核 / 金额字段缺失无法对比。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=_compare_settlement_vs_policy,
    )
    registry.register(
        ToolVersion(
            version_id="tv_compare_same_drug_1",
            tool_id=TOOL_COMPARE_SAME_DRUG_ACROSS_SETTLEMENTS,
            semantic_version="1.0.0",
            definition=ToolDefinition(
                tool_id=TOOL_COMPARE_SAME_DRUG_ACROSS_SETTLEMENTS,
                name="同药跨单费用对比",
                description="按国标码对齐多张结算单的同一药品/项目，确定性对比单价/数量/医保内占比/先行自付，不引入 LLM 推断",
                contract_kind=ToolContractKind.FUNCTION,
                target_ref="src.runtime.policy_qa.settlement_record_lookup.compare_same_drug_across_settlements",
                risk_level=ToolRiskLevel.LOW,
                tags=["对比计算类", "同药跨单"],
                input_schema={
                    "settlement_ids": {
                        "type": "array<string>",
                        "required": True,
                        "description": "结算单号列表（至少两笔），如同一患者三次结算的单号",
                    },
                },
                output_schema={
                    "comparisons": {
                        "type": "array<object>",
                        "description": "逐项目对比（drug_key/item_name/settlement_ids/entries/differences/match）",
                    },
                    "comparison_count": {"type": "integer", "description": "跨单同码项目数"},
                    "all_match": {"type": "boolean", "description": "全部对比项是否一致（无跨单同码项目时为 null）"},
                    "conclusion": {"type": "string", "description": "确定性对比结论"},
                    "uncertainties": {"type": "array<string>", "description": "差异归因边界声明"},
                },
                execution_detail=(
                    "对齐与对比（纯函数，无 LLM；容差 DIFF_TOLERANCE = ±2%）：\n"
                    "  对齐键：NATION_CODE（国标码，盘点 100% 填充），回退 xmdm；\n"
                    "  分组后仅对比出现在 ≥2 张结算单的项目；\n"
                    "  逐项 flag：单价不一致 / 数量不一致 / 医保内占比不一致 / 先行自付不一致；\n"
                    "  差异归因（政策时段变化、乙类先行自付规则、年度累计）不在本工具范围，\n"
                    "  一律落 uncertainties 声明（T7/T8 权威规则未接入）。"
                ),
            ),
            status=ToolStatus.MATERIALIZED,
        ),
        implementation=settlement_record_lookup.compare_same_drug_across_settlements,
    )
