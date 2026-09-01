import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileRun,
    CompileStep,
    ValidationIssue,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
    PostgresCompilationTraceStore,
)


def run(
    run_id: str,
    *,
    status: str = "RUNNING",
    started_at: datetime | None = None,
) -> CompileRun:
    return CompileRun(
        run_id=run_id,
        document_id="doc_x",
        unit_id="unit_x",
        extraction_id=f"ext_{run_id}",
        raw_input={"source_text": "原文"},
        llm_output={"rules": [{"ratio": "0.1"}]},
        model_name="gateway-model",
        prompt_version="prompt-v1",
        schema_version="schema-v1",
        status=status,
        **({"started_at": started_at} if started_at else {}),
    )


def step(run_id: str, sequence_no: int, stage: str) -> CompileStep:
    return CompileStep(
        step_id=f"{run_id}_{sequence_no}",
        run_id=run_id,
        sequence_no=sequence_no,
        stage=stage,
        status="PASS",
        input_payload={"sequence": sequence_no},
        output_payload={"ok": True},
        finished_at=datetime.now(timezone.utc),
    )


def rule(version: int) -> CanonicalRule:
    return CanonicalRule(
        rule_id="rule_x",
        subject="personal_payment_ratio",
        result={"ratio": Decimal("0.1")},
        evidence=["evidence_x"],
        rule_version=version,
    )


