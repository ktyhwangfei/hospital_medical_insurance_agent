"""候选发布答案验证门禁服务。"""
from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from src.knowledge_extension.rule_explanation.answer_verification.gate_models import (
    AnswerVerificationCaseResult,
    AnswerVerificationRun,
)
from src.knowledge_extension.rule_explanation.answer_verification.gate_store import (
    AnswerVerificationGateStore,
)
from src.knowledge_extension.rule_explanation.answer_verification.models import (
    AnswerEvidenceRef,
    KnowledgeAnswerDimensionResult,
    KnowledgeAnswerEvalFailure,
    KnowledgeAnswerVerificationDimension,
    KnowledgeAnswerVerificationInput,
    KnowledgeAnswerVerificationResult,
    KnowledgeAnswerVerificationStatus,
    QueryPlanItem,
    RuleKnowledgePort,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    KnowledgeAnswerVerifier,
)
from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
)
from src.knowledge_extension.rule_explanation.quality_service import ReleaseSearchPort
from src.knowledge_extension.rule_explanation.quality_store import PolicyQualityStore


SUPPORTED_GATE_DIMENSIONS = {
    KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY,
    KnowledgeAnswerVerificationDimension.CONCLUSION_CONSISTENCY,
    KnowledgeAnswerVerificationDimension.CALCULATION_CONSISTENCY,
    KnowledgeAnswerVerificationDimension.COVERAGE_COMPLETENESS,
}
UNSUPPORTED_CITATION_SUPPORT_REASON = "维度 citation_support 尚未实现门禁支持"


class PolicyAnswerVerificationGateService:
    """基于经典测试夹具，对候选 release 执行确定性答案验证门禁。"""

    def __init__(
        self,
        quality_store: PolicyQualityStore,
        gate_store: AnswerVerificationGateStore,
        searcher: ReleaseSearchPort,
        rule_port_factory: Callable[[str], RuleKnowledgePort | None],
    ) -> None:
        self._quality_store = quality_store
        self._gate_store = gate_store
        self._searcher = searcher
        self._rule_port_factory = rule_port_factory

    def run_release(self, release_id: str) -> AnswerVerificationRun:
        """运行答案验证门禁；任何知识源异常均记录为阻断，不向 API 抛 500。"""
        release = self._require_release(release_id)
        cases = [
            case
            for case in self._quality_store.list_test_cases(active_only=True)
            if case.required
        ]
        case_set_version = self._quality_store.current_case_set_version()
        run_id = f"avrun_{uuid4().hex}"
        port_error: str | None = None
        try:
            port = self._rule_port_factory(release.rules_collection)
        except Exception as exc:
            port = None
            port_error = f"知识源异常: {type(exc).__name__}"

        case_results = [
            self._evaluate_case(run_id, release, case, port, port_error)
            for case in cases
        ]
        blocked_reasons = [
            f"{result.case_id}: {reason}"
            for result in case_results
            for reason in result.blocked_reasons
        ]
        status = "failed" if blocked_reasons else "passed"
        run = AnswerVerificationRun(
            run_id=run_id,
            release_id=release.release_id,
            case_set_version=case_set_version,
            status=status,
            blocked_reasons=blocked_reasons,
            quality_run_id=release.quality_run_id,
        )
        self._gate_store.save_run(run)
        self._gate_store.save_case_results(case_results)
        return run

    def _require_release(self, release_id: str) -> KnowledgeRelease:
        release = self._quality_store.get_release(release_id)
        if release is None:
            raise ValueError(f"候选版本不存在: {release_id}")
        if release.status not in {"ready", "failed", "passed"}:
            raise ValueError(f"候选版本状态不可运行答案验证门禁: {release.status}")
        return release

    def _evaluate_case(
        self,
        run_id: str,
        release: KnowledgeRelease,
        case: PolicyQATestCase,
        port: RuleKnowledgePort | None,
        port_error: str | None,
    ) -> AnswerVerificationCaseResult:
        fixture = case.answer_verification
        if fixture is None:
            return self._blocked_case(run_id, case.case_id, "缺少答案验证夹具")

        result_ids, search_error = self._safe_search(release, case)
        planned_queries = _actual_planned_queries(fixture.planned_queries, case, result_ids)
        missing_required_rules = _actual_missing_required_rules(case, result_ids)
        evidence, evidence_error = self._resolved_evidence(fixture.expected_evidence, port)
        envelope = KnowledgeAnswerVerificationInput(
            qa_turn_id=f"gate:{run_id}:{case.case_id}",
            question=case.query,
            answer=fixture.answer,
            answer_status="complete",
            citations=fixture.citations,
            internal_evidence=evidence,
            release_rules_collection=release.rules_collection,
            release_facts_collection=release.facts_collection,
            scenario=fixture.scenario,
            planned_queries=planned_queries,
            missing_required_rules=missing_required_rules,
            calculation_trace=fixture.calculation_trace,
        )
        try:
            verification = KnowledgeAnswerVerifier(port).verify(envelope)
        except Exception as exc:
            verification = _synthetic_verification(
                envelope.qa_turn_id,
                KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR,
                f"验证器异常: {type(exc).__name__}",
            )

        gated_dimensions = list(fixture.gated_dimensions)
        blocked_reasons = _gate_blocked_reasons(gated_dimensions, verification)
        skipped_dimensions = [
            dimension
            for dimension in SUPPORTED_GATE_DIMENSIONS
            if dimension not in gated_dimensions
        ]
        # 检索、知识源解析异常按 fail-closed 追加为阻断，绝不伪通过。
        for reason in (port_error, search_error, evidence_error):
            if reason:
                blocked_reasons.append(reason)
        status = "failed" if blocked_reasons else "passed"
        return AnswerVerificationCaseResult(
            run_id=run_id,
            case_id=case.case_id,
            status=status,
            gated_dimensions=gated_dimensions,
            skipped_dimensions=skipped_dimensions,
            blocked_reasons=blocked_reasons,
            verification=verification,
        )

    def _safe_search(
        self, release: KnowledgeRelease, case: PolicyQATestCase
    ) -> tuple[list[str], str | None]:
        try:
            return self._searcher.search(release, case), None
        except Exception as exc:
            return [], f"检索实跑异常: {type(exc).__name__}"

    def _resolved_evidence(
        self,
        expected: list[AnswerEvidenceRef],
        port: RuleKnowledgePort | None,
    ) -> tuple[list[AnswerEvidenceRef], str | None]:
        if not expected:
            return [], None
        if port is None:
            return [item.model_copy(deep=True) for item in expected], "规则知识源不可用"
        resolved: list[AnswerEvidenceRef] = []
        try:
            for item in expected:
                rule = port.get_rule_by_id(item.rule_id) if item.rule_id else None
                if rule is None:
                    resolved.append(item.model_copy(deep=True))
                    continue
                # source_text/hash 只来自候选 release 知识源；结构化结论字段保留夹具声明。
                resolved.append(item.model_copy(update={
                    "source_text": rule.source_text,
                    "source_text_hash": rule.source_text_hash,
                    "policy_id": item.policy_id or rule.policy_id,
                    "clause_id": item.clause_id or rule.clause_id,
                    "rule_instance_key": item.rule_instance_key or rule.rule_instance_key,
                    "query_name": item.query_name or rule.query_name,
                }))
        except Exception as exc:
            return resolved, f"规则知识源解析异常: {type(exc).__name__}"
        return resolved, None

    def _blocked_case(
        self, run_id: str, case_id: str, reason: str
    ) -> AnswerVerificationCaseResult:
        verification = _synthetic_verification(
            f"gate:{run_id}:{case_id}",
            KnowledgeAnswerVerificationStatus.BLOCKED_BY_EVALUATOR,
            reason,
        )
        return AnswerVerificationCaseResult(
            run_id=run_id,
            case_id=case_id,
            status="failed",
            blocked_reasons=[reason],
            verification=verification,
        )


