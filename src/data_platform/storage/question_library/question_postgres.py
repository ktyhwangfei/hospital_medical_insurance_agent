"""可信问题库 PostgreSQL 存储 — issue #37。

trusted_questions + question_match_events 双表；DDL 遵循 CREATE+ALTER
双写约定（AGENTS.md 已知陷阱：旧库加列必须 ALTER 同步，否则 INSERT 报
UndefinedColumn 500）。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
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

TRUSTED_QUESTIONS_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS trusted_questions (
        question_id VARCHAR(64) PRIMARY KEY,
        standard_question TEXT NOT NULL,
        synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
        roles JSONB NOT NULL DEFAULT '[]'::jsonb,
        object_code VARCHAR(128) NOT NULL,
        metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
        dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
        time_scope TEXT,
        filters JSONB NOT NULL DEFAULT '[]'::jsonb,
        query_plan JSONB NOT NULL,
        allow_drilldown BOOLEAN NOT NULL DEFAULT FALSE,
        expected_result JSONB NOT NULL DEFAULT '{}'::jsonb,
        reviewer VARCHAR(128),
        version INTEGER NOT NULL DEFAULT 1,
        status VARCHAR(32) NOT NULL DEFAULT 'draft',
        revision INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS question_id VARCHAR(64)",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS standard_question TEXT",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS synonyms JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS roles JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS object_code VARCHAR(128)",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS metrics JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS dimensions JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS time_scope TEXT",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS filters JSONB DEFAULT '[]'::jsonb",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS query_plan JSONB",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS allow_drilldown BOOLEAN DEFAULT FALSE",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS expected_result JSONB DEFAULT '{}'::jsonb",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS reviewer VARCHAR(128)",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'draft'",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 1",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_trusted_questions_status ON trusted_questions(status, updated_at DESC)",
)

QUESTION_MATCH_EVENTS_TABLE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS question_match_events (
        event_id VARCHAR(64) PRIMARY KEY,
        asked_text TEXT NOT NULL,
        outcome VARCHAR(16) NOT NULL,
        matched_question_id VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL
    )""",
    "ALTER TABLE question_match_events ADD COLUMN IF NOT EXISTS event_id VARCHAR(64)",
    "ALTER TABLE question_match_events ADD COLUMN IF NOT EXISTS asked_text TEXT",
    "ALTER TABLE question_match_events ADD COLUMN IF NOT EXISTS outcome VARCHAR(16)",
    "ALTER TABLE question_match_events ADD COLUMN IF NOT EXISTS matched_question_id VARCHAR(64)",
    "ALTER TABLE question_match_events ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ",
    "CREATE INDEX IF NOT EXISTS idx_question_match_events_outcome ON question_match_events(outcome, created_at DESC)",
)

_QUESTION_COLUMNS = (
    "question_id, standard_question, synonyms, roles, object_code, metrics, dimensions, "
    "time_scope, filters, query_plan, allow_drilldown, expected_result, reviewer, "
    "version, status, revision, created_at, updated_at"
)

_EVENT_COLUMNS = "event_id, asked_text, outcome, matched_question_id, created_at"


