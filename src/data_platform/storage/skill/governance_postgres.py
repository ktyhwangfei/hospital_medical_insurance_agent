"""PostgreSQL Skill 评测与发布治理存储。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
    SkillGovernanceNotFoundError,
)
from src.data_platform.storage.skill.version_postgres import (
    SKILL_VERSION_TABLE_SCHEMA,
)
from src.data_platform.storage.skill.postgres import SKILL_TABLE_SCHEMA
from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillEvalMetrics,
    SkillEvalResult,
    SkillEvalRun,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)


SKILL_GOVERNANCE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_eval_cases (
    case_id VARCHAR(64) PRIMARY KEY,
    suite_version INTEGER NOT NULL,
    question_template TEXT NOT NULL,
    expected_skill_id VARCHAR(128),
    required BOOLEAN NOT NULL DEFAULT TRUE,
    risk_tags JSONB NOT NULL DEFAULT '[]',
    business_tags JSONB NOT NULL DEFAULT '[]',
    source_type VARCHAR(64) NOT NULL,
    source_ref TEXT NOT NULL DEFAULT '',
    contains_sensitive_data BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_eval_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL,
    version_id VARCHAR(64) NOT NULL,
    baseline_version_id VARCHAR(64),
    suite_version INTEGER NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    metrics JSONB NOT NULL,
    results JSONB NOT NULL DEFAULT '[]',
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_skill_eval_runs_skill_created
    ON skill_eval_runs(skill_id, created_at DESC);

CREATE TABLE IF NOT EXISTS skill_releases (
    release_id VARCHAR(64) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL,
    version_id VARCHAR(64) NOT NULL,
    environment VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    baseline_release_id VARCHAR(64),
    eval_run_id VARCHAR(64) NOT NULL,
    artifact_hash VARCHAR(64) NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    rollout_percent INTEGER NOT NULL DEFAULT 0,
    runtime_mode VARCHAR(32) NOT NULL DEFAULT 'shadow',
    revision INTEGER NOT NULL DEFAULT 1,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    activated_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_release_active
    ON skill_releases(skill_id, environment)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_skill_releases_skill_environment_created
    ON skill_releases(skill_id, environment, created_at DESC);

CREATE TABLE IF NOT EXISTS skill_release_approvals (
    approval_id VARCHAR(64) PRIMARY KEY,
    release_id VARCHAR(64) NOT NULL UNIQUE,
    artifact_hash VARCHAR(64) NOT NULL,
    eval_run_id VARCHAR(64) NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    baseline_release_id VARCHAR(64),
    approved_by VARCHAR(128) NOT NULL,
    approver_role VARCHAR(128) NOT NULL,
    reason TEXT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL
);
"""