class FakePostgreSQLClient:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}
        self.steps: list[dict] = []
        self.lineages: list[dict] = []
        self.executed_sql: list[str] = []

    def execute(self, sql: str, params=()):
        normalized = " ".join(sql.lower().split())
        self.executed_sql.append(normalized)
        if normalized.startswith("insert into policy_compile_runs"):
            if params[0] in self.runs:
                raise ValueError("duplicate run")
            keys = (
                "run_id", "document_id", "unit_id", "extraction_id", "raw_input",
                "llm_output", "model_name", "prompt_version", "schema_version",
                "compiler_version", "status", "metrics", "error", "started_at",
                "finished_at",
            )
            row = dict(zip(keys, params))
            for name in ("raw_input", "llm_output", "metrics", "error"):
                if isinstance(row[name], str):
                    row[name] = json.loads(row[name])
            self.runs[row["run_id"]] = row
            return []
        if normalized.startswith("insert into policy_compile_steps"):
            keys = (
                "step_id", "run_id", "sequence_no", "stage", "status",
                "input_payload", "output_payload", "issues", "error", "duration_ms",
                "started_at", "finished_at",
            )
            row = dict(zip(keys, params))
            for name in ("input_payload", "output_payload", "issues", "error"):
                if isinstance(row[name], str):
                    row[name] = json.loads(row[name])
            if any(
                item["step_id"] == row["step_id"]
                or (
                    item["run_id"] == row["run_id"]
                    and item["sequence_no"] == row["sequence_no"]
                )
                for item in self.steps
            ):
                if "on conflict do nothing" in normalized:
                    return []
                raise ValueError("duplicate step")
            self.steps.append(row)
            return [dict(row)] if "returning" in normalized else []
        if normalized.startswith("update policy_compile_runs"):
            status, metrics, error, finished_at, run_id = params
            row = self.runs.get(run_id)
            if not row or row["status"] != "RUNNING":
                return []
            row.update(
                status=status,
                metrics=json.loads(metrics),
                error=json.loads(error) if error else None,
                finished_at=finished_at,
            )
            return [dict(row)]
        if normalized.startswith("insert into policy_rule_lineage"):
            keys = (
                "lineage_id", "rule_id", "extraction_id", "doc_id", "compile_run_id",
                "rule_version", "canonical_rule", "release_id", "published_at",
                "created_at",
            )
            if "do nothing" in normalized:
                values = (*params[:7], None, None, params[7])
            else:
                values = params
            row = dict(zip(keys, values))
            if row["canonical_rule"]:
                row["canonical_rule"] = json.loads(row["canonical_rule"])
            existing = next((
                item for item in self.lineages
                if item["rule_id"] == row["rule_id"]
                and item["compile_run_id"] == row["compile_run_id"]
            ), None)
            if existing is not None and "do nothing" in normalized:
                return []
            if existing is not None and "do update" in normalized:
                if (
                    existing["release_id"] not in {None, row["release_id"]}
                    or existing["extraction_id"] != row["extraction_id"]
                    or existing["doc_id"] != row["doc_id"]
                    or existing["rule_version"] != row["rule_version"]
                    or existing["canonical_rule"] != row["canonical_rule"]
                ):
                    return []
                if existing["release_id"] is None:
                    existing["published_at"] = row["published_at"]
                existing["release_id"] = row["release_id"]
                return [dict(existing)]
            self.lineages.append(row)
            return [dict(row)] if "returning" in normalized else []
        if normalized.startswith("update policy_rule_lineage"):
            (
                canonical_rule, release_id, rule_version, created_at,
                rule_id, run_id, expected_release_id,
            ) = params
            for row in self.lineages:
                if (
                    row["rule_id"] == rule_id
                    and row["compile_run_id"] == run_id
                    and row["release_id"] in {None, expected_release_id}
                ):
                    row.update(
                        canonical_rule=json.loads(canonical_rule),
                        release_id=release_id,
                        rule_version=rule_version,
                        created_at=created_at,
                    )
                    return [dict(row)]
            return []
        if "from policy_compile_runs where run_id" in normalized:
            row = self.runs.get(params[0])
            return [dict(row)] if row else []
        if "from policy_compile_runs where extraction_id" in normalized:
            return [
                {"exists": 1}
                for row in self.runs.values()
                if row["extraction_id"] == params[0]
            ][:1]
        if "from policy_compile_steps where run_id" in normalized:
            return sorted(
                [dict(item) for item in self.steps if item["run_id"] == params[0]],
                key=lambda item: item["sequence_no"],
            )
        if "from policy_rule_lineage as lineage" in normalized:
            return sorted(
                [
                    dict(item) for item in self.lineages
                    if item["rule_id"] == params[0]
                    and (params[1] is None or item["compile_run_id"] == params[2])
                ],
                key=lambda item: (
                    self.runs[item["compile_run_id"]]["started_at"],
                    item["created_at"],
                    item["rule_version"] or 0,
                ),
                reverse=True,
            )
        if (
            "select rule_id, compile_run_id from policy_rule_lineage where release_id"
            in normalized
        ):
            return [
                {
                    "rule_id": item["rule_id"],
                    "compile_run_id": item["compile_run_id"],
                }
                for item in self.lineages
                if item["release_id"] == params[0]
                and item["compile_run_id"] is not None
                and item["canonical_rule"] is not None
            ]
        return []


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return InMemoryCompilationTraceStore()
    postgres = PostgresCompilationTraceStore("postgresql://test")
    postgres._client = FakePostgreSQLClient()
    return postgres


def test_runs_and_steps_are_append_only(store) -> None:
    created = store.create_run(run("run_1"))
    assert created.status == "RUNNING"
    with pytest.raises(ValueError):
        store.create_run(run("run_1"))

    store.append_step("run_1", step("run_1", 1, "CANONICALIZE"))
    with pytest.raises(ValueError):
        store.append_step("run_1", step("run_1", 1, "CANONICALIZE"))

    finished = store.finish_run("run_1", status="PASS", metrics={"rules": 1})
    assert finished.status == "PASS"
    with pytest.raises(ValueError):
        store.finish_run("run_1", status="FAIL", metrics={})


