"""可信问题库存储端口 — issue #37。

trusted_questions 单表承载设计 §14.1 全部字段（同义表达/角色/指标/维度/
时间口径/筛选/查询计划/允许下钻/预期结果特征/审核人/版本）；question_match_events
追加留痕每次试问（hit/clarify/selected），支撑「越问越准」同义表达运营。
"""
from __future__ import annotations

from typing import Protocol

from src.domain.question_library.models import (
    QuestionMatchEvent,
    QuestionMatchEventOutcome,
    QuestionMatchEventPage,
    TrustedQuestion,
    TrustedQuestionPage,
    TrustedQuestionStatus,
)


class TrustedQuestionStorage(Protocol):
    """可信问题库存储契约。

    - insert_question：追加一行（question_id/revision 由服务层生成）；
    - update_question：仅当库内 revision == expected_revision 时写入并
      revision+1，不一致抛 QuestionRevisionConflictError，问题不存在抛
      TrustedQuestionNotFoundError；状态机合法性由服务层前置校验；
    - list_texts：返回全部（或非归档）问题的 (question_id, 标准问题/同义表达)
      原文对，服务层负责归一化后做同义冲突检测；
    - record_match_event / list_match_events：追加与按 outcome 过滤分页。
    """

    def insert_question(self, question: TrustedQuestion) -> TrustedQuestion: ...

    def get_question(self, question_id: str) -> TrustedQuestion: ...

    def list_questions(
        self,
        *,
        status: TrustedQuestionStatus | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TrustedQuestionPage: ...

    def list_published(self) -> list[TrustedQuestion]:
        """匹配引擎取数面：全部已发布问题（一期 50~100 条，全量可承受）。"""
        ...

    def update_question(
        self,
        question: TrustedQuestion,
        *,
        expected_revision: int,
    ) -> TrustedQuestion: ...

    def list_texts(self, *, include_archived: bool = False) -> list[tuple[str, str]]: ...

    def record_match_event(self, event: QuestionMatchEvent) -> QuestionMatchEvent: ...

    def list_match_events(
        self,
        *,
        outcome: QuestionMatchEventOutcome | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> QuestionMatchEventPage: ...

    def count_questions_by_status(self) -> dict[str, int]: ...

    def count_match_events(self) -> dict[str, int]: ...