class PostgresSkillGovernanceStorage:
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
            self._client.execute(SKILL_TABLE_SCHEMA)
            self._client.execute(SKILL_VERSION_TABLE_SCHEMA)
            self._client.execute(SKILL_GOVERNANCE_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _json_value(value: object, default: object) -> object:
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    def save_case(self, case: SkillEvalCase) -> SkillEvalCase:
        rows = self._get_client().execute(
            """
            INSERT INTO skill_eval_cases (
                case_id, suite_version, question_template, expected_skill_id,
                required, risk_tags, business_tags, source_type, source_ref,
                contains_sensitive_data, enabled, created_by, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (case_id) DO UPDATE SET
                suite_version = EXCLUDED.suite_version,
                question_template = EXCLUDED.question_template,
                expected_skill_id = EXCLUDED.expected_skill_id,
                required = EXCLUDED.required,
                risk_tags = EXCLUDED.risk_tags,
                business_tags = EXCLUDED.business_tags,
                source_type = EXCLUDED.source_type,
                source_ref = EXCLUDED.source_ref,
                contains_sensitive_data = EXCLUDED.contains_sensitive_data,
                enabled = EXCLUDED.enabled,
                updated_at = EXCLUDED.updated_at
            WHERE EXCLUDED.suite_version > skill_eval_cases.suite_version
            RETURNING *
            """,
            (
                case.case_id,
                case.suite_version,
                case.question_template,
                case.expected_skill_id,
                case.required,
                self._json(case.risk_tags),
                self._json(case.business_tags),
                case.source_type,
                case.source_ref,
                case.contains_sensitive_data,
                case.enabled,
                case.created_by,
                case.created_at,
                case.updated_at,
            ),
        )
        if not rows:
            raise SkillGovernanceConflictError("评测用例 suite_version 必须递增")
        return self._row_to_case(rows[0])

    def get_case(self, case_id: str) -> SkillEvalCase | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_eval_cases WHERE case_id = %s", (case_id,)
        )
        return None if not rows else self._row_to_case(rows[0])

    def list_cases(self, *, enabled_only: bool = False) -> list[SkillEvalCase]:
        where = "WHERE enabled = TRUE" if enabled_only else ""
        rows = self._get_client().execute(
            f"SELECT * FROM skill_eval_cases {where} ORDER BY suite_version, case_id"
        )
        return [self._row_to_case(row) for row in rows]

    def save_run(self, run: SkillEvalRun) -> SkillEvalRun:
        rows = self._get_client().execute(
            """
            INSERT INTO skill_eval_runs (
                run_id, skill_id, version_id, baseline_version_id, suite_version,
                config_hash, status, metrics, results, created_by, created_at,
                completed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                run.run_id,
                run.skill_id,
                run.version_id,
                run.baseline_version_id,
                run.suite_version,
                run.config_hash,
                run.status.value,
                self._json(run.metrics.model_dump(mode="json")),
                self._json([result.model_dump(mode="json") for result in run.results]),
                run.created_by,
                run.created_at,
                run.completed_at,
            ),
        )
        return self._row_to_run(rows[0])

    def get_run(self, skill_id: str, run_id: str) -> SkillEvalRun | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_eval_runs WHERE skill_id = %s AND run_id = %s",
            (skill_id, run_id),
        )
        return None if not rows else self._row_to_run(rows[0])

    def list_runs(self, skill_id: str) -> list[SkillEvalRun]:
        rows = self._get_client().execute(
            "SELECT * FROM skill_eval_runs WHERE skill_id = %s ORDER BY created_at DESC",
            (skill_id,),
        )
        return [self._row_to_run(row) for row in rows]

    def save_release(self, release: SkillRelease) -> SkillRelease:
        try:
            rows = self._get_client().execute(
                """
                INSERT INTO skill_releases (
                    release_id, skill_id, version_id, environment, status,
                    baseline_release_id, eval_run_id, artifact_hash, config_hash,
                    rollout_percent, runtime_mode, revision, created_by, created_at,
                    activated_at, retired_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                self._release_params(release),
            )
        except Exception as exc:
            raise SkillGovernanceConflictError("发布 ID 或 active 唯一性冲突") from exc
        return self._row_to_release(rows[0])

    def get_release(self, release_id: str) -> SkillRelease | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_releases WHERE release_id = %s", (release_id,)
        )
        return None if not rows else self._row_to_release(rows[0])

    def list_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str | None = None,
    ) -> list[SkillRelease]:
        if environment is None:
            sql = "SELECT * FROM skill_releases WHERE skill_id = %s ORDER BY created_at DESC"
            params = (skill_id,)
        else:
            sql = """
                SELECT * FROM skill_releases
                WHERE skill_id = %s AND environment = %s
                ORDER BY created_at DESC
            """
            params = (skill_id, str(environment))
        rows = self._get_client().execute(sql, params)
        return [self._row_to_release(row) for row in rows]

    def list_active_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str,
    ) -> list[SkillRelease]:
        rows = self._get_client().execute(
            """
            SELECT * FROM skill_releases
            WHERE skill_id = %s AND environment = %s AND status = 'active'
            """,
            (skill_id, str(environment)),
        )
        return [self._row_to_release(row) for row in rows]

    def update_release(
        self, release: SkillRelease, *, expected_revision: int
    ) -> SkillRelease:
        if release.revision != expected_revision + 1:
            raise SkillGovernanceConflictError("新 revision 必须递增 1")
        rows = self._get_client().execute(
            """
            UPDATE skill_releases SET
                status = %s, baseline_release_id = %s, rollout_percent = %s,
                revision = %s, activated_at = %s, retired_at = %s
            WHERE release_id = %s AND revision = %s
            RETURNING *
            """,
            (
                release.status.value,
                release.baseline_release_id,
                release.rollout_percent,
                release.revision,
                release.activated_at,
                release.retired_at,
                release.release_id,
                expected_revision,
            ),
        )
        if not rows:
            raise SkillGovernanceConflictError("发布 revision 已变化")
        return self._row_to_release(rows[0])

    def activate_release(
        self, release_id: str, *, expected_revision: int
    ) -> SkillRelease:
        client = self._get_client()
        now = datetime.now(timezone.utc)
        with client.transaction():
            rows = client.execute(
                "SELECT * FROM skill_releases WHERE release_id = %s FOR UPDATE",
                (release_id,),
            )
            if not rows:
                raise SkillGovernanceNotFoundError(f"发布不存在: {release_id}")
            candidate = self._row_to_release(rows[0])
            if candidate.revision != expected_revision:
                raise SkillGovernanceConflictError("发布 revision 已变化")
            if candidate.status != SkillReleaseStatus.APPROVED:
                raise SkillGovernanceConflictError("只有 approved release 可以激活")
            client.execute(
                """
                UPDATE skill_releases SET
                    status = 'retired', revision = revision + 1, retired_at = %s
                WHERE skill_id = %s AND environment = %s AND status = 'active'
                """,
                (now, candidate.skill_id, candidate.environment.value),
            )
            activated_rows = client.execute(
                """
                UPDATE skill_releases SET
                    status = 'active', revision = revision + 1,
                    rollout_percent = 100, activated_at = %s
                WHERE release_id = %s AND revision = %s
                RETURNING *
                """,
                (now, release_id, expected_revision),
            )
        return self._row_to_release(activated_rows[0])

    def save_approval(
        self, approval: SkillReleaseApproval
    ) -> SkillReleaseApproval:
        try:
            rows = self._get_client().execute(
                """
                INSERT INTO skill_release_approvals (
                    approval_id, release_id, artifact_hash, eval_run_id,
                    config_hash, baseline_release_id, approved_by,
                    approver_role, reason, approved_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    approval.approval_id,
                    approval.release_id,
                    approval.artifact_hash,
                    approval.eval_run_id,
                    approval.config_hash,
                    approval.baseline_release_id,
                    approval.approved_by,
                    approval.approver_role,
                    approval.reason,
                    approval.approved_at,
                ),
            )
        except Exception as exc:
            raise SkillGovernanceConflictError("该发布已经存在审批证据") from exc
        return self._row_to_approval(rows[0])

    def get_approval(self, release_id: str) -> SkillReleaseApproval | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_release_approvals WHERE release_id = %s",
            (release_id,),
        )
        return None if not rows else self._row_to_approval(rows[0])

    @staticmethod
    def _release_params(release: SkillRelease) -> tuple[object, ...]:
        return (
            release.release_id,
            release.skill_id,
            release.version_id,
            release.environment.value,
            release.status.value,
            release.baseline_release_id,
            release.eval_run_id,
            release.artifact_hash,
            release.config_hash,
            release.rollout_percent,
            release.runtime_mode,
            release.revision,
            release.created_by,
            release.created_at,
            release.activated_at,
            release.retired_at,
        )

    @classmethod
    def _row_to_case(cls, row: dict[str, Any]) -> SkillEvalCase:
        return SkillEvalCase(
            **{
                **row,
                "risk_tags": cls._json_value(row.get("risk_tags"), []),
                "business_tags": cls._json_value(row.get("business_tags"), []),
            }
        )

    @classmethod
    def _row_to_run(cls, row: dict[str, Any]) -> SkillEvalRun:
        metrics = cls._json_value(row.get("metrics"), {})
        results = cls._json_value(row.get("results"), [])
        return SkillEvalRun(
            run_id=row["run_id"],
            skill_id=row["skill_id"],
            version_id=row["version_id"],
            baseline_version_id=row.get("baseline_version_id"),
            suite_version=row["suite_version"],
            config_hash=row["config_hash"],
            status=row["status"],
            metrics=SkillEvalMetrics.model_validate(metrics),
            results=[SkillEvalResult.model_validate(result) for result in results],
            created_by=row["created_by"],
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
        )

    @staticmethod
    def _row_to_release(row: dict[str, Any]) -> SkillRelease:
        return SkillRelease.model_validate(row)

    @staticmethod
    def _row_to_approval(row: dict[str, Any]) -> SkillReleaseApproval:
        return SkillReleaseApproval.model_validate(row)
