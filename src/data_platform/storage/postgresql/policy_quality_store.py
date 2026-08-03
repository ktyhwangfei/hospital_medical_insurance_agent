"""政策知识版本与质量报告 PostgreSQL 存储。"""
from __future__ import annotations

import json

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
    QualityCaseResult,
    QualityRun,
)


QUALITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_qa_test_cases (
    case_id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    query TEXT NOT NULL,
    mode VARCHAR(32) NOT NULL,
    expected_knowledge_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    required BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    case_set_version INTEGER NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE SEQUENCE IF NOT EXISTS policy_case_set_version_seq;

CREATE TABLE IF NOT EXISTS policy_knowledge_releases (
    release_id VARCHAR(64) PRIMARY KEY,
    status VARCHAR(32) NOT NULL,
    facts_collection VARCHAR(256) NOT NULL,
    rules_collection VARCHAR(256) NOT NULL,
    contract_version VARCHAR(64) NOT NULL,
    case_set_version INTEGER NOT NULL,
    config_hash VARCHAR(128) NOT NULL,
    quality_score DOUBLE PRECISION,
    consistency_score DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    promoted_at TIMESTAMPTZ,
    promoted_by VARCHAR(128)
);

CREATE TABLE IF NOT EXISTS policy_quality_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    release_id VARCHAR(64) NOT NULL REFERENCES policy_knowledge_releases(release_id),
    baseline_release_id VARCHAR(64),
    case_set_version INTEGER NOT NULL,
    config_hash VARCHAR(128) NOT NULL,
    repeat_count INTEGER NOT NULL CHECK (repeat_count >= 3),
    status VARCHAR(32) NOT NULL,
    candidate_score DOUBLE PRECISION,
    baseline_score DOUBLE PRECISION,
    consistency_score DOUBLE PRECISION,
    blocked_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS policy_quality_case_results (
    run_id VARCHAR(64) NOT NULL REFERENCES policy_quality_runs(run_id) ON DELETE CASCADE,
    target VARCHAR(16) NOT NULL,
    case_id VARCHAR(64) NOT NULL,
    repeat_index INTEGER NOT NULL,
    result_knowledge_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    score DOUBLE PRECISION NOT NULL,
    passed BOOLEAN NOT NULL,
    diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, target, case_id, repeat_index)
);

