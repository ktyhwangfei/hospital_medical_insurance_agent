"""通过现有 Policy QA SSE 执行端到端 Skill 评测。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.domain.skill.governance_models import (
    RouteAssertions,
    SkillEvalAssertion,
    SkillEvalAssertionResult,
    SkillEvalStage,
    SkillEvalTask,
    SkillEvalTaskResult,
    SkillEvalTaskStatus,
    SkillEvalTrajectoryStep,
    canonical_eval_hash,
)
from src.domain.skill.regression_models import (
    AnswerQualityAssertions,
    SkillErrorDimension,
    SkillRegressionCase,
)
from src.runtime.policy_qa.models import PolicyQARequest
from src.runtime.policy_qa.public_contract import PolicyQAPublicResult
from src.runtime.skill_management.evaluation_attribution import attribute_failure
from src.runtime.skill_management.evaluation_judge import (
    SkillEvalJudge,
    derive_task_status,
)
from src.runtime.skill_management.regression_evaluators import (
    SkillRegressionEvaluatorRegistry,
)


class PolicyQAEvalPrefix(BaseModel):
    """同一次评测内可恢复的脱敏结算语义上下文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    boundary_kind: Literal["after_settlement_loaded"] = "after_settlement_loaded"
    rewritten_question: str = Field(min_length=1, max_length=2000)
    selected_skill_id: str = Field(min_length=1, max_length=128)
    profile_id: str | None = Field(default=None, max_length=128)
    settlement_context: dict[str, Any]


PolicyQAEvalObserver = Callable[[str, dict[str, Any]], None]
PolicyQAStreamFactory = Callable[
    [PolicyQARequest, PolicyQAEvalObserver, PolicyQAEvalPrefix | None],
    AsyncIterable[str],
]


def _real_policy_qa_stream(
    request: PolicyQARequest,
    observer: PolicyQAEvalObserver,
    prefix: PolicyQAEvalPrefix | None,
) -> AsyncIterable[str]:
    from src.runtime.api.policy_qa_routes import _policy_qa_stream

    return _policy_qa_stream(
        request,
        evaluation_observer=observer,
        evaluation_prefix=prefix,
    )


