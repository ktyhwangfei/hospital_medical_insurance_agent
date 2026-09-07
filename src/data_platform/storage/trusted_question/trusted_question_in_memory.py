"""开发与测试使用的可信问题库内存存储。

实现 ``TrustedQuestionStorage`` 端口，线程安全（RLock），所有返回值深拷贝，
避免外部修改污染存储状态。
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock

from src.data_platform.storage.trusted_question.trusted_question_ports import (
    TrustedQuestionConflictError,
    TrustedQuestionNotFoundError,
)
from src.domain.trusted_qa.models import (
    TrustedQuestion,
    TrustedQuestionStatus,
    TrustedQuestionSynonym,
    ensure_editable,
    validate_transition,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryTrustedQuestionStorage:
    """可信问题库内存存储（线程安全）。"""

    def __init__(self) -> None:
        self._questions: dict[str, TrustedQuestion] = {}
        self._lock = RLock()

    @staticmethod
    def _copy(value: TrustedQuestion) -> TrustedQuestion:
        return value.model_copy(deep=True)

    def save_question(self, question: TrustedQuestion) -> TrustedQuestion:
        with self._lock:
            if question.question_id in self._questions:
                raise TrustedQuestionConflictError(
                    f"可信问题已存在: {question.question_id}"
                )
            stored = self._copy(question)
            self._questions[question.question_id] = stored
            return self._copy(stored)

    def get_question(self, question_id: str) -> TrustedQuestion | None:
        with self._lock:
            question = self._questions.get(question_id)
            return None if question is None else self._copy(question)

    def list_questions(
        self,
        *,
        status: TrustedQuestionStatus | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TrustedQuestion]:
        with self._lock:
            result = []
            for question in self._questions.values():
                if status is not None and question.status != status:
                    continue
                if keyword and not self._matches_keyword(question, keyword):
                    continue
                result.append(self._copy(question))
            # 与 PG 适配器保持一致：created_at 倒序，question_id 升序兜底稳定排序
            # （利用 Python sort 稳定性：先按 question_id 升序，再按 created_at 倒序）
            result.sort(key=lambda q: q.question_id)
            result.sort(key=lambda q: q.created_at, reverse=True)
            return result[offset : offset + limit]

    @staticmethod
    def _matches_keyword(question: TrustedQuestion, keyword: str) -> bool:
        lowered = keyword.lower()
        if lowered in question.standard_question.lower():
            return True
        return any(lowered in s.expression.lower() for s in question.synonyms)

    def update_question(
        self, question: TrustedQuestion, *, expected_version: int
    ) -> TrustedQuestion:
        with self._lock:
            current = self._questions.get(question.question_id)
            if current is None:
                raise TrustedQuestionNotFoundError(
                    f"可信问题不存在: {question.question_id}"
                )
            ensure_editable(current.status)
            if current.version != expected_version:
                raise TrustedQuestionConflictError("可信问题 version 已变化")
            if question.version != expected_version + 1:
                raise TrustedQuestionConflictError("新 version 必须递增 1")
            stored = self._copy(question)
            self._questions[question.question_id] = stored
            return self._copy(stored)

    def transition_status(
        self,
        question_id: str,
        to_status: TrustedQuestionStatus,
        *,
        expected_version: int,
        operator: str = "",
        review_note: str | None = None,
    ) -> TrustedQuestion:
        with self._lock:
            current = self._questions.get(question_id)
            if current is None:
                raise TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}")
            validate_transition(current.status, to_status)
            if current.version != expected_version:
                raise TrustedQuestionConflictError("可信问题 version 已变化")
            now = _now()
            update: dict[str, object] = {
                "status": to_status,
                "version": current.version + 1,
                "updated_at": now,
            }
            # approve / reject 留痕审核人；retire 仅推进状态
            if to_status in (TrustedQuestionStatus.ACTIVE, TrustedQuestionStatus.DRAFT):
                update["reviewed_by"] = operator or current.reviewed_by
                update["reviewed_at"] = now
            if review_note is not None:
                update["review_note"] = review_note
            transitioned = current.model_copy(update=update, deep=True)
            self._questions[question_id] = transitioned
            return self._copy(transitioned)

    def add_synonym(
        self,
        question_id: str,
        synonym: TrustedQuestionSynonym,
        *,
        expected_version: int,
    ) -> TrustedQuestion:
        with self._lock:
            current = self._questions.get(question_id)
            if current is None:
                raise TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}")
            if current.version != expected_version:
                raise TrustedQuestionConflictError("可信问题 version 已变化")
            expressions = {s.expression for s in current.synonyms}
            synonyms = list(current.synonyms)
            if synonym.expression not in expressions:
                synonyms.append(synonym)
            return self._store_synonyms(current, synonyms)

    def remove_synonym(
        self,
        question_id: str,
        expression: str,
        *,
        expected_version: int,
    ) -> TrustedQuestion:
        with self._lock:
            current = self._questions.get(question_id)
            if current is None:
                raise TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}")
            if current.version != expected_version:
                raise TrustedQuestionConflictError("可信问题 version 已变化")
            synonyms = [s for s in current.synonyms if s.expression != expression]
            if len(synonyms) == len(current.synonyms):
                raise TrustedQuestionNotFoundError(f"同义表达不存在: {expression}")
            return self._store_synonyms(current, synonyms)

    def _store_synonyms(
        self, current: TrustedQuestion, synonyms: list[TrustedQuestionSynonym]
    ) -> TrustedQuestion:
        updated = current.model_copy(
            update={
                "synonyms": synonyms,
                "version": current.version + 1,
                "updated_at": _now(),
            },
            deep=True,
        )
        self._questions[current.question_id] = updated
        return self._copy(updated)
