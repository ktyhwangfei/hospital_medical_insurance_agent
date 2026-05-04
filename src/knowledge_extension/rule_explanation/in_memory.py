from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus
from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleExplanationResult, RuleType


class InMemoryRuleExplainer:
    def explain(self, request: RuleExplanationRequest) -> RuleExplanationResult:
        if request.rule_type is RuleType.ERROR_CODE and request.rule_code == "E001":
            return RuleExplanationResult(
                status=KnowledgeExtensionStatus.SUCCESS,
                rule_code=request.rule_code,
                meaning="错误码 E001 表示医保结算交易状态或费用状态需要核对。",
                conditions=["医保结算异常导办", "存在交易或收费状态不一致"],
                suggestions=["核查医保交易状态", "核查收费明细状态", "必要时由人工在既有系统处理"],
                limitations=["该解释仅作为导办建议，不代表医保正式裁决"],
                citations=[Citation(source_id="asset-error-code-001", source_type="error_code", title="医保错误码知识", version="2026.1", section="E001", evidence="错误码 E001 常见于交易状态异常")],
                audit_events=[AuditSummary(event_type="rule_explained", summary={"rule_code": request.rule_code})],
            )
        if request.rule_type is RuleType.DRG_DIP and request.rule_code == "DRG_LOSS_RISK":
            return RuleExplanationResult(
                status=KnowledgeExtensionStatus.SUCCESS,
                rule_code=request.rule_code,
                meaning="DRG/DIP 风险提示表示当前费用或诊断组合可能存在分组亏损风险。",
                conditions=["出院前联合质控", "存在 DRG/DIP 风险命中"],
                suggestions=["核查诊断、手术和费用明细完整性", "由人工在既有业务系统复核"],
                limitations=["不代表正式分组结果"],
                citations=[Citation(source_id="asset-audit-rule-001", source_type="audit_rule", title="出院前审核规则", version="2026.1", section="DRG/DIP", evidence="DRG/DIP 风险需人工复核")],
                requires_human_review=True,
                review_hint="该风险影响费用与分组判断，需要人工在既有系统复核。",
                audit_events=[AuditSummary(event_type="rule_explained", summary={"rule_code": request.rule_code})],
            )
        return RuleExplanationResult(
            status=KnowledgeExtensionStatus.NO_HIT,
            rule_code=request.rule_code,
            uncertainties=[f"未找到规则 {request.rule_code} 的可靠解释依据，建议人工复核"],
            requires_human_review=True,
            review_hint="规则未知或证据不足，不能生成确定性处理结论。",
            audit_events=[AuditSummary(event_type="rule_unknown", summary={"rule_code": request.rule_code})],
        )
