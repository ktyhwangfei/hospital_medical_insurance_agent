"""政策答案验证发布门禁 PostgreSQL 存储。"""
from __future__ import annotations

import json

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.knowledge_extension.rule_explanation.answer_verification.gate_models import (
    AnswerVerificationCaseResult,
    AnswerVerificationRun,
)


ANSWER_VERIFICATION_GATE_SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS policy_answer_verification_run_sequence_seq;

CREATE TABLE IF NOT EXISTS policy_answer_verification_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    run_sequence BIGINT NOT NULL DEFAULT nextval('policy_answer_verification_run_sequence_seq'),
    release_id VARCHAR(64) NOT NULL,
    case_set_version INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    quality_run_id VARCHAR(64)
);

CREATE TABLE IF NOT EXISTS policy_answer_verification_case_results (
    run_id VARCHAR(64) NOT NULL REFERENCES policy_answer_verification_runs(run_id) ON DELETE CASCADE,
    case_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    gated_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    skipped_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification JSONB NOT NULL,
    PRIMARY KEY (run_id, case_id)
);
"""

ANSWER_VERIFICATION_GATE_MIGRATIONS = (
    """ALTER TABLE policy_answer_verification_runs
       ADD COLUMN IF NOT EXISTS run_sequence BIGINT""",
    """ALTER TABLE policy_answer_verification_runs
       ADD COLUMN IF NOT EXISTS release_id VARCHAR(64)""",
    """ALTER TABLE policy_answer_verification_runs
       ADD COLUMN IF NOT EXISTS case_set_version INTEGER""",
    """ALTER TABLE policy_answer_verification_runs
       ADD COLUMN IF NOT EXISTS status VARCHAR(32)""",
    """ALTER TABLE policy_answer_verification_runs
       ADD COLUMN IF NOT EXISTS blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb""",
    """ALTER TABLE policy_answer_verification_runs
       ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP""",
    """ALTER TABLE policy_answer_verification_runs
       ADD COLUMN IF NOT EXISTS quality_run_id VARCHAR(64)""",
    """ALTER TABLE policy_answer_verification_runs
       ALTER COLUMN run_sequence SET DEFAULT nextval('policy_answer_verification_run_sequence_seq')""",
    """ALTER TABLE policy_answer_verification_case_results
       ADD COLUMN IF NOT EXISTS status VARCHAR(32)""",
    """ALTER TABLE policy_answer_verification_case_results
       ADD COLUMN IF NOT EXISTS gated_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb""",
    """ALTER TABLE policy_answer_verification_case_results
       ADD COLUMN IF NOT EXISTS skipped_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb""",
    """ALTER TABLE policy_answer_verification_case_results
       ADD COLUMN IF NOT EXISTS blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb""",
    """ALTER TABLE policy_answer_verification_case_results
       ADD COLUMN IF NOT EXISTS verification JSONB""",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_answer_verification_runs_run_sequence
       ON policy_answer_verification_runs(run_sequence)""",
)


class PostgresAnswerVerificationGateStore:
    """AnswerVerificationGateStore 的 PostgreSQL adapter。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is not None:
            return self._client
        client = PostgreSQLClient(self._database_url)
        try:
            for statement in ANSWER_VERIFICATION_GATE_SCHEMA.split(";"):
                if statement.strip():
                    client.execute(statement)
            for statement in ANSWER_VERIFICATION_GATE_MIGRATIONS:
                client.execute(statement)
        except BaseException:
            try:
                client.close()
            except BaseException:
                pass
            raise
        self._client = client
        return client

    def save_run(self, run: AnswerVerificationRun) -> AnswerVerificationRun:
        self._get_client().execute(
            """INSERT INTO policy_answer_verification_runs
               (run_id,release_id,case_set_version,status,blocked_reasons,created_at,quality_run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(run_id) DO UPDATE SET status=EXCLUDED.status,
               blocked_reasons=EXCLUDED.blocked_reasons,quality_run_id=EXCLUDED.quality_run_id""",
            (
                run.run_id,
                run.release_id,
                run.case_set_version,
                run.status,
                json.dumps(run.blocked_reasons),
                run.created_at,
                run.quality_run_id,
            ),
        )
        return run

    def get_run(self, run_id: str) -> AnswerVerificationRun | None:
        rows = self._get_client().execute(
            "SELECT * FROM policy_answer_verification_runs WHERE run_id=%s", (run_id,)
        )
        return AnswerVerificationRun(**rows[0]) if rows else None

    def get_latest_run(self, release_id: str) -> AnswerVerificationRun | None:
        rows = self._get_client().execute(
            """SELECT * FROM policy_answer_verification_runs
               WHERE release_id=%s ORDER BY run_sequence DESC LIMIT 1""",
            (release_id,),
        )
        return AnswerVerificationRun(**rows[0]) if rows else None

    def save_case_results(self, results: list[AnswerVerificationCaseResult]) -> None:
        self._get_client().execute_many(
            """INSERT INTO policy_answer_verification_case_results
               (run_id,case_id,status,gated_dimensions,skipped_dimensions,blocked_reasons,verification)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(run_id,case_id) DO UPDATE SET status=EXCLUDED.status,
               gated_dimensions=EXCLUDED.gated_dimensions,
               skipped_dimensions=EXCLUDED.skipped_dimensions,
               blocked_reasons=EXCLUDED.blocked_reasons,verification=EXCLUDED.verification""",
            [
                (
                    item.run_id,
                    item.case_id,
                    item.status,
                    json.dumps([dimension.value for dimension in item.gated_dimensions]),
                    json.dumps([dimension.value for dimension in item.skipped_dimensions]),
                    json.dumps(item.blocked_reasons),
                    json.dumps(item.verification.model_dump(mode="json")),
                )
                for item in results
            ],
        )

    def list_case_results(self, run_id: str) -> list[AnswerVerificationCaseResult]:
        rows = self._get_client().execute(
            """SELECT * FROM policy_answer_verification_case_results
               WHERE run_id=%s ORDER BY case_id""",
            (run_id,),
        )
        return [AnswerVerificationCaseResult(**row) for row in rows]