def test_recompilation_keeps_ordered_trace_history_and_snapshots(store) -> None:
    for version in (1, 2):
        run_id = f"run_{version}"
        store.create_run(run(run_id))
        store.append_step(run_id, step(run_id, 1, "CANONICALIZE"))
        store.append_step(run_id, step(run_id, 2, "VALIDATE"))
        store.finish_run(run_id, status="PASS", metrics={"version": version})
        store.save_lineage(
            rule=rule(version),
            run_id=run_id,
            extraction_id=f"ext_{version}",
            document_id="doc_x",
            release_id=f"release_{version}",
        )

    trace = store.get_rule_trace("rule_x")

    assert trace is not None
    assert trace.rule.rule_version == 2
    assert trace.rule.result == {"ratio": Decimal("0.1")}
    assert [item.sequence_no for item in trace.steps] == [1, 2]
    assert [item.rule_version for item in trace.history] == [2, 1]
    assert trace.raw_input == {"source_text": "原文"}
    assert trace.llm_output == {"rules": [{"ratio": "0.1"}]}
    assert trace.publication.release_id == "release_2"


def test_failed_run_remains_queryable(store) -> None:
    store.create_run(run("run_failed"))
    failed = store.finish_run(
        "run_failed",
        status="FAIL",
        metrics={"issues": 1},
        error={"code": "TRACE_WRITE_FAILED"},
    )

    assert store.get_run("run_failed") == failed
    assert failed.error == {"code": "TRACE_WRITE_FAILED"}


def test_latest_failed_attempt_is_current_even_without_canonical_rule(store) -> None:
    earlier = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
    later = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
    store.create_run(run("run_pass", started_at=earlier))
    store.finish_run("run_pass", status="PASS", metrics={})
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_pass",
        extraction_id="ext_pass",
        document_id="doc_x",
    )
    issue = ValidationIssue(
        issue_id="issue_latest_fail",
        severity="FAIL",
        code="LATEST_COMPILATION_FAILED",
        stage="VALIDATE",
        fact_id="rule_x",
        message="最新编译失败",
        recommended_action="修复后重试",
    )
    store.create_run(run("run_fail", started_at=later))
    store.append_step(
        "run_fail",
        step("run_fail", 1, "VALIDATE").model_copy(
            update={"status": "FAIL", "issues": [issue]}
        ),
    )
    store.finish_run("run_fail", status="FAIL", metrics={"issues": 1})
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=None,
        run_id="run_fail",
        extraction_id="ext_fail",
        document_id="doc_x",
    )

    trace = store.get_rule_trace("rule_x")

    assert trace is not None
    assert trace.run.run_id == "run_fail"
    assert trace.rule is None
    assert trace.issues == [issue]
    assert [item.run_id for item in trace.history] == ["run_fail", "run_pass"]

    passed = store.get_rule_trace("rule_x", run_id="run_pass")
    failed = store.get_rule_trace("rule_x", run_id="run_fail")
    assert passed is not None
    assert passed.run.run_id == "run_pass"
    assert passed.rule == rule(1)
    assert [item.run_id for item in passed.history] == ["run_pass"]
    assert failed is not None
    assert failed.run.run_id == "run_fail"
    assert failed.rule is None
    assert [item.run_id for item in failed.history] == ["run_fail"]
    assert store.get_rule_trace("rule_x", run_id="run_wrong") is None
    if isinstance(store, PostgresCompilationTraceStore):
        exact_query = next(
            sql for sql in reversed(store._client.executed_sql)
            if "from policy_rule_lineage as lineage" in sql
        )
        assert "lineage.compile_run_id=%s" in exact_query


def test_extraction_run_marker_supports_idempotent_backfill(store) -> None:
    assert not store.has_extraction_run("ext_run_1")

    store.create_run(run("run_1"))

    assert store.has_extraction_run("ext_run_1")


def test_release_lineage_requires_every_rule(store) -> None:
    store.create_run(run("run_1"))
    store.finish_run("run_1", status="PASS", metrics={})
    store.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )

    assert store.has_release_lineage("release_1", [("rule_x", "run_1")])
    assert not store.has_release_lineage("release_1", [("rule_x", "run_other")])
    assert not store.has_release_lineage(
        "release_1", [("rule_x", "run_1"), ("rule_missing", "run_2")]
    )

    store.create_run(run("run_extra"))
    store.finish_run("run_extra", status="PASS", metrics={})
    store.save_lineage(
        rule=rule(1).model_copy(update={"rule_id": "rule_extra"}),
        run_id="run_extra",
        extraction_id="ext_extra",
        document_id="doc_x",
        release_id="release_1",
    )
    assert not store.has_release_lineage("release_1", [("rule_x", "run_1")])