class PolicyQAEvaluationRunner:
    def __init__(
        self,
        *,
        stream_factory: PolicyQAStreamFactory = _real_policy_qa_stream,
        resume_factory: PolicyQAStreamFactory | None = None,
        evaluator_registry: SkillRegressionEvaluatorRegistry | None = None,
        judge: SkillEvalJudge | None = None,
    ) -> None:
        self._stream_factory = stream_factory
        self._resume_factory = resume_factory or stream_factory
        self._evaluators = evaluator_registry or SkillRegressionEvaluatorRegistry()
        self._judge = judge

    async def run(self, task: SkillEvalTask) -> SkillEvalTaskResult:
        result, prefix = await self._execute(
            task,
            self._stream_factory,
            None,
            run_judge=True,
        )
        declared = next(
            (
                item
                for item in task.trajectory_prefixes
                if item.boundary_kind == "after_settlement_loaded"
            ),
            None,
        )
        if result.status != SkillEvalTaskStatus.FAILED or declared is None or prefix is None:
            return result

        diagnostic, _ = await self._execute(
            task,
            self._resume_factory,
            prefix,
            run_judge=False,
        )
        if diagnostic.status == SkillEvalTaskStatus.PASSED:
            first = result.failure_attributions[0]
            attributions = (
                attribute_failure(
                    task_id=task.task_id,
                    failure_code=first.failure_code,
                    dimension=first.dimension,
                    evidence_refs=(declared.prefix_id,),
                    before_settlement_prefix=True,
                ),
            )
        else:
            attributions = result.failure_attributions
        return result.model_copy(
            update={
                "failure_attributions": attributions,
                "diagnostic_prefix_id": declared.prefix_id,
            }
        )

    async def _execute(
        self,
        task: SkillEvalTask,
        factory: PolicyQAStreamFactory,
        resume_prefix: PolicyQAEvalPrefix | None,
        *,
        run_judge: bool,
    ) -> tuple[SkillEvalTaskResult, PolicyQAEvalPrefix | None]:
        selected_skill_id: str | None = None
        settlement_found: bool | None = None
        captured_prefix: PolicyQAEvalPrefix | None = None
        trajectory: list[SkillEvalTrajectoryStep] = []

        def observe(event: str, payload: dict[str, Any]) -> None:
            nonlocal selected_skill_id, settlement_found, captured_prefix
            if event == "skill_selected":
                selected_skill_id = str(payload.get("skill_id") or "") or None
            if event == "settlement_loaded" and isinstance(payload.get("prefix"), dict):
                try:
                    captured_prefix = PolicyQAEvalPrefix.model_validate(payload["prefix"])
                except ValidationError:
                    captured_prefix = None
            if event == "settlement_loaded" and "record_found" in payload:
                settlement_found = bool(payload["record_found"])
            stage = _OBSERVER_STAGES.get(event)
            if stage is not None:
                trajectory.append(
                    SkillEvalTrajectoryStep(
                        task_id=task.task_id,
                        sequence=len(trajectory),
                        stage=stage,
                        status="completed",
                        action=event,
                        observation_summary=_observation_summary(event, payload),
                        observation_hash=canonical_eval_hash(payload),
                    )
                )

        events = await _consume_sse(
            factory(
                PolicyQARequest(
                    question=task.input.question,
                    settlement_id=task.input.settlement_id or "",
                    role=task.input.role,
                ),
                observe,
                resume_prefix,
            )
        )
        result_event = next((data for event, data in events if event == "result"), None)
        done_event = next((data for event, data in events if event == "done"), None)
        error_event = next((data for event, data in events if event == "error"), None)
        if result_event is None or done_event is None:
            return (
                SkillEvalTaskResult(
                    task_id=task.task_id,
                    status=SkillEvalTaskStatus.BLOCKED,
                    selected_skill_id=selected_skill_id,
                    trajectory=tuple(trajectory),
                    failure_attributions=(
                        attribute_failure(
                            task_id=task.task_id,
                            failure_code="EVALUATOR_STREAM_INCOMPLETE",
                            evidence_refs=(
                                str((error_event or {}).get("error_code")),
                            )
                            if (error_event or {}).get("error_code")
                            else (),
                        ),
                    ),
                ),
                captured_prefix,
            )

        if settlement_found is False:
            return (
                SkillEvalTaskResult(
                    task_id=task.task_id,
                    status=SkillEvalTaskStatus.INVALID_DATASET,
                    selected_skill_id=selected_skill_id,
                    trajectory=tuple(trajectory),
                    failure_attributions=(
                        attribute_failure(
                            task_id=task.task_id,
                            failure_code="DATASET_RESOURCE_NOT_FOUND",
                            evidence_refs=tuple(
                                f"{item.resource_type}:{item.resource_id}"
                                for item in task.data_locators
                            ),
                        ),
                    ),
                ),
                captured_prefix,
            )

        try:
            public_result = PolicyQAPublicResult.model_validate(result_event.get("result"))
        except ValidationError:
            return (
                SkillEvalTaskResult(
                    task_id=task.task_id,
                    status=SkillEvalTaskStatus.BLOCKED,
                    selected_skill_id=selected_skill_id,
                    trajectory=tuple(trajectory),
                    failure_attributions=(
                        attribute_failure(
                            task_id=task.task_id,
                            failure_code="EVALUATOR_RESULT_SCHEMA_INVALID",
                        ),
                    ),
                ),
                captured_prefix,
            )

        assertion_results = tuple(
            self._evaluate_assertion(task, assertion, public_result, selected_skill_id)
            for assertion in task.assertions
        )
        required_failed = any(
            assertion.required and result.status == SkillEvalTaskStatus.FAILED
            for assertion, result in zip(task.assertions, assertion_results, strict=True)
        )
        blocked = any(
            result.status == SkillEvalTaskStatus.BLOCKED for result in assertion_results
        )
        any_failed = any(
            result.status == SkillEvalTaskStatus.FAILED for result in assertion_results
        )
        status = (
            SkillEvalTaskStatus.BLOCKED
            if blocked
            else SkillEvalTaskStatus.FAILED
            if required_failed
            else SkillEvalTaskStatus.NEEDS_REVIEW
            if any_failed
            else SkillEvalTaskStatus.PASSED
        )
        rubric = next(
            (
                (index, assertion)
                for index, assertion in enumerate(task.assertions)
                if isinstance(assertion.expected, AnswerQualityAssertions)
                and assertion.expected.rubric_id
            ),
            None,
        )
        if run_judge and self._judge is not None and rubric is not None:
            rubric_index, rubric_assertion = rubric
            judge = await asyncio.to_thread(
                self._judge.evaluate,
                task,
                public_result,
                rubric_id=rubric_assertion.expected.rubric_id,
            )
            judge_codes = tuple(judge.failure_codes) or (
                ()
                if judge.status == "passed"
                else (f"JUDGE_{judge.status.upper()}",)
            )
            if judge_codes:
                judge_status = {
                    "failed": SkillEvalTaskStatus.FAILED,
                    "blocked": SkillEvalTaskStatus.BLOCKED,
                    "needs_review": SkillEvalTaskStatus.NEEDS_REVIEW,
                }.get(judge.status, SkillEvalTaskStatus.PASSED)
                updated = list(assertion_results)
                current = updated[rubric_index]
                updated[rubric_index] = current.model_copy(
                    update={
                        "status": judge_status,
                        "failure_codes": (*current.failure_codes, *judge_codes),
                    }
                )
                assertion_results = tuple(updated)
            if not required_failed and not blocked and not any_failed:
                status = derive_task_status(
                    deterministic_failures=[],
                    judge=judge,
                    judge_required=rubric_assertion.required,
                )
        attributions = tuple(
            attribute_failure(
                task_id=task.task_id,
                failure_code=code,
                dimension=result.dimension,
                evidence_refs=(result.assertion_id,),
            )
            for result in assertion_results
            for code in result.failure_codes
        )
        return (
            SkillEvalTaskResult(
                task_id=task.task_id,
                status=status,
                selected_skill_id=selected_skill_id,
                answer_excerpt=public_result.answer[:2000],
                assertion_results=assertion_results,
                trajectory=tuple(trajectory),
                failure_attributions=attributions,
            ),
            captured_prefix,
        )

    def _evaluate_assertion(
        self,
        task: SkillEvalTask,
        assertion: SkillEvalAssertion,
        public_result: PolicyQAPublicResult,
        selected_skill_id: str | None,
    ) -> SkillEvalAssertionResult:
        output = adapt_output(assertion.output_adapter, public_result, selected_skill_id)
        if isinstance(assertion.expected, RouteAssertions):
            expected = assertion.expected.expected_skill_id
            passed = selected_skill_id == expected
            failures = () if passed else ("ROUTE_SKILL_MISMATCH",)
            status = SkillEvalTaskStatus.PASSED if passed else SkillEvalTaskStatus.FAILED
        else:
            case_type = SkillErrorDimension(assertion.expected.case_type)
            case = SkillRegressionCase(
                case_id=assertion.assertion_id,
                target_skill_id=task.target_skill_id,
                case_type=case_type,
                input_template=task.input.model_dump(mode="json"),
                expected_assertions=assertion.expected,
                required=assertion.required,
                source_type="skill_eval_task",
                source_ref=task.task_id,
                source_hash=canonical_eval_hash(assertion.model_dump(mode="json")),
                confirmed_by="evaluation-runner",
            )
            evaluated = self._evaluators.evaluate(case, output)
            failures = tuple(evaluated.failure_codes)
            status = (
                SkillEvalTaskStatus.BLOCKED
                if evaluated.status == "blocked_by_evaluator"
                else SkillEvalTaskStatus.PASSED
                if evaluated.passed
                else SkillEvalTaskStatus.FAILED
            )
        actual = next(
            (output[key] for key in ("amount", "selected_skill_id", "status", "answer") if key in output),
            None,
        )
        return SkillEvalAssertionResult(
            assertion_id=assertion.assertion_id,
            dimension=assertion.dimension,
            status=status,
            actual_value=actual,
            failure_codes=failures,
        )


