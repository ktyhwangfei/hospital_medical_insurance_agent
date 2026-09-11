"""可信问题库服务测试 — issue #37（审核生命周期 + 同义运营 + 执行绑定计划
+ 冷启动 + 越问越准事件留痕）。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.data_platform.storage.question_library.question_in_memory import (
    InMemoryTrustedQuestionStorage,
)
from src.domain.question_library.models import (
    InvalidQuestionTransitionError,
    QuestionMatchEventOutcome,
    QuestionMatchKind,
    QuestionRevisionConflictError,
    QuestionRoleForbiddenError,
    QuestionSynonymConflictError,
    TrustedQuestionDraft,
    TrustedQuestionStatus,
)
from src.runtime.question_library.service import QuestionLibraryService

NOW = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)


def _draft(standard: str = "本年度医保基金支付总额是多少", synonyms: list[str] | None = None,
           roles: list[str] | None = None) -> TrustedQuestionDraft:
    return TrustedQuestionDraft(
        standard_question=standard,
        synonyms=synonyms or [],
        roles=roles or [],
        object_code="mzjyxx",
        metrics=["fund_pay_total"],
        dimensions=[],
        time_scope="本年度",
        query_plan={
            "object_code": "mzjyxx",
            "scope": {"query_scope": "whole_settlement"},
            "metrics": ["fund_pay_total"],
            "group_by": [],
            "filters": [],
            "order_by": [],
            "limit": 100,
        },
        expected_result={"grain": ["全院"], "metrics": ["fund_pay_total"]},
    )


class _RecordingExecutor:
    def __init__(self, result=None):
        self.plans: list[dict] = []
        self._result = result or {
            "rows": [{"fund_pay_total": 123.45}],
            "quality_status": "complete",
        }

    def __call__(self, plan: dict) -> dict:
        self.plans.append(plan)
        return self._result


def _service(**kwargs) -> QuestionLibraryService:
    storage = InMemoryTrustedQuestionStorage()
    defaults = {
        "plan_validator": lambda plan: None,
        "query_executor": _RecordingExecutor(),
        "history_source": lambda: [],
        "now": lambda: NOW,
    }
    defaults.update(kwargs)
    return QuestionLibraryService(storage, **defaults)


def _publish(service: QuestionLibraryService, draft: TrustedQuestionDraft | None = None):
    question = service.create_draft(draft or _draft(), actor="engineer-1")
    return service.review(
        question.question_id, approve=True, reviewer="reviewer-1", expected_revision=1
    )


class TestCreateAndReview:
    def test_draft_created_with_defaults(self):
        service = _service()
        question = service.create_draft(_draft(), actor="engineer-1")
        assert question.status is TrustedQuestionStatus.DRAFT
        assert question.version == 1 and question.revision == 1
        assert question.reviewer is None

    def test_plan_validator_invoked(self):
        seen: list[dict] = []

        def validator(plan):
            seen.append(plan)

        service = _service(plan_validator=validator)
        draft = _draft()
        service.create_draft(draft, actor="engineer-1")
        assert seen == [draft.query_plan]

    def test_plan_validator_failure_blocks_draft(self):
        def validator(plan):
            raise ValueError("锚点字段未在已发布模型登记为 identifier")

        service = _service(plan_validator=validator)
        with pytest.raises(ValueError, match="锚点字段"):
            service.create_draft(_draft(), actor="engineer-1")
        assert service.list_questions().total == 0

    def test_review_approve_publishes_with_version_and_reviewer(self):
        service = _service()
        question = _publish(service)
        assert question.status is TrustedQuestionStatus.PUBLISHED
        assert question.reviewer == "reviewer-1"
        assert question.version == 2
        assert question.revision == 2

    def test_review_reject_archives(self):
        service = _service()
        draft = service.create_draft(_draft(), actor="engineer-1")
        question = service.review(
            draft.question_id, approve=False, reviewer="reviewer-1", expected_revision=1
        )
        assert question.status is TrustedQuestionStatus.ARCHIVED

    def test_review_only_from_draft(self):
        service = _service()
        question = _publish(service)
        with pytest.raises(InvalidQuestionTransitionError):
            service.review(
                question.question_id, approve=True, reviewer="reviewer-1", expected_revision=2
            )

    def test_review_revision_conflict(self):
        service = _service()
        draft = service.create_draft(_draft(), actor="engineer-1")
        with pytest.raises(QuestionRevisionConflictError):
            service.review(
                draft.question_id, approve=True, reviewer="reviewer-1", expected_revision=99
            )

    def test_archive_published_question(self):
        service = _service()
        question = _publish(service)
        archived = service.archive(question.question_id, expected_revision=2)
        assert archived.status is TrustedQuestionStatus.ARCHIVED

    def test_duplicate_normalized_text_rejected(self):
        service = _service()
        _publish(service)
        # 归一化后与已发布标准问题相同（仅标点差异）→ 冲突
        with pytest.raises(QuestionSynonymConflictError):
            service.create_draft(_draft(standard="本年度医保基金支付总额是多少！"), actor="engineer-1")

    def test_synonym_collision_rejected(self):
        service = _service()
        _publish(service, _draft(synonyms=["基金支付总额"]))
        with pytest.raises(QuestionSynonymConflictError):
            service.create_draft(_draft(standard="其他问题？", synonyms=["基金支付总额？"]), actor="engineer-1")


class TestMatchAndExecute:
    def test_match_hit_records_event(self):
        service = _service()
        question = _publish(service)
        outcome = service.match("本年度医保基金支付总额是多少？")
        assert outcome.kind is QuestionMatchKind.HIT
        events = service.list_match_events()
        assert events.total == 1
        assert events.items[0].outcome is QuestionMatchEventOutcome.HIT
        assert events.items[0].matched_question_id == question.question_id

    def test_match_clarify_records_event(self):
        service = _service()
        _publish(service)
        outcome = service.match("医保基金支付了多少")
        assert outcome.kind is QuestionMatchKind.CLARIFY
        events = service.list_match_events()
        assert events.items[0].outcome is QuestionMatchEventOutcome.CLARIFY
        assert events.items[0].matched_question_id is None

    def test_match_draft_not_matched(self):
        service = _service()
        service.create_draft(_draft(), actor="engineer-1")
        outcome = service.match("本年度医保基金支付总额是多少")
        # 草稿不可命中（未审核），也不出现在候选中
        assert outcome.kind is QuestionMatchKind.CLARIFY
        assert outcome.candidates == []

    def test_execute_runs_bound_plan_verbatim(self):
        executor = _RecordingExecutor()
        service = _service(query_executor=executor)
        question = _publish(service)
        result = service.execute(question.question_id)
        assert result["rows"][0]["fund_pay_total"] == 123.45
        # 核心不变量：执行的查询计划与存储计划逐字段一致（结果 100% 正确的机制）
        assert executor.plans == [question.query_plan]

    def test_execute_only_published(self):
        service = _service()
        draft = service.create_draft(_draft(), actor="engineer-1")
        with pytest.raises(InvalidQuestionTransitionError):
            service.execute(draft.question_id)

    def test_execute_role_forbidden(self):
        executor = _RecordingExecutor()
        service = _service(query_executor=executor)
        question = _publish(service, _draft(roles=["information_department"]))
        with pytest.raises(QuestionRoleForbiddenError):
            service.execute(question.question_id, roles=["doctor"])
        assert executor.plans == []

    def test_resolve_records_selected_event(self):
        service = _service()
        question = _publish(service)
        resolved = service.resolve(question.question_id, asked_text="基金支付总额")
        assert resolved.question_id == question.question_id
        events = service.list_match_events()
        assert events.items[0].outcome is QuestionMatchEventOutcome.SELECTED
        assert events.items[0].asked_text == "基金支付总额"


class TestSynonymOperations:
    def test_add_synonym_publishes_new_phasing(self):
        service = _service()
        question = _publish(service)
        updated = service.add_synonym(
            question.question_id, synonym="今年基金支付总额是多少", expected_revision=2
        )
        assert updated.synonyms == ["今年基金支付总额是多少"]
        # 新问法即刻可命中——越问越准闭环
        outcome = service.match("今年基金支付总额是多少？")
        assert outcome.kind is QuestionMatchKind.HIT

    def test_add_synonym_conflict_with_other_question(self):
        service = _service()
        first = _publish(service)
        second = _publish(service, _draft(standard="个人自付总额是多少？"))
        with pytest.raises(QuestionSynonymConflictError) as excinfo:
            service.add_synonym(
                second.question_id, synonym="本年度医保基金支付总额是多少", expected_revision=2
            )
        assert excinfo.value.existing_question_id == first.question_id

    def test_add_synonym_duplicate_within_same_question(self):
        service = _service()
        question = _publish(service, _draft(synonyms=["基金支付总额"]))
        with pytest.raises(QuestionSynonymConflictError):
            service.add_synonym(question.question_id, synonym="基金支付总额！", expected_revision=2)

    def test_add_synonym_archived_rejected(self):
        service = _service()
        question = _publish(service)
        service.archive(question.question_id, expected_revision=2)
        with pytest.raises(InvalidQuestionTransitionError):
            service.add_synonym(question.question_id, synonym="新问法", expected_revision=3)


class TestColdStartAndStats:
    def test_cold_start_groups_frequency_and_excludes_covered(self):
        history = [
            ("本年度医保基金支付总额是多少", "2026-09-01"),
            ("本年度医保基金支付总额是多少？", "2026-09-02"),
            ("本年度医保基金支付总额是多少！", "2026-09-03"),
            ("个人自付总额怎么查", "2026-09-02"),
        ]
        service = _service(history_source=lambda: history)
        _publish(service)  # 覆盖「本年度医保基金支付总额是多少」（归一化后同文）
        candidates = service.cold_start(limit=100)
        texts = [c.question_text for c in candidates]
        assert "个人自付总额怎么查" in texts
        assert all("医保基金支付总额" not in text for text in texts)

    def test_cold_start_respects_limit(self):
        history = [(f"问题{i}", "2026-09-02") for i in range(10)]
        service = _service(history_source=lambda: history)
        assert len(service.cold_start(limit=5)) == 5

    def test_cold_start_without_source_returns_empty(self):
        service = _service(history_source=None)
        assert service.cold_start() == []

    def test_stats_counts(self):
        service = _service()
        _publish(service)
        service.create_draft(_draft(standard="个人自付总额是多少？"), actor="engineer-1")
        service.match("本年度医保基金支付总额是多少")
        service.match("随便问点啥")
        stats = service.stats()
        assert stats.question_counts == {"draft": 1, "published": 1, "archived": 0}
        assert stats.match_event_counts == {"hit": 1, "clarify": 1}
