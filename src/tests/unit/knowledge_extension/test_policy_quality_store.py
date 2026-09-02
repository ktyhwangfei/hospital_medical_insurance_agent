from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest


QUALITY_CONFIG_HASH = "197ceb8357b8a65b5db3db7044838ff7fd7010ab36caf2b11270e4ab61607e22"


def _release(release_id: str, status: str = "ready"):
    from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease

    return KnowledgeRelease(
        release_id=release_id,
        status=status,
        facts_collection=f"policy_facts_{release_id}",
        rules_collection=f"policy_rules_{release_id}",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
    )


def _release_with_source(
    release_id: str,
    source_change_set_id: str,
    status: str = "ready",
):
    from src.knowledge_extension.rule_explanation.quality_models import KnowledgeRelease

    return KnowledgeRelease(
        release_id=release_id,
        status=status,
        facts_collection=f"policy_facts_{release_id}",
        rules_collection=f"policy_rules_{release_id}",
        contract_version="2",
        case_set_version=1,
        config_hash=QUALITY_CONFIG_HASH,
        source_change_set_id=source_change_set_id,
    )


class _FakePolicyQualityClient:
    """仅替代 PostgreSQL I/O，保留 release UPSERT 的真实字段语义。"""

    def __init__(
        self,
        *,
        has_source_lineage_column: bool = True,
        has_quality_run_id_column: bool = True,
        has_build_error_column: bool = True,
        has_run_sequence_column: bool = True,
        run_sequences: dict[str, int | None] | None = None,
        run_sequence_has_default: bool = True,
        run_sequence_not_null: bool = True,
        run_sequence_owned: bool = True,
        run_sequence_next: int = 1,
        has_run_sequence_unique_index: bool = True,
        has_answer_verification_column: bool = False,
    ) -> None:
        self.releases: dict[str, dict] = {}
        self.has_source_lineage_column = has_source_lineage_column
        self.has_quality_run_id_column = has_quality_run_id_column
        self.has_build_error_column = has_build_error_column
        self.has_answer_verification_column = has_answer_verification_column
        self.has_run_sequence_column = has_run_sequence_column
        self.run_sequences = dict(run_sequences or {})
        self.run_sequence_has_default = run_sequence_has_default
        self.run_sequence_not_null = run_sequence_not_null
        self.run_sequence_owned = run_sequence_owned
        self.run_sequence_next = run_sequence_next
        self.has_run_sequence_unique_index = has_run_sequence_unique_index
        self.fail_source_lineage_migration = False
        self.fail_run_sequence_migration = False
        self.fail_lock_timeout_reset = False
        self.fail_close = False
        self.executed_sql: list[str] = []
        self.closed = False

    def execute(self, sql: str, params=None):
        normalized = " ".join(sql.split())
        upper = normalized.upper()
        self.executed_sql.append(normalized)
        if "FROM INFORMATION_SCHEMA.COLUMNS" in upper:
            assert "TABLE_SCHEMA = CURRENT_SCHEMA()" in upper
            if "COLUMN_NAME = 'SOURCE_CHANGE_SET_ID'" in upper:
                assert "TABLE_NAME = 'POLICY_KNOWLEDGE_RELEASES'" in upper
                return [{"exists": self.has_source_lineage_column}]
            if "COLUMN_NAME = 'QUALITY_RUN_ID'" in upper:
                assert "TABLE_NAME = 'POLICY_KNOWLEDGE_RELEASES'" in upper
                return [{"exists": self.has_quality_run_id_column}]
            if "COLUMN_NAME = 'BUILD_ERROR'" in upper:
                assert "TABLE_NAME = 'POLICY_KNOWLEDGE_RELEASES'" in upper
                return [{"exists": self.has_build_error_column}]
            if "COLUMN_NAME = 'ANSWER_VERIFICATION'" in upper:
                assert "TABLE_NAME = 'POLICY_QA_TEST_CASES'" in upper
                return [{"exists": self.has_answer_verification_column}]
            assert "TABLE_NAME = 'POLICY_QUALITY_RUNS'" in upper
            assert "COLUMN_NAME = 'RUN_SEQUENCE'" in upper
            return [{"exists": self.has_run_sequence_column}]
        if upper.startswith("ALTER TABLE POLICY_KNOWLEDGE_RELEASES"):
            if "SOURCE_CHANGE_SET_ID" in upper and self.fail_source_lineage_migration:
                raise RuntimeError("migration lock timeout")
            if "SOURCE_CHANGE_SET_ID" in upper:
                self.has_source_lineage_column = True
            if "QUALITY_RUN_ID" in upper:
                self.has_quality_run_id_column = True
            if "BUILD_ERROR" in upper:
                self.has_build_error_column = True
            return []
        if upper.startswith("ALTER TABLE POLICY_QUALITY_RUNS"):
            if self.fail_run_sequence_migration:
                raise RuntimeError("run sequence migration lock timeout")
            if "ADD COLUMN" in upper:
                self.has_run_sequence_column = True
            if "SET DEFAULT" in upper:
                self.run_sequence_has_default = True
            if "SET NOT NULL" in upper:
                self.run_sequence_not_null = True
            return []
        if upper.startswith("ALTER TABLE POLICY_QA_TEST_CASES"):
            if "ANSWER_VERIFICATION" in upper and "ADD COLUMN" in upper:
                self.has_answer_verification_column = True
            return []
        if upper.startswith("CREATE UNIQUE INDEX"):
            if not self.has_run_sequence_column:
                raise RuntimeError("run_sequence column does not exist")
            self.has_run_sequence_unique_index = True
            return []
        if upper.startswith("WITH ORDERED_RUNS AS"):
            next_sequence = max(
                (value for value in self.run_sequences.values() if value is not None),
                default=0,
            ) + 1
            for run_id in sorted(self.run_sequences):
                if self.run_sequences[run_id] is None:
                    self.run_sequences[run_id] = next_sequence
                    next_sequence += 1
            return []
        if upper.startswith("SELECT SETVAL"):
            maximum = max(self.run_sequences.values(), default=0)  # type: ignore[arg-type]
            self.run_sequence_next = max(self.run_sequence_next, int(maximum) + 1)
            return []
        if upper.startswith("ALTER SEQUENCE"):
            self.run_sequence_owned = True
            return []
        if upper == "RESET LOCK_TIMEOUT" and self.fail_lock_timeout_reset:
            raise RuntimeError("lock timeout reset failed")
        if upper.startswith((
            "CREATE ",
            "SET LOCK_TIMEOUT",
            "SET LOCAL LOCK_TIMEOUT",
            "RESET LOCK_TIMEOUT",
            "SELECT PG_ADVISORY_XACT_LOCK",
        )):
            return []
        if upper.startswith("INSERT INTO POLICY_KNOWLEDGE_RELEASES"):
            assert params is not None
            columns_text = normalized.split("(", 1)[1].split(")", 1)[0]
            columns = [column.strip() for column in columns_text.split(",")]
            inserted = dict(zip(columns, params, strict=True))
            release_id = inserted["release_id"]
            existing = self.releases.get(release_id)
            if existing is not None and "DO NOTHING" in upper:
                return []
            if existing is None:
                self.releases[release_id] = inserted
            else:
                update_clause = normalized.split("DO UPDATE SET", 1)[1]
                where_clause = update_clause.split("WHERE", 1)[1] if "WHERE" in update_clause else ""
                guards = re.findall(
                    r"policy_knowledge_releases\.(\w+)\s+"
                    r"(=|IS NOT DISTINCT FROM)\s+EXCLUDED\.\w+",
                    where_clause,
                    flags=re.IGNORECASE,
                )
                for field, operator in guards:
                    current = existing.get(field)
                    proposed = inserted.get(field)
                    if operator == "=" and (current is None or proposed is None):
                        return []
                    if current != proposed:
                        return []
                update_clause = update_clause.split("RETURNING", 1)[0]
                for field in re.findall(r"(\w+)=EXCLUDED\.\w+", update_clause):
                    existing[field] = inserted[field]
            if "RETURNING *" in upper:
                return [self.releases[release_id].copy()]
            return []
        if upper.startswith("SELECT * FROM POLICY_KNOWLEDGE_RELEASES WHERE"):
            assert params is not None
            row = self.releases.get(params[0])
            return [row.copy()] if row else []
        if upper.startswith("SELECT * FROM POLICY_KNOWLEDGE_RELEASES ORDER BY"):
            return [row.copy() for row in reversed(self.releases.values())]
        raise AssertionError(f"未支持的 SQL: {normalized}")

    @contextmanager
    def transaction(self):
        client = self

        class Cursor:
            rows: list[dict]

            def __init__(self) -> None:
                self.rows = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback) -> None:
                return None

            def execute(self, sql: str, params=None) -> None:
                self.rows = client.execute(sql, params)

            def fetchone(self):
                if not self.rows:
                    return None
                return tuple(self.rows[0].values())

        class Connection:
            def cursor(self):
                return Cursor()

        self.executed_sql.append("BEGIN")
        try:
            yield Connection()
        except BaseException:
            self.executed_sql.append("ROLLBACK")
            raise
        else:
            self.executed_sql.append("COMMIT")

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("client close failed")