def adapt_output(
    adapter: str,
    public_result: PolicyQAPublicResult,
    selected_skill_id: str | None,
) -> dict[str, Any]:
    if adapter == "route":
        return {"selected_skill_id": selected_skill_id}
    if adapter == "self_pay_one":
        item = next(
            (
                value
                for value in public_result.field_explanations
                if value.field_name == "个人自付一"
            ),
            None,
        )
        return {"amount": None if item is None else item.value}
    if adapter == "citation":
        return {
            "sources": [item.title for item in public_result.policy_evidence],
            "supports_answer": bool(public_result.citations),
        }
    if adapter == "safety":
        return {
            "status": public_result.action_status or public_result.answer_status,
            "actions": [],
        }
    return {"answer": public_result.answer}


async def _consume_sse(stream: AsyncIterable[str]) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    buffer = ""
    async for chunk in stream:
        buffer += chunk.replace("\r\n", "\n")
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            event = "message"
            data_lines: list[str] = []
            for line in raw.splitlines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            if data_lines:
                try:
                    data = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    data = {}
                if isinstance(data, dict):
                    events.append((event, data))
    return events


_OBSERVER_STAGES = {
    "context_rewritten": SkillEvalStage.CONTEXT,
    "skill_selected": SkillEvalStage.ROUTING,
    "settlement_loaded": SkillEvalStage.SETTLEMENT_LOOKUP,
    "policy_retrieved": SkillEvalStage.POLICY_RETRIEVAL,
    "result_verified": SkillEvalStage.DETERMINISTIC_VERIFICATION,
}


def _observation_summary(event: str, payload: dict[str, Any]) -> str:
    if event == "skill_selected":
        return f"已选择 Skill：{payload.get('skill_id') or '未知'}"
    if event == "policy_retrieved":
        return f"已检索 {payload.get('policy_count', 0)} 条政策证据"
    return {
        "context_rewritten": "已使用结算语义补全问题",
        "settlement_loaded": "已加载结算业务语义",
        "result_verified": "已完成公开结果验证",
    }.get(event, event)
