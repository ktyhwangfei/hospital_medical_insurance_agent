"""PostgreSQL 可信问题库存储。

遵循 ``draft_postgres`` / ``session/postgres`` 模式：内联 schema 常量、懒连接、
``client.execute`` 返回 dict rows、JSONB 字段用 ``json.dumps`` 写入。

建表 DDL 双写（仓库硬性约束）：CREATE TABLE 包含全量列，同时逐列配
``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``——旧库已建表时 CREATE IF NOT EXISTS
不补列，缺 ALTER 会在 INSERT 报 UndefinedColumn 500。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
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

TRUSTED_QUESTION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trusted_questions (
    question_id VARCHAR(64) PRIMARY KEY,
    standard_question TEXT NOT NULL,
    synonyms JSONB NOT NULL DEFAULT '[]',
    applicable_roles JSONB NOT NULL DEFAULT '[]',
    metric_codes JSONB NOT NULL DEFAULT '[]',
    dimensions JSONB NOT NULL DEFAULT '[]',
    time_scope JSONB NOT NULL DEFAULT '{}',
    filters JSONB NOT NULL DEFAULT '[]',
    query_plan JSONB,
    allowed_drilldowns JSONB NOT NULL DEFAULT '[]',
    expected_result_traits JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_by VARCHAR(64) NOT NULL DEFAULT '',
    reviewed_by VARCHAR(64),
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trusted_questions_status
    ON trusted_questions(status);
CREATE INDEX IF NOT EXISTS idx_trusted_questions_created
    ON trusted_questions(created_at DESC);
"""

