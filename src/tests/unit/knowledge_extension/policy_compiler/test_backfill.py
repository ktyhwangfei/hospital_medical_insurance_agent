import json
from datetime import datetime, timezone

import pytest

from src.knowledge_extension.rule_explanation.change_set_models import (
    ChangeSetItem,
    KnowledgeChangeSet,
)
from src.knowledge_extension.rule_explanation.change_set_store import (
    InMemoryChangeSetStore,
)
from src.knowledge_extension.rule_explanation.policy_compiler import backfill
from src.knowledge_extension.rule_explanation.policy_compiler.models import (
    CanonicalRule,
    CompileRun,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
)


def test_change_set_candidate_linking_is_exact_and_idempotent() -> None:
    traces = InMemoryCompilationTraceStore()
    for run_id, status, started_at in (
        ("run_pass", "PASS", datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)),
        ("run_review", "REVIEW", datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)),
    ):
        traces.create_run(CompileRun(
            run_id=run_id,
            document_id="doc_1",
            unit_id="unit_1",
            extraction_id=f"ext_{run_id}",
            raw_input={},
            llm_output={},
            started_at=started_at,
        ))
        traces.finish_run(run_id, status=status, metrics={})
    canonical = CanonicalRule(
        rule_id="rule_canonical",
        subject="payment_ratio",
        result={"ratio": "0.8"},
        evidence=["evidence_1"],
    )
    change_sets = InMemoryChangeSetStore()
    change_sets.save(KnowledgeChangeSet(
        change_set_id="CS_legacy",
        source_document_version_id="doc_v1",
        doc_id="doc_1",
        doc_title="政策",
        items=[
            ChangeSetItem(
                item_id="item_pass",
                change_type="ADD",
                rule_id="knowledge_alias",
                unit_id="unit_1",
                doc_id="doc_1",
                compile_run_id="run_pass",
                compilation_status="PASS",
                canonical_rule=canonical,
            ),
            ChangeSetItem(
                item_id="item_review",
                change_type="ADD",
                rule_id="rule_shared",
                unit_id="unit_1",
                doc_id="doc_1",
                compile_run_id="run_review",
                compilation_status="REVIEW",
                canonical_rule=None,
            ),
        ],
    ))
    link_candidates = getattr(backfill, "link_change_set_candidates", None)
    assert link_candidates is not None

    first = link_candidates(change_sets, traces)
    second = link_candidates(change_sets, traces)

    assert first.linked == 2
    assert first.link_skipped == 0
    assert second.linked == 0
    assert second.link_skipped == 2
    passed = traces.get_rule_trace("rule_canonical", run_id="run_pass")
    review = traces.get_rule_trace("rule_shared", run_id="run_review")
    assert passed is not None
    assert passed.rule == canonical
    assert passed.publication is None
    assert traces.get_rule_trace("knowledge_alias", run_id="run_pass") is None
    assert review is not None
    assert review.rule is None
    assert review.publication is None


def test_change_set_candidate_linking_reports_missing_runs() -> None:
    traces = InMemoryCompilationTraceStore()
    change_sets = InMemoryChangeSetStore()
    canonical = CanonicalRule(
        rule_id="rule_canonical",
        subject="payment_ratio",
        result={"ratio": "0.8"},
        evidence=["evidence_1"],
    )
    change_sets.save(KnowledgeChangeSet(
        change_set_id="CS_missing",
        source_document_version_id="doc_v1",
        doc_id="doc_1",
        doc_title="政策",
        items=[ChangeSetItem(
            item_id="item_missing",
            change_type="ADD",
            rule_id="knowledge_alias",
            unit_id="unit_1",
            doc_id="doc_1",
            compile_run_id="run_missing",
            compilation_status="PASS",
            canonical_rule=canonical,
        )],
    ))

    report = backfill.link_change_set_candidates(change_sets, traces)

    assert report.linked == 0
    assert report.link_skipped == 0
    assert [item.model_dump() for item in report.missing] == [{
        "change_set_id": "CS_missing",
        "item_id": "item_missing",
        "target_rule_id": "rule_canonical",
        "compile_run_id": "run_missing",
    }]
    assert traces.get_run("run_missing") is None


def test_main_prints_report_before_failing_for_missing_runs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = backfill.MissingCandidateRun(
        change_set_id="CS_missing",
        item_id="item_missing",
        target_rule_id="rule_canonical",
        compile_run_id="run_missing",
    )
    monkeypatch.setattr(
        backfill,
        "backfill_rules",
        lambda *_args: backfill.BackfillReport(compiled=1),
    )
    monkeypatch.setattr(
        backfill,
        "link_change_set_candidates",
        lambda *_args: backfill.CandidateLinkReport(missing=[missing]),
    )

    with pytest.raises(RuntimeError, match="1 个变更项的编译运行不存在"):
        backfill.main()

    report = json.loads(capsys.readouterr().out)
    assert report["compiled"] == 1
    assert report["linked"] == 0
    assert report["link_skipped"] == 0
    assert report["missing"] == [missing.model_dump()]