def _actual_planned_queries(
    fixture_queries: list[QueryPlanItem],
    case: PolicyQATestCase,
    result_ids: list[str],
) -> list[QueryPlanItem]:
    hit_count = len(result_ids)
    if fixture_queries:
        return [query.model_copy(update={"hit_count": hit_count}) for query in fixture_queries]
    return [QueryPlanItem(query_name=case.mode, required=True, hit_count=hit_count)]


def _actual_missing_required_rules(
    case: PolicyQATestCase, result_ids: list[str]
) -> list[str]:
    fixture = case.answer_verification
    expected_rule_ids = (
        [item.rule_id for item in fixture.expected_evidence if item.rule_id]
        if fixture is not None
        else []
    )
    if not expected_rule_ids:
        expected_rule_ids = list(case.expected_knowledge_ids)
    found = set(result_ids)
    return [rule_id for rule_id in expected_rule_ids if rule_id not in found]


def _gate_blocked_reasons(
    gated_dimensions: list[KnowledgeAnswerVerificationDimension],
    verification: KnowledgeAnswerVerificationResult,
) -> list[str]:
    reasons: list[str] = []
    for dimension in gated_dimensions:
        if dimension == KnowledgeAnswerVerificationDimension.CITATION_SUPPORT:
            reasons.append(UNSUPPORTED_CITATION_SUPPORT_REASON)
            continue
        if dimension not in SUPPORTED_GATE_DIMENSIONS:
            reasons.append(f"维度 {dimension.value} 尚未实现门禁支持")
            continue
        result = verification.dimensions.get(dimension.value)
        if result is None:
            reasons.append(f"维度 {dimension.value} 未返回验证结果")
        elif result.status != KnowledgeAnswerVerificationStatus.PASSED:
            reasons.append(f"维度 {dimension.value} 未通过: {result.status.value}")
    return reasons


def _synthetic_verification(
    qa_turn_id: str,
    status: KnowledgeAnswerVerificationStatus,
    reason: str,
) -> KnowledgeAnswerVerificationResult:
    dimension = KnowledgeAnswerVerificationDimension.CITATION_AUTHENTICITY
    return KnowledgeAnswerVerificationResult(
        verification_id=f"kav_gate_{uuid4().hex}",
        qa_turn_id=qa_turn_id,
        status=status,
        dimensions={
            dimension.value: KnowledgeAnswerDimensionResult(
                dimension=dimension,
                status=status,
                failures=[KnowledgeAnswerEvalFailure("ANSWER_GATE_BLOCKED", reason)],
                details={"reason": reason},
            )
        },
    )
