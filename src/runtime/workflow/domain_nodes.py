"""Workflow 内部确定性领域节点及其强类型契约。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from src.runtime.policy_qa.settlement_policy_compare import compare_settlement_vs_policy
from src.runtime.workflow.executor import DomainHandler

DOMAIN_HANDLER_VERSION = "1.0.0"
EVIDENCE_COMPLETENESS = "evidence_completeness"
SETTLEMENT_POLICY_COMPARE = "settlement_policy_compare"
EVIDENCE_MERGE = "evidence_merge"


class EvidenceCompletenessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_fact: dict[str, Any]
    policy_evidence: dict[str, Any]


class EvidenceCompletenessOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complete: bool
    missing_evidence: list[str]


class SettlementPolicyCompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_fact: dict[str, Any]
    policy_evidence: dict[str, Any]


class SettlementPolicyCompareOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparisons: list[dict[str, Any]]
    all_match: bool
    conclusion: str
    comparison_count: int


class EvidenceMergeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_evidence: dict[str, Any]
    comparison: dict[str, Any]
    evidence_check: dict[str, Any]


class EvidenceMergeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: list[dict[str, Any]]
    evidence_count: int
    comparisons: list[dict[str, Any]]
    all_match: bool
    conclusion: str
    missing_evidence: list[str]


def _check_evidence(
    settlement_fact: dict[str, Any], policy_evidence: dict[str, Any]
) -> dict[str, Any]:
    missing: list[str] = []
    if not settlement_fact.get("settlement_id"):
        missing.append("结算事实")
    if not policy_evidence.get("evidence"):
        missing.append("政策证据")
    return {"complete": not missing, "missing_evidence": missing}


def _compare(
    settlement_fact: dict[str, Any], policy_evidence: dict[str, Any]
) -> dict[str, Any]:
    return compare_settlement_vs_policy(settlement_fact, policy_evidence)


def _merge_evidence(
    policy_evidence: dict[str, Any],
    comparison: dict[str, Any],
    evidence_check: dict[str, Any],
) -> dict[str, Any]:
    evidence = list(policy_evidence.get("evidence") or [])
    return {
        "evidence": evidence,
        "evidence_count": len(evidence),
        "comparisons": list(comparison.get("comparisons") or []),
        "all_match": bool(comparison.get("all_match")),
        "conclusion": str(comparison.get("conclusion") or ""),
        "missing_evidence": list(evidence_check.get("missing_evidence") or []),
    }


DOMAIN_HANDLERS: dict[tuple[str, str], DomainHandler] = {
    (EVIDENCE_COMPLETENESS, DOMAIN_HANDLER_VERSION): DomainHandler(
        input_model=EvidenceCompletenessInput,
        output_model=EvidenceCompletenessOutput,
        implementation=_check_evidence,
    ),
    (SETTLEMENT_POLICY_COMPARE, DOMAIN_HANDLER_VERSION): DomainHandler(
        input_model=SettlementPolicyCompareInput,
        output_model=SettlementPolicyCompareOutput,
        implementation=_compare,
    ),
    (EVIDENCE_MERGE, DOMAIN_HANDLER_VERSION): DomainHandler(
        input_model=EvidenceMergeInput,
        output_model=EvidenceMergeOutput,
        implementation=_merge_evidence,
    ),
}
