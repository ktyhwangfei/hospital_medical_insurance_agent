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
    DEFAULT_ROUTING_SUITE_ID,
    FailureAttribution,
    FailureCluster,
    SkillEvalBenchmark,
    SkillEvalCase,
    SkillEvalDatasetVersion,
    SkillEvalDimensionSummary,
    SkillEvalEnvironmentSnapshot,
    SkillEvalMetrics,
    SkillEvalResult,
    SkillEvalRun,
    SkillEvalSuite,
    SkillEvalTask,
    SkillEvalTaskResult,
    SkillEvalTrajectoryStep,
    SkillRegressionEvalRecord,
    SkillRegressionSummary,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)


SKILL_GOVERNANCE_TABLE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS skill_eval_suites (
    suite_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    scope VARCHAR(16) NOT NULL,
    skill_id VARCHAR(128),
    purpose TEXT NOT NULL DEFAULT '',
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    revision INTEGER NOT NULL DEFAULT 1,
    created_by VARCHAR(128) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (
        (scope = 'platform' AND skill_id IS NULL)
        OR (scope = 'skill' AND skill_id IS NOT NULL)
    )
);

INSERT INTO skill_eval_suites (
    suite_id, name, scope, skill_id, purpose, status, revision,
    created_by, updated_by, created_at, updated_at
) VALUES (
    '{DEFAULT_ROUTING_SUITE_ID}', '平台默认路由测评集', 'platform', NULL,
    '兼容历史路由评测与发布门禁', 'active', 1,
    'system', 'system', NOW(), NOW()
) ON CONFLICT (suite_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS skill_eval_cases (
    case_id VARCHAR(64) PRIMARY KEY,
    suite_id VARCHAR(64) NOT NULL DEFAULT '{DEFAULT_ROUTING_SUITE_ID}'
        REFERENCES skill_eval_suites(suite_id),
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
ALTER TABLE skill_eval_cases
    ADD COLUMN IF NOT EXISTS suite_id VARCHAR(64)
    NOT NULL DEFAULT '{DEFAULT_ROUTING_SUITE_ID}';
CREATE INDEX IF NOT EXISTS idx_skill_eval_cases_suite_version
    ON skill_eval_cases(suite_id, suite_version, case_id);

CREATE TABLE IF NOT EXISTS skill_eval_suite_state (
    singleton_id SMALLINT PRIMARY KEY CHECK (singleton_id = 1),
    revision INTEGER NOT NULL DEFAULT 0
);
INSERT INTO skill_eval_suite_state (singleton_id, revision)
SELECT 1, COALESCE(MAX(suite_version), 0) FROM skill_eval_cases
ON CONFLICT (singleton_id) DO UPDATE SET
    revision = GREATEST(
        skill_eval_suite_state.revision,
        EXCLUDED.revision
    );

CREATE TABLE IF NOT EXISTS skill_eval_tasks (
    task_id VARCHAR(80) PRIMARY KEY,
    suite_id VARCHAR(64) NOT NULL REFERENCES skill_eval_suites(suite_id),
    target_skill_id VARCHAR(128) NOT NULL,
    name VARCHAR(256) NOT NULL,
    task_partition VARCHAR(16) NOT NULL,
    task_snapshot JSONB NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_eval_tasks_suite
    ON skill_eval_tasks(suite_id, enabled, task_id);

CREATE TABLE IF NOT EXISTS skill_eval_dataset_versions (
    dataset_version_id VARCHAR(80) PRIMARY KEY,
    suite_id VARCHAR(64) NOT NULL REFERENCES skill_eval_suites(suite_id),
    version_number INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (suite_id, version_number),
    UNIQUE (suite_id, content_hash)
);

CREATE TABLE IF NOT EXISTS skill_eval_benchmarks (
    benchmark_id VARCHAR(80) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL,
    dataset_version_id VARCHAR(80) NOT NULL
        REFERENCES skill_eval_dataset_versions(dataset_version_id),
    benchmark_snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_eval_benchmarks_skill_created
    ON skill_eval_benchmarks(skill_id, created_at DESC);

CREATE TABLE IF NOT EXISTS skill_eval_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL REFERENCES skills(skill_id),
    version_id VARCHAR(64) NOT NULL REFERENCES skill_versions(version_id),
    baseline_version_id VARCHAR(64) REFERENCES skill_versions(version_id),
    suite_version INTEGER NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    routing_manifest_hash VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    metrics JSONB NOT NULL,
    results JSONB NOT NULL DEFAULT '[]',
    case_snapshots JSONB NOT NULL DEFAULT '[]',
    regression_results JSONB NOT NULL DEFAULT '[]',
    regression_summary JSONB,
    dataset_version_id VARCHAR(80) REFERENCES skill_eval_dataset_versions(dataset_version_id),
    benchmark_id VARCHAR(80) REFERENCES skill_eval_benchmarks(benchmark_id),
    environment_snapshot JSONB,
    task_results JSONB NOT NULL DEFAULT '[]',
    trajectory_summary JSONB NOT NULL DEFAULT '[]',
    failure_attributions JSONB NOT NULL DEFAULT '[]',
    failure_clusters JSONB NOT NULL DEFAULT '[]',
    dimension_summary JSONB NOT NULL DEFAULT '[]',
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_skill_eval_runs_skill_created
    ON skill_eval_runs(skill_id, created_at DESC);
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS case_snapshots JSONB NOT NULL DEFAULT '[]';
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS routing_manifest_hash VARCHAR(64) NOT NULL DEFAULT repeat('0', 64);
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS regression_results JSONB NOT NULL DEFAULT '[]';
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS regression_summary JSONB;
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS dataset_version_id VARCHAR(80)
    REFERENCES skill_eval_dataset_versions(dataset_version_id);
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS benchmark_id VARCHAR(80)
    REFERENCES skill_eval_benchmarks(benchmark_id);
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS environment_snapshot JSONB;
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS task_results JSONB NOT NULL DEFAULT '[]';
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS trajectory_summary JSONB NOT NULL DEFAULT '[]';
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS failure_attributions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS failure_clusters JSONB NOT NULL DEFAULT '[]';
ALTER TABLE skill_eval_runs
    ADD COLUMN IF NOT EXISTS dimension_summary JSONB NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS skill_releases (
    release_id VARCHAR(64) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL REFERENCES skills(skill_id),
    version_id VARCHAR(64) NOT NULL REFERENCES skill_versions(version_id),
    environment VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL,
    baseline_release_id VARCHAR(64) REFERENCES skill_releases(release_id),
    eval_run_id VARCHAR(64) NOT NULL REFERENCES skill_eval_runs(run_id),
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
    release_id VARCHAR(64) NOT NULL UNIQUE REFERENCES skill_releases(release_id),
    artifact_hash VARCHAR(64) NOT NULL,
    eval_run_id VARCHAR(64) NOT NULL REFERENCES skill_eval_runs(run_id),
    config_hash VARCHAR(64) NOT NULL,
    baseline_release_id VARCHAR(64) REFERENCES skill_releases(release_id),
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

    def save_suite(self, suite: SkillEvalSuite) -> SkillEvalSuite:
        try:
            rows = self._get_client().execute(
                """
                INSERT INTO skill_eval_suites (
                    suite_id, name, scope, skill_id, purpose, status, revision,
                    created_by, updated_by, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    suite.suite_id,
                    suite.name,
                    suite.scope.value,
                    suite.skill_id,
                    suite.purpose,
                    suite.status.value,
                    suite.revision,
                    suite.created_by,
                    suite.updated_by,
                    suite.created_at,
                    suite.updated_at,
                ),
            )
        except Exception as exc:
            raise SkillGovernanceConflictError(
                f"测评集 ID 已存在: {suite.suite_id}"
            ) from exc
        return self._row_to_suite(rows[0])

    def get_suite(self, suite_id: str) -> SkillEvalSuite | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_eval_suites WHERE suite_id = %s",
            (suite_id,),
        )
        return None if not rows else self._row_to_suite(rows[0])

    def list_suites(
        self,
        *,
        skill_id: str | None = None,
        include_inactive: bool = True,
    ) -> list[SkillEvalSuite]:
        clauses: list[str] = []
        params: list[object] = []
        if skill_id is not None:
            clauses.append("(scope = 'platform' OR skill_id = %s)")
            params.append(skill_id)
        if not include_inactive:
            clauses.append("status = 'active'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._get_client().execute(
            f"""
            SELECT * FROM skill_eval_suites {where}
            ORDER BY scope, name, suite_id
            """,
            tuple(params),
        )
        return [self._row_to_suite(row) for row in rows]

    def update_suite(
        self,
        suite: SkillEvalSuite,
        *,
        expected_revision: int,
    ) -> SkillEvalSuite:
        rows = self._get_client().execute(
            """
            UPDATE skill_eval_suites
            SET name = %s, purpose = %s, status = %s, revision = %s,
                updated_by = %s, updated_at = %s
            WHERE suite_id = %s AND revision = %s
            RETURNING *
            """,
            (
                suite.name,
                suite.purpose,
                suite.status.value,
                suite.revision,
                suite.updated_by,
                suite.updated_at,
                suite.suite_id,
                expected_revision,
            ),
        )
        if not rows:
            raise SkillGovernanceConflictError("测评集 revision 已变化")
        return self._row_to_suite(rows[0])

    def delete_suite(self, suite_id: str) -> bool:
        rows = self._get_client().execute(
            "DELETE FROM skill_eval_suites WHERE suite_id = %s RETURNING suite_id",
            (suite_id,),
        )
        return bool(rows)

    def count_cases(self, suite_id: str) -> int:
        rows = self._get_client().execute(
            "SELECT COUNT(*) AS n FROM skill_eval_cases WHERE suite_id = %s",
            (suite_id,),
        )
        return int(rows[0]["n"]) if rows else 0

    def save_task(self, task: SkillEvalTask) -> SkillEvalTask:
        try:
            rows = self._get_client().execute(
                """
                INSERT INTO skill_eval_tasks (
                    task_id, suite_id, target_skill_id, name, task_partition,
                    task_snapshot, enabled, revision, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    task.task_id,
                    task.suite_id,
                    task.target_skill_id,
                    task.name,
                    task.partition.value,
                    self._json(task.model_dump(mode="json")),
                    task.enabled,
                    task.revision,
                    task.created_at,
                    task.updated_at,
                ),
            )
        except Exception as exc:
            raise SkillGovernanceConflictError(
                f"评测任务 ID 已存在或测评集无效: {task.task_id}"
            ) from exc
        return self._row_to_task(rows[0])

    def get_task(self, task_id: str) -> SkillEvalTask | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_eval_tasks WHERE task_id = %s",
            (task_id,),
        )
        return None if not rows else self._row_to_task(rows[0])

    def list_tasks(
        self,
        suite_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[SkillEvalTask]:
        enabled_clause = " AND enabled = TRUE" if enabled_only else ""
        rows = self._get_client().execute(
            f"""
            SELECT * FROM skill_eval_tasks
            WHERE suite_id = %s{enabled_clause}
            ORDER BY task_id
            """,
            (suite_id,),
        )
        return [self._row_to_task(row) for row in rows]

    def update_task(
        self,
        task: SkillEvalTask,
        *,
        expected_revision: int,
    ) -> SkillEvalTask:
        if task.revision != expected_revision + 1:
            raise SkillGovernanceConflictError("新 revision 必须递增 1")
        rows = self._get_client().execute(
            """
            UPDATE skill_eval_tasks SET
                target_skill_id = %s, name = %s, task_partition = %s,
                task_snapshot = %s, enabled = %s, revision = %s, updated_at = %s
            WHERE task_id = %s AND suite_id = %s AND revision = %s
            RETURNING *
            """,
            (
                task.target_skill_id,
                task.name,
                task.partition.value,
                self._json(task.model_dump(mode="json")),
                task.enabled,
                task.revision,
                task.updated_at,
                task.task_id,
                task.suite_id,
                expected_revision,
            ),
        )
        if not rows:
            raise SkillGovernanceConflictError("评测任务 revision 已变化")
        return self._row_to_task(rows[0])

    def save_dataset_version(
        self,
        version: SkillEvalDatasetVersion,
    ) -> SkillEvalDatasetVersion:
        try:
            rows = self._get_client().execute(
                """
                INSERT INTO skill_eval_dataset_versions (
                    dataset_version_id, suite_id, version_number, content_hash,
                    snapshot, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    version.dataset_version_id,
                    version.suite_id,
                    version.version_number,
                    version.content_hash,
                    self._json(version.model_dump(mode="json")),
                    version.created_at,
                ),
            )
        except Exception as exc:
            raise SkillGovernanceConflictError(
                "数据集版本 ID、序号或内容哈希已存在"
            ) from exc
        return self._row_to_dataset_version(rows[0])

    def get_dataset_version(
        self,
        dataset_version_id: str,
    ) -> SkillEvalDatasetVersion | None:
        rows = self._get_client().execute(
            """
            SELECT * FROM skill_eval_dataset_versions
            WHERE dataset_version_id = %s
            """,
            (dataset_version_id,),
        )
        return None if not rows else self._row_to_dataset_version(rows[0])

    def list_dataset_versions(
        self,
        suite_id: str,
    ) -> list[SkillEvalDatasetVersion]:
        rows = self._get_client().execute(
            """
            SELECT * FROM skill_eval_dataset_versions
            WHERE suite_id = %s
            ORDER BY version_number DESC
            """,
            (suite_id,),
        )
        return [self._row_to_dataset_version(row) for row in rows]

    def save_benchmark(self, benchmark: SkillEvalBenchmark) -> SkillEvalBenchmark:
        try:
            rows = self._get_client().execute(
                """
                INSERT INTO skill_eval_benchmarks (
                    benchmark_id, skill_id, dataset_version_id,
                    benchmark_snapshot, created_at
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    benchmark.benchmark_id,
                    benchmark.skill_id,
                    benchmark.dataset_version_id,
                    self._json(benchmark.model_dump(mode="json")),
                    benchmark.created_at,
                ),
            )
        except Exception as exc:
            raise SkillGovernanceConflictError(
                f"Benchmark ID 已存在或数据集版本无效: {benchmark.benchmark_id}"
            ) from exc
        return self._row_to_benchmark(rows[0])

    def get_benchmark(self, benchmark_id: str) -> SkillEvalBenchmark | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_eval_benchmarks WHERE benchmark_id = %s",
            (benchmark_id,),
        )
        return None if not rows else self._row_to_benchmark(rows[0])

    def list_benchmarks(
        self,
        skill_id: str | None = None,
    ) -> list[SkillEvalBenchmark]:
        if skill_id is None:
            rows = self._get_client().execute(
                "SELECT * FROM skill_eval_benchmarks ORDER BY created_at DESC"
            )
        else:
            rows = self._get_client().execute(
                """
                SELECT * FROM skill_eval_benchmarks
                WHERE skill_id = %s ORDER BY created_at DESC
                """,
                (skill_id,),
            )
        return [self._row_to_benchmark(row) for row in rows]

    def next_suite_version(self) -> int:
        rows = self._get_client().execute(
            """
            UPDATE skill_eval_suite_state
            SET revision = revision + 1
            WHERE singleton_id = 1
            RETURNING revision
            """
        )
        if not rows:
            raise SkillGovernanceConflictError("评测集版本分配失败")
        return int(rows[0]["revision"])

    def current_suite_version(self) -> int:
        rows = self._get_client().execute(
            "SELECT revision FROM skill_eval_suite_state WHERE singleton_id = 1"
        )
        return int(rows[0]["revision"]) if rows else 0

    def save_case_with_new_suite_version(
        self, case: SkillEvalCase
    ) -> SkillEvalCase:
        client = self._get_client()
        with client.transaction():
            suite_version = self.next_suite_version()
            versioned_case = case.model_copy(
                update={"suite_version": suite_version}, deep=True
            )
            return self.save_case(versioned_case)

    def snapshot_enabled_cases(self) -> tuple[int, list[SkillEvalCase]]:
        client = self._get_client()
        with client.transaction():
            rows = client.execute(
                """
                SELECT revision FROM skill_eval_suite_state
                WHERE singleton_id = 1
                FOR SHARE
                """
            )
            suite_version = int(rows[0]["revision"]) if rows else 0
            cases = self.list_cases(enabled_only=True)
            return suite_version, cases

    def save_case(self, case: SkillEvalCase) -> SkillEvalCase:
        rows = self._get_client().execute(
            """
            INSERT INTO skill_eval_cases (
                case_id, suite_id, suite_version, question_template, expected_skill_id,
                required, risk_tags, business_tags, source_type, source_ref,
                contains_sensitive_data, enabled, created_by, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (case_id) DO UPDATE SET
                suite_id = EXCLUDED.suite_id,
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
                case.suite_id,
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

    def delete_case(self, case_id: str) -> bool:
        rows = self._get_client().execute(
            "DELETE FROM skill_eval_cases WHERE case_id = %s RETURNING case_id",
            (case_id,),
        )
        return bool(rows)

    def list_cases(
        self,
        *,
        suite_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillEvalCase]:
        clauses: list[str] = []
        params: list[object] = []
        if suite_id is not None:
            clauses.append("suite_id = %s")
            params.append(suite_id)
        if enabled_only:
            clauses.append("enabled = TRUE")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._get_client().execute(
            f"SELECT * FROM skill_eval_cases {where} ORDER BY suite_version, case_id",
            tuple(params),
        )
        return [self._row_to_case(row) for row in rows]

    def save_run(self, run: SkillEvalRun) -> SkillEvalRun:
        rows = self._get_client().execute(
            """
            INSERT INTO skill_eval_runs (
                run_id, skill_id, version_id, baseline_version_id, suite_version,
                config_hash, routing_manifest_hash, status, metrics, results,
                case_snapshots, regression_results, regression_summary,
                dataset_version_id, benchmark_id, environment_snapshot,
                task_results, trajectory_summary, failure_attributions,
                failure_clusters, dimension_summary,
                created_by, created_at, completed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                run.run_id,
                run.skill_id,
                run.version_id,
                run.baseline_version_id,
                run.suite_version,
                run.config_hash,
                run.routing_manifest_hash,
                run.status.value,
                self._json(run.metrics.model_dump(mode="json")),
                self._json([result.model_dump(mode="json") for result in run.results]),
                self._json([case.model_dump(mode="json") for case in run.case_snapshots]),
                self._json([r.model_dump(mode="json") for r in run.regression_results]),
                self._json(run.regression_summary.model_dump(mode="json"))
                if run.regression_summary
                else None,
                run.dataset_version_id,
                run.benchmark_id,
                self._json(run.environment_snapshot.model_dump(mode="json"))
                if run.environment_snapshot
                else None,
                self._json([result.model_dump(mode="json") for result in run.task_results]),
                self._json([step.model_dump(mode="json") for step in run.trajectory_summary]),
                self._json([
                    attribution.model_dump(mode="json")
                    for attribution in run.failure_attributions
                ]),
                self._json([
                    cluster.model_dump(mode="json") for cluster in run.failure_clusters
                ]),
                self._json([
                    summary.model_dump(mode="json") for summary in run.dimension_summary
                ]),
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

    def list_runs(self, skill_id: str | None = None) -> list[SkillEvalRun]:
        if skill_id is not None:
            rows = self._get_client().execute(
                "SELECT * FROM skill_eval_runs WHERE skill_id = %s ORDER BY created_at DESC",
                (skill_id,),
            )
        else:
            rows = self._get_client().execute(
                "SELECT * FROM skill_eval_runs ORDER BY created_at DESC",
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
        self,
        release_id: str,
        *,
        expected_revision: int,
        expected_suite_version: int | None = None,
    ) -> SkillRelease:
        client = self._get_client()
        now = datetime.now(timezone.utc)
        with client.transaction():
            if expected_suite_version is not None:
                suite_rows = client.execute(
                    """
                    SELECT revision FROM skill_eval_suite_state
                    WHERE singleton_id = 1
                    FOR SHARE
                    """
                )
                current_suite_version = (
                    int(suite_rows[0]["revision"]) if suite_rows else 0
                )
                if current_suite_version != expected_suite_version:
                    raise SkillGovernanceConflictError("评测集版本已变化")
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
            active_rows = client.execute(
                """
                SELECT release_id FROM skill_releases
                WHERE skill_id = %s AND environment = %s AND status = 'active'
                FOR UPDATE
                """,
                (candidate.skill_id, candidate.environment.value),
            )
            if len(active_rows) > 1:
                raise SkillGovernanceConflictError(
                    "同一 Skill 和环境存在多个 active release"
                )
            active_id = active_rows[0]["release_id"] if active_rows else None
            if active_id != candidate.baseline_release_id:
                raise SkillGovernanceConflictError("活动基线已变化")
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

    def approve_release(
        self,
        release: SkillRelease,
        approval: SkillReleaseApproval,
        *,
        expected_revision: int,
    ) -> SkillRelease:
        if release.revision != expected_revision + 1:
            raise SkillGovernanceConflictError("新 revision 必须递增 1")
        if release.status != SkillReleaseStatus.APPROVED:
            raise SkillGovernanceConflictError("审批事务的目标状态必须是 approved")
        if approval.release_id != release.release_id:
            raise SkillGovernanceConflictError("审批证据与发布不匹配")
        client = self._get_client()
        try:
            with client.transaction():
                current_rows = client.execute(
                    "SELECT revision FROM skill_releases WHERE release_id = %s FOR UPDATE",
                    (release.release_id,),
                )
                if not current_rows:
                    raise SkillGovernanceNotFoundError(
                        f"发布不存在: {release.release_id}"
                    )
                if current_rows[0]["revision"] != expected_revision:
                    raise SkillGovernanceConflictError("发布 revision 已变化")
                client.execute(
                    """
                    INSERT INTO skill_release_approvals (
                        approval_id, release_id, artifact_hash, eval_run_id,
                        config_hash, baseline_release_id, approved_by,
                        approver_role, reason, approved_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                updated_rows = client.execute(
                    """
                    UPDATE skill_releases SET status = 'approved', revision = %s
                    WHERE release_id = %s AND revision = %s
                    RETURNING *
                    """,
                    (release.revision, release.release_id, expected_revision),
                )
        except (SkillGovernanceConflictError, SkillGovernanceNotFoundError):
            raise
        except Exception as exc:
            raise SkillGovernanceConflictError(
                "审批证据或发布 revision 冲突"
            ) from exc
        return self._row_to_release(updated_rows[0])

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
    def _row_to_suite(cls, row: dict[str, Any]) -> SkillEvalSuite:
        return SkillEvalSuite.model_validate(row)

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
    def _row_to_task(cls, row: dict[str, Any]) -> SkillEvalTask:
        return SkillEvalTask.model_validate(
            cls._json_value(row.get("task_snapshot"), {})
        )

    @classmethod
    def _row_to_dataset_version(
        cls,
        row: dict[str, Any],
    ) -> SkillEvalDatasetVersion:
        return SkillEvalDatasetVersion.model_validate(
            cls._json_value(row.get("snapshot"), {})
        )

    @classmethod
    def _row_to_benchmark(cls, row: dict[str, Any]) -> SkillEvalBenchmark:
        return SkillEvalBenchmark.model_validate(
            cls._json_value(row.get("benchmark_snapshot"), {})
        )

    @classmethod
    def _row_to_run(cls, row: dict[str, Any]) -> SkillEvalRun:
        metrics = cls._json_value(row.get("metrics"), {})
        results = cls._json_value(row.get("results"), [])
        case_snapshots = cls._json_value(row.get("case_snapshots"), [])
        regression_results_raw = cls._json_value(row.get("regression_results"), [])
        regression_summary_raw = row.get("regression_summary")
        environment_snapshot_raw = row.get("environment_snapshot")
        task_results_raw = cls._json_value(row.get("task_results"), [])
        trajectory_summary_raw = cls._json_value(row.get("trajectory_summary"), [])
        failure_attributions_raw = cls._json_value(
            row.get("failure_attributions"), []
        )
        failure_clusters_raw = cls._json_value(row.get("failure_clusters"), [])
        dimension_summary_raw = cls._json_value(row.get("dimension_summary"), [])
        return SkillEvalRun(
            run_id=row["run_id"],
            skill_id=row["skill_id"],
            version_id=row["version_id"],
            baseline_version_id=row.get("baseline_version_id"),
            suite_version=row["suite_version"],
            config_hash=row["config_hash"],
            routing_manifest_hash=row["routing_manifest_hash"],
            status=row["status"],
            metrics=SkillEvalMetrics.model_validate(metrics),
            results=[SkillEvalResult.model_validate(result) for result in results],
            case_snapshots=[
                SkillEvalCase.model_validate(case) for case in case_snapshots
            ],
            regression_results=[
                SkillRegressionEvalRecord.model_validate(r)
                for r in regression_results_raw
            ],
            regression_summary=SkillRegressionSummary.model_validate(
                cls._json_value(regression_summary_raw, {})
            )
            if regression_summary_raw
            else None,
            dataset_version_id=row.get("dataset_version_id"),
            benchmark_id=row.get("benchmark_id"),
            environment_snapshot=SkillEvalEnvironmentSnapshot.model_validate(
                cls._json_value(environment_snapshot_raw, {})
            )
            if environment_snapshot_raw
            else None,
            task_results=[
                SkillEvalTaskResult.model_validate(result)
                for result in task_results_raw
            ],
            trajectory_summary=[
                SkillEvalTrajectoryStep.model_validate(step)
                for step in trajectory_summary_raw
            ],
            failure_attributions=[
                FailureAttribution.model_validate(attribution)
                for attribution in failure_attributions_raw
            ],
            failure_clusters=[
                FailureCluster.model_validate(cluster)
                for cluster in failure_clusters_raw
            ],
            dimension_summary=[
                SkillEvalDimensionSummary.model_validate(summary)
                for summary in dimension_summary_raw
            ],
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
