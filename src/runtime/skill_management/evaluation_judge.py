"""Skill 评测开放 Rubric 的严格 JSON Judge。"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.domain.skill.governance_models import SkillEvalTask, SkillEvalTaskStatus
from src.model_service.exceptions import ModelError
from src.model_service.gateway import ModelGateway
from src.model_service.models import Message
from src.runtime.policy_qa.public_contract import PolicyQAPublicResult


class SkillEvalJudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["passed", "failed", "blocked", "needs_review"]
    rubric_scores: dict[str, int]
    evidence_refs: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    model_name: str | None = None


class SkillEvalJudge:
    def __init__(
        self,
        gateway: ModelGateway | None = None,
        *,
        model_override: str | None = None,
    ) -> None:
        self._gateway = gateway or ModelGateway()
        self._model_override = model_override

    def evaluate(
        self,
        task: SkillEvalTask,
        public_result: PolicyQAPublicResult,
        *,
        rubric_id: str,
    ) -> SkillEvalJudgeResult:
        payload = {
            "question": task.input.question,
            "answer": public_result.answer,
            "answer_status": public_result.answer_status,
            "citations": [
                {"title": item.title, "excerpt": item.excerpt}
                for item in public_result.citations
            ],
            "rubric_id": rubric_id,
        }
        messages = [
            Message(
                role="system",
                content=(
                    "你是 Skill 评测 Judge。只输出符合 SkillEvalJudgeResult 的 JSON；"
                    "不得补写政策事实，不得把缺失证据判为通过。"
                ),
            ),
            Message(
                role="user",
                content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            ),
        ]
        try:
            response = self._gateway.generate(
                messages,
                model_type="llm",
                scene="skill_eval_judge",
                model_override=self._model_override,
            )
            result = SkillEvalJudgeResult.model_validate_json(response.content)
            return result.model_copy(update={"model_name": response.model_name})
        except (ModelError, ValidationError, json.JSONDecodeError) as exc:
            return SkillEvalJudgeResult(
                status="blocked",
                rubric_scores={},
                failure_codes=["JUDGE_UNAVAILABLE"],
                uncertainties=[str(exc)[:500]],
            )


def derive_task_status(
    *,
    deterministic_failures: list[str],
    judge: SkillEvalJudgeResult | None,
    judge_required: bool = True,
) -> SkillEvalTaskStatus:
    """确定性失败优先，Judge 绝不能覆盖金额或安全硬断言。"""
    if deterministic_failures:
        return SkillEvalTaskStatus.FAILED
    if judge is None or judge.status == "passed":
        return SkillEvalTaskStatus.PASSED
    if judge.status == "needs_review":
        return SkillEvalTaskStatus.NEEDS_REVIEW
    if judge.status == "blocked":
        return (
            SkillEvalTaskStatus.BLOCKED
            if judge_required
            else SkillEvalTaskStatus.PASSED
        )
    return (
        SkillEvalTaskStatus.FAILED
        if judge_required
        else SkillEvalTaskStatus.NEEDS_REVIEW
    )