def _postgres_store(client: _FakePolicyQualityClient):
    from src.data_platform.storage.postgresql.policy_quality_store import (
        PostgresPolicyQualityStore,
    )

    store = PostgresPolicyQualityStore("postgresql://test")
    store._client = client
    return store


def _initialize_postgres_store(monkeypatch, client: _FakePolicyQualityClient):
    from src.data_platform.storage.postgresql import policy_quality_store

    monkeypatch.setattr(
        policy_quality_store,
        "PostgreSQLClient",
        lambda database_url: client,
    )
    store = policy_quality_store.PostgresPolicyQualityStore("postgresql://test")
    store._get_client()
    return store


def _save_passed_run(
    store, release_id: str, case_set_version: int = 1,
    baseline_release_id: str | None = None,
) -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun

    store.save_run(QualityRun(
        run_id=f"run_{release_id}",
        release_id=release_id,
        baseline_release_id=baseline_release_id,
        case_set_version=case_set_version,
        config_hash=QUALITY_CONFIG_HASH,
        status="passed",
    ))


def test_case_changes_create_new_case_set_version() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import PolicyQATestCase
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    first = store.save_test_case(PolicyQATestCase(
        case_id="case_1",
        name="职工住院支付比例",
        query="职工住院报销比例是多少",
        mode="semantic",
        expected_knowledge_ids=["kn_1"],
        required=True,
    ))
    updated = first.model_copy(update={"query": "在职职工住院支付比例"})
    second = store.save_test_case(updated)

    assert first.case_set_version == 1
    assert second.case_set_version == 2
    assert store.current_case_set_version() == 2


