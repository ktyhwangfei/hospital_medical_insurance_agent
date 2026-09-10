"""可信问题库内存存储 — 测试与 USE_MEMORY_STORAGE=1 回退。"""
from __future__ import annotations

from src.domain.question_library.models import (
    QuestionMatchEvent,
    QuestionMatchEventOutcome,
    QuestionMatchEventPage,
    QuestionRevisionConflictError,
    TrustedQuestion,
    TrustedQuestionNotFoundError,
    TrustedQuestionPage,
    TrustedQuestionStatus,
)


class InMemoryTrustedQuestionStorage:
    def __init__(self) -> None:
        self._questions: dict[str, TrustedQuestion] = {}
        self._events: list[QuestionMatchEvent] = []

    def insert_question(self, question: TrustedQuestion) -> TrustedQuestion:
        self._questions[question.question_id] = question
        return question

    def get_question(self, question_id: str) -> TrustedQuestion:
        question = self._questions.get(question_id)
        if question is None:
            raise TrustedQuestionNotFoundError(question_id)
        return question

    def list_questions(
        self,
        *,
        status: TrustedQuestionStatus | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TrustedQuestionPage:
        items = sorted(self._questions.values(), key=lambda item: item.updated_at, reverse=True)
        if status is not None:
            items = [item for item in items if item.status is status]
        if q:
            needle = q.strip().lower()
            items = [
                item for item in items
                if needle in item.standard_question.lower()
                or any(needle in synonym.lower() for synonym in item.synonyms)
            ]
        total = len(items)
        start = (page - 1) * page_size
        return TrustedQuestionPage(
            items=items[start:start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_published(self) -> list[TrustedQuestion]:
        return [item for item in self._questions.values() if item.status is TrustedQuestionStatus.PUBLISHED]

    def update_question(self, question: TrustedQuestion, *, expected_revision: int) -> TrustedQuestion:
        current = self.get_question(question.question_id)
        if current.revision != expected_revision:
            raise QuestionRevisionConflictError(question.question_id, expected_revision, current.revision)
        updated = question.model_copy(update={"revision": expected_revision + 1})
        self._questions[question.question_id] = updated
        return updated

    def list_texts(self, *, include_archived: bool = False) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for item in self._questions.values():
            if item.status is TrustedQuestionStatus.ARCHIVED and not include_archived:
                continue
            pairs.append((item.question_id, item.standard_question))
            pairs.extend((item.question_id, synonym) for synonym in item.synonyms)
        return pairs

    def record_match_event(self, event: QuestionMatchEvent) -> QuestionMatchEvent:
        self._events.append(event)
        return event

    def list_match_events(
        self,
        *,
        outcome: QuestionMatchEventOutcome | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> QuestionMatchEventPage:
        events = sorted(self._events, key=lambda item: item.created_at, reverse=True)
        if outcome is not None:
            events = [item for item in events if item.outcome is outcome]
        total = len(events)
        start = (page - 1) * page_size
        return QuestionMatchEventPage(
            items=events[start:start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )

    def count_questions_by_status(self) -> dict[str, int]:
        counts = {"draft": 0, "published": 0, "archived": 0}
        for item in self._questions.values():
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
        return counts

    def count_match_events(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._events:
            counts[item.outcome.value] = counts.get(item.outcome.value, 0) + 1
        return counts
