"""可信问题库存储端口（port/adapter 模式）。

遵循项目统一存储约定：默认 PostgreSQL，``USE_MEMORY_STORAGE=1`` 回退内存实现。
所有写操作携带乐观锁 ``expected_version``，冲突时抛 ``TrustedQuestionConflictError``。
状态机合法性由领域层 ``validate_transition`` 裁定，存储层只做执行与并发控制。
"""

from __future__ import annotations

from typing import Protocol

from src.domain.trusted_qa.models import (
    TrustedQuestion,
    TrustedQuestionStatus,
    TrustedQuestionSynonym,
)

__all__ = [
    "TrustedQuestionConflictError",
    "TrustedQuestionNotFoundError",
    "TrustedQuestionStorage",
]


class TrustedQuestionConflictError(ValueError):
    """可信问题 version 冲突或唯一性冲突。"""


class TrustedQuestionNotFoundError(LookupError):
    """可信问题不存在。"""


class TrustedQuestionStorage(Protocol):
    def save_question(self, question: TrustedQuestion) -> TrustedQuestion:
        """新建可信问题；question_id 已存在时抛 ConflictError。"""
        ...

    def get_question(self, question_id: str) -> TrustedQuestion | None:
        """按 question_id 取可信问题；不存在返回 None。"""
        ...

    def list_questions(
        self,
        *,
        status: TrustedQuestionStatus | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TrustedQuestion]:
        """列出可信问题；keyword 匹配标准问题与同义表达，按 created_at 倒序。"""
        ...

    def update_question(
        self, question: TrustedQuestion, *, expected_version: int
    ) -> TrustedQuestion:
        """乐观锁内容更新；仅 draft/pending_review 可编辑，新 version 必须递增 1。"""
        ...

    def transition_status(
        self,
        question_id: str,
        to_status: TrustedQuestionStatus,
        *,
        expected_version: int,
        operator: str = "",
        review_note: str | None = None,
    ) -> TrustedQuestion:
        """状态机流转（乐观锁）；approve/reject 记录 reviewed_by/reviewed_at。"""
        ...

    def add_synonym(
        self,
        question_id: str,
        synonym: TrustedQuestionSynonym,
        *,
        expected_version: int,
    ) -> TrustedQuestion:
        """追加同义表达（按 expression 去重）；active 状态也允许运营。"""
        ...

    def remove_synonym(
        self,
        question_id: str,
        expression: str,
        *,
        expected_version: int,
    ) -> TrustedQuestion:
        """移除同义表达；expression 不存在时抛 NotFoundError。"""
        ...