def test_ready_release_identity_is_immutable() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_release(_release("rel_1"))

    with pytest.raises(ValueError, match="不可修改"):
        store.save_release(_release("rel_1").model_copy(update={"contract_version": "3"}))


def test_release_without_source_lineage_roundtrips_in_memory() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    created = store.create_release(_release("legacy"))
    saved = store.save_release(created.model_copy(update={"status": "testing"}))

    assert created.source_change_set_id is None
    assert saved.source_change_set_id is None
    assert store.get_release("legacy").source_change_set_id is None  # type: ignore[union-attr]
    assert store.list_releases()[0].source_change_set_id is None


def test_release_source_lineage_roundtrips_in_memory() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    created = store.create_release(_release_with_source("candidate", "change_set_1"))
    saved = store.save_release(created.model_copy(update={"status": "testing"}))

    assert created.source_change_set_id == "change_set_1"
    assert saved.source_change_set_id == "change_set_1"
    assert store.get_release("candidate").source_change_set_id == "change_set_1"  # type: ignore[union-attr]
    assert store.list_releases()[0].source_change_set_id == "change_set_1"


def test_release_source_lineage_is_immutable_in_memory() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.create_release(_release_with_source("candidate", "change_set_1"))

    with pytest.raises(ValueError, match="不可修改"):
        store.save_release(_release_with_source("candidate", "change_set_2"))

    assert store.get_release("candidate").source_change_set_id == "change_set_1"  # type: ignore[union-attr]


def test_policy_quality_schema_migrates_release_source_lineage() -> None:
    from src.data_platform.storage.postgresql import policy_quality_store

    ddl = " ".join(policy_quality_store.QUALITY_SCHEMA.upper().split())
    migration = " ".join(
        getattr(
            policy_quality_store,
            "RELEASE_SOURCE_LINEAGE_MIGRATION_SQL",
            "",
        ).upper().split()
    )

    assert "SOURCE_CHANGE_SET_ID VARCHAR(64)" in ddl
    assert "ALTER TABLE POLICY_KNOWLEDGE_RELEASES" not in ddl
    assert (
        "ALTER TABLE POLICY_KNOWLEDGE_RELEASES ADD COLUMN IF NOT EXISTS "
        "SOURCE_CHANGE_SET_ID VARCHAR(64)"
    ) in migration


