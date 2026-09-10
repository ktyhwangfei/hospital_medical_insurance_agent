"""可信问题库服务 — issue #37（审核流 + 同义表达运营 + 冷启动 + 执行）。"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any, Callable

from src.data_platform.storage.question_library.question_ports import TrustedQuestionStorage
from src.domain.question_library.models import (
    ColdStartCandidate,
    InvalidQuestionTransitionError,
    QuestionLibraryStats,
    QuestionMatchEvent,
    QuestionMatchEventOutcome,
    QuestionMatchEventPage,
    QuestionMatchKind,
    QuestionMatchOutcome,
    QuestionRevisionConflictError,
    QuestionRoleForbiddenError,
    QuestionSynonymConflictError,
    TrustedQuestion,
    TrustedQuestionDraft,
    TrustedQuestionNotFoundError,
    TrustedQuestionPage,
    TrustedQuestionStatus,
    new_match_event_id,
    new_question_id,
    normalize_question_text,
)
from src.runtime.question_library.matcher import QuestionMatcher


def utc_now() -> datetime:
    return datetime.now(UTC)


class QuestionLibraryService:
    """匹配（命中/澄清）+ 审核生命周期 + 越问越准同义运营 + 冷启动候选。

    plan_validator：创建草稿时对绑定查询计划做编译期校验（生产侧注入
    语义层 planner 干跑，测试注入 fake）；query_executor：命中/选中后执行
    绑定计划（生产侧注入 SemanticQueryService.execute，测试注入 fake 以
    断言「执行的 SemanticQuery 与存储计划逐字段一致」）。
    """

    def __init__(
        self,
        storage: TrustedQuestionStorage,
        *,
        plan_validator: Callable[[dict[str, Any]], None] | None = None,
        query_executor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        history_source: Callable[[], list[tuple[str, str]]] | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._storage = storage
        self._matcher = QuestionMatcher()
        self._plan_validator = plan_validator
        self._query_executor = query_executor
        self._history_source = history_source
        self._now = now

    # ── 匹配与执行 ──

    def match(self, asked_text: str, *, roles: list[str] | None = None) -> QuestionMatchOutcome:
        outcome = self._matcher.match(asked_text, self._storage.list_published(), roles=roles)
        self._storage.record_match_event(
            QuestionMatchEvent(
                event_id=new_match_event_id(),
                asked_text=asked_text,
                outcome=QuestionMatchEventOutcome.HIT
                if outcome.kind is QuestionMatchKind.HIT
                else QuestionMatchEventOutcome.CLARIFY,
                matched_question_id=outcome.question.question_id if outcome.question else None,
                created_at=self._now(),
            )
        )
        return outcome

    def resolve(self, question_id: str, *, asked_text: str | None = None) -> TrustedQuestion:
        """澄清后的显式选择：留痕 selected 事件，只允许已发布问题。"""
        question = self._require_published(question_id)
        self._storage.record_match_event(
            QuestionMatchEvent(
                event_id=new_match_event_id(),
                asked_text=asked_text or question.standard_question,
                outcome=QuestionMatchEventOutcome.SELECTED,
                matched_question_id=question.question_id,
                created_at=self._now(),
            )
        )
        return question

    def execute(self, question_id: str, *, roles: list[str] | None = None) -> dict[str, Any]:
        """执行绑定查询计划——计划在草稿期经编译校验、发布前经人工审核。"""
        question = self._require_published(question_id)
        if not question.applies_to_roles(roles):
            raise QuestionRoleForbiddenError(question_id, roles or [])
        if self._query_executor is None:
            raise RuntimeError("查询执行器未注入（query_executor）")
        return self._query_executor(question.query_plan)

    # ── 审核生命周期 ──

    def create_draft(self, draft: TrustedQuestionDraft, *, actor: str) -> TrustedQuestion:
        if self._plan_validator is not None:
            self._plan_validator(draft.query_plan)
        self._assert_texts_free([draft.standard_question, *draft.synonyms])
        now = self._now()
        question = TrustedQuestion(
            question_id=new_question_id(),
            **draft.model_dump(),
            created_at=now,
            updated_at=now,
        )
        return self._storage.insert_question(question)

    def review(
        self,
        question_id: str,
        *,
        approve: bool,
        reviewer: str,
        expected_revision: int,
    ) -> TrustedQuestion:
        """医保业务审核：通过 → published（version+1 记录审核人）；驳回 → archived。"""
        current = self._storage.get_question(question_id)
        if current.status is not TrustedQuestionStatus.DRAFT:
            raise InvalidQuestionTransitionError(question_id, "review", current.status)
        if not reviewer.strip():
            raise ValueError("审核人不能为空")
        now = self._now()
        if approve:
            updated = current.model_copy(
                update={
                    "status": TrustedQuestionStatus.PUBLISHED,
                    "reviewer": reviewer.strip(),
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
        else:
            updated = current.model_copy(
                update={
                    "status": TrustedQuestionStatus.ARCHIVED,
                    "reviewer": reviewer.strip(),
                    "updated_at": now,
                }
            )
        return self._storage.update_question(updated, expected_revision=expected_revision)

    def archive(self, question_id: str, *, expected_revision: int) -> TrustedQuestion:
        current = self._storage.get_question(question_id)
        if current.status is TrustedQuestionStatus.ARCHIVED:
            raise InvalidQuestionTransitionError(question_id, "archive", current.status)
        updated = current.model_copy(
            update={
                "status": TrustedQuestionStatus.ARCHIVED,
                "updated_at": self._now(),
            }
        )
        return self._storage.update_question(updated, expected_revision=expected_revision)

    def add_synonym(
        self,
        question_id: str,
        *,
        synonym: str,
        expected_revision: int,
    ) -> TrustedQuestion:
        """越问越准：把澄清事件中的真实问法固化为同义表达。"""
        current = self._storage.get_question(question_id)
        if current.status is TrustedQuestionStatus.ARCHIVED:
            raise InvalidQuestionTransitionError(question_id, "add_synonym", current.status)
        synonym = synonym.strip()
        if not synonym:
            raise ValueError("同义表达不能为空白")
        if normalize_question_text(synonym) in {
            normalize_question_text(current.standard_question),
            *(normalize_question_text(s) for s in current.synonyms),
        }:
            raise QuestionSynonymConflictError(synonym, question_id)
        self._assert_texts_free([synonym], exclude_question_id=question_id)
        updated = current.model_copy(
            update={
                "synonyms": [*current.synonyms, synonym],
                "updated_at": self._now(),
            }
        )
        return self._storage.update_question(updated, expected_revision=expected_revision)

    # ── 查询与统计 ──

    def get_question(self, question_id: str) -> TrustedQuestion:
        return self._storage.get_question(question_id)

    def list_questions(
        self,
        *,
        status: TrustedQuestionStatus | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TrustedQuestionPage:
        return self._storage.list_questions(status=status, q=q, page=page, page_size=page_size)

    def list_match_events(
        self,
        *,
        outcome: QuestionMatchEventOutcome | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> QuestionMatchEventPage:
        return self._storage.list_match_events(outcome=outcome, page=page, page_size=page_size)

    def stats(self) -> QuestionLibraryStats:
        return QuestionLibraryStats(
            question_counts=self._storage.count_questions_by_status(),
            match_event_counts=self._storage.count_match_events(),
        )

    def cold_start(self, *, limit: int = 100) -> list[ColdStartCandidate]:
        """从政策问答历史高频问题筛冷启动候选（issue #37：一期 50~100 条）。

        已被任何非归档问题文本（标准或同义）覆盖的问法不再出现在候选中。
        """
        if self._history_source is None:
            return []
        covered = {
            normalize_question_text(text)
            for _question_id, text in self._storage.list_texts(include_archived=False)
        }
        frequencies: Counter[str] = Counter()
        for question_text, _created_at in self._history_source():
            text = question_text.strip()
            if not text or normalize_question_text(text) in covered:
                continue
            frequencies[text] += 1
        return [
            ColdStartCandidate(question_text=text, frequency=count)
            for text, count in frequencies.most_common(limit)
        ]

    # ── 内部 ──

    def _require_published(self, question_id: str) -> TrustedQuestion:
        question = self._storage.get_question(question_id)
        if question.status is not TrustedQuestionStatus.PUBLISHED:
            raise InvalidQuestionTransitionError(question_id, "execute", question.status)
        return question

    def _assert_texts_free(self, texts: list[str], *, exclude_question_id: str | None = None) -> None:
        """同一归一化表达只能绑定一个问题（含草稿），防止命中歧义。"""
        owned: dict[str, str] = {}
        for question_id, text in self._storage.list_texts(include_archived=False):
            normalized = normalize_question_text(text)
            if normalized:
                owned.setdefault(normalized, question_id)
        if exclude_question_id is not None:
            current = self._storage.get_question(exclude_question_id)
            for text in [current.standard_question, *current.synonyms]:
                owned.pop(normalize_question_text(text), None)
        for text in texts:
            normalized = normalize_question_text(text)
            if normalized and normalized in owned:
                raise QuestionSynonymConflictError(text, owned[normalized])
