"""为历史工作台规则补齐可审计的编译运行。"""
from __future__ import annotations

import json
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from src.knowledge_extension.rule_explanation.change_set_store import ChangeSetStore
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeItem,
)
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CompileRun,
    CompileStep,
    ValidationIssue,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    CompilationTraceStore,
)


class WorkbenchPort(Protocol):
    def list_documents(self) -> Any: ...
    def get_document(self, doc_id: str) -> Any: ...


class CompilationPort(Protocol):
    def compile_units(self, units: list[ApprovedUnit]) -> Any: ...


class ExtractionPort(Protocol):
    def get_extraction(self, extraction_id: str) -> dict[str, Any] | None: ...


class MissingCandidateRun(BaseModel):
    change_set_id: str
    item_id: str
    target_rule_id: str
    compile_run_id: str


class BackfillReport(BaseModel):
    compiled: int = 0
    legacy_imported: int = 0
    skipped: int = 0
    linked: int = 0
    link_skipped: int = 0
    missing: list[MissingCandidateRun] = Field(default_factory=list)


class CandidateLinkReport(BaseModel):
    linked: int = 0
    link_skipped: int = 0
    missing: list[MissingCandidateRun] = Field(default_factory=list)


def link_change_set_candidates(
    change_sets: ChangeSetStore,
    traces: CompilationTraceStore,
) -> CandidateLinkReport:
    """仅为持久化变更项补齐其既有编译运行关联。"""
    linked = link_skipped = 0
    missing: list[MissingCandidateRun] = []
    for change_set in change_sets.list():
        for item in change_set.items:
            run_id = item.compile_run_id
            target_rule_id = (
                item.canonical_rule.rule_id if item.canonical_rule else item.rule_id
            )
            if not run_id:
                link_skipped += 1
                continue
            run = traces.get_run(run_id)
            if run is None:
                missing.append(MissingCandidateRun(
                    change_set_id=change_set.change_set_id,
                    item_id=item.item_id,
                    target_rule_id=target_rule_id,
                    compile_run_id=run_id,
                ))
                continue
            if traces.get_rule_trace(target_rule_id, run_id=run_id) is not None:
                link_skipped += 1
                continue
            traces.save_candidate_lineage(
                rule_id=target_rule_id,
                rule=item.canonical_rule,
                run_id=run_id,
                extraction_id=run.extraction_id,
                document_id=run.document_id,
            )
            linked += 1
    return CandidateLinkReport(
        linked=linked,
        link_skipped=link_skipped,
        missing=missing,
    )


def backfill_rules(
    workbench: WorkbenchPort,
    compilation: CompilationPort,
    extractions: ExtractionPort,
    traces: CompilationTraceStore,
) -> BackfillReport:
    compiled = legacy_imported = skipped = 0
    for summary in workbench.list_documents().items:
        document = workbench.get_document(summary.doc_id)
        for unit in document.units:
            if unit.status not in {"reviewed", "published"}:
                continue
            for knowledge in unit.knowledge:
                if traces.get_rule_trace(knowledge.knowledge_id) is not None:
                    skipped += 1
                    continue
                single = unit.model_copy(update={
                    "knowledge": [knowledge],
                    "knowledge_count": 1,
                })
                if extractions.get_extraction(knowledge.extraction_id) is not None:
                    compilation.compile_units([single])
                    compiled += 1
                else:
                    _import_legacy(single, knowledge, traces)
                    legacy_imported += 1
    return BackfillReport(
        compiled=compiled,
        legacy_imported=legacy_imported,
        skipped=skipped,
    )


def _import_legacy(
    unit: ApprovedUnit,
    knowledge: KnowledgeItem,
    traces: CompilationTraceStore,
) -> None:
    run_id = f"run_{uuid4().hex}"
    issue = ValidationIssue(
        issue_id=f"issue_{uuid4().hex}",
        severity="REVIEW",
        code="LEGACY_HISTORY_MISSING",
        stage="LEGACY_IMPORT",
        rule_id=knowledge.knowledge_id,
        message="历史规则缺少可重建的提取记录",
        recommended_action="发布前人工核验规则快照与政策原文",
    )
    snapshot = knowledge.model_dump(mode="json")
    run = CompileRun(
        run_id=run_id,
        document_id=unit.doc_id,
        unit_id=unit.unit_id,
        extraction_id=knowledge.extraction_id,
        raw_input={"source_text": unit.source_text, "path": unit.path},
        llm_output={"legacy_rule": snapshot},
    )
    traces.create_run(run)
    traces.append_step(run_id, CompileStep(
        step_id=f"{run_id}_1",
        run_id=run_id,
        sequence_no=1,
        stage="LEGACY_IMPORT",
        status="REVIEW",
        input_payload={"legacy_rule": snapshot},
        output_payload={"history_complete": False},
        issues=[issue],
    ))
    traces.finish_run(run_id, status="REVIEW", metrics={"issues": 1})
    traces.save_candidate_lineage(
        rule_id=knowledge.knowledge_id,
        rule=None,
        run_id=run_id,
        extraction_id=knowledge.extraction_id,
        document_id=unit.doc_id,
    )


def main() -> None:
    from src.knowledge_extension.rule_explanation.change_set_store import (
        PostgresChangeSetStore,
    )
    from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
        KnowledgeWorkbenchService,
    )
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore
    from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
        PolicyRuleCompiler,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.service import (
        PolicyCompilationService,
    )
    from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
        PostgresCompilationTraceStore,
    )

    pipeline = PipelineStore()
    traces = PostgresCompilationTraceStore()
    report = backfill_rules(
        KnowledgeWorkbenchService(pipeline),
        PolicyCompilationService(pipeline, PolicyRuleCompiler(), traces),
        pipeline,
        traces,
    )
    link_report = link_change_set_candidates(PostgresChangeSetStore(), traces)
    report = report.model_copy(update={
        "linked": link_report.linked,
        "link_skipped": link_report.link_skipped,
        "missing": link_report.missing,
    })
    print(json.dumps(report.model_dump(), ensure_ascii=False))
    if report.missing:
        raise RuntimeError(f"{len(report.missing)} 个变更项的编译运行不存在")


if __name__ == "__main__":
    main()