def test_missing_release_build_error_column_runs_bounded_migration(monkeypatch) -> None:
    client = _FakePolicyQualityClient(has_build_error_column=False)

    _initialize_postgres_store(monkeypatch, client)

    upper_sql = [sql.upper() for sql in client.executed_sql]
    query_index = next(
        index for index, sql in enumerate(upper_sql)
        if "COLUMN_NAME = 'BUILD_ERROR'" in sql
    )
    set_index = upper_sql.index("SET LOCK_TIMEOUT = '5S'", query_index)
    alter_index = next(
        index for index, sql in enumerate(upper_sql[set_index:], start=set_index)
        if sql.startswith("ALTER TABLE POLICY_KNOWLEDGE_RELEASES")
        and "BUILD_ERROR" in sql
    )
    reset_index = upper_sql.index("RESET LOCK_TIMEOUT", alter_index)
    assert query_index < set_index < alter_index < reset_index


def test_existing_release_source_column_skips_alter(monkeypatch) -> None:
    client = _FakePolicyQualityClient(
        has_source_lineage_column=True,
        has_answer_verification_column=True,
    )

    _initialize_postgres_store(monkeypatch, client)

    assert any("INFORMATION_SCHEMA.COLUMNS" in sql.upper() for sql in client.executed_sql)
    assert not any(
        sql.upper().startswith("ALTER TABLE POLICY_KNOWLEDGE_RELEASES")
        for sql in client.executed_sql
    )
    assert "SET LOCK_TIMEOUT = '5S'" not in {
        sql.upper() for sql in client.executed_sql
    }


def test_missing_release_source_column_runs_bounded_migration(monkeypatch) -> None:
    client = _FakePolicyQualityClient(has_source_lineage_column=False)

    _initialize_postgres_store(monkeypatch, client)

    upper_sql = [sql.upper() for sql in client.executed_sql]
    set_index = upper_sql.index("SET LOCK_TIMEOUT = '5S'")
    alter_index = next(
        index for index, sql in enumerate(upper_sql)
        if sql.startswith("ALTER TABLE POLICY_KNOWLEDGE_RELEASES")
    )
    reset_index = upper_sql.index("RESET LOCK_TIMEOUT")
    assert set_index < alter_index < reset_index
    assert client.has_source_lineage_column is True


def test_release_source_migration_resets_lock_timeout_on_failure(monkeypatch) -> None:
    client = _FakePolicyQualityClient(has_source_lineage_column=False)
    client.fail_source_lineage_migration = True

    with pytest.raises(RuntimeError, match="migration lock timeout"):
        _initialize_postgres_store(monkeypatch, client)

    assert client.executed_sql[-1].upper() == "RESET LOCK_TIMEOUT"


def test_failed_initialization_retries_with_fresh_client(monkeypatch) -> None:
    from src.data_platform.storage.postgresql import policy_quality_store

    failed_client = _FakePolicyQualityClient(has_source_lineage_column=False)
    failed_client.fail_source_lineage_migration = True
    retry_client = _FakePolicyQualityClient(has_source_lineage_column=False)
    clients = iter([failed_client, retry_client])
    monkeypatch.setattr(
        policy_quality_store,
        "PostgreSQLClient",
        lambda database_url: next(clients),
    )
    store = policy_quality_store.PostgresPolicyQualityStore("postgresql://test")

    with pytest.raises(RuntimeError, match="migration lock timeout"):
        store._get_client()

    assert failed_client.closed is True
    assert store._client is None

    initialized = store._get_client()

    assert initialized is retry_client
    assert retry_client.has_source_lineage_column is True
    assert any(
        "INFORMATION_SCHEMA.COLUMNS" in sql.upper()
        for sql in retry_client.executed_sql
    )


def test_migration_failure_remains_primary_when_reset_also_fails(monkeypatch) -> None:
    from src.data_platform.storage.postgresql import policy_quality_store

    client = _FakePolicyQualityClient(has_source_lineage_column=False)
    client.fail_source_lineage_migration = True
    client.fail_lock_timeout_reset = True
    monkeypatch.setattr(
        policy_quality_store,
        "PostgreSQLClient",
        lambda database_url: client,
    )
    store = policy_quality_store.PostgresPolicyQualityStore("postgresql://test")

    with pytest.raises(RuntimeError, match="migration lock timeout"):
        store._get_client()

    assert client.executed_sql[-1].upper() == "RESET LOCK_TIMEOUT"
    assert client.closed is True
    assert store._client is None


def test_initialization_failure_remains_primary_when_close_fails(monkeypatch) -> None:
    from src.data_platform.storage.postgresql import policy_quality_store

    client = _FakePolicyQualityClient(has_source_lineage_column=False)
    client.fail_source_lineage_migration = True
    client.fail_close = True
    monkeypatch.setattr(
        policy_quality_store,
        "PostgreSQLClient",
        lambda database_url: client,
    )
    store = policy_quality_store.PostgresPolicyQualityStore("postgresql://test")

    with pytest.raises(RuntimeError, match="migration lock timeout"):
        store._get_client()

    assert client.closed is True
    assert store._client is None


