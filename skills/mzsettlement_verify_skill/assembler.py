"""门诊结算核验 Skill 的轻量装配入口。"""
from __future__ import annotations

from .models import OutpatientSettlementContext, OutpatientVerificationResult
from .strategies import ProfileStrategy


class OutpatientSettlementVerifierAssembler:
    """保持平台入口稳定，并把业务行为委托给 YAML 驱动策略。"""

    def __init__(self) -> None:
        self.strategy = ProfileStrategy()
        self.profile_ids = self.strategy.profile_ids

    def detect_profile(self, question: str) -> str | None:
        return self.strategy.detect_profile(question)

    def requires_human_confirmation(self, question: str) -> bool:
        return self.strategy.requires_human_confirmation(question)

    def build_semantic_queries(self, settlement_id: str, profile_id: str) -> list[object]:
        return self.strategy.build_semantic_queries(settlement_id, profile_id)

    def build_context(
        self, results: list[object], profile_id: str
    ) -> OutpatientSettlementContext:
        return self.strategy.build_context(results, profile_id)

    def build_policy_context(
        self, context: OutpatientSettlementContext, profile_id: str
    ) -> dict[str, str | bool | None]:
        return self.strategy.build_policy_context(context, profile_id)

    def build_policy_queries(
        self,
        profile_id: str,
        context: OutpatientSettlementContext | None = None,
    ) -> list[object]:
        return self.strategy.build_policy_queries(profile_id, context)

    def execute(
        self,
        context: OutpatientSettlementContext,
        *,
        profile_id: str = "overall-settlement-verification",
        policy_evidence: list[dict] | None = None,
    ) -> OutpatientVerificationResult:
        return self.strategy.execute(
            context,
            profile_id=profile_id,
            policy_evidence=policy_evidence,
        )


def load() -> OutpatientSettlementVerifierAssembler:
    """SkillLoader 动态加载入口。"""
    return OutpatientSettlementVerifierAssembler()
