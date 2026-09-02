import json
from types import SimpleNamespace

import pytest

from src.domain.skill.governance_models import (
    SkillEvalAssertion,
    SkillEvalDimension,
    SkillEvalTask,
    SkillEvalTaskInput,
    SkillEvalTaskStatus,
    SkillEvalStage,
    TrajectoryPrefix,
)
from src.domain.skill.regression_models import (
    AnswerQualityAssertions,
    CalculationAssertions,
)
from src.runtime.policy_qa.public_contract import (
    OutpatientFieldExplanation,
    PolicyCitation,
    PolicyQAPublicResult,
    VerificationSummary,
)
from src.runtime.skill_management.evaluation_runner import (
    PolicyQAEvalPrefix,
    PolicyQAEvaluationRunner,
)
from src.runtime.skill_management.evaluation_attribution import cluster_failures
from src.runtime.skill_management.evaluation_judge import (
    SkillEvalJudge,
    SkillEvalJudgeResult,
    derive_task_status,
)


def _task(
    expected_value: float = 510.96,
    *,
    rubric_id: str | None = None,
) -> SkillEvalTask:
    return SkillEvalTask(
        task_id="EVT_person_21",
        suite_id="EVS_mz",
        target_skill_id="mzsettlement_verify_skill",
        name="人员类别 21 费用组成",
        input=SkillEvalTaskInput(
            question="费用组成",
            settlement_id="011100030X260417004975",
        ),
        assertions=(
            SkillEvalAssertion(
                assertion_id="self_pay_one",
                dimension=SkillEvalDimension.BEHAVIOR,
                output_adapter="self_pay_one",
                expected=CalculationAssertions(expected_value=expected_value),
            ),
            SkillEvalAssertion(
                assertion_id="answer",
                dimension=SkillEvalDimension.ANSWER_QUALITY,
                output_adapter="public_answer",
                expected=AnswerQualityAssertions(
                    answerable=True,
                    must_include=[str(expected_value)],
                    rubric_id=rubric_id,
                ),
            ),
        ),
        trajectory_prefixes=(
            TrajectoryPrefix(
                prefix_id="after_settlement_loaded",
                boundary_kind="after_settlement_loaded",
            ),
        ),
        created_by="quality-user",
        updated_by="quality-user",
    )


def _public_result(amount: float) -> PolicyQAPublicResult:
    return PolicyQAPublicResult(
        answer=f"个人自付一为 {amount} 元。",
        answer_status="complete",
        citations=[PolicyCitation(title="结算数据", excerpt="结算单原值")],
        verification_summary=VerificationSummary(
            settlement_checked=True,
            calculation_checked=True,
            policy_count=0,
            message="已核对",
        ),
        field_explanations=[
            OutpatientFieldExplanation(
                field_name="个人自付一",
                value=amount,
                state="non_zero",
                explanation="采用结算单原值。",
                citations=["settlement-data"],
            )
        ],
    )


def _stream_with_amount(amount: float):
    async def stream(request, observer, prefix):
        observer(
            "context_rewritten",
            {"question": f"门诊费用；用户问题：{request.question}"},
        )
        observer(
            "skill_selected",
            {
                "skill_id": "mzsettlement_verify_skill",
                "profile_id": "overall-settlement-verification",
            },
        )
        observer(
            "settlement_loaded",
            {
                "settlement_id": request.settlement_id,
                "prefix": PolicyQAEvalPrefix(
                    rewritten_question=f"门诊费用；用户问题：{request.question}",
                    selected_skill_id="mzsettlement_verify_skill",
                    profile_id="overall-settlement-verification",
                    settlement_context={
                        "record_found": True,
                        "self_pay_one": amount,
                    },
                ).model_dump(mode="json"),
            },
        )
        observer("policy_retrieved", {"policy_count": 0})
        public = _public_result(amount)
        observer(
            "result_verified",
            {"answer_status": public.answer_status},
        )
        yield "event: result\n"
        yield f"data: {json.dumps({'result': public.model_dump(mode='json')}, ensure_ascii=False)}\n\n"
        yield "event: done\n"
        yield 'data: {"success": true, "halt_reason": "verified"}\n\n'

    return stream