def test_release_without_source_lineage_roundtrips_in_postgres_store() -> None:
    client = _FakePolicyQualityClient()
    store = _postgres_store(client)
    legacy = _release("legacy")
    client.releases[legacy.release_id] = legacy.model_dump(
        exclude={"source_change_set_id"}
    )

    loaded = store.get_release("legacy")
    saved = store.save_release(legacy.model_copy(update={"status": "testing"}))

    assert loaded is not None and loaded.source_change_set_id is None
    assert saved.source_change_set_id is None
    assert store.list_releases()[0].source_change_set_id is None


def test_release_source_lineage_roundtrips_in_postgres_store() -> None:
    client = _FakePolicyQualityClient()
    store = _postgres_store(client)
    release = _release_with_source("candidate", "change_set_1")

    created = store.create_release(release)
    loaded = store.get_release("candidate")
    saved = store.save_release(release.model_copy(update={"status": "testing"}))

    assert created.source_change_set_id == "change_set_1"
    assert loaded is not None and loaded.source_change_set_id == "change_set_1"
    assert saved.source_change_set_id == "change_set_1"
    assert store.list_releases()[0].source_change_set_id == "change_set_1"


@pytest.mark.parametrize(("field", "replacement"), [
    ("facts_collection", "other_facts"),
    ("rules_collection", "other_rules"),
    ("contract_version", "3"),
    ("case_set_version", 2),
    ("config_hash", "other_config"),
    ("source_change_set_id", "change_set_2"),
])
def test_release_identity_is_immutable_in_postgres_store(
    field: str,
    replacement: str | int,
) -> None:
    client = _FakePolicyQualityClient()
    store = _postgres_store(client)
    original = store.create_release(_release_with_source("candidate", "change_set_1"))

    with pytest.raises(ValueError, match="不可修改"):
        store.save_release(original.model_copy(update={field: replacement}))

    assert store.get_release("candidate") == original


def test_candidate_and_baseline_results_are_stored_separately() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityCaseResult
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_case_results([
        QualityCaseResult(
            run_id="run_1",
            target="candidate",
            case_id="case_1",
            repeat_index=0,
            result_knowledge_ids=["kn_new"],
            score=1,
            passed=True,
        ),
        QualityCaseResult(
            run_id="run_1",
            target="baseline",
            case_id="case_1",
            repeat_index=0,
            result_knowledge_ids=["kn_old"],
            score=0,
            passed=False,
        ),
    ])

    assert {(result.target, result.result_knowledge_ids[0]) for result in store.case_results} == {
        ("candidate", "kn_new"),
        ("baseline", "kn_old"),
    }


def test_latest_run_is_queryable_by_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_run(QualityRun(run_id="run_1", release_id="candidate", case_set_version=1, config_hash="cfg"))
    store.save_run(QualityRun(run_id="run_2", release_id="candidate", case_set_version=2, config_hash="cfg"))

    assert store.get_latest_run("candidate").run_id == "run_2"  # type: ignore[union-attr]


def test_quality_run_claim_and_completion_require_matching_owner() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_release(_release("candidate", status="failed"))

    previous_status = store.claim_quality_run("candidate", "run_owner")

    assert previous_status == "failed"
    claimed = store.get_release("candidate")
    assert claimed is not None
    assert claimed.status == "testing"
    assert claimed.quality_run_id == "run_owner"
    with pytest.raises(ValueError, match="质量运行"):
        store.claim_quality_run("candidate", "run_other")
    with pytest.raises(ValueError, match="所有权"):
        store.complete_quality_run(
            "candidate",
            "run_other",
            status="passed",
            quality_score=1.0,
            consistency_score=1.0,
        )
    assert store.get_release("candidate").status == "testing"  # type: ignore[union-attr]

    completed = store.complete_quality_run(
        "candidate",
        "run_owner",
        status="passed",
        quality_score=1.0,
        consistency_score=1.0,
    )

    assert completed.status == "passed"
    assert completed.quality_run_id is None


def test_quality_run_restore_is_owner_checked_and_returns_original_status() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_release(_release("candidate"))
    original_status = store.claim_quality_run("candidate", "run_owner")

    with pytest.raises(ValueError, match="所有权"):
        store.restore_quality_run("candidate", "run_other", original_status)
    restored = store.restore_quality_run("candidate", "run_owner", original_status)

    assert restored.status == "ready"
    assert restored.quality_run_id is None


