from typing import Protocol

from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleExplanationResult


class RuleExplainer(Protocol):
    def explain(self, request: RuleExplanationRequest) -> RuleExplanationResult: ...