@pytest.mark.asyncio
async def test_runner_uses_public_result_and_hard_failure_wins() -> None:
    task = _task()
    runner = PolicyQAEvaluationRunner(stream_factory=_stream_with_amount(127.74))

    result = await runner.run(task)

    assert result.status == SkillEvalTaskStatus.FAILED
    assert result.selected_skill_id == "mzsettlement_verify_skill"
    assert "CALCULATION_TOLERANCE_EXCEEDED" in {
        code
        for assertion in result.assertion_results
        for code in assertion.failure_codes
    }
    clusters = cluster_failures(
        {task.task_id: task},
        list(result.failure_attributions),
    )
    calculation = next(
        item
        for item in clusters
        if item.failure_code == "CALCULATION_TOLERANCE_EXCEEDED"
    )
    assert calculation.task_ids == (task.task_id,)


@pytest.mark.asyncio
async def test_prefix_success_attributes_failure_before_boundary() -> None:
    runner = PolicyQAEvaluationRunner(
        stream_factory=_stream_with_amount(127.74),
        resume_factory=_stream_with_amount(510.96),
    )

    result = await runner.run(_task())

    assert result.status == SkillEvalTaskStatus.FAILED
    assert result.diagnostic_prefix_id == "after_settlement_loaded"
    assert result.failure_attributions[0].stage == SkillEvalStage.SETTLEMENT_LOOKUP
    assert result.failure_attributions[0].owner_type == "agent"


@pytest.mark.asyncio
async def test_runner_blocks_incomplete_sse_stream() -> None:
    async def incomplete_stream(request, observer, prefix):
        yield 'event: error\ndata: {"error_code": "POLICY_QA_FAILED"}\n\n'

    result = await PolicyQAEvaluationRunner(
        stream_factory=incomplete_stream,
    ).run(_task())

    assert result.status == SkillEvalTaskStatus.BLOCKED
    assert result.failure_attributions[0].failure_code == "EVALUATOR_STREAM_INCOMPLETE"
    assert result.failure_attributions[0].owner_type == "evaluator"


@pytest.mark.asyncio
async def test_runner_marks_missing_settlement_as_invalid_dataset() -> None:
    async def missing_settlement_stream(request, observer, prefix):
        observer(
            "skill_selected",
            {"skill_id": "mzsettlement_verify_skill"},
        )
        observer("settlement_loaded", {"record_found": False})
        payload = json.dumps({"result": _public_result(0).model_dump(mode="json")})
        yield f"event: result\ndata: {payload}\n\n"
        yield 'event: done\ndata: {"success": true}\n\n'

    result = await PolicyQAEvaluationRunner(
        stream_factory=missing_settlement_stream,
    ).run(_task())

    assert result.status == SkillEvalTaskStatus.INVALID_DATASET
    assert result.failure_attributions[0].owner_type == "dataset"


def test_judge_cannot_override_deterministic_failure() -> None:
    result = derive_task_status(
        deterministic_failures=["CALCULATION_TOLERANCE_EXCEEDED"],
        judge=SkillEvalJudgeResult(
            status="passed",
            rubric_scores={"clarity": 4},
        ),
    )

    assert result == SkillEvalTaskStatus.FAILED


def test_optional_judge_unavailable_does_not_block_hard_pass() -> None:
    result = derive_task_status(
        deterministic_failures=[],
        judge=SkillEvalJudgeResult(status="blocked", rubric_scores={}),
        judge_required=False,
    )

    assert result == SkillEvalTaskStatus.PASSED


@pytest.mark.asyncio
async def test_runner_calls_judge_once_without_overriding_hard_failure() -> None:
    class Judge:
        calls = 0

        def evaluate(self, task, public_result, *, rubric_id):
            self.calls += 1
            return SkillEvalJudgeResult(status="passed", rubric_scores={"clarity": 4})

    judge = Judge()
    result = await PolicyQAEvaluationRunner(
        stream_factory=_stream_with_amount(127.74),
        judge=judge,
    ).run(_task(rubric_id="clarity_v1"))

    assert judge.calls == 1
    assert result.status == SkillEvalTaskStatus.FAILED


def test_judge_blocks_invalid_json_at_model_boundary() -> None:
    class Gateway:
        def generate(self, messages, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(content="not-json", model_name="judge-model")

    gateway = Gateway()
    result = SkillEvalJudge(gateway=gateway, model_override="judge-v1").evaluate(
        _task(rubric_id="clarity_v1"),
        _public_result(510.96),
        rubric_id="clarity_v1",
    )

    assert result.status == "blocked"
    assert result.failure_codes == ["JUDGE_UNAVAILABLE"]
    assert gateway.kwargs == {
        "model_type": "llm",
        "scene": "skill_eval_judge",
        "model_override": "judge-v1",
    }
