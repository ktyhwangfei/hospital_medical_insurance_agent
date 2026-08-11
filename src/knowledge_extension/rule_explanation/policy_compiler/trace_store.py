"""政策规则编译运行、步骤与规则血缘存储。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol

from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileRun,
    CompileStatus,
    CompileStep,
    RuleCompilationTraceResponse,
    RulePublication,
    RuleTraceHistorySummary,
)


class CompilationTraceStore(Protocol):
    def create_run(self, run: CompileRun) -> CompileRun: ...
    def append_step(self, run_id: str, step: CompileStep) -> CompileStep: ...
    def finish_run(
        self,
        run_id: str,
        *,
        status: CompileStatus,
        metrics: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> CompileRun: ...
    def get_run(self, run_id: str) -> CompileRun | None: ...
    def has_extraction_run(self, extraction_id: str) -> bool: ...
    def save_candidate_lineage(
        self,
        *,
        rule_id: str,
        rule: CanonicalRule | None,
        run_id: str,
        extraction_id: str,
        document_id: str,
    ) -> None: ...
    def save_lineage(
        self,
        *,
        rule: CanonicalRule,
        run_id: str,
        extraction_id: str,
        document_id: str,
        release_id: str,
    ) -> None: ...
    def get_rule_trace(self, rule_id: str) -> RuleCompilationTraceResponse | None: ...
    def has_release_lineage(
        self, release_id: str, rule_runs: list[tuple[str, str]]
    ) -> bool: ...


class InMemoryCompilationTraceStore:
    def __init__(self) -> None:
        self._runs: dict[str, CompileRun] = {}
        self._steps: dict[str, list[CompileStep]] = {}
        self._lineages: list[dict[str, Any]] = []

    def create_run(self, run: CompileRun) -> CompileRun:
        if run.run_id in self._runs:
            raise ValueError(f"编译运行已存在: {run.run_id}")
        self._runs[run.run_id] = run.model_copy(deep=True)
        return run.model_copy(deep=True)

    def append_step(self, run_id: str, step: CompileStep) -> CompileStep:
        if run_id not in self._runs or step.run_id != run_id:
            raise ValueError(f"编译运行不存在或步骤不匹配: {run_id}")
        items = self._steps.setdefault(run_id, [])
        existing = next((
            item for item in items
            if item.step_id == step.step_id or item.sequence_no == step.sequence_no
        ), None)
        if existing is not None and existing.stage == "PUBLISH" and existing == step:
            return existing.model_copy(deep=True)
        if existing is not None:
            raise ValueError(f"编译步骤已存在: {step.step_id}")
        items.append(step.model_copy(deep=True))
        return step.model_copy(deep=True)

    def finish_run(
        self,
        run_id: str,
        *,
        status: CompileStatus,
        metrics: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> CompileRun:
        run = self._runs.get(run_id)
        if run is None or run.status != "RUNNING":
            raise ValueError(f"编译运行不可完成: {run_id}")
        finished = run.model_copy(update={
            "status": status,
            "metrics": metrics,
            "error": error,
            "finished_at": datetime.now(timezone.utc),
        }, deep=True)
        self._runs[run_id] = finished
        return finished.model_copy(deep=True)

    def get_run(self, run_id: str) -> CompileRun | None:
        run = self._runs.get(run_id)
        return run.model_copy(deep=True) if run else None

    def has_extraction_run(self, extraction_id: str) -> bool:
        return any(run.extraction_id == extraction_id for run in self._runs.values())

    def save_lineage(
        self,
        *,
        rule: CanonicalRule,
        run_id: str,
        extraction_id: str,
        document_id: str,
        release_id: str,
    ) -> None:
        if run_id not in self._runs:
            raise ValueError(f"编译运行不存在: {run_id}")
        candidate = next((
            item for item in self._lineages
            if item["rule_id"] == rule.rule_id
            and item["run_id"] == run_id
        ), None)
        if candidate is not None:
            if candidate["release_id"] not in {None, release_id}:
                raise ValueError(
                    f"编译运行 {run_id} 已关联其他发布: "
                    f"{candidate['release_id']}"
                )
            if (
                candidate["rule"] != rule
                or candidate["extraction_id"] != extraction_id
                or candidate["document_id"] != document_id
            ):
                raise ValueError(f"编译运行 {run_id} 血缘快照冲突")
            candidate["release_id"] = release_id
            return
        self._lineages.append({
            "rule_id": rule.rule_id,
            "rule": rule.model_copy(deep=True),
            "run_id": run_id,
            "extraction_id": extraction_id,
            "document_id": document_id,
            "release_id": release_id,
            "created_at": datetime.now(timezone.utc),
        })

    def save_candidate_lineage(
        self,
        *,
        rule_id: str,
        rule: CanonicalRule | None,
        run_id: str,
        extraction_id: str,
        document_id: str,
    ) -> None:
        if run_id not in self._runs:
            raise ValueError(f"编译运行不存在: {run_id}")
        if any(
            item["rule_id"] == rule_id and item["run_id"] == run_id
            for item in self._lineages
        ):
            return
        self._lineages.append({
            "rule_id": rule_id,
            "rule": rule.model_copy(deep=True) if rule else None,
            "run_id": run_id,
            "extraction_id": extraction_id,
            "document_id": document_id,
            "release_id": None,
            "created_at": datetime.now(timezone.utc),
        })

    def get_rule_trace(self, rule_id: str) -> RuleCompilationTraceResponse | None:
        lineages = sorted(
            (item for item in self._lineages if item["rule_id"] == rule_id),
            key=lambda item: (
                item["rule"] is not None,
                item["rule"].rule_version if item["rule"] else -1,
                item["created_at"],
            ),
            reverse=True,
        )
        if not lineages:
            return None
        current = lineages[0]
        run = self._runs[current["run_id"]]
        steps = sorted(self._steps.get(run.run_id, []), key=lambda item: item.sequence_no)
        return self._trace(current, run, steps, lineages)

    def has_release_lineage(
        self, release_id: str, rule_runs: list[tuple[str, str]]
    ) -> bool:
        traced = {
            (item["rule_id"], item["run_id"]) for item in self._lineages
            if item["release_id"] == release_id and item["rule"] is not None
        }
        return set(rule_runs) == traced

    def _trace(
        self,
        current: dict[str, Any],
        run: CompileRun,
        steps: list[CompileStep],
        lineages: list[dict[str, Any]],
    ) -> RuleCompilationTraceResponse:
        return RuleCompilationTraceResponse(
            rule_id=current["rule_id"],
            rule=current["rule"],
            run=run,
            raw_input=run.raw_input,
            llm_output=run.llm_output,
            steps=steps,
            issues=[issue for step in steps for issue in step.issues],
            publication=(
                RulePublication(
                    release_id=current["release_id"],
                    published_at=current["created_at"],
                )
                if current["release_id"] else None
            ),
            history=[
                RuleTraceHistorySummary(
                    run_id=item["run_id"],
                    rule_version=(item["rule"].rule_version if item["rule"] else None),
                    status=self._runs[item["run_id"]].status,
                    compiler_version=(
                        item["rule"].compiler_version
                        if item["rule"] else self._runs[item["run_id"]].compiler_version
                    ),
                    started_at=self._runs[item["run_id"]].started_at,
                    finished_at=self._runs[item["run_id"]].finished_at,
                )
                for item in lineages
            ],
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_compile_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    document_id VARCHAR(64) NOT NULL,
    unit_id VARCHAR(128) NOT NULL,
    extraction_id VARCHAR(64) NOT NULL,
    raw_input JSONB NOT NULL,
    llm_output JSONB NOT NULL,
    model_name VARCHAR(128),
    prompt_version VARCHAR(128),
    schema_version VARCHAR(128),
    compiler_version VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}',
    error JSONB,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_policy_compile_runs_extraction
    ON policy_compile_runs(extraction_id);
CREATE TABLE IF NOT EXISTS policy_compile_steps (
    step_id VARCHAR(96) PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES policy_compile_runs(run_id),
    sequence_no INTEGER NOT NULL,
    stage VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL,
    input_payload JSONB NOT NULL DEFAULT '{}',
    output_payload JSONB NOT NULL DEFAULT '{}',
    issues JSONB NOT NULL DEFAULT '[]',
    error JSONB,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    UNIQUE(run_id, sequence_no)
);
CREATE INDEX IF NOT EXISTS idx_policy_compile_steps_run
    ON policy_compile_steps(run_id, sequence_no);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lineage_rule_compile_run
    ON policy_rule_lineage(rule_id, compile_run_id);
"""


