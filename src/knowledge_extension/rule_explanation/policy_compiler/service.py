"""政策事实编译及轨迹持久化协调。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeItem,
)
from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
    PolicyRuleCompiler,
)
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileRun,
    CompileStatus,
    CompileStep,
    PolicyFact,
    ValidationIssue,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    CompilationTraceStore,
)


class ExtractionReadPort(Protocol):
    def get_extraction(self, extraction_id: str) -> dict[str, Any] | None: ...


class CompiledCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    knowledge_id: str
    compile_run_id: str
    status: CompileStatus
    canonical_rules: list[CanonicalRule] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)


class PolicyCompilationService:
    def __init__(
        self,
        pipeline_store: ExtractionReadPort,
        compiler: PolicyRuleCompiler,
        trace_store: CompilationTraceStore,
    ) -> None:
        self._pipeline = pipeline_store
        self._compiler = compiler
        self._traces = trace_store

    def compile_units(self, units: list[ApprovedUnit]) -> dict[str, CompiledCandidate]:
        entries = [
            (unit, knowledge)
            for unit in units
            for knowledge in unit.knowledge
        ]
        runs: dict[str, CompileRun] = {}
        facts: dict[str, PolicyFact] = {}
        try:
            for unit, knowledge in entries:
                extraction = self._pipeline.get_extraction(knowledge.extraction_id)
                if extraction is None:
                    raise ValueError(f"提取记录不存在: {knowledge.extraction_id}")
                run = self._start_run(unit, knowledge, extraction)
                runs[knowledge.knowledge_id] = run
                self._append_snapshot_steps(run)
                facts[knowledge.knowledge_id] = self._to_fact(knowledge, extraction)

            result = self._compiler.compile(list(facts.values()), run_id="compile_batch")
            candidates: dict[str, CompiledCandidate] = {}
            for unit, knowledge in entries:
                run = runs[knowledge.knowledge_id]
                fact = facts[knowledge.knowledge_id]
                owned = self._owned_rules(knowledge, fact, result.rules)
                issues = [
                    issue for issue in result.issues
                    if issue.fact_id == fact.fact_id
                    or issue.rule_id in {rule.rule_id for rule in owned}
                ]
                if not owned and result.status in {"REVIEW", "FAIL"} and not issues:
                    issues = list(result.issues)
                status = self._status(issues)
                if not owned and status == "PASS":
                    status = "REVIEW"
                for compiler_step in result.steps:
                    self._traces.append_step(
                        run.run_id,
                        compiler_step.model_copy(update={
                            "step_id": f"{run.run_id}_{compiler_step.sequence_no + 2}",
                            "run_id": run.run_id,
                            "sequence_no": compiler_step.sequence_no + 2,
                        }),
                    )
                self._traces.finish_run(
                    run.run_id,
                    status=status,
                    metrics={"rules": len(owned), "issues": len(issues)},
                )
                associated_rule_ids: set[str] = set()
                for rule in owned:
                    self._traces.save_candidate_lineage(
                        rule_id=rule.rule_id,
                        rule=rule,
                        run_id=run.run_id,
                        extraction_id=knowledge.extraction_id,
                        document_id=unit.doc_id,
                    )
                    associated_rule_ids.add(rule.rule_id)
                if knowledge.knowledge_id not in associated_rule_ids:
                    self._traces.save_candidate_lineage(
                        rule_id=knowledge.knowledge_id,
                        rule=owned[0] if len(owned) == 1 else None,
                        run_id=run.run_id,
                        extraction_id=knowledge.extraction_id,
                        document_id=unit.doc_id,
                    )
                candidates[knowledge.knowledge_id] = CompiledCandidate(
                    knowledge_id=knowledge.knowledge_id,
                    compile_run_id=run.run_id,
                    status=status,
                    canonical_rules=owned,
                    issues=issues,
                )
            return candidates
        except Exception as exc:
            self._finish_failed_runs(runs, exc)
            raise

    def _start_run(
        self,
        unit: ApprovedUnit,
        knowledge: KnowledgeItem,
        extraction: dict[str, Any],
    ) -> CompileRun:
        extracted_fields = extraction.get("extracted_fields") or {}
        run = CompileRun(
            run_id=f"run_{uuid4().hex}",
            document_id=unit.doc_id,
            unit_id=unit.unit_id,
            extraction_id=knowledge.extraction_id,
            raw_input={
                "document_id": unit.doc_id,
                "unit_id": unit.unit_id,
                "source_text": extraction.get("source_text") or unit.source_text,
            },
            llm_output=extracted_fields,
            model_name=extraction.get("model_name") or extracted_fields.get("model_name"),
            prompt_version=(
                extraction.get("prompt_version") or extracted_fields.get("prompt_version")
            ),
            schema_version=extracted_fields.get("schema_version"),
            compiler_version=self._compiler.compiler_version,
        )
        self._traces.create_run(run)
        return run

    def _append_snapshot_steps(self, run: CompileRun) -> None:
        now = datetime.now(timezone.utc)
        self._traces.append_step(run.run_id, CompileStep(
            step_id=f"{run.run_id}_1",
            run_id=run.run_id,
            sequence_no=1,
            stage="INPUT_SNAPSHOT",
            status="PASS",
            input_payload=run.raw_input,
            output_payload=run.raw_input,
            finished_at=now,
        ))
        self._traces.append_step(run.run_id, CompileStep(
            step_id=f"{run.run_id}_2",
            run_id=run.run_id,
            sequence_no=2,
            stage="LLM_EXTRACTION",
            status="PASS",
            input_payload=run.raw_input,
            output_payload=run.llm_output,
            finished_at=now,
        ))

    def _to_fact(
        self, knowledge: KnowledgeItem, extraction: dict[str, Any]
    ) -> PolicyFact:
        raw_rule = self._find_raw_rule(knowledge, extraction)
        fields = {field.field_code: field.raw_value for field in knowledge.fields}
        expression = raw_rule.get("expression") or fields.pop("expression", None)
        subject = str(
            raw_rule.get("subject")
            or knowledge.topic_concept
            or raw_rule.get("rule_type")
            or knowledge.rule_type_enum
            or knowledge.knowledge_id
        ).lower()
        population = (
            raw_rule.get("population")
            or raw_rule.get("person_type")
            or raw_rule.get("psn_type")
            or fields.pop("population", None)
            or fields.pop("person_type", None)
            or fields.pop("psn_type", None)
        )
        result = raw_rule.get("result") or raw_rule.get("value")
        if not isinstance(result, dict):
            result = {}
            for name, value in fields.items():
                if name == "ratio" or name.endswith("_ratio"):
                    result["ratio"] = value
                elif name == "amount" or name.endswith("_amount"):
                    result["amount"] = value
            if not result and expression is None:
                result = {"value": knowledge.business_sentence}
        excluded = {
            "rule_id", "knowledge_id", "fact_id", "rule_type", "source_text",
            "confidence", "expression", "relations", "subject", "result", "value",
        }
        conditions = {
            name: value for name, value in fields.items()
            if name not in excluded
            and name not in {"ratio", "amount"}
            and not name.endswith(("_ratio", "_amount"))
        }
        evidence = [f"knowledge:{knowledge.knowledge_id}"]
        evidence.extend(item.evidence_id for item in knowledge.evidences)
        if len(evidence) == 1:
            evidence.extend(item.evidence for item in knowledge.citations if item.evidence)
        return PolicyFact(
            fact_id=knowledge.knowledge_id,
            subject=subject,
            population=str(population) if population is not None else None,
            conditions=conditions,
            value=result,
            expression=expression,
            evidence=list(dict.fromkeys(evidence)),
            document_id=extraction.get("doc_id"),
            unit_id=knowledge.unit_id,
            extraction_id=knowledge.extraction_id,
            confidence=Decimal(str(knowledge.confidence.overall)),
        )

    @staticmethod
    def _find_raw_rule(
        knowledge: KnowledgeItem, extraction: dict[str, Any]
    ) -> dict[str, Any]:
        rules = (extraction.get("extracted_fields") or {}).get("rules") or []
        for rule in rules:
            if str(rule.get("knowledge_id") or rule.get("rule_id") or "") == knowledge.knowledge_id:
                return dict(rule)
        expected = {field.field_code: field.raw_value for field in knowledge.fields}
        for rule in rules:
            if all(rule.get(name) == value for name, value in expected.items()):
                return dict(rule)
        return expected

    @staticmethod
    def _owned_rules(
        knowledge: KnowledgeItem,
        fact: PolicyFact,
        rules: list[CanonicalRule],
    ) -> list[CanonicalRule]:
        marker = f"knowledge:{knowledge.knowledge_id}"
        if fact.expression is None or fact.expression.operator == "ABSOLUTE":
            return [
                rule for rule in rules
                if rule.source_type == "DIRECT" and marker in rule.evidence
            ]
        return [
            rule for rule in rules
            if rule.source_type == "DERIVED" and marker in rule.evidence
        ]

    @staticmethod
    def _status(issues: list[ValidationIssue]) -> CompileStatus:
        severities = {issue.severity for issue in issues}
        if "FAIL" in severities:
            return "FAIL"
        if "REVIEW" in severities:
            return "REVIEW"
        if "WARN" in severities:
            return "WARN"
        return "PASS"

    def _finish_failed_runs(self, runs: dict[str, CompileRun], exc: Exception) -> None:
        # 编译器异常不能留下 RUNNING 孤儿；轨迹写入失败也不能遮蔽原始异常。
        error = {"type": type(exc).__name__, "message": str(exc)}
        for knowledge_id, run in runs.items():
            try:
                current = self._traces.get_run(run.run_id)
            except Exception:
                continue
            if current is None or current.status != "RUNNING":
                continue
            issue = ValidationIssue(
                issue_id=f"{run.run_id}_exception",
                severity="FAIL",
                code="COMPILATION_EXCEPTION",
                stage="VALIDATE",
                fact_id=knowledge_id,
                message=str(exc),
                recommended_action="修复编译异常后重新生成变更集",
            )
            now = datetime.now(timezone.utc)
            try:
                self._traces.append_step(run.run_id, CompileStep(
                    step_id=f"{run.run_id}_3",
                    run_id=run.run_id,
                    sequence_no=3,
                    stage="VALIDATE",
                    status="FAIL",
                    issues=[issue],
                    error=error,
                    started_at=now,
                    finished_at=now,
                ))
            except Exception:
                pass
            try:
                self._traces.finish_run(
                    run.run_id,
                    status="FAIL",
                    metrics={"rules": 0, "issues": 1},
                    error=error,
                )
            except Exception:
                pass
            try:
                self._traces.save_candidate_lineage(
                    rule_id=knowledge_id,
                    rule=None,
                    run_id=run.run_id,
                    extraction_id=run.extraction_id,
                    document_id=run.document_id,
                )
            except Exception:
                pass