def test_candidate_lineage_is_queryable_and_publication_fills_same_history(store) -> None:
    store.create_run(run("run_1"))
    store.append_step("run_1", step("run_1", 1, "CANONICALIZE"))
    store.finish_run("run_1", status="PASS", metrics={})
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
    )

    candidate = store.get_rule_trace("rule_x")

    assert candidate is not None
    assert candidate.rule_id == "rule_x"
    assert candidate.rule == rule(1)
    assert candidate.publication is None
    assert len(candidate.history) == 1

    store.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )
    first_publication = store.get_rule_trace("rule_x").publication
    store.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )
    published = store.get_rule_trace("rule_x")

    assert published is not None
    assert published.publication is not None
    assert published.publication.release_id == "release_1"
    assert published.publication == first_publication
    assert len(published.history) == 1
    assert store.has_release_lineage("release_1", [("rule_x", "run_1")])


def test_candidate_without_canonical_rule_keeps_failed_run_and_issues_queryable(store) -> None:
    issue = ValidationIssue(
        issue_id="issue_1",
        severity="FAIL",
        code="RATIO_INVALID",
        stage="CANONICALIZE",
        fact_id="knowledge_failed",
        message="比例不是有效数值",
        recommended_action="提供结构化数值",
    )
    store.create_run(run("run_failed"))
    failed_step = step("run_failed", 1, "CANONICALIZE").model_copy(
        update={"status": "FAIL", "issues": [issue]}
    )
    store.append_step("run_failed", failed_step)
    store.finish_run("run_failed", status="FAIL", metrics={"issues": 1})
    store.save_candidate_lineage(
        rule_id="knowledge_failed",
        rule=None,
        run_id="run_failed",
        extraction_id="ext_run_failed",
        document_id="doc_x",
    )

    trace = store.get_rule_trace("knowledge_failed")

    assert trace is not None
    assert trace.rule_id == "knowledge_failed"
    assert trace.rule is None
    assert trace.run.status == "FAIL"
    assert [item.sequence_no for item in trace.steps] == [1]
    assert trace.issues == [issue]
    assert trace.publication is None


def test_candidate_lineage_duplicate_write_is_idempotent(store) -> None:
    store.create_run(run("run_1"))
    store.finish_run("run_1", status="PASS", metrics={})

    for _ in range(2):
        store.save_candidate_lineage(
            rule_id="rule_x",
            rule=rule(1),
            run_id="run_1",
            extraction_id="ext_1",
            document_id="doc_x",
        )

    trace = store.get_rule_trace("rule_x")

    assert trace is not None
    assert len(trace.history) == 1


def test_identical_publish_step_is_idempotent_but_changed_payload_conflicts(store) -> None:
    store.create_run(run("run_1"))
    publish = step("run_1", 8, "PUBLISH").model_copy(update={
        "step_id": "run_1_publish_release_1",
        "input_payload": {"release_id": "release_1", "rule_id": "rule_x"},
        "output_payload": {"rules_collection": "rules_release_1"},
    })

    store.append_step("run_1", publish)
    store.append_step("run_1", publish)

    with pytest.raises(ValueError, match="编译步骤已存在"):
        store.append_step(
            "run_1",
            publish.model_copy(update={
                "output_payload": {"rules_collection": "rules_other"}
            }),
        )