def _row_to_question(row: dict[str, Any]) -> TrustedQuestion:
    return TrustedQuestion(
        question_id=row["question_id"],
        standard_question=row["standard_question"],
        synonyms=list(row["synonyms"] or []),
        roles=list(row["roles"] or []),
        object_code=row["object_code"],
        metrics=list(row["metrics"] or []),
        dimensions=list(row["dimensions"] or []),
        time_scope=row["time_scope"],
        filters=list(row["filters"] or []),
        query_plan=dict(row["query_plan"] or {}),
        allow_drilldown=bool(row["allow_drilldown"]),
        expected_result=dict(row["expected_result"] or {}),
        reviewer=row["reviewer"],
        version=int(row["version"]),
        status=TrustedQuestionStatus(row["status"]),
        revision=int(row["revision"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_event(row: dict[str, Any]) -> QuestionMatchEvent:
    return QuestionMatchEvent(
        event_id=row["event_id"],
        asked_text=row["asked_text"],
        outcome=QuestionMatchEventOutcome(row["outcome"]),
        matched_question_id=row["matched_question_id"],
        created_at=row["created_at"],
    )


class PostgresTrustedQuestionStorage:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            for statement in TRUSTED_QUESTIONS_TABLE_SCHEMA:
                self._client.execute(statement)
            for statement in QUESTION_MATCH_EVENTS_TABLE_SCHEMA:
                self._client.execute(statement)
        return self._client

    def insert_question(self, question: TrustedQuestion) -> TrustedQuestion:
        client = self._get_client()
        client.execute(
            f"INSERT INTO trusted_questions ({_QUESTION_COLUMNS}) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            _question_params(question),
        )
        return question

    def get_question(self, question_id: str) -> TrustedQuestion:
        rows = self._get_client().execute(
            f"SELECT {_QUESTION_COLUMNS} FROM trusted_questions WHERE question_id = %s",
            (question_id,),
        )
        if not rows:
            raise TrustedQuestionNotFoundError(question_id)
        return _row_to_question(rows[0])

    def list_questions(
        self,
        *,
        status: TrustedQuestionStatus | None = None,
        q: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> TrustedQuestionPage:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status.value)
        if q:
            clauses.append("(position(%s in standard_question) > 0 OR position(%s IN synonyms::text) > 0)")
            needle = q.strip().lower()
            params.extend([needle, needle])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total_rows = self._get_client().execute(
            f"SELECT COUNT(*) AS total FROM trusted_questions {where}",
            tuple(params),
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        rows = self._get_client().execute(
            f"SELECT {_QUESTION_COLUMNS} FROM trusted_questions {where} "
            "ORDER BY updated_at DESC LIMIT %s OFFSET %s",
            tuple(params) + (page_size, (page - 1) * page_size),
        )
        return TrustedQuestionPage(
            items=[_row_to_question(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_published(self) -> list[TrustedQuestion]:
        rows = self._get_client().execute(
            f"SELECT {_QUESTION_COLUMNS} FROM trusted_questions WHERE status = 'published' "
            "ORDER BY standard_question",
        )
        return [_row_to_question(row) for row in rows]

    def update_question(self, question: TrustedQuestion, *, expected_revision: int) -> TrustedQuestion:
        client = self._get_client()
        rows = client.execute(
            "UPDATE trusted_questions SET standard_question=%s, synonyms=%s, roles=%s, object_code=%s, "
            "metrics=%s, dimensions=%s, time_scope=%s, filters=%s, query_plan=%s, allow_drilldown=%s, "
            "expected_result=%s, reviewer=%s, version=%s, status=%s, revision=%s, updated_at=%s "
            "WHERE question_id=%s AND revision=%s RETURNING revision",
            (
                question.standard_question,
                json.dumps(question.synonyms, ensure_ascii=False),
                json.dumps(question.roles, ensure_ascii=False),
                question.object_code,
                json.dumps(question.metrics, ensure_ascii=False),
                json.dumps(question.dimensions, ensure_ascii=False),
                question.time_scope,
                json.dumps(question.filters, ensure_ascii=False),
                json.dumps(question.query_plan, ensure_ascii=False),
                question.allow_drilldown,
                json.dumps(question.expected_result, ensure_ascii=False),
                question.reviewer,
                question.version,
                question.status.value,
                expected_revision + 1,
                question.updated_at if question.updated_at.tzinfo else question.updated_at.replace(tzinfo=UTC),
                question.question_id,
                expected_revision,
            ),
        )
        if not rows:
            current = self.get_question(question.question_id)
            raise QuestionRevisionConflictError(question.question_id, expected_revision, current.revision)
        return question.model_copy(update={"revision": int(rows[0]["revision"])})

    def list_texts(self, *, include_archived: bool = False) -> list[tuple[str, str]]:
        where = "" if include_archived else "WHERE status <> 'archived'"
        rows = self._get_client().execute(
            "SELECT question_id, standard_question, synonyms FROM trusted_questions " + where,
        )
        pairs: list[tuple[str, str]] = []
        for row in rows:
            pairs.append((row["question_id"], row["standard_question"]))
            pairs.extend((row["question_id"], synonym) for synonym in (row["synonyms"] or []))
        return pairs

    def record_match_event(self, event: QuestionMatchEvent) -> QuestionMatchEvent:
        self._get_client().execute(
            f"INSERT INTO question_match_events ({_EVENT_COLUMNS}) VALUES (%s,%s,%s,%s,%s)",
            (
                event.event_id,
                event.asked_text,
                event.outcome.value,
                event.matched_question_id,
                event.created_at,
            ),
        )
        return event

    def list_match_events(
        self,
        *,
        outcome: QuestionMatchEventOutcome | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> QuestionMatchEventPage:
        clauses = ["outcome = %s"] if outcome is not None else []
        params: list[Any] = [outcome.value] if outcome is not None else []
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total_rows = self._get_client().execute(
            f"SELECT COUNT(*) AS total FROM question_match_events {where}",
            tuple(params),
        )
        total = int(total_rows[0]["total"]) if total_rows else 0
        rows = self._get_client().execute(
            f"SELECT {_EVENT_COLUMNS} FROM question_match_events {where} "
            "ORDER BY created_at DESC LIMIT %s OFFSET %s",
            tuple(params) + (page_size, (page - 1) * page_size),
        )
        return QuestionMatchEventPage(
            items=[_row_to_event(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def count_questions_by_status(self) -> dict[str, int]:
        rows = self._get_client().execute(
            "SELECT status, COUNT(*) AS total FROM trusted_questions GROUP BY status",
        )
        counts = {"draft": 0, "published": 0, "archived": 0}
        for row in rows:
            counts[str(row["status"])] = int(row["total"])
        return counts

    def count_match_events(self) -> dict[str, int]:
        rows = self._get_client().execute(
            "SELECT outcome, COUNT(*) AS total FROM question_match_events GROUP BY outcome",
        )
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row["outcome"])] = int(row["total"])
        return counts


def _question_params(question: TrustedQuestion) -> tuple[Any, ...]:
    return (
        question.question_id,
        question.standard_question,
        json.dumps(question.synonyms, ensure_ascii=False),
        json.dumps(question.roles, ensure_ascii=False),
        question.object_code,
        json.dumps(question.metrics, ensure_ascii=False),
        json.dumps(question.dimensions, ensure_ascii=False),
        question.time_scope,
        json.dumps(question.filters, ensure_ascii=False),
        json.dumps(question.query_plan, ensure_ascii=False),
        question.allow_drilldown,
        json.dumps(question.expected_result, ensure_ascii=False),
        question.reviewer,
        question.version,
        question.status.value,
        question.revision,
        question.created_at if question.created_at.tzinfo else question.created_at.replace(tzinfo=UTC),
        question.updated_at if question.updated_at.tzinfo else question.updated_at.replace(tzinfo=UTC),
    )