def test_latest_run_uses_first_save_order_when_timestamps_match() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    created_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    store = InMemoryPolicyQualityStore()
    first = QualityRun(
        run_id="run_z",
        release_id="candidate",
        case_set_version=1,
        config_hash="cfg",
        created_at=created_at,
    )
    second = first.model_copy(update={"run_id": "run_a"})
    store.save_run(first)
    store.save_run(second)
    store.save_run(first.model_copy(update={"status": "failed"}))

    latest = store.get_latest_run("candidate")

    assert latest is not None and latest.run_id == "run_a"


def test_postgres_latest_run_orders_by_persisted_first_save_sequence() -> None:
    from src.data_platform.storage.postgresql.policy_quality_store import (
        PostgresPolicyQualityStore,
    )
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun

    class RunClient:
        def __init__(self) -> None:
            self.executed_sql: list[str] = []

        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split())
            self.executed_sql.append(normalized)
            if normalized.upper().startswith("INSERT INTO POLICY_QUALITY_RUNS"):
                return []
            if normalized.upper().startswith(
                "SELECT * FROM POLICY_QUALITY_RUNS WHERE RELEASE_ID"
            ):
                return [{
                    "run_id": "run_second",
                    "release_id": params[0],
                    "case_set_version": 1,
                    "config_hash": "cfg",
                    "repeat_count": 3,
                    "status": "passed",
                    "blocked_reasons": [],
                    "created_at": datetime(2026, 8, 6, tzinfo=timezone.utc),
                    "run_sequence": 2,
                }]
            raise AssertionError(f"未支持的 SQL: {normalized}")

    client = RunClient()
    store = PostgresPolicyQualityStore("postgresql://test")
    store._client = client  # type: ignore[assignment]
    created_at = datetime(2026, 8, 6, tzinfo=timezone.utc)
    store.save_run(QualityRun(
        run_id="run_first",
        release_id="candidate",
        case_set_version=1,
        config_hash="cfg",
        created_at=created_at,
    ))
    store.save_run(QualityRun(
        run_id="run_second",
        release_id="candidate",
        case_set_version=1,
        config_hash="cfg",
        created_at=created_at,
    ))
    store.save_run(QualityRun(
        run_id="run_first",
        release_id="candidate",
        case_set_version=1,
        config_hash="cfg",
        status="failed",
        created_at=created_at,
    ))

    latest = store.get_latest_run("candidate")

    assert latest is not None and latest.run_id == "run_second"
    latest_sql = client.executed_sql[-1].upper()
    assert "ORDER BY RUN_SEQUENCE DESC" in latest_sql
    insert_sql = client.executed_sql[0].upper()
    assert "RUN_SEQUENCE" not in insert_sql


def test_postgres_quality_run_claim_and_completion_use_owner_cas() -> None:
    from src.data_platform.storage.postgresql.policy_quality_store import (
        PostgresPolicyQualityStore,
    )

    class ClaimClient:
        def __init__(self) -> None:
            self.executed: list[tuple[str, tuple]] = []

        def execute(self, sql: str, params=()):
            normalized = " ".join(sql.split())
            self.executed.append((normalized, params))
            if normalized.upper().startswith("WITH CANDIDATE AS"):
                return [{"previous_status": "failed"}]
            if normalized.upper().startswith("UPDATE POLICY_KNOWLEDGE_RELEASES"):
                return [{
                    **_release("candidate", status="passed").model_dump(),
                    "quality_run_id": None,
                }]
            raise AssertionError(f"未支持的 SQL: {normalized}")

    client = ClaimClient()
    store = PostgresPolicyQualityStore("postgresql://test")
    store._client = client  # type: ignore[assignment]

    previous = store.claim_quality_run("candidate", "run_owner")
    completed = store.complete_quality_run(
        "candidate",
        "run_owner",
        status="passed",
        quality_score=1.0,
        consistency_score=1.0,
    )

    assert previous == "failed"
    assert completed.status == "passed"
    claim_sql, claim_params = client.executed[0]
    assert "STATUS IN ('READY','FAILED')" in claim_sql.upper()
    assert "QUALITY_RUN_ID IS NULL" in claim_sql.upper()
    assert claim_params == ("run_owner", "candidate")
    complete_sql, complete_params = client.executed[1]
    assert "QUALITY_RUN_ID=%S" in complete_sql.upper()
    assert "STATUS='TESTING'" in complete_sql.upper()
    assert "QUALITY_RUN_ID=NULL" in complete_sql.upper()
    assert complete_params[-2:] == ("candidate", "run_owner")


