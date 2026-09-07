"""可信问题命中执行闭环（Issue #37 Slice 6）。

命中（matched）后回放可信问题携带的 SemanticQuery 快照，按
expected_result_traits 做确定性校验。校验不过或执行失败一律
如实上报，绝不伪造结果（来源可追溯约束）。
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.domain.trusted_qa.models import TrustedQuestion
from src.semantic_layer.query_planner import (
    SemanticQuery,
    SemanticQueryResult,
    SemanticQueryService,
)


class TrustedAnswerOutcome(StrEnum):
    """执行结果四态。

    - executed：执行成功且通过全部 expected_result_traits 校验
    - no_plan：可信问题未携带可回放的查询计划快照
    - trait_violation：执行成功但结果不满足声明的预期特征
    - execution_failed：语义层执行抛错（如实上报，不重试不伪造）
    """

    EXECUTED = "executed"
    NO_PLAN = "no_plan"
    TRAIT_VIOLATION = "trait_violation"
    EXECUTION_FAILED = "execution_failed"


class TrustedAnswerResult(BaseModel):
    """命中执行结果（DTO）。"""

    model_config = ConfigDict(frozen=True)

    outcome: TrustedAnswerOutcome
    question_id: str
    result: SemanticQueryResult | None = None
    violations: list[str] = Field(default_factory=list)


def _validate_traits(
    traits: dict,
    result: SemanticQueryResult,
) -> list[str]:
    """expected_result_traits 确定性校验，返回违例列表（空=通过）。

    支持的声明键：
    - allowed_quality: list[str]（默认 ["complete"]）——quality_status 白名单
    - min_rows / max_rows: int——结果行数上下界
    - required_columns: list[str]——每行必须出现的列名
    """
    violations: list[str] = []

    allowed_quality = traits.get("allowed_quality", ["complete"])
    if result.quality_status not in allowed_quality:
        violations.append(
            f"quality_status={result.quality_status} 不在允许集合 {allowed_quality}"
        )

    row_count = len(result.rows)
    min_rows = traits.get("min_rows")
    if min_rows is not None and row_count < int(min_rows):
        violations.append(f"行数 {row_count} 低于下限 {min_rows}")
    max_rows = traits.get("max_rows")
    if max_rows is not None and row_count > int(max_rows):
        violations.append(f"行数 {row_count} 超过上限 {max_rows}")

    required_columns: list[str] = list(traits.get("required_columns", []))
    if required_columns and result.rows:
        present = set().union(*(row.keys() for row in result.rows))
        missing = [c for c in required_columns if c not in present]
        if missing:
            violations.append(f"结果缺少声明列 {missing}")
    elif required_columns and not result.rows:
        violations.append(f"结果为空行，无法确认声明列 {required_columns}")

    return violations


def execute_trusted_answer(
    question: TrustedQuestion,
    service: SemanticQueryService,
) -> TrustedAnswerResult:
    """回放可信问题的查询计划快照并按预期特征校验。"""
    if question.query_plan is None:
        return TrustedAnswerResult(
            outcome=TrustedAnswerOutcome.NO_PLAN,
            question_id=question.question_id,
            violations=["可信问题未携带查询计划快照"],
        )

    try:
        # query_plan 为 SemanticQuery 声明式快照；LogicalQueryPlan 由 planner 确定性重放
        semantic_query = SemanticQuery.model_validate(question.query_plan)
    except ValidationError as exc:
        return TrustedAnswerResult(
            outcome=TrustedAnswerOutcome.NO_PLAN,
            question_id=question.question_id,
            violations=[f"查询计划快照无法解析: {exc.errors()[0]['msg']}"],
        )

    try:
        result = service.execute(semantic_query)
    except Exception as exc:
        return TrustedAnswerResult(
            outcome=TrustedAnswerOutcome.EXECUTION_FAILED,
            question_id=question.question_id,
            violations=[f"语义层执行失败: {type(exc).__name__}: {exc}"],
        )

    violations = _validate_traits(question.expected_result_traits, result)
    if violations:
        return TrustedAnswerResult(
            outcome=TrustedAnswerOutcome.TRAIT_VIOLATION,
            question_id=question.question_id,
            result=result,
            violations=violations,
        )
    return TrustedAnswerResult(
        outcome=TrustedAnswerOutcome.EXECUTED,
        question_id=question.question_id,
        result=result,
    )
