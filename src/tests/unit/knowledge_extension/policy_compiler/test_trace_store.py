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


def run(run_id: str, *, status: str = "RUNNING") -> CompileRun:
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

    def execute(self, sql: str, params=()):
        normalized = " ".join(sql.lower().split())
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
            if any(item["step_id"] == params[0] for item in self.steps):
                raise ValueError("duplicate step")
            keys = (
                "step_id", "run_id", "sequence_no", "stage", "status",
                "input_payload", "output_payload", "issues", "error", "duration_ms",
                "started_at", "finished_at",
            )
            row = dict(zip(keys, params))
            for name in ("input_payload", "output_payload", "issues", "error"):
                if isinstance(row[name], str):
                    row[name] = json.loads(row[name])
            self.steps.append(row)
            return []
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
                "rule_version", "canonical_rule", "release_id", "created_at",
            )
            row = dict(zip(keys, params))
            row["canonical_rule"] = (
                json.loads(row["canonical_rule"]) if row["canonical_rule"] else None
            )
            self.lineages.append(row)
            return []
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
        if "from policy_rule_lineage where rule_id" in normalized:
            return sorted(
                [dict(item) for item in self.lineages if item["rule_id"] == params[0]],
                key=lambda item: item["rule_version"],
                reverse=True,
            )
        if "select rule_id from policy_rule_lineage where release_id" in normalized:
            return [
                {"rule_id": item["rule_id"]}
                for item in self.lineages
                if item["release_id"] == params[0]
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

    assert store.has_release_lineage("release_1", ["rule_x"])
    assert not store.has_release_lineage("release_1", ["rule_x", "rule_missing"])


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
    assert len(published.history) == 1
    assert store.has_release_lineage("release_1", ["rule_x"])


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
