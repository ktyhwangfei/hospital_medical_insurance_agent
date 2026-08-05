from src.domain.skill.governance_models import SkillEvalCase, SkillEvalDiff
from src.skill_infra.route_evaluator import evaluate_route_suite


def _case(
    question: str,
    expected_skill_id: str | None,
    *,
    required: bool = True,
) -> SkillEvalCase:
    return SkillEvalCase(
        case_id=question,
        suite_version=1,
        question_template=question,
        expected_skill_id=expected_skill_id,
        required=required,
        created_by="quality-user",
    )


def _manifest(skill_id: str, include_keywords: list[str]) -> dict[str, object]:
    return {
        "skill_id": skill_id,
        "skill_name": skill_id,
        "supported_intents": include_keywords,
        "excluded_intents": [],
    }


def test_evaluate_route_suite_marks_new_failure() -> None:
    case = _case("统筹自付怎么算", "settlement")
    baseline = [_manifest("settlement", ["统筹自付"])]
    candidate = [_manifest("settlement", ["起付线"])]

    evaluation = evaluate_route_suite([case], candidate, baseline)

    assert evaluation.metrics.required_passed == 0
    assert evaluation.metrics.regression_count == 1
    assert evaluation.metrics.gate_passed is False
    assert evaluation.results[0].diff == SkillEvalDiff.NEW_FAILURE


def test_gate_rejects_new_false_takeover() -> None:
    case = _case("今天天气怎么样", None)
    baseline = [_manifest("settlement", ["统筹自付"])]
    candidate = [_manifest("settlement", ["天气"])]

    evaluation = evaluate_route_suite([case], candidate, baseline)

    assert evaluation.metrics.new_false_takeover_count == 1
    assert evaluation.metrics.gate_passed is False
    assert evaluation.results[0].candidate_skill_id == "settlement"


def test_gate_passes_when_required_cases_pass_without_regression() -> None:
    cases = [
        _case("统筹自付怎么算", "settlement"),
        _case("今天天气怎么样", None),
    ]
    manifests = [_manifest("settlement", ["统筹自付"])]

    evaluation = evaluate_route_suite(cases, manifests, manifests)

    assert evaluation.metrics.required_passed == 2
    assert evaluation.metrics.top1_accuracy == 1.0
    assert evaluation.metrics.gate_passed is True
    assert {result.diff for result in evaluation.results} == {
        SkillEvalDiff.UNCHANGED_PASS
    }


def test_empty_suite_never_passes_release_gate() -> None:
    evaluation = evaluate_route_suite([], [], [])

    assert evaluation.metrics.total == 0
    assert evaluation.metrics.gate_passed is False
