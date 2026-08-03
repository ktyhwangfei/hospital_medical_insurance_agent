"""政策知识候选版与活动版的统一质量评测服务。"""
from __future__ import annotations

from itertools import combinations
from statistics import mean
from typing import Protocol
from uuid import uuid4

from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
    QualityCaseResult,
    QualityRun,
)
from src.knowledge_extension.rule_explanation.quality_store import PolicyQualityStore


class ReleaseSearchPort(Protocol):
    """按一个完整 release 的 collection 对执行检索，防止事实与规则串版。"""

    def search(self, release: KnowledgeRelease, case: PolicyQATestCase) -> list[str]: ...


class PolicyQualityService:
    def __init__(self, store: PolicyQualityStore, searcher: ReleaseSearchPort) -> None:
        self._store = store
        self._searcher = searcher

    def run_release(
        self,
        release_id: str,
        *,
        repeat_count: int = 3,
        minimum_quality: float = 0.8,
        minimum_consistency: float = 0.9,
    ) -> QualityRun:
        if repeat_count < 3:
            raise ValueError("统一测试至少重复运行 3 次")
        candidate = self._require_candidate(release_id)
        cases = self._store.list_test_cases(active_only=True)
        case_set_version = self._store.current_case_set_version()
        baseline = self._store.get_active_release()
        self._validate_comparison(candidate, baseline, case_set_version, cases)

        run = QualityRun(
            run_id=f"run_{uuid4().hex}",
            release_id=candidate.release_id,
            baseline_release_id=baseline.release_id if baseline else None,
            case_set_version=case_set_version,
            config_hash=candidate.config_hash,
            repeat_count=repeat_count,
            status="running",
        )
        self._store.save_run(run)
        self._store.save_release(candidate.model_copy(update={"status": "testing"}))

        candidate_results = self._evaluate(run, "candidate", candidate, cases)
        baseline_results = (
            self._evaluate(run, "baseline", baseline, cases) if baseline else []
        )
        all_results = [*candidate_results, *baseline_results]
        self._store.save_case_results(all_results)

        candidate_score = _mean_score(candidate_results)
        baseline_score = _mean_score(baseline_results) if baseline else None
        consistency = _repeat_consistency(candidate_results)
        blocked_reasons = self._blocked_reasons(
            cases=cases,
            candidate_results=candidate_results,
            candidate_score=candidate_score,
            baseline_score=baseline_score,
            consistency=consistency,
            minimum_quality=minimum_quality,
            minimum_consistency=minimum_consistency,
        )
        status = "failed" if blocked_reasons else "passed"
        finished = run.model_copy(update={
            "status": status,
            "candidate_score": candidate_score,
            "baseline_score": baseline_score,
            "consistency_score": consistency,
            "blocked_reasons": blocked_reasons,
        })
        self._store.save_run(finished)
        self._store.save_release(candidate.model_copy(update={
            "status": status,
            "quality_score": candidate_score,
            "consistency_score": consistency,
        }))
        return finished

    def _require_candidate(self, release_id: str) -> KnowledgeRelease:
        release = self._store.get_release(release_id)
        if release is None:
            raise ValueError(f"候选版本不存在: {release_id}")
        if release.status != "ready":
            raise ValueError(f"候选版本必须处于 ready 状态: {release.status}")
        return release

    @staticmethod
    def _validate_comparison(
        candidate: KnowledgeRelease,
        baseline: KnowledgeRelease | None,
        case_set_version: int,
        cases: list[PolicyQATestCase],
    ) -> None:
        if not cases:
            raise ValueError("没有可用的经典测试用例")
        if candidate.case_set_version != case_set_version:
            raise ValueError("候选版本的用例集版本不是当前版本")
        if baseline and baseline.config_hash != candidate.config_hash:
            raise ValueError("候选版本与当前版本的测试配置不一致")

    def _evaluate(
        self,
        run: QualityRun,
        target: str,
        release: KnowledgeRelease,
        cases: list[PolicyQATestCase],
    ) -> list[QualityCaseResult]:
        results: list[QualityCaseResult] = []
        for case in cases:
            for repeat_index in range(run.repeat_count):
                result_ids = self._searcher.search(release, case)
                score, passed, diagnostics = _score_result(
                    result_ids, case.expected_knowledge_ids
                )
                results.append(QualityCaseResult(
                    run_id=run.run_id,
                    target=target,
                    case_id=case.case_id,
                    repeat_index=repeat_index,
                    result_knowledge_ids=result_ids,
                    score=score,
                    passed=passed,
                    diagnostics=diagnostics,
                ))
        return results

    @staticmethod
    def _blocked_reasons(
        *,
        cases: list[PolicyQATestCase],
        candidate_results: list[QualityCaseResult],
        candidate_score: float,
        baseline_score: float | None,
        consistency: float,
        minimum_quality: float,
        minimum_consistency: float,
    ) -> list[str]:
        reasons: list[str] = []
        required_ids = {case.case_id for case in cases if case.required}
        if any(not result.passed for result in candidate_results if result.case_id in required_ids):
            reasons.append("必测用例未全部通过")
        if candidate_score < minimum_quality:
            reasons.append("候选质量低于绝对门槛")
        if consistency < minimum_consistency:
            reasons.append("重复运行一致性低于门槛")
        if baseline_score is not None and candidate_score <= baseline_score:
            reasons.append("候选质量必须严格高于当前版本")
        return reasons


def _score_result(
    result_ids: list[str], expected_ids: list[str]
) -> tuple[float, bool, dict[str, float]]:
    result = set(result_ids)
    expected = set(expected_ids)
    if not expected:
        score = 1.0 if not result else 0.0
        return score, not result, {"precision": score, "recall": 1.0, "f1": score}
    matched = result & expected
    precision = len(matched) / len(result) if result else 0.0
    recall = len(matched) / len(expected)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return f1, expected <= result, {
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _mean_score(results: list[QualityCaseResult]) -> float:
    return mean(result.score for result in results) if results else 0.0


def _repeat_consistency(results: list[QualityCaseResult]) -> float:
    by_case: dict[str, list[set[str]]] = {}
    for result in results:
        by_case.setdefault(result.case_id, []).append(set(result.result_knowledge_ids))
    similarities: list[float] = []
    for repetitions in by_case.values():
        for left, right in combinations(repetitions, 2):
            union = left | right
            similarities.append(len(left & right) / len(union) if union else 1.0)
    return mean(similarities) if similarities else 1.0