CREATE TABLE IF NOT EXISTS policy_active_release (
    singleton_id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton_id),
    release_id VARCHAR(64) NOT NULL REFERENCES policy_knowledge_releases(release_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by VARCHAR(128)
);
"""


class PostgresPolicyQualityStore:
    """PolicyQualityStore 的 PostgreSQL adapter。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            for statement in QUALITY_SCHEMA.split(";"):
                if statement.strip():
                    self._client.execute(statement)
        return self._client

    def save_test_case(self, case: PolicyQATestCase) -> PolicyQATestCase:
        client = self._get_client()
        version_rows = client.execute("SELECT nextval('policy_case_set_version_seq') AS version")
        version = int(version_rows[0]["version"])
        saved = case.model_copy(update={"case_set_version": version})
        client.execute(
            """INSERT INTO policy_qa_test_cases
               (case_id,name,query,mode,expected_knowledge_ids,filters,required,active,case_set_version,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (case_id) DO UPDATE SET name=EXCLUDED.name,query=EXCLUDED.query,
               mode=EXCLUDED.mode,expected_knowledge_ids=EXCLUDED.expected_knowledge_ids,
               filters=EXCLUDED.filters,required=EXCLUDED.required,active=EXCLUDED.active,
               case_set_version=EXCLUDED.case_set_version,updated_at=EXCLUDED.updated_at""",
            (saved.case_id, saved.name, saved.query, saved.mode,
             json.dumps(saved.expected_knowledge_ids), json.dumps(saved.filters),
             saved.required, saved.active, version, saved.updated_at),
        )
        return saved

    def current_case_set_version(self) -> int:
        rows = self._get_client().execute(
            "SELECT COALESCE(MAX(case_set_version),0) AS version FROM policy_qa_test_cases"
        )
        return int(rows[0]["version"])

    def list_test_cases(self, active_only: bool = True) -> list[PolicyQATestCase]:
        where = "WHERE active=TRUE" if active_only else ""
        rows = self._get_client().execute(f"SELECT * FROM policy_qa_test_cases {where} ORDER BY case_id")
        return [PolicyQATestCase(**row) for row in rows]

    def save_release(self, release: KnowledgeRelease) -> KnowledgeRelease:
        self._get_client().execute(
            """INSERT INTO policy_knowledge_releases
               (release_id,status,facts_collection,rules_collection,contract_version,
                case_set_version,config_hash,quality_score,consistency_score,created_at,promoted_at,promoted_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (release_id) DO UPDATE SET status=EXCLUDED.status,
               quality_score=EXCLUDED.quality_score,consistency_score=EXCLUDED.consistency_score,
               promoted_at=EXCLUDED.promoted_at,promoted_by=EXCLUDED.promoted_by""",
            (
                release.release_id, release.status, release.facts_collection,
                release.rules_collection, release.contract_version,
                release.case_set_version, release.config_hash, release.quality_score,
                release.consistency_score, release.created_at, release.promoted_at,
                release.promoted_by,
            ),
        )
        return release

    def create_release(self, release: KnowledgeRelease) -> KnowledgeRelease:
        rows = self._get_client().execute(
            """INSERT INTO policy_knowledge_releases
               (release_id,status,facts_collection,rules_collection,contract_version,
                case_set_version,config_hash,quality_score,consistency_score,created_at,promoted_at,promoted_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (release_id) DO NOTHING RETURNING *""",
            (
                release.release_id, release.status, release.facts_collection,
                release.rules_collection, release.contract_version,
                release.case_set_version, release.config_hash, release.quality_score,
                release.consistency_score, release.created_at, release.promoted_at,
                release.promoted_by,
            ),
        )
        if not rows:
            raise ValueError(f"release {release.release_id} 已存在")
        return KnowledgeRelease(**rows[0])

    def get_release(self, release_id: str) -> KnowledgeRelease | None:
        rows = self._get_client().execute(
            "SELECT * FROM policy_knowledge_releases WHERE release_id=%s", (release_id,)
        )
        return KnowledgeRelease(**rows[0]) if rows else None

    def list_releases(self) -> list[KnowledgeRelease]:
        rows = self._get_client().execute(
            "SELECT * FROM policy_knowledge_releases ORDER BY created_at DESC"
        )
        return [KnowledgeRelease(**row) for row in rows]

    def get_active_release(self) -> KnowledgeRelease | None:
        rows = self._get_client().execute(
            """SELECT r.* FROM policy_active_release a
               JOIN policy_knowledge_releases r ON r.release_id=a.release_id
               WHERE a.singleton_id=TRUE"""
        )
        return KnowledgeRelease(**rows[0]) if rows else None

    def promote_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease:
        return self._switch_release(release_id, promoted_by, allow_retired=False)

    def rollback_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease:
        return self._switch_release(release_id, promoted_by, allow_retired=True)

    def _switch_release(self, release_id: str, promoted_by: str, allow_retired: bool) -> KnowledgeRelease:
        client = self._get_client()
        allowed = ("retired",) if allow_retired else ("passed",)
        with client.transaction() as connection:
            with connection.cursor() as cursor:
                # 固定事务锁覆盖“尚无 singleton 行”的首发场景，再锁现有活动指针行。
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('policy_active_release'))"
                )
                cursor.execute(
                    "SELECT release_id FROM policy_active_release "
                    "WHERE singleton_id=TRUE FOR UPDATE"
                )
                active_row = cursor.fetchone()
                current_active_release_id = active_row[0] if active_row else None
                cursor.execute(
                    "SELECT status,config_hash,promoted_at FROM policy_knowledge_releases WHERE release_id=%s FOR UPDATE",
                    (release_id,),
                )
                row = cursor.fetchone()
                if row is None or row[0] not in allowed:
                    raise ValueError(f"release {release_id} 未通过质量门禁或不可回滚")
                if allow_retired and row[2] is None:
                    raise ValueError(f"release {release_id} 不可回滚")
                if not allow_retired:
                    cursor.execute(
                        "SELECT COALESCE(MAX(case_set_version),0) FROM policy_qa_test_cases"
                    )
                    current_case_set_version = int(cursor.fetchone()[0])
                    cursor.execute(
                        """SELECT status,case_set_version,config_hash,baseline_release_id
                           FROM policy_quality_runs WHERE release_id=%s
                           ORDER BY created_at DESC LIMIT 1 FOR UPDATE""",
                        (release_id,),
                    )
                    latest_run = cursor.fetchone()
                    if latest_run is None or latest_run[0] != "passed":
                        raise ValueError(f"release {release_id} 缺少最新通过的质量运行")
                    if int(latest_run[1]) != current_case_set_version:
                        raise ValueError(f"release {release_id} 未通过最新用例集")
                    if latest_run[2] != row[1]:
                        raise ValueError(f"release {release_id} 的测试配置与质量运行不一致")
                    if latest_run[3] != current_active_release_id:
                        raise ValueError(f"release {release_id} 的质量运行活动基线已过期")
                cursor.execute(
                    "UPDATE policy_knowledge_releases SET status='retired' WHERE status='active' AND release_id<>%s",
                    (release_id,),
                )
                cursor.execute(
                    "UPDATE policy_knowledge_releases SET status='active',promoted_at=CURRENT_TIMESTAMP,promoted_by=%s WHERE release_id=%s",
                    (promoted_by, release_id),
                )
                cursor.execute(
                    """INSERT INTO policy_active_release(singleton_id,release_id,updated_by)
                       VALUES(TRUE,%s,%s) ON CONFLICT(singleton_id) DO UPDATE SET
                       release_id=EXCLUDED.release_id,updated_at=CURRENT_TIMESTAMP,updated_by=EXCLUDED.updated_by""",
                    (release_id, promoted_by),
                )
        active = self.get_release(release_id)
        if active is None:
            raise RuntimeError("活动版本切换后读取失败")
        return active

    def save_run(self, run: QualityRun) -> QualityRun:
        self._get_client().execute(
            """INSERT INTO policy_quality_runs
               (run_id,release_id,baseline_release_id,case_set_version,config_hash,repeat_count,
                status,candidate_score,baseline_score,consistency_score,blocked_reasons,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(run_id) DO UPDATE SET status=EXCLUDED.status,
               candidate_score=EXCLUDED.candidate_score,baseline_score=EXCLUDED.baseline_score,
               consistency_score=EXCLUDED.consistency_score,blocked_reasons=EXCLUDED.blocked_reasons""",
            (run.run_id, run.release_id, run.baseline_release_id, run.case_set_version,
             run.config_hash, run.repeat_count, run.status, run.candidate_score,
             run.baseline_score, run.consistency_score, json.dumps(run.blocked_reasons), run.created_at),
        )
        return run

    def get_run(self, run_id: str) -> QualityRun | None:
        rows = self._get_client().execute(
            "SELECT * FROM policy_quality_runs WHERE run_id=%s", (run_id,)
        )
        return QualityRun(**rows[0]) if rows else None

    def get_latest_run(self, release_id: str) -> QualityRun | None:
        rows = self._get_client().execute(
            "SELECT * FROM policy_quality_runs WHERE release_id=%s ORDER BY created_at DESC LIMIT 1",
            (release_id,),
        )
        return QualityRun(**rows[0]) if rows else None

    def save_case_results(self, results: list[QualityCaseResult]) -> None:
        self._get_client().execute_many(
            """INSERT INTO policy_quality_case_results
               (run_id,target,case_id,repeat_index,result_knowledge_ids,score,passed,diagnostics)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(run_id,target,case_id,repeat_index) DO UPDATE SET
               result_knowledge_ids=EXCLUDED.result_knowledge_ids,score=EXCLUDED.score,
               passed=EXCLUDED.passed,diagnostics=EXCLUDED.diagnostics""",
            [(item.run_id, item.target, item.case_id, item.repeat_index,
              json.dumps(item.result_knowledge_ids), item.score, item.passed,
              json.dumps(item.diagnostics)) for item in results],
        )

    def list_case_results(self, run_id: str) -> list[QualityCaseResult]:
        rows = self._get_client().execute(
            "SELECT * FROM policy_quality_case_results WHERE run_id=%s ORDER BY case_id,target,repeat_index",
            (run_id,),
        )
        return [QualityCaseResult(**row) for row in rows]
