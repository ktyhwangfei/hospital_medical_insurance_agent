"""PostgreSQL Skill 回归案例池与回归用例存储。

显式列映射 + JSONB 严格反序列化；案例池按 (tenant_id, source_qa_turn_id)
软删除唯一，回归用例按 (source_type, source_ref, case_type) 唯一。所有
写操作用乐观锁 revision；受影响行数为零时抛统一冲突异常。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.skill.regression_ports import (
    SkillRegressionConflictError,
    SkillRegressionNotFoundError,
)
from src.domain.skill.regression_models import (
    SkillErrorDimension,
    SkillEvalCasePoolItem,
    SkillEvalCasePoolStatus,
    SkillFeedbackReasonCode,
    SkillRegressionCase,
)


SKILL_REGRESSION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_eval_case_pool (
    pool_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(128) NOT NULL,
    source_qa_turn_id VARCHAR(80) NOT NULL,
    source_user_id VARCHAR(128) NOT NULL DEFAULT '',
    reason_code VARCHAR(64) NOT NULL,
    error_dimension VARCHAR(32) NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    question_excerpt TEXT NOT NULL DEFAULT '',
    answer_excerpt TEXT NOT NULL DEFAULT '',
    source_selected_skill_id VARCHAR(128),
    source_hash VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending_triage',
    revision INTEGER NOT NULL DEFAULT 1,
    eval_case_ref JSONB,
    transformed_dimension VARCHAR(32),
    transformed_proposal JSONB,
    transformed_root_cause TEXT,
    transformed_citations JSONB NOT NULL DEFAULT '[]',
    transformed_uncertainties JSONB NOT NULL DEFAULT '[]',
    rejection_reason TEXT,
    created_by VARCHAR(128) NOT NULL DEFAULT 'system',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_eval_pool_turn
ON skill_eval_case_pool(tenant_id, source_qa_turn_id)
WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_skill_eval_pool_tenant_status
ON skill_eval_case_pool(tenant_id, status, created_at DESC)
WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS skill_regression_cases (
    case_id VARCHAR(64) PRIMARY KEY,
    target_skill_id VARCHAR(128) NOT NULL,
    case_type VARCHAR(32) NOT NULL,
    input_template JSONB NOT NULL DEFAULT '{}',
    expected_assertions JSONB NOT NULL,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    evaluator_status VARCHAR(32) NOT NULL DEFAULT 'blocked_by_evaluator',
    evaluator_version VARCHAR(64),
    source_type VARCHAR(64) NOT NULL DEFAULT 'policy_qa_feedback',
    source_ref VARCHAR(80) NOT NULL,
    source_hash VARCHAR(64) NOT NULL,
    confirmed_by VARCHAR(128) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_regression_source
ON skill_regression_cases(source_type, source_ref, case_type)
WHERE enabled = TRUE;

CREATE INDEX IF NOT EXISTS idx_skill_regression_skill_type
ON skill_regression_cases(target_skill_id, case_type)
WHERE enabled = TRUE;
"""


