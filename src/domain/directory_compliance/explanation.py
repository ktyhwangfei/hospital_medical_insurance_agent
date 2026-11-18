"""双方向解释组装（Issue #85，设计 V2.0 §8）。

确定性模板：数字与事实取自裁定结果，不经模型改写。
患者侧措辞纪律：
- 不出现"违规""开错""骗保""退费"等定性与承诺用语；
- 资料不足不等于有问题，必须如实说明"记录中未见"而非"不符合"；
- 有疑点时不影响已结算费用，引导至院内医保窗口/医保办人工核实。
"""
from __future__ import annotations

from src.domain.directory_compliance.models import (
    ComplianceRiskTier,
    LineComplianceResult,
    RuleStatus,
    VerdictStatus,
)

# 患者侧禁用词（断言用，防回归）
PATIENT_BANNED_WORDS = ("违规", "开错", "骗保", "退费", "罚款", "处罚")


def _money(value) -> str:
    return f"{value:.2f}"


def _condition_lines(result: LineComplianceResult) -> list[str]:
    lines = []
    for verdict in result.verdicts:
        span = verdict.condition.source_span
        if verdict.status == VerdictStatus.SUPPORTED:
            detail = verdict.evidence[0].summary if verdict.evidence else "有记录支持"
            lines.append(f"条件「{span}」：{detail}")
        elif verdict.status == VerdictStatus.CONTRADICTED:
            detail = verdict.evidence[0].summary if verdict.evidence else "与记录不一致"
            lines.append(f"条件「{span}」：{detail}")
        else:
            lines.append(f"条件「{span}」：{verdict.missing or '暂无法核验'}")
    return lines


def build_patient_explanation(result: LineComplianceResult) -> str:
    """患者方向解释：为什么这么收费 / 当前核实状态。"""
    name, fee, fee_out = result.item_name, result.fee, result.fee_out
    if result.rule_status != RuleStatus.PUBLISHED:
        return f"{name}：当前限制规则尚未完成审核，本次仅作草稿回放，暂不能据此确认是否符合支付条件。具体费用请参照本结算单费用解释。"
    if result.risk_tier == ComplianceRiskTier.CLEAR and result.explanation_ready:
        return (
            f"{name}：本次规则所覆盖的支付条件有记录支持。"
            f"本行记录费用 {_money(fee)} 元，其中医保内 {_money(result.fee_in)} 元、医保外 {_money(fee_out)} 元；"
            "具体负担类别和计算原因请参照原费用分解，不由条件核验结果推定。"
        )
    if result.risk_tier == ComplianceRiskTier.CONTRA and result.explanation_ready:
        return (
            f"{name} {_money(fee)} 元：该药的医保支付附带有特定使用条件，目前发现本次记录与条件存在不一致之处，"
            f"本次费用以结算单为准；如需了解该条件与费用处理的关系，可向医保窗口核实。"
        )
    # REVIEW / SUSPECT：资料不足或方向性疑点，对患者只陈述事实与核实渠道
    spans = "、".join(dict.fromkeys(v.condition.source_span for v in result.verdicts if v.status in (
        VerdictStatus.INSUFFICIENT_EVIDENCE, VerdictStatus.UNVERIFIABLE,
    )))
    return (
        f"{name} {_money(fee)} 元：该药的医保支付附带有特定使用条件，费用以结算单为准；"
        f"目前对「{spans}」尚缺足够的核验依据，这不代表存在问题，也不能据此确认条件符合。"
        f"如需补充核实，可向医保窗口了解所需资料。"
    )


def build_ops_explanation(result: LineComplianceResult) -> str:
    """医保办方向解释：事前审核提醒与原因（含证据链）。"""
    name = result.item_name
    header = {
        ComplianceRiskTier.CONTRA: f"核实线索：{name} 记录医保内 {_money(result.fee_in)} 元，所核验规则存在条件冲突，不等于基金损失或正式违规结论。",
        ComplianceRiskTier.SUSPECT: f"重点复核：{name} 按医保内结算 {_money(result.fee_in)} 元，存在方向性疑点。",
        ComplianceRiskTier.REVIEW: f"抽查建议：{name} 按医保内结算 {_money(result.fee_in)} 元，目录限制条件的支持证据不足。",
        ComplianceRiskTier.CLEAR: f"核验结果：{name} 记录医保内 {_money(result.fee_in)} 元，本次规则覆盖条件有记录支持。",
    }[result.risk_tier]
    lines = "；".join(_condition_lines(result))
    tail = "资料缺失不构成违规结论，建议调取病历或医嘱核实。" if result.risk_tier in (
        ComplianceRiskTier.REVIEW, ComplianceRiskTier.SUSPECT) else ""
    prefix = "草稿回放（规则未审核，不作正式结论）：" if result.rule_status != RuleStatus.PUBLISHED else ""
    return f"{prefix}{header}{lines}。{tail}".rstrip("。") + "。"