def test_policy_quality_schema_has_monotonic_run_sequence_migration() -> None:
    from src.data_platform.storage.postgresql import policy_quality_store

    ddl = " ".join(policy_quality_store.QUALITY_SCHEMA.upper().split())
    migration = " ".join(
        getattr(policy_quality_store, "QUALITY_RUN_SEQUENCE_MIGRATION_SQL", "")
        .upper()
        .split()
    )
    unique_index = " ".join(
        policy_quality_store.QUALITY_RUN_SEQUENCE_UNIQUE_INDEX_SQL.upper().split()
    )
    owner_migration = " ".join(
        policy_quality_store.RELEASE_QUALITY_RUN_ID_MIGRATION_SQL.upper().split()
    )

    assert "QUALITY_RUN_ID VARCHAR(64)" in ddl
    assert "ADD COLUMN IF NOT EXISTS QUALITY_RUN_ID VARCHAR(64)" in owner_migration
    assert "CREATE SEQUENCE IF NOT EXISTS POLICY_QUALITY_RUN_SEQUENCE_SEQ" in ddl
    assert (
        "RUN_SEQUENCE BIGINT NOT NULL DEFAULT "
        "NEXTVAL('POLICY_QUALITY_RUN_SEQUENCE_SEQ')"
    ) in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in unique_index
    assert (
        "ADD COLUMN IF NOT EXISTS RUN_SEQUENCE BIGINT"
    ) in migration
    assert "ROW_NUMBER() OVER (ORDER BY CREATED_AT ASC, RUN_ID ASC)" in migration
    assert "SELECT SETVAL(" in migration
    assert "GREATEST(" in migration
    assert "IS_CALLED" in migration
    assert "'POLICY_QUALITY_RUN_SEQUENCE_SEQ'" in migration
    assert "ALTER COLUMN RUN_SEQUENCE SET DEFAULT NEXTVAL(" in migration
    assert "ALTER COLUMN RUN_SEQUENCE SET NOT NULL" in migration
    assert "CREATE UNIQUE INDEX IF NOT EXISTS" in migration


def test_missing_run_sequence_column_runs_bounded_retryable_migration(
    monkeypatch,
) -> None:
    client = _FakePolicyQualityClient(has_run_sequence_column=False)

    _initialize_postgres_store(monkeypatch, client)

    upper_sql = [sql.upper() for sql in client.executed_sql]
    begin_index = upper_sql.index("BEGIN")
    timeout_index = upper_sql.index("SET LOCAL LOCK_TIMEOUT = '5S'")
    alter_index = next(
        index
        for index, sql in enumerate(upper_sql)
        if sql.startswith("ALTER TABLE POLICY_QUALITY_RUNS")
        and "ADD COLUMN" in sql
    )
    commit_index = upper_sql.index("COMMIT")
    assert begin_index < timeout_index < alter_index < commit_index
    assert client.has_run_sequence_column is True


def test_existing_incomplete_run_sequence_is_reconciled_without_reordering_values(
    monkeypatch,
) -> None:
    client = _FakePolicyQualityClient(
        has_run_sequence_column=True,
        run_sequences={"run_existing": 7, "run_missing": None},
        run_sequence_has_default=False,
        run_sequence_not_null=False,
        run_sequence_owned=False,
        run_sequence_next=2,
        has_run_sequence_unique_index=False,
    )

    _initialize_postgres_store(monkeypatch, client)

    upper_sql = [sql.upper() for sql in client.executed_sql]
    assert "BEGIN" in upper_sql
    assert "COMMIT" in upper_sql
    assert client.run_sequences["run_existing"] == 7
    assert client.run_sequences["run_missing"] == 8
    assert client.run_sequence_has_default is True
    assert client.run_sequence_not_null is True
    assert client.run_sequence_owned is True
    assert client.run_sequence_next >= 9
    assert client.has_run_sequence_unique_index is True

    before = client.run_sequences.copy()
    _initialize_postgres_store(monkeypatch, client)

    assert client.run_sequences == before