class PostgresSkillRegressionStorage:
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
            self._client.execute(SKILL_REGRESSION_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _loads(value: object, default: Any) -> Any:
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    # ── 案例池 ──────────────────────────────────────────────────

    def create_pool_item(
        self, item: SkillEvalCasePoolItem
    ) -> SkillEvalCasePoolItem:
        client = self._get_client()
        with client.transaction():
            rows = client.execute(
                """
                SELECT * FROM skill_eval_case_pool
                WHERE tenant_id = %s AND source_qa_turn_id = %s AND deleted_at IS NULL
                LIMIT 1
                """,
                (item.tenant_id, item.source_qa_turn_id),
            )
            if rows:
                return self._row_to_pool(rows[0])
            client.execute(
                """
                INSERT INTO skill_eval_case_pool (
                    pool_id, tenant_id, source_qa_turn_id, source_user_id,
                    reason_code, error_dimension, comment, question_excerpt,
                    answer_excerpt, source_selected_skill_id, source_hash,
                    status, revision, eval_case_ref, transformed_dimension,
                    transformed_proposal, transformed_root_cause,
                    transformed_citations, transformed_uncertainties,
                    rejection_reason, created_by, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    item.pool_id,
                    item.tenant_id,
                    item.source_qa_turn_id,
                    item.source_user_id,
                    item.reason_code.value,
                    item.error_dimension.value,
                    item.comment,
                    item.question_excerpt,
                    item.answer_excerpt,
                    item.source_selected_skill_id,
                    item.source_hash,
                    item.status.value,
                    item.revision,
                    self._json(item.eval_case_ref.model_dump()) if item.eval_case_ref else None,
                    item.transformed_dimension.value if item.transformed_dimension else None,
                    self._json(item.transformed_proposal) if item.transformed_proposal else None,
                    item.transformed_root_cause,
                    self._json(item.transformed_citations),
                    self._json(item.transformed_uncertainties),
                    item.rejection_reason,
                    item.created_by,
                    item.created_at,
                    item.updated_at,
                ),
            )
            return item.model_copy(deep=True)

    def get_pool_item(
        self, pool_id: str, *, tenant_id: str | None = None
    ) -> SkillEvalCasePoolItem | None:
        rows = self._get_client().execute(
            """
            SELECT * FROM skill_eval_case_pool
            WHERE pool_id = %s AND deleted_at IS NULL
            """,
            (pool_id,),
        )
        if not rows:
            return None
        item = self._row_to_pool(rows[0])
        if tenant_id is not None and item.tenant_id != tenant_id:
            return None
        return item

    def list_pool_items(
        self,
        *,
        tenant_id: str | None = None,
        status=None,
        error_dimension=None,
        target_skill_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SkillEvalCasePoolItem]:
        clauses = ["deleted_at IS NULL"]
        params: list[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id = %s")
            params.append(tenant_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(str(status))
        if error_dimension is not None:
            clauses.append("error_dimension = %s")
            params.append(str(error_dimension))
        if target_skill_id is not None:
            clauses.append("source_selected_skill_id = %s")
            params.append(target_skill_id)
        params.extend([limit, offset])
        rows = self._get_client().execute(
            f"""
            SELECT * FROM skill_eval_case_pool
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return [self._row_to_pool(row) for row in rows]

    def count_pool_items(self, *, tenant_id: str | None = None) -> int:
        clause = "deleted_at IS NULL"
        params: tuple[Any, ...] = ()
        if tenant_id is not None:
            clause += " AND tenant_id = %s"
            params = (tenant_id,)
        rows = self._get_client().execute(
            f"SELECT COUNT(*) AS n FROM skill_eval_case_pool WHERE {clause}", params
        )
        return int(rows[0]["n"]) if rows else 0

    def _apply_pool_mutation(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        expected_revision: int,
        set_clause: str,
        params: tuple[Any, ...],
    ) -> SkillEvalCasePoolItem:
        client = self._get_client()
        with client.transaction():
            rows = client.execute(
                f"""
                UPDATE skill_eval_case_pool SET {set_clause}, updated_at = NOW()
                WHERE pool_id = %s AND tenant_id = %s AND revision = %s AND deleted_at IS NULL
                RETURNING *
                """,
                params + (pool_id, tenant_id, expected_revision),
            )
            if not rows:
                self._raise_missing_or_stale(pool_id, tenant_id, expected_revision)
            return self._row_to_pool(rows[0])

    def _raise_missing_or_stale(
        self, pool_id: str, tenant_id: str, expected_revision: int
    ) -> None:
        rows = self._get_client().execute(
            """
            SELECT revision FROM skill_eval_case_pool
            WHERE pool_id = %s AND tenant_id = %s AND deleted_at IS NULL
            """,
            (pool_id, tenant_id),
        )
        if not rows:
            raise SkillRegressionNotFoundError(f"案例池条目不存在: {pool_id}")
        raise SkillRegressionConflictError(
            f"案例池条目 revision 已变化（期望 {expected_revision}，当前 {rows[0]['revision']}）"
        )

    def update_pool_item(
        self,
        item: SkillEvalCasePoolItem,
        *,
        expected_revision: int,
        tenant_id: str | None = None,
    ) -> SkillEvalCasePoolItem:
        tenant = tenant_id or item.tenant_id
        return self._apply_pool_mutation(
            item.pool_id,
            tenant_id=tenant,
            expected_revision=expected_revision,
            set_clause="revision = revision + 1",
            params=(),
        )

    def transform_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        transformed_dimension,
        transformed_proposal,
        transformed_root_cause,
        transformed_citations,
        transformed_uncertainties,
        expected_revision: int,
    ) -> SkillEvalCasePoolItem:
        return self._apply_pool_mutation(
            pool_id,
            tenant_id=tenant_id,
            expected_revision=expected_revision,
            set_clause=(
                "status = 'transformed', transformed_dimension = %s, "
                "transformed_proposal = %s, transformed_root_cause = %s, "
                "transformed_citations = %s, transformed_uncertainties = %s, "
                "revision = revision + 1"
            ),
            params=(
                transformed_dimension.value if transformed_dimension else None,
                self._json(transformed_proposal) if transformed_proposal else None,
                transformed_root_cause,
                self._json(transformed_citations),
                self._json(transformed_uncertainties),
            ),
        )

    def confirm_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        case_type: str,
        case_id: str,
        expected_revision: int,
    ) -> SkillEvalCasePoolItem:
        client = self._get_client()
        with client.transaction():
            current_rows = client.execute(
                """
                SELECT * FROM skill_eval_case_pool
                WHERE pool_id = %s AND tenant_id = %s AND deleted_at IS NULL
                """,
                (pool_id, tenant_id),
            )
            if not current_rows:
                raise SkillRegressionNotFoundError(f"案例池条目不存在: {pool_id}")
            current = self._row_to_pool(current_rows[0])
            if (
                current.status == SkillEvalCasePoolStatus.CONFIRMED
                and current.eval_case_ref is not None
                and current.eval_case_ref.case_type == case_type
                and current.eval_case_ref.case_id == case_id
            ):
                return current
            if current.revision != expected_revision:
                raise SkillRegressionConflictError(
                    f"案例池条目 revision 已变化（期望 {expected_revision}，当前 {current.revision}）"
                )
            if current.status == SkillEvalCasePoolStatus.CONFIRMED:
                raise SkillRegressionConflictError("案例池条目已确认到不同资产")
            rows = client.execute(
                """
                UPDATE skill_eval_case_pool SET
                    status = 'confirmed',
                    eval_case_ref = %s,
                    revision = revision + 1,
                    updated_at = NOW()
                WHERE pool_id = %s AND tenant_id = %s AND revision = %s AND deleted_at IS NULL
                RETURNING *
                """,
                (
                    self._json({"case_type": case_type, "case_id": case_id}),
                    pool_id,
                    tenant_id,
                    expected_revision,
                ),
            )
            if not rows:
                raise SkillRegressionConflictError("案例池条目确认失败")
            return self._row_to_pool(rows[0])

    def reject_pool_item(
        self,
        pool_id: str,
        *,
        tenant_id: str,
        reason: str,
        expected_revision: int,
    ) -> SkillEvalCasePoolItem:
        return self._apply_pool_mutation(
            pool_id,
            tenant_id=tenant_id,
            expected_revision=expected_revision,
            set_clause=(
                "status = 'rejected', rejection_reason = %s, revision = revision + 1"
            ),
            params=(reason,),
        )

    def soft_delete_expired_pool_items(self, *, before: datetime) -> int:
        client = self._get_client()
        with client.transaction():
            rows = client.execute(
                """
                UPDATE skill_eval_case_pool SET deleted_at = NOW()
                WHERE status <> 'confirmed' AND deleted_at IS NULL AND created_at < %s
                RETURNING pool_id
                """,
                (before,),
            )
            return len(rows)

    def detach_pool_item_source(
        self, pool_id: str, *, tenant_id: str
    ) -> SkillEvalCasePoolItem:
        client = self._get_client()
        with client.transaction():
            rows = client.execute(
                """
                UPDATE skill_eval_case_pool SET
                    source_user_id = '', question_excerpt = '', answer_excerpt = '',
                    comment = '', revision = revision + 1, updated_at = NOW()
                WHERE pool_id = %s AND tenant_id = %s AND deleted_at IS NULL
                RETURNING *
                """,
                (pool_id, tenant_id),
            )
            if not rows:
                raise SkillRegressionNotFoundError(f"案例池条目不存在: {pool_id}")
            return self._row_to_pool(rows[0])

    # ── 回归用例 ────────────────────────────────────────────────

    def create_case(self, case: SkillRegressionCase) -> SkillRegressionCase:
        client = self._get_client()
        try:
            client.execute(
                """
                INSERT INTO skill_regression_cases (
                    case_id, target_skill_id, case_type, input_template,
                    expected_assertions, required, evaluator_status,
                    evaluator_version, source_type, source_ref, source_hash,
                    confirmed_by, enabled, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    case.case_id,
                    case.target_skill_id,
                    case.case_type.value,
                    self._json(case.input_template),
                    self._json(case.expected_assertions.model_dump()),
                    case.required,
                    case.evaluator_status.value,
                    case.evaluator_version,
                    case.source_type,
                    case.source_ref,
                    case.source_hash,
                    case.confirmed_by,
                    case.enabled,
                    case.created_at,
                    case.updated_at,
                ),
            )
        except Exception as exc:  # 唯一索引冲突
            if "uq_skill_regression_source" in str(exc) or "unique" in str(exc).lower():
                raise SkillRegressionConflictError(
                    "同一来源与维度的回归用例已存在"
                ) from exc
            raise
        return case.model_copy(deep=True)

    def get_case(self, case_id: str) -> SkillRegressionCase | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_regression_cases WHERE case_id = %s", (case_id,)
        )
        return None if not rows else self._row_to_case(rows[0])

    def list_cases(
        self,
        *,
        target_skill_id: str | None = None,
        case_type=None,
        enabled_only: bool = False,
    ) -> list[SkillRegressionCase]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_skill_id is not None:
            clauses.append("target_skill_id = %s")
            params.append(target_skill_id)
        if case_type is not None:
            clauses.append("case_type = %s")
            params.append(str(case_type))
        if enabled_only:
            clauses.append("enabled = TRUE")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._get_client().execute(
            f"SELECT * FROM skill_regression_cases {where} ORDER BY created_at ASC",
            tuple(params),
        )
        return [self._row_to_case(row) for row in rows]

    def count_cases(self) -> int:
        rows = self._get_client().execute(
            "SELECT COUNT(*) AS n FROM skill_regression_cases"
        )
        return int(rows[0]["n"]) if rows else 0

    # ── 行 → 模型 ───────────────────────────────────────────────

    def _row_to_pool(self, row: dict[str, Any]) -> SkillEvalCasePoolItem:
        return SkillEvalCasePoolItem.model_validate(
            {
                "pool_id": row["pool_id"],
                "tenant_id": row["tenant_id"],
                "source_qa_turn_id": row["source_qa_turn_id"],
                "source_user_id": row["source_user_id"],
                "reason_code": row["reason_code"],
                "error_dimension": row["error_dimension"],
                "comment": row["comment"],
                "question_excerpt": row["question_excerpt"],
                "answer_excerpt": row["answer_excerpt"],
                "source_selected_skill_id": row.get("source_selected_skill_id"),
                "source_hash": row["source_hash"],
                "status": row["status"],
                "revision": int(row["revision"]),
                "eval_case_ref": self._loads(row.get("eval_case_ref"), None),
                "transformed_dimension": row.get("transformed_dimension"),
                "transformed_proposal": self._loads(row.get("transformed_proposal"), None),
                "transformed_root_cause": row.get("transformed_root_cause"),
                "transformed_citations": self._loads(row.get("transformed_citations"), []),
                "transformed_uncertainties": self._loads(
                    row.get("transformed_uncertainties"), []
                ),
                "rejection_reason": row.get("rejection_reason"),
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    def _row_to_case(self, row: dict[str, Any]) -> SkillRegressionCase:
        return SkillRegressionCase.model_validate(
            {
                "case_id": row["case_id"],
                "target_skill_id": row["target_skill_id"],
                "case_type": row["case_type"],
                "input_template": self._loads(row.get("input_template"), {}),
                "expected_assertions": self._loads(row.get("expected_assertions"), {}),
                "required": row["required"],
                "evaluator_status": row["evaluator_status"],
                "evaluator_version": row.get("evaluator_version"),
                "source_type": row["source_type"],
                "source_ref": row["source_ref"],
                "source_hash": row["source_hash"],
                "confirmed_by": row["confirmed_by"],
                "enabled": row["enabled"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