def test_postgres_candidate_write_uses_unique_conflict_safe_sql() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_store import (
        LINEAGE_TABLE,
        LINEAGE_MIGRATION,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        _SCHEMA,
    )

    postgres = PostgresCompilationTraceStore("postgresql://test")
    fake = FakePostgreSQLClient()
    postgres._client = fake
    postgres.create_run(run("run_1"))
    postgres.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
    )
    postgres.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )

    candidate_insert = next(
        sql for sql in fake.executed_sql
        if sql.startswith("insert into policy_rule_lineage")
    )
    publication_upsert = next(
        sql for sql in reversed(fake.executed_sql)
        if sql.startswith("insert into policy_rule_lineage")
    )
    assert "on conflict (rule_id, compile_run_id) do nothing" in candidate_insert
    assert "on conflict (rule_id, compile_run_id) do update" in publication_upsert
    assert "policy_rule_lineage.release_id is null" in publication_upsert
    assert "policy_rule_lineage.extraction_id=excluded.extraction_id" in publication_upsert
    assert "policy_rule_lineage.doc_id=excluded.doc_id" in publication_upsert
    assert "canonical_rule is not distinct from excluded.canonical_rule" in publication_upsert
    assert "created_at=excluded.created_at" not in publication_upsert
    assert "when policy_rule_lineage.release_id is null" in publication_upsert
    assert "else policy_rule_lineage.published_at" in publication_upsert
    assert "published_at timestamptz" in LINEAGE_TABLE.lower()
    assert "add column if not exists published_at timestamptz" in LINEAGE_MIGRATION.lower()
    assert "published_at timestamptz default" not in LINEAGE_MIGRATION.lower()
    assert "add column if not exists published_at timestamptz" in _SCHEMA.lower()
    assert _SCHEMA.lower().index("add column if not exists published_at") < (
        _SCHEMA.lower().index("unique index")
    )
    assert "unique index" in LINEAGE_MIGRATION.lower()
    assert "unique index" in _SCHEMA.lower()


def test_compile_run_cannot_be_reassociated_to_another_release(store) -> None:
    store.create_run(run("run_1"))
    store.finish_run("run_1", status="PASS", metrics={})
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
    )
    store.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )

    with pytest.raises(ValueError, match="已关联其他发布"):
        store.save_lineage(
            rule=rule(1),
            run_id="run_1",
            extraction_id="ext_1",
            document_id="doc_x",
            release_id="release_2",
        )

    assert store.has_release_lineage("release_1", [("rule_x", "run_1")])
    assert not store.has_release_lineage("release_2", [("rule_x", "run_1")])


def test_pipeline_schema_adds_lineage_columns_before_unique_index() -> None:
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

    class SchemaClient:
        def __init__(self) -> None:
            self.compile_run_column_exists = False
            self.unique_index_created = False

        def execute(self, sql, params=()):
            normalized = " ".join(sql.lower().split())
            if "add column if not exists compile_run_id" in normalized:
                self.compile_run_column_exists = True
            if "uq_lineage_rule_compile_run" in normalized:
                if not self.compile_run_column_exists:
                    raise AssertionError("unique index created before compile_run_id migration")
                self.unique_index_created = True
            return []

    client = SchemaClient()
    pipeline = PipelineStore()
    pipeline._client = client

    pipeline._ensure_schema()

    assert client.unique_index_created


def test_history_uses_attempt_time_and_old_publication_does_not_reorder(store) -> None:
    for run_id, candidate_rule, started_at in (
        ("run_v2", rule(2), datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)),
        ("run_v1", rule(1), datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)),
        ("run_null", None, datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)),
    ):
        store.create_run(run(run_id, started_at=started_at))
        store.finish_run(run_id, status="PASS", metrics={})
        store.save_candidate_lineage(
            rule_id="rule_x",
            rule=candidate_rule,
            run_id=run_id,
            extraction_id=f"ext_{run_id}",
            document_id="doc_x",
        )

    store.save_lineage(
        rule=rule(1),
        run_id="run_v1",
        extraction_id="ext_run_v1",
        document_id="doc_x",
        release_id="release_old",
    )
    trace = store.get_rule_trace("rule_x")

    assert trace is not None
    assert trace.rule == rule(2)
    assert [item.rule_version for item in trace.history] == [2, 1, None]
    assert trace.publication is None

    if isinstance(store, PostgresCompilationTraceStore):
        history_sql = next(
            sql for sql in store._client.executed_sql
            if "from policy_rule_lineage as lineage" in sql
        )
        assert "run.started_at desc" in history_sql
        assert "lineage.created_at desc" in history_sql