def test_run_sequence_migration_failure_can_retry_with_fresh_client(
    monkeypatch,
) -> None:
    from src.data_platform.storage.postgresql import policy_quality_store

    failed_client = _FakePolicyQualityClient(has_run_sequence_column=False)
    failed_client.fail_run_sequence_migration = True
    retry_client = _FakePolicyQualityClient(has_run_sequence_column=False)
    clients = iter([failed_client, retry_client])
    monkeypatch.setattr(
        policy_quality_store,
        "PostgreSQLClient",
        lambda database_url: next(clients),
    )
    store = policy_quality_store.PostgresPolicyQualityStore("postgresql://test")

    with pytest.raises(RuntimeError, match="run sequence migration lock timeout"):
        store._get_client()

    assert failed_client.closed is True
    assert store._client is None
    assert "ROLLBACK" in failed_client.executed_sql
    assert store._get_client() is retry_client
    assert retry_client.has_run_sequence_column is True


def test_only_passed_release_can_be_promoted_atomically() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("rel_old", status="passed"))
    _save_passed_run(store, "rel_old")
    store.promote_release("rel_old", promoted_by="reviewer")
    store.save_release(_release("rel_failed", status="failed"))

    with pytest.raises(ValueError, match="未通过质量门禁"):
        store.promote_release("rel_failed", promoted_by="reviewer")

    assert store.get_active_release().release_id == "rel_old"  # type: ignore[union-attr]
    assert store.get_release("rel_old").status == "active"  # type: ignore[union-attr]


def test_promotion_switches_one_pointer_and_rollback_restores_previous_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("rel_1", status="passed"))
    _save_passed_run(store, "rel_1")
    store.promote_release("rel_1", promoted_by="reviewer")
    store.save_release(_release("rel_2", status="passed"))
    _save_passed_run(store, "rel_2", baseline_release_id="rel_1")

    promoted = store.promote_release("rel_2", promoted_by="reviewer")

    assert promoted.release_id == "rel_2"
    assert store.get_active_release().release_id == "rel_2"  # type: ignore[union-attr]
    assert store.get_release("rel_1").status == "retired"  # type: ignore[union-attr]

    rolled_back = store.rollback_release("rel_1", promoted_by="reviewer")

    assert rolled_back.release_id == "rel_1"
    assert store.get_active_release().release_id == "rel_1"  # type: ignore[union-attr]
    assert store.get_release("rel_2").status == "retired"  # type: ignore[union-attr]


@pytest.mark.parametrize("status", ["ready", "testing", "passed"])
def test_rollback_rejects_release_that_was_never_active(status: str) -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_release(_release("candidate", status=status))

    with pytest.raises(ValueError, match="不可回滚"):
        store.rollback_release("candidate", promoted_by="reviewer")


def test_promotion_rejects_run_compared_to_stale_active_release() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("current", status="active"))
    store.active_release_id = "current"
    store.save_release(_release("candidate", status="passed"))
    store.save_run(QualityRun(
        run_id="run_candidate", release_id="candidate", baseline_release_id="previous",
        case_set_version=1, config_hash=QUALITY_CONFIG_HASH, status="passed",
    ))

    with pytest.raises(ValueError, match="活动基线"):
        store.promote_release("candidate", promoted_by="reviewer")


def test_create_release_is_atomic_and_preserves_existing_identity() -> None:
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    original = store.create_release(_release("candidate"))

    with pytest.raises(ValueError, match="已存在"):
        store.create_release(_release("candidate").model_copy(update={"contract_version": "3"}))

    assert store.get_release("candidate") == original


def test_promotion_rejects_passed_run_after_case_set_changes() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import PolicyQATestCase
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store.save_test_case(PolicyQATestCase(
        case_id="case_1", name="原用例", query="原用例", mode="semantic"
    ))
    store.save_release(_release("candidate", status="passed"))
    _save_passed_run(store, "candidate")
    store.save_test_case(PolicyQATestCase(
        case_id="case_2", name="新增用例", query="新增用例", mode="semantic"
    ))

    with pytest.raises(ValueError, match="最新用例集"):
        store.promote_release("candidate", promoted_by="reviewer")


def test_promotion_rejects_passed_run_with_different_config_hash() -> None:
    from src.knowledge_extension.rule_explanation.quality_models import QualityRun
    from src.knowledge_extension.rule_explanation.quality_store import InMemoryPolicyQualityStore

    store = InMemoryPolicyQualityStore()
    store._case_set_version = 1
    store.save_release(_release("candidate", status="passed"))
    store.save_run(QualityRun(
        run_id="run_candidate",
        release_id="candidate",
        case_set_version=1,
        config_hash="forged",
        status="passed",
    ))

    with pytest.raises(ValueError, match="测试配置"):
        store.promote_release("candidate", promoted_by="reviewer")