class PostgresCompilationTraceStore:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url
        self._client: Any | None = None

    def _get_client(self):
        if self._client is None:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient

            self._client = PostgreSQLClient(self._database_url or DATABASE_URL)
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    self._client.execute(statement)
        return self._client

    def create_run(self, run: CompileRun) -> CompileRun:
        if self.get_run(run.run_id) is not None:
            raise ValueError(f"编译运行已存在: {run.run_id}")
        self._get_client().execute(
            """INSERT INTO policy_compile_runs
               (run_id, document_id, unit_id, extraction_id, raw_input, llm_output,
                model_name, prompt_version, schema_version, compiler_version, status,
                metrics, error, started_at, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                run.run_id, run.document_id, run.unit_id, run.extraction_id,
                self._json(run.raw_input), self._json(run.llm_output), run.model_name,
                run.prompt_version, run.schema_version, run.compiler_version, run.status,
                self._json(run.metrics), self._json(run.error), run.started_at, run.finished_at,
            ),
        )
        return run

    def append_step(self, run_id: str, step: CompileStep) -> CompileStep:
        if self.get_run(run_id) is None or step.run_id != run_id:
            raise ValueError(f"编译运行不存在或步骤不匹配: {run_id}")
        # 先依赖唯一约束竞争写入，再重读判定是否为完全相同的发布重试。
        rows = self._get_client().execute(
            """INSERT INTO policy_compile_steps
               (step_id, run_id, sequence_no, stage, status, input_payload,
                output_payload, issues, error, duration_ms, started_at, finished_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT DO NOTHING RETURNING *""",
            (
                step.step_id, run_id, step.sequence_no, step.stage, step.status,
                self._json(step.input_payload), self._json(step.output_payload),
                self._json([issue.model_dump(mode="json") for issue in step.issues]),
                self._json(step.error), step.duration_ms, step.started_at, step.finished_at,
            ),
        )
        if rows:
            return step
        existing = next((
            item for item in self._get_steps(run_id)
            if item.step_id == step.step_id or item.sequence_no == step.sequence_no
        ), None)
        if existing is not None and existing.stage == "PUBLISH" and existing == step:
            return existing
        raise ValueError(f"编译步骤已存在: {step.step_id}")

    def finish_run(
        self,
        run_id: str,
        *,
        status: CompileStatus,
        metrics: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> CompileRun:
        rows = self._get_client().execute(
            """UPDATE policy_compile_runs
               SET status=%s, metrics=%s, error=%s, finished_at=%s
               WHERE run_id=%s AND status='RUNNING' RETURNING *""",
            (status, self._json(metrics), self._json(error), datetime.now(timezone.utc), run_id),
        )
        if not rows:
            raise ValueError(f"编译运行不可完成: {run_id}")
        return self._run_row(rows[0])

    def get_run(self, run_id: str) -> CompileRun | None:
        rows = self._get_client().execute(
            "SELECT * FROM policy_compile_runs WHERE run_id=%s", (run_id,)
        )
        return self._run_row(rows[0]) if rows else None

    def has_extraction_run(self, extraction_id: str) -> bool:
        return bool(self._get_client().execute(
            "SELECT 1 FROM policy_compile_runs WHERE extraction_id=%s LIMIT 1",
            (extraction_id,),
        ))

    def save_lineage(
        self,
        *,
        rule: CanonicalRule,
        run_id: str,
        extraction_id: str,
        document_id: str,
        release_id: str,
    ) -> None:
        # 候选发布只补 release_id，编译时固化的审计快照与时间不得覆盖。
        rows = self._get_client().execute(
            """INSERT INTO policy_rule_lineage
               (lineage_id, rule_id, extraction_id, doc_id, compile_run_id,
                rule_version, canonical_rule, release_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (rule_id, compile_run_id) DO UPDATE SET
                 release_id=EXCLUDED.release_id
               WHERE (policy_rule_lineage.release_id IS NULL
                  OR policy_rule_lineage.release_id=EXCLUDED.release_id)
                 AND policy_rule_lineage.extraction_id=EXCLUDED.extraction_id
                 AND policy_rule_lineage.doc_id=EXCLUDED.doc_id
                 AND policy_rule_lineage.rule_version IS NOT DISTINCT FROM EXCLUDED.rule_version
                 AND policy_rule_lineage.canonical_rule IS NOT DISTINCT FROM EXCLUDED.canonical_rule
               RETURNING *""",
            (
                f"lin_{uuid.uuid4().hex[:16]}", rule.rule_id, extraction_id,
                document_id, run_id, rule.rule_version,
                self._json(rule.model_dump(mode="json")), release_id,
                datetime.now(timezone.utc),
            ),
        )
        if not rows:
            raise ValueError(f"编译运行 {run_id} 血缘快照冲突或已关联其他发布")

    def save_candidate_lineage(
        self,
        *,
        rule_id: str,
        rule: CanonicalRule | None,
        run_id: str,
        extraction_id: str,
        document_id: str,
    ) -> None:
        self._get_client().execute(
            """INSERT INTO policy_rule_lineage
               (lineage_id, rule_id, extraction_id, doc_id, compile_run_id,
                rule_version, canonical_rule, release_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s)
               ON CONFLICT (rule_id, compile_run_id) DO NOTHING""",
            (
                f"lin_{uuid.uuid4().hex[:16]}", rule_id, extraction_id, document_id,
                run_id, rule.rule_version if rule else None,
                self._json(rule.model_dump(mode="json")) if rule else None,
                datetime.now(timezone.utc),
            ),
        )

    def get_rule_trace(self, rule_id: str) -> RuleCompilationTraceResponse | None:
        rows = self._get_client().execute(
            """SELECT * FROM policy_rule_lineage WHERE rule_id=%s
               AND compile_run_id IS NOT NULL
               ORDER BY (canonical_rule IS NULL) ASC,
                        rule_version DESC NULLS LAST,
                        created_at DESC""",
            (rule_id,),
        )
        if not rows:
            return None
        current = rows[0]
        run = self.get_run(current["compile_run_id"])
        if run is None:
            return None
        steps = self._get_steps(run.run_id)
        history: list[RuleTraceHistorySummary] = []
        for row in rows:
            historical_run = self.get_run(row["compile_run_id"])
            if historical_run is None:
                continue
            raw_rule = self._load(row.get("canonical_rule"), None)
            historical_rule = CanonicalRule(**raw_rule) if raw_rule else None
            history.append(RuleTraceHistorySummary(
                run_id=historical_run.run_id,
                rule_version=historical_rule.rule_version if historical_rule else None,
                status=historical_run.status,
                compiler_version=(
                    historical_rule.compiler_version
                    if historical_rule else historical_run.compiler_version
                ),
                started_at=historical_run.started_at,
                finished_at=historical_run.finished_at,
            ))
        raw_current_rule = self._load(current.get("canonical_rule"), None)
        return RuleCompilationTraceResponse(
            rule_id=str(current["rule_id"]),
            rule=CanonicalRule(**raw_current_rule) if raw_current_rule else None,
            run=run,
            raw_input=run.raw_input,
            llm_output=run.llm_output,
            steps=steps,
            issues=[issue for item in steps for issue in item.issues],
            publication=(
                RulePublication(
                    release_id=current["release_id"],
                    published_at=current.get("created_at"),
                )
                if current.get("release_id") else None
            ),
            history=history,
        )

    def has_release_lineage(
        self, release_id: str, rule_runs: list[tuple[str, str]]
    ) -> bool:
        rows = self._get_client().execute(
            """SELECT rule_id, compile_run_id FROM policy_rule_lineage
               WHERE release_id=%s AND compile_run_id IS NOT NULL
               AND canonical_rule IS NOT NULL""",
            (release_id,),
        )
        traced = {
            (str(row["rule_id"]), str(row["compile_run_id"])) for row in rows
        }
        return set(rule_runs) == traced

    def _get_steps(self, run_id: str) -> list[CompileStep]:
        rows = self._get_client().execute(
            "SELECT * FROM policy_compile_steps WHERE run_id=%s ORDER BY sequence_no",
            (run_id,),
        )
        return [CompileStep(**{
            **row,
            "input_payload": self._load(row.get("input_payload"), {}),
            "output_payload": self._load(row.get("output_payload"), {}),
            "issues": self._load(row.get("issues"), []),
            "error": self._load(row.get("error"), None),
        }) for row in rows]

    @classmethod
    def _run_row(cls, row: dict[str, Any]) -> CompileRun:
        return CompileRun(**{
            **row,
            "raw_input": cls._load(row.get("raw_input"), {}),
            "llm_output": cls._load(row.get("llm_output"), {}),
            "metrics": cls._load(row.get("metrics"), {}),
            "error": cls._load(row.get("error"), None),
        })

    @staticmethod
    def _json(value: Any) -> str | None:
        return None if value is None else json.dumps(value, ensure_ascii=False, default=str)

    @staticmethod
    def _load(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            return json.loads(value)
        return value
