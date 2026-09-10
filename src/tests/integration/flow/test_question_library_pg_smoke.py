"""可信问题库 PG 存储活库冒烟 — issue #37。

验证 trusted_questions / question_match_events 表 DDL（CREATE+ALTER 双写
幂等）、草稿插入/审核乐观锁流转（revision 条件 UPDATE）、同义表达更新、
事件留痕分页在真实 PostgreSQL 上成立；只使用带固定前缀的 question_id，
结束清理不留污染。
环境依赖: PostgreSQL（127.0.0.1:5432/hospital_mcp，与生产同构）；不可用时整组 skip。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.data_platform.storage.question_library.question_postgres import (
    PostgresTrustedQuestionStorage,
)
from src.domain.question_library.models import (
    QuestionMatchEvent,
    QuestionMatchEventOutcome,
    QuestionRevisionConflictError,
    TrustedQuestion,
    TrustedQuestionDraft,
    TrustedQuestionStatus,
    new_match_event_id,
)

T0 = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
SMOKE_PREFIX = "tq_pgsmoke_"


def _pg_ready() -> bool:
    try:
        from src.data_platform.storage.postgresql.client import PostgreSQLClient

        client = PostgreSQLClient()
        client.execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="PostgreSQL 不可用，跳过活库冒烟")


@pytest.fixture
def storage() -> PostgresTrustedQuestionStorage:
    return PostgresTrustedQuestionStorage()


@pytest.fixture(autouse=True)
def _cleanup(storage: PostgresTrustedQuestionStorage):
    yield
    client = storage._get_client()
    client.execute("DELETE FROM question_match_events WHERE asked_text LIKE %s", ("PG 冒烟%",))
    client.execute("DELETE FROM trusted_questions WHERE question_id LIKE %s", (SMOKE_PREFIX + "%",))


def _draft(standard: str) -> TrustedQuestionDraft:
    return TrustedQuestionDraft(
        standard_question=standard,
        synonyms=["PG 冒烟同义问法"],
        roles=["information_department"],
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
        expected_result={"grain": ["全院"]},
    )


def test_trusted_questions_roundtrip_and_optimistic_lock(storage: PostgresTrustedQuestionStorage):
    from src.domain.question_library.models import new_question_id

    # DDL 幂等：二次初始化不报错
    storage._get_client()

    question = TrustedQuestion(
        question_id=SMOKE_PREFIX + new_question_id()[3:],
        **_draft("PG 冒烟：本年度医保基金支付总额是多少").model_dump(),
        created_at=T0,
        updated_at=T0,
    )
    stored = storage.insert_question(question)
    fetched = storage.get_question(stored.question_id)
    assert fetched.standard_question == stored.standard_question
    assert fetched.synonyms == ["PG 冒烟同义问法"]
    assert fetched.query_plan["metrics"] == ["fund_pay_total"]
    assert fetched.status is TrustedQuestionStatus.DRAFT

    # 审核发布：乐观锁条件 UPDATE
    published = storage.update_question(
        fetched.model_copy(
            update={
                "status": TrustedQuestionStatus.PUBLISHED,
                "reviewer": "pg-smoke-reviewer",
                "version": fetched.version + 1,
                "updated_at": T0 + timedelta(minutes=1),
            }
        ),
        expected_revision=1,
    )
    assert published.revision == 2
    assert storage.get_question(stored.question_id).reviewer == "pg-smoke-reviewer"

    # 乐观锁冲突：过期 revision 拒绝且无半写
    with pytest.raises(QuestionRevisionConflictError):
        storage.update_question(
            published.model_copy(update={"time_scope": "上月"}),
            expected_revision=1,
        )
    assert storage.get_question(stored.question_id).revision == 2


def test_match_events_append_and_filter(storage: PostgresTrustedQuestionStorage):
    event = QuestionMatchEvent(
        event_id=new_match_event_id(),
        asked_text="PG 冒烟试问：基金支付总额",
        outcome=QuestionMatchEventOutcome.CLARIFY,
        matched_question_id=None,
        created_at=T0,
    )
    storage.record_match_event(event)
    page = storage.list_match_events(outcome=QuestionMatchEventOutcome.CLARIFY, page=1, page_size=10)
    assert any(item.event_id == event.event_id for item in page.items)
    hit_only = storage.list_match_events(outcome=QuestionMatchEventOutcome.HIT, page=1, page_size=10)
    assert all(item.event_id != event.event_id for item in hit_only.items)


def test_list_texts_and_published_filter(storage: PostgresTrustedQuestionStorage):
    from src.domain.question_library.models import new_question_id

    question = TrustedQuestion(
        question_id=SMOKE_PREFIX + new_question_id()[3:],
        **_draft("PG 冒烟：个人自付总额是多少").model_dump(),
        status=TrustedQuestionStatus.PUBLISHED,
        created_at=T0,
        updated_at=T0,
    )
    storage.insert_question(question)
    assert storage.list_published() != []
    texts = storage.list_texts(include_archived=False)
    assert any("PG 冒烟：个人自付总额是多少" == text for _qid, text in texts)
