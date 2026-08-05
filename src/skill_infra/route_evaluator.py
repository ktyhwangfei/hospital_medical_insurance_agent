"""基于不可变 Manifest 快照的确定性 Skill 路由评测。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillEvalDiff,
    SkillEvalMetrics,
    SkillEvalResult,
)
from src.skill_infra.skill_loader import LoadedSkill
from src.skill_infra.unified_router import compute_keyword_score


class RouteSuiteEvaluation(BaseModel):
    """一次纯函数评测的指标与逐案结果。"""

    model_config = ConfigDict(frozen=True)

    metrics: SkillEvalMetrics
    results: list[SkillEvalResult]


def _loaded_skill(manifest: Mapping[str, Any]) -> LoadedSkill:
    skill_id = str(manifest.get("skill_id") or "")
    return LoadedSkill(
        skill_id=skill_id,
        skill_name=str(manifest.get("skill_name") or skill_id),
        assembler=None,
        manifest=dict(manifest),
        include_keywords=[
            str(value) for value in (manifest.get("supported_intents") or [])
        ],
        excluded_intents=[
            str(value) for value in (manifest.get("excluded_intents") or [])
        ],
        business_action=str(manifest.get("business_action") or ""),
        business_object=str(manifest.get("business_object") or ""),
    )


def _route(
    question: str,
    manifests: Sequence[Mapping[str, Any]],
) -> tuple[str | None, float, list[str]]:
    matches: list[tuple[float, int, str, list[str]]] = []
    for manifest in manifests:
        skill = _loaded_skill(manifest)
        if not skill.skill_id:
            continue
        confidence, keywords = compute_keyword_score(question, skill)
        if confidence <= 0.0:
            continue
        matches.append((confidence, len(keywords), skill.skill_id, keywords))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if not matches:
        return None, 0.0, []
    confidence, _, skill_id, keywords = matches[0]
    return skill_id, min(round(confidence, 4), 1.0), keywords


def _diff(
    candidate_skill_id: str | None,
    baseline_skill_id: str | None,
    candidate_passed: bool,
    baseline_passed: bool,
) -> SkillEvalDiff:
    if candidate_passed and not baseline_passed:
        return SkillEvalDiff.NEW_PASS
    if baseline_passed and not candidate_passed:
        return SkillEvalDiff.NEW_FAILURE
    if candidate_skill_id != baseline_skill_id:
        return SkillEvalDiff.ROUTE_CHANGED
    if candidate_passed:
        return SkillEvalDiff.UNCHANGED_PASS
    return SkillEvalDiff.UNCHANGED_FAIL


def evaluate_route_suite(
    cases: Sequence[SkillEvalCase],
    candidate_manifests: Sequence[Mapping[str, Any]],
    baseline_manifests: Sequence[Mapping[str, Any]],
) -> RouteSuiteEvaluation:
    """比较候选与基线路由，并由服务端计算发布门禁。"""
    results: list[SkillEvalResult] = []
    for case in cases:
        candidate_id, candidate_confidence, candidate_keywords = _route(
            case.question_template, candidate_manifests
        )
        baseline_id, baseline_confidence, baseline_keywords = _route(
            case.question_template, baseline_manifests
        )
        candidate_passed = candidate_id == case.expected_skill_id
        baseline_passed = baseline_id == case.expected_skill_id
        results.append(
            SkillEvalResult(
                case_id=case.case_id,
                expected_skill_id=case.expected_skill_id,
                candidate_skill_id=candidate_id,
                baseline_skill_id=baseline_id,
                candidate_confidence=candidate_confidence,
                baseline_confidence=baseline_confidence,
                candidate_passed=candidate_passed,
                baseline_passed=baseline_passed,
                required=case.required,
                diff=_diff(
                    candidate_id,
                    baseline_id,
                    candidate_passed,
                    baseline_passed,
                ),
                candidate_keywords=candidate_keywords,
                baseline_keywords=baseline_keywords,
            )
        )

    total = len(results)
    passed = sum(result.candidate_passed for result in results)
    baseline_passed = sum(result.baseline_passed for result in results)
    required_results = [result for result in results if result.required]
    required_passed = sum(result.candidate_passed for result in required_results)
    regression_count = sum(
        result.diff == SkillEvalDiff.NEW_FAILURE for result in results
    )
    false_takeovers = sum(
        result.expected_skill_id is None
        and result.baseline_skill_id is None
        and result.candidate_skill_id is not None
        for result in results
    )
    accuracy = passed / total if total else 0.0
    baseline_accuracy = baseline_passed / total if total else 0.0
    gate_passed = bool(
        total
        and required_passed == len(required_results)
        and accuracy >= baseline_accuracy
        and false_takeovers == 0
    )
    return RouteSuiteEvaluation(
        metrics=SkillEvalMetrics(
            total=total,
            passed=passed,
            required_total=len(required_results),
            required_passed=required_passed,
            top1_accuracy=round(accuracy, 4),
            baseline_top1_accuracy=round(baseline_accuracy, 4),
            regression_count=regression_count,
            new_false_takeover_count=false_takeovers,
            gate_passed=gate_passed,
        ),
        results=results,
    )