# CREATE+ALTER 双写：旧库不重建，逐列补列（与 CREATE 列清单一一对应）
TRUSTED_QUESTION_COLUMNS_DDL = """
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS question_id VARCHAR(64);
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS standard_question TEXT;
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS synonyms JSONB NOT NULL DEFAULT '[]';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS applicable_roles JSONB NOT NULL DEFAULT '[]';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS metric_codes JSONB NOT NULL DEFAULT '[]';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS dimensions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS time_scope JSONB NOT NULL DEFAULT '{}';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS filters JSONB NOT NULL DEFAULT '[]';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS query_plan JSONB;
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS allowed_drilldowns JSONB NOT NULL DEFAULT '[]';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS expected_result_traits JSONB NOT NULL DEFAULT '{}';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'draft';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS created_by VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(64);
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS review_note TEXT;
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE trusted_questions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PostgresTrustedQuestionStorage:
    """可信问题库 PostgreSQL 存储。"""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        client: PostgreSQLClient | None = None,
    ) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client = client
        self._schema_ensured = False

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
        if not self._schema_ensured:
            self._client.execute(TRUSTED_QUESTION_TABLE_SCHEMA)
            self._client.execute(TRUSTED_QUESTION_COLUMNS_DDL)
            self._schema_ensured = True
        return self._client

    # ── 查询 ────────────────────────────────────────────────────

    def get_question(self, question_id: str) -> TrustedQuestion | None:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM trusted_questions WHERE question_id = %s",
            (question_id,),
        )
        return None if not rows else self._row_to_question(rows[0])

    def list_questions(
        self,
        *,
        status: TrustedQuestionStatus | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TrustedQuestion]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = %s")
            params.append(status.value)
        if keyword:
            clauses.append(
                "(standard_question ILIKE %s"
                " OR EXISTS (SELECT 1 FROM jsonb_array_elements(synonyms) s"
                "            WHERE s->>'expression' ILIKE %s))"
            )
            like = f"%{keyword}%"
            params.extend([like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM trusted_questions"
            f"{where} ORDER BY created_at DESC, question_id"
            " LIMIT %s OFFSET %s",  # noqa: S608
            (*params, limit, offset),
        )
        return [self._row_to_question(row) for row in rows]

    # ── 写入 ────────────────────────────────────────────────────

    def save_question(self, question: TrustedQuestion) -> TrustedQuestion:
        client = self._get_client()
        rows = client.execute(
            """
            INSERT INTO trusted_questions (
                question_id, standard_question, synonyms, applicable_roles,
                metric_codes, dimensions, time_scope, filters, query_plan,
                allowed_drilldowns, expected_result_traits, status,
                created_by, reviewed_by, reviewed_at, review_note,
                version, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (question_id) DO NOTHING
            RETURNING *
            """,
            self._question_params(question),
        )
        if not rows:
            raise TrustedQuestionConflictError(f"可信问题已存在: {question.question_id}")
        return self._row_to_question(rows[0])

    def update_question(
        self, question: TrustedQuestion, *, expected_version: int
    ) -> TrustedQuestion:
        if question.version != expected_version + 1:
            raise TrustedQuestionConflictError("新 version 必须递增 1")
        current = self.get_question(question.question_id)
        if current is None:
            raise TrustedQuestionNotFoundError(f"可信问题不存在: {question.question_id}")
        ensure_editable(current.status)
        client = self._get_client()
        rows = client.execute(
            """
            UPDATE trusted_questions SET
                standard_question = %s, synonyms = %s, applicable_roles = %s,
                metric_codes = %s, dimensions = %s, time_scope = %s,
                filters = %s, query_plan = %s, allowed_drilldowns = %s,
                expected_result_traits = %s, status = %s,
                reviewed_by = %s, reviewed_at = %s, review_note = %s,
                version = %s, updated_at = %s
            WHERE question_id = %s AND version = %s
            RETURNING *
            """,
            (
                question.standard_question,
                json.dumps(
                    [s.model_dump(mode="json") for s in question.synonyms],
                    ensure_ascii=False,
                ),
                json.dumps(question.applicable_roles, ensure_ascii=False),
                json.dumps(question.metric_codes, ensure_ascii=False),
                json.dumps(question.dimensions, ensure_ascii=False),
                json.dumps(question.time_scope, ensure_ascii=False),
                json.dumps(question.filters, ensure_ascii=False),
                json.dumps(question.query_plan, ensure_ascii=False)
                if question.query_plan is not None
                else None,
                json.dumps(question.allowed_drilldowns, ensure_ascii=False),
                json.dumps(question.expected_result_traits, ensure_ascii=False),
                question.status.value,
                question.reviewed_by,
                question.reviewed_at,
                question.review_note,
                question.version,
                question.updated_at,
                question.question_id,
                expected_version,
            ),
        )
        if not rows:
            raise TrustedQuestionConflictError("可信问题 version 已变化")
        return self._row_to_question(rows[0])

    def transition_status(
        self,
        question_id: str,
        to_status: TrustedQuestionStatus,
        *,
        expected_version: int,
        operator: str = "",
        review_note: str | None = None,
    ) -> TrustedQuestion:
        current = self.get_question(question_id)
        if current is None:
            raise TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}")
        validate_transition(current.status, to_status)
        now = _now()
        # approve / reject 留痕审核人；retire 仅记录操作时间
        reviewed_by = current.reviewed_by
        reviewed_at = current.reviewed_at
        if to_status in (TrustedQuestionStatus.ACTIVE, TrustedQuestionStatus.DRAFT):
            reviewed_by = operator or current.reviewed_by
            reviewed_at = now
        client = self._get_client()
        rows = client.execute(
            """
            UPDATE trusted_questions SET
                status = %s, reviewed_by = %s, reviewed_at = %s,
                review_note = %s, version = %s, updated_at = %s
            WHERE question_id = %s AND version = %s
            RETURNING *
            """,
            (
                to_status.value,
                reviewed_by,
                reviewed_at,
                review_note if review_note is not None else current.review_note,
                expected_version + 1,
                now,
                question_id,
                expected_version,
            ),
        )
        if not rows:
            raise TrustedQuestionConflictError("可信问题 version 已变化")
        return self._row_to_question(rows[0])

    def add_synonym(
        self,
        question_id: str,
        synonym: TrustedQuestionSynonym,
        *,
        expected_version: int,
    ) -> TrustedQuestion:
        current = self.get_question(question_id)
        if current is None:
            raise TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}")
        expressions = {s.expression for s in current.synonyms}
        synonyms = list(current.synonyms)
        if synonym.expression not in expressions:
            synonyms.append(synonym)
        return self._write_synonyms(
            question_id, synonyms, expected_version=expected_version
        )

    def remove_synonym(
        self,
        question_id: str,
        expression: str,
        *,
        expected_version: int,
    ) -> TrustedQuestion:
        current = self.get_question(question_id)
        if current is None:
            raise TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}")
        synonyms = [s for s in current.synonyms if s.expression != expression]
        if len(synonyms) == len(current.synonyms):
            raise TrustedQuestionNotFoundError(f"同义表达不存在: {expression}")
        return self._write_synonyms(
            question_id, synonyms, expected_version=expected_version
        )

    def _write_synonyms(
        self,
        question_id: str,
        synonyms: list[TrustedQuestionSynonym],
        *,
        expected_version: int,
    ) -> TrustedQuestion:
        client = self._get_client()
        rows = client.execute(
            """
            UPDATE trusted_questions SET
                synonyms = %s, version = %s, updated_at = %s
            WHERE question_id = %s AND version = %s
            RETURNING *
            """,
            (
                json.dumps(
                    [s.model_dump(mode="json") for s in synonyms], ensure_ascii=False
                ),
                expected_version + 1,
                _now(),
                question_id,
                expected_version,
            ),
        )
        if not rows:
            raise TrustedQuestionConflictError("可信问题 version 已变化")
        return self._row_to_question(rows[0])

    # ── 行映射 ──────────────────────────────────────────────────

    @staticmethod
    def _question_params(question: TrustedQuestion) -> tuple[Any, ...]:
        return (
            question.question_id,
            question.standard_question,
            json.dumps(
                [s.model_dump(mode="json") for s in question.synonyms],
                ensure_ascii=False,
            ),
            json.dumps(question.applicable_roles, ensure_ascii=False),
            json.dumps(question.metric_codes, ensure_ascii=False),
            json.dumps(question.dimensions, ensure_ascii=False),
            json.dumps(question.time_scope, ensure_ascii=False),
            json.dumps(question.filters, ensure_ascii=False),
            json.dumps(question.query_plan, ensure_ascii=False)
            if question.query_plan is not None
            else None,
            json.dumps(question.allowed_drilldowns, ensure_ascii=False),
            json.dumps(question.expected_result_traits, ensure_ascii=False),
            question.status.value,
            question.created_by,
            question.reviewed_by,
            question.reviewed_at,
            question.review_note,
            question.version,
            question.created_at,
            question.updated_at,
        )

    @staticmethod
    def _json_value(value: Any, default: Any) -> Any:
        """JSONB 列读取兼容：psycopg 驱动可能返回已解析对象或 JSON 字符串。"""
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    @classmethod
    def _row_to_question(cls, row: dict[str, Any]) -> TrustedQuestion:
        synonyms_raw: list[Any] = cls._json_value(row.get("synonyms"), [])
        return TrustedQuestion(
            question_id=row["question_id"],
            standard_question=row["standard_question"],
            synonyms=[TrustedQuestionSynonym.model_validate(s) for s in synonyms_raw],
            applicable_roles=cls._json_value(row.get("applicable_roles"), []),
            metric_codes=cls._json_value(row.get("metric_codes"), []),
            dimensions=cls._json_value(row.get("dimensions"), []),
            time_scope=cls._json_value(row.get("time_scope"), {}),
            filters=cls._json_value(row.get("filters"), []),
            query_plan=cls._json_value(row.get("query_plan"), None) or None,
            allowed_drilldowns=cls._json_value(row.get("allowed_drilldowns"), []),
            expected_result_traits=cls._json_value(row.get("expected_result_traits"), {}),
            status=TrustedQuestionStatus(row["status"]),
            created_by=row.get("created_by") or "",
            reviewed_by=row.get("reviewed_by"),
            reviewed_at=row.get("reviewed_at"),
            review_note=row.get("review_note"),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