def test_publication_uses_first_publish_time_not_candidate_time(store, monkeypatch) -> None:
    from src.knowledge_extension.rule_explanation.policy_compiler import trace_store

    candidate_time = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)
    publish_time = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
    retry_time = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
    moments = iter((candidate_time, publish_time, retry_time))

    class Clock:
        @classmethod
        def now(cls, tz):
            return next(moments)

    store.create_run(run("run_1"))
    store.finish_run("run_1", status="PASS", metrics={})
    monkeypatch.setattr(trace_store, "datetime", Clock)
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
    )
    store.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )

    first = store.get_rule_trace("rule_x")
    assert first is not None
    assert first.publication is not None
    assert first.publication.published_at == publish_time

    store.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )
    retried = store.get_rule_trace("rule_x")
    assert retried is not None
    assert retried.publication == first.publication


def test_legacy_release_without_publish_time_does_not_invent_one(store) -> None:
    store.create_run(run("run_legacy"))
    store.finish_run("run_legacy", status="PASS", metrics={})
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_legacy",
        extraction_id="ext_legacy",
        document_id="doc_x",
    )
    lineages = (
        store._lineages
        if isinstance(store, InMemoryCompilationTraceStore)
        else store._client.lineages
    )
    lineages[0]["release_id"] = "release_legacy"

    trace = store.get_rule_trace("rule_x")

    assert trace is not None
    assert trace.publication is not None
    assert trace.publication.release_id == "release_legacy"
    assert trace.publication.published_at is None

    store.save_lineage(
        rule=rule(1),
        run_id="run_legacy",
        extraction_id="ext_legacy",
        document_id="doc_x",
        release_id="release_legacy",
    )
    retried = store.get_rule_trace("rule_x")
    assert retried is not None
    assert retried.publication is not None
    assert retried.publication.published_at is None


@pytest.mark.parametrize(
    ("published_rule", "extraction_id", "document_id"),
    [
        (rule(1).model_copy(update={"result": {"ratio": Decimal("0.2")}}), "ext_1", "doc_x"),
        (rule(2), "ext_1", "doc_x"),
        (rule(1), "ext_changed", "doc_x"),
        (rule(1), "ext_1", "doc_changed"),
    ],
)
def test_candidate_snapshot_must_match_before_publication(
    store, published_rule, extraction_id, document_id
) -> None:
    store.create_run(run("run_1"))
    store.finish_run("run_1", status="PASS", metrics={})
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
    )

    with pytest.raises(ValueError, match="快照冲突"):
        store.save_lineage(
            rule=published_rule,
            run_id="run_1",
            extraction_id=extraction_id,
            document_id=document_id,
            release_id="release_1",
        )

    trace = store.get_rule_trace("rule_x")
    assert trace is not None
    assert trace.rule == rule(1)
    assert trace.publication is None


def test_same_release_retry_rejects_changed_snapshot(store) -> None:
    store.create_run(run("run_1"))
    store.finish_run("run_1", status="PASS", metrics={})
    store.save_candidate_lineage(
        rule_id="rule_x",
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
    )
    store.save_lineage(
        rule=rule(1),
        run_id="run_1",
        extraction_id="ext_1",
        document_id="doc_x",
        release_id="release_1",
    )
    before = store.get_rule_trace("rule_x")

    with pytest.raises(ValueError, match="快照冲突"):
        store.save_lineage(
            rule=rule(2),
            run_id="run_1",
            extraction_id="ext_1",
            document_id="doc_x",
            release_id="release_1",
        )

    assert store.get_rule_trace("rule_x") == before


def test_postgres_step_insert_is_conflict_safe() -> None:
    postgres = PostgresCompilationTraceStore("postgresql://test")
    fake = FakePostgreSQLClient()
    postgres._client = fake
    postgres.create_run(run("run_1"))
    publish = step("run_1", 8, "PUBLISH")

    postgres.append_step("run_1", publish)

    insert_sql = next(
        sql for sql in fake.executed_sql
        if sql.startswith("insert into policy_compile_steps")
    )
    assert "on conflict do nothing" in insert_sql
    assert "returning" in insert_sql
