"""命中执行闭环 golden 用例集（Issue #37 Slice 6）。

验收口径：命中时结果必须来自 query_plan 快照回放且通过
expected_result_traits 校验；任何异常/违例如实上报，绝不伪造。
"""

from __future__ import annotations

from typing import Any, Literal

from src.domain.trusted_qa.models import TrustedQuestion, TrustedQuestionStatus
from src.runtime.trusted_qa.executor import (
    TrustedAnswerOutcome,
    execute_trusted_answer,
)
from src.semantic_layer.query_planner import (
    QueryEvidence,
    SemanticQueryResult,
    SemanticQueryService,
)

VALID_QUERY_PLAN: dict[str, Any] = {
    "object_code": "outpatient_settlement",
    "scope": {
        "entity_code": "settlement",
        "anchor": {"field_code": "settlement_id", "value": "E001"},
        "query_scope": "whole_settlement",
    },
    "metrics": ["total_cost"],
    "limit": 100,
}


def _make_result(
    rows: list[dict[str, Any]] | None = None,
    quality_status: Literal["complete", "partial", "unavailable"] = "complete",
) -> SemanticQueryResult:
    return SemanticQueryResult(
        rows=rows if rows is not None else [{"total_cost": 100.0}],
        model_version="v1",
        result_grain=["settlement"],
        query_scope="whole_settlement",
        quality_status=quality_status,
        evidence=QueryEvidence(plan_hash="h", datasets_used=["ds"]),
    )


class _StubService(SemanticQueryService):
    """不重连数据库的执行桩：返回预置结果或抛预置异常。"""

    def __init__(self, result: SemanticQueryResult | None = None, error: Exception | None = None):
        self._result = result
        self._error = error
        self.received_query: Any = None

    def execute(self, query: Any) -> SemanticQueryResult:
        self.received_query = query
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _question(
    query_plan: dict[str, Any] | None = VALID_QUERY_PLAN,
    traits: dict[str, Any] | None = None,
) -> TrustedQuestion:
    return TrustedQuestion(
        question_id="tq_golden_01",
        standard_question="统筹自付为什么这么多？",
        query_plan=query_plan,
        expected_result_traits=traits or {},
        status=TrustedQuestionStatus.ACTIVE,
        created_by="golden",
    )


class TestGoldenCases:
    def test_executed_happy_path(self) -> None:
        """命中 → 快照回放 → 默认要求 complete，通过即 executed。"""
        service = _StubService(result=_make_result())
        answer = execute_trusted_answer(_question(), service)
        assert answer.outcome == TrustedAnswerOutcome.EXECUTED
        assert answer.result is not None and answer.result.rows == [{"total_cost": 100.0}]
        assert answer.violations == []
        # 快照被解析为 SemanticQuery 回放
        assert service.received_query is not None
        assert service.received_query.object_code == "outpatient_settlement"

    def test_no_plan_snapshot(self) -> None:
        answer = execute_trusted_answer(_question(query_plan=None), _StubService())
        assert answer.outcome == TrustedAnswerOutcome.NO_PLAN
        assert answer.result is None

    def test_invalid_plan_snapshot(self) -> None:
        answer = execute_trusted_answer(
            _question(query_plan={"object_code": "x"}), _StubService()
        )
        assert answer.outcome == TrustedAnswerOutcome.NO_PLAN
        assert "无法解析" in answer.violations[0]

    def test_quality_not_in_allowed_set(self) -> None:
        service = _StubService(result=_make_result(quality_status="partial"))
        answer = execute_trusted_answer(_question(), service)
        assert answer.outcome == TrustedAnswerOutcome.TRAIT_VIOLATION
        assert any("quality_status" in v for v in answer.violations)

    def test_quality_allowed_set_relaxed(self) -> None:
        service = _StubService(result=_make_result(quality_status="partial"))
        answer = execute_trusted_answer(
            _question(traits={"allowed_quality": ["complete", "partial"]}), service
        )
        assert answer.outcome == TrustedAnswerOutcome.EXECUTED

    def test_row_bounds(self) -> None:
        rows = [{"total_cost": float(i)} for i in range(5)]
        service = _StubService(result=_make_result(rows=rows))
        answer = execute_trusted_answer(_question(traits={"max_rows": 3}), service)
        assert answer.outcome == TrustedAnswerOutcome.TRAIT_VIOLATION
        assert any("上限" in v for v in answer.violations)

        service_ok = _StubService(result=_make_result(rows=rows))
        answer_ok = execute_trusted_answer(
            _question(traits={"min_rows": 1, "max_rows": 10}), service_ok
        )
        assert answer_ok.outcome == TrustedAnswerOutcome.EXECUTED

    def test_required_columns_missing(self) -> None:
        service = _StubService(result=_make_result())
        answer = execute_trusted_answer(
            _question(traits={"required_columns": ["total_cost", "self_pay"]}), service
        )
        assert answer.outcome == TrustedAnswerOutcome.TRAIT_VIOLATION
        assert any("self_pay" in v for v in answer.violations)

    def test_required_columns_empty_rows(self) -> None:
        service = _StubService(result=_make_result(rows=[]))
        answer = execute_trusted_answer(
            _question(traits={"required_columns": ["total_cost"]}), service
        )
        assert answer.outcome == TrustedAnswerOutcome.TRAIT_VIOLATION

    def test_execution_failure_reported_honestly(self) -> None:
        """执行抛错如实上报 execution_failed，不伪造结果不重试。"""
        service = _StubService(error=RuntimeError("SQL Server 连接超时"))
        answer = execute_trusted_answer(_question(), service)
        assert answer.outcome == TrustedAnswerOutcome.EXECUTION_FAILED
        assert answer.result is None
        assert "连接超时" in answer.violations[0]

    def test_trait_violation_still_carries_result(self) -> None:
        """违例时保留原始结果供人工核查（可追溯），但绝不算 executed。"""
        service = _StubService(result=_make_result(quality_status="partial"))
        answer = execute_trusted_answer(_question(), service)
        assert answer.outcome == TrustedAnswerOutcome.TRAIT_VIOLATION
        assert answer.result is not None
