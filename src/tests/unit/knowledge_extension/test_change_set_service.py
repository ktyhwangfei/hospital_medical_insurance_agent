"""知识变更集聚合服务测试（V4.1 S2）。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from src.knowledge_extension.rule_explanation import change_set_models, change_set_service
from src.knowledge_extension.rule_explanation.change_set_models import ChangeSetItem
from src.knowledge_extension.rule_explanation.change_set_service import (
    ChangeSetService,
    change_set_id_for,
    change_set_id_for_task,
)
from src.knowledge_extension.rule_explanation.change_set_store import (
    InMemoryChangeSetStore,
    PostgresChangeSetStore,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_service import (
    KnowledgeWorkbenchService,
)
from src.knowledge_extension.rule_explanation.policy_compiler.compiler import (
    PolicyRuleCompiler,
)
from src.knowledge_extension.rule_explanation.policy_compiler.service import (
    PolicyCompilationService,
)
from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
    InMemoryCompilationTraceStore,
)
from src.tests.unit.knowledge_extension.test_knowledge_workbench import (
    FakePipelineStore,
    _extraction,
    _leaf_ids,
    _rules,
)


def test_build_change_set_for_document() -> None:
    first = _leaf_ids()[0]
    store = InMemoryChangeSetStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        store,
    )

    change_set = service.build_for_document("doc_1")

    # 按 doc 批次聚合：2 条规则全量 additions
    assert change_set.change_set_id == change_set_id_for("doc_1")
    assert change_set.status == "PENDING_REVIEW"
    assert change_set.summary["additions"] == 2
    assert len(change_set.items) == 2
    # 变更项内容：after 为完整规则单元，含证据与风险
    item: ChangeSetItem = change_set.items[0]
    assert item.change_type == "ADD"
    assert item.rule_id == item.item_id[len("ci_"):]
    assert item.after["topic_concept"] in ("PAYMENT_RATIO", "ELIGIBILITY")
    assert item.evidence_ids and item.evidence_ids[0].startswith("ev_")
    assert item.risk_level in ("LOW", "MEDIUM", "HIGH")
    # 质量报告聚合
    assert change_set.quality_report.source_fidelity is not None
    assert change_set.quality_report.structural_completeness is not None
    # 风险统计与 items 一致
    assert sum(change_set.risk_summary.values()) == 2
    # 落库可查
    assert service.get_change_set(change_set.change_set_id) is not None
    assert len(service.list_change_sets("doc_1")) == 1


def test_build_change_set_compiles_items_and_snapshots_extraction() -> None:
    first = _leaf_ids()[0]
    extraction = _extraction(first, _rules())
    pipeline = FakePipelineStore([extraction])
    pipeline.get_extraction = lambda extraction_id: (
        extraction if extraction_id == extraction["extraction_id"] else None
    )
    traces = InMemoryCompilationTraceStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(pipeline),
        InMemoryChangeSetStore(),
        compilation_service=PolicyCompilationService(
            pipeline, PolicyRuleCompiler(), traces
        ),
    )

    change_set = service.build_for_document("doc_1")

    # compiler 新拦截：缺少结构化结果（无数值/金额字段）的资格类规则 → REVIEW（RESULT_MISSING），
    # 而非静默 PASS——测试适配新语义，NEEDS_DECISION 属预期。
    assert change_set.status == "NEEDS_DECISION"
    assert all(item.compile_run_id for item in change_set.items)
    by_status: dict[str, int] = {}
    for item in change_set.items:
        by_status[item.compilation_status] = by_status.get(item.compilation_status, 0) + 1
    assert by_status.get("PASS", 0) >= 1, "有数值结果的规则应 PASS"
    assert by_status.get("REVIEW", 0) >= 1, "无结果的资格规则应 REVIEW"
    first_run = traces.get_run(change_set.items[0].compile_run_id)
    assert first_run.raw_input["source_text"] == extraction["source_text"]
    assert first_run.llm_output == extraction["extracted_fields"]
    for item in change_set.items:
        trace = traces.get_rule_trace(item.rule_id)
        assert trace is not None
        assert trace.rule_id == item.rule_id
        assert trace.rule == item.canonical_rule
        assert trace.run.run_id == item.compile_run_id
        assert trace.publication is None


def test_business_dimensions_reach_candidate_and_canonical_conditions() -> None:
    first = _leaf_ids()[0]
    rule = dict(
        _rules()[0],
        insu_type="城镇职工基本医疗保险",
        setl_type="按项目结算",
    )
    extraction = _extraction(first, [rule])
    pipeline = FakePipelineStore([extraction])
    pipeline.get_extraction = lambda _extraction_id: extraction
    service = ChangeSetService(
        KnowledgeWorkbenchService(pipeline),
        InMemoryChangeSetStore(),
        compilation_service=PolicyCompilationService(
            pipeline, PolicyRuleCompiler(), InMemoryCompilationTraceStore()
        ),
    )

    item = service.build_for_document("doc_1").items[0]

    fields = {field["field_code"]: field["raw_value"] for field in item.after["fields"]}
    assert fields["insu_type"] == "城镇职工基本医疗保险"
    assert fields["setl_type"] == "按项目结算"
    assert item.canonical_rule is not None
    assert item.canonical_rule.conditions["insu_type"] == "城镇职工基本医疗保险"
    assert item.canonical_rule.conditions["setl_type"] == "按项目结算"


def test_review_compilation_persists_run_and_blocks_candidate() -> None:
    first = _leaf_ids()[0]
    relation_rule = {
        "rule_id": "relative_only",
        "rule_type": "payment_ratio",
        "psn_type": "retiree",
        "expression": {
            "operator": "MULTIPLY",
            "reference": {"population": "employee"},
            "factor": "0.6",
        },
        "source_text": "退休人员按在职人员比例折算。",
        "confidence": 0.9,
    }
    extraction = _extraction(first, [relation_rule])
    pipeline = FakePipelineStore([extraction])
    pipeline.get_extraction = lambda extraction_id: extraction
    traces = InMemoryCompilationTraceStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(pipeline),
        InMemoryChangeSetStore(),
        compilation_service=PolicyCompilationService(
            pipeline, PolicyRuleCompiler(), traces
        ),
    )

    change_set = service.build_for_document("doc_1")

    assert change_set.status == "NEEDS_DECISION"
    assert change_set.items[0].compilation_status == "REVIEW"
    assert change_set.items[0].canonical_rule is None
    assert {blocker["code"] for blocker in change_set.blockers} == {"NOT_FOUND"}
    assert traces.get_run(change_set.items[0].compile_run_id).status == "REVIEW"
    trace = traces.get_rule_trace(change_set.items[0].rule_id)
    assert trace is not None
    assert trace.rule_id == change_set.items[0].rule_id
    assert trace.rule is None
    assert trace.run.status == "REVIEW"
    assert {issue.code for issue in trace.issues} == {"NOT_FOUND"}


def test_legacy_change_set_items_remain_uncompiled() -> None:
    first = _leaf_ids()[0]
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        InMemoryChangeSetStore(),
    )

    change_set = service.build_for_document("doc_1")

    assert all(item.compile_run_id is None for item in change_set.items)
    assert all(item.canonical_rule is None for item in change_set.items)


def test_trace_write_failure_finishes_started_run_before_raising() -> None:
    first = _leaf_ids()[0]
    extraction = _extraction(first, _rules()[:1])
    pipeline = FakePipelineStore([extraction])
    pipeline.get_extraction = lambda extraction_id: extraction

    class FailingTraceStore(InMemoryCompilationTraceStore):
        last_run_id = ""
        failed_once = False

        def create_run(self, run):
            self.last_run_id = run.run_id
            return super().create_run(run)

        def append_step(self, run_id, step):
            if not self.failed_once:
                self.failed_once = True
                raise RuntimeError("trace unavailable")
            return super().append_step(run_id, step)

    traces = FailingTraceStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(pipeline),
        InMemoryChangeSetStore(),
        compilation_service=PolicyCompilationService(
            pipeline, PolicyRuleCompiler(), traces
        ),
    )

    with pytest.raises(RuntimeError, match="trace unavailable"):
        service.build_for_document("doc_1")

    assert traces.get_run(traces.last_run_id).status == "FAIL"


def test_trace_failure_during_compiler_exception_does_not_mask_original() -> None:
    first = _leaf_ids()[0]
    extraction = _extraction(first, _rules()[:1])
    pipeline = FakePipelineStore([extraction])
    pipeline.get_extraction = lambda _extraction_id: extraction

    class RaisingCompiler:
        compiler_version = "test"

        def compile(self, _facts, *, run_id):
            raise RuntimeError("compiler exploded")

    class UnavailableTraceStore(InMemoryCompilationTraceStore):
        def save_candidate_lineage(self, **kwargs):
            raise RuntimeError("trace unavailable")

    with pytest.raises(RuntimeError, match="compiler exploded"):
        PolicyCompilationService(
            pipeline, RaisingCompiler(), UnavailableTraceStore()
        ).compile_units(
            KnowledgeWorkbenchService(pipeline).get_document("doc_1").units
        )


def test_build_change_set_is_idempotent_upsert() -> None:
    first = _leaf_ids()[0]
    store = InMemoryChangeSetStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        store,
    )

    service.build_for_document("doc_1")
    service.build_for_document("doc_1")

    assert len(store.list("doc_1")) == 1


def test_build_for_units_aggregates_only_selected_units_and_persists_source_context() -> None:
    first, second = _leaf_ids()
    first_extraction = _extraction(first, _rules())
    second_extraction = _extraction(second, _rules())
    second_extraction["extraction_id"] = "ext_2"
    workbench = KnowledgeWorkbenchService(
        FakePipelineStore([first_extraction, second_extraction])
    )
    document = workbench.get_document("doc_1")
    selected_first_unit = change_set_service.SelectedKnowledgeUnit(
        unit=document.units[0],
        source_revision=change_set_models.SourceUnitRevision(
            doc_id=document.doc_id,
            doc_title=document.doc_title,
            unit_id=document.units[0].unit_id,
            unit_revision_id="UR_doc1_first_v3",
            path=document.units[0].path,
        ),
    )
    store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, store)

    result = service.build_for_units(
        task_id="KB_20260805_001",
        task_name="门诊待遇知识构建",
        units=[selected_first_unit],
        semantic_contract_version="v1.0",
        supersedes_candidate_id="CS_previous",
    )

    assert {item.unit_id for item in result.items} == {selected_first_unit.unit.unit_id}
    assert result.build_task_id == "KB_20260805_001"
    assert result.semantic_contract_version == "v1.0"
    assert result.supersedes_candidate_id == "CS_previous"
    assert result.source_units == [selected_first_unit.source_revision]
    assert result.doc_id == "doc_1"
    assert result.doc_title == "门诊待遇知识构建"
    persisted = service.get_change_set(result.change_set_id)
    assert persisted is not None
    assert persisted.build_task_id == "KB_20260805_001"
    assert persisted.semantic_contract_version == "v1.0"
    assert persisted.supersedes_candidate_id == "CS_previous"
    assert persisted.source_units == [selected_first_unit.source_revision]


def test_fail_candidate_marks_persisted_candidate_failed_and_blocks_review() -> None:
    store = InMemoryChangeSetStore()
    service = ChangeSetService(object(), store)
    candidate = store.save(
        change_set_models.KnowledgeChangeSet(
            change_set_id="CS_failed_build",
            source_document_version_id="doc-1",
            doc_id="doc-1",
            doc_title="Failed candidate",
            build_task_id="KB_failed_build",
            status="PENDING_REVIEW",
        )
    )

    failed = service.fail_candidate(
        candidate.change_set_id,
        reason="final task save failed",
    )

    assert failed.status == "FAILED"
    assert failed.review_decision == {
        "action": "build_failed",
        "reason": "final task save failed",
    }
    assert store.get(candidate.change_set_id) == failed
    with pytest.raises(ValueError):
        service.approve(candidate.change_set_id, "reviewer")


def test_build_for_units_uses_task_id_to_avoid_overwriting_candidates() -> None:
    first = _leaf_ids()[0]
    workbench = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())]))
    unit = workbench.get_document("doc_1").units[0]
    selected = change_set_service.SelectedKnowledgeUnit(
        unit=unit,
        source_revision=change_set_models.SourceUnitRevision(
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            unit_id=unit.unit_id,
            unit_revision_id="UR_doc1_first_v3",
            path=unit.path,
        ),
    )
    store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, store)

    first_result = service.build_for_units(
        task_id="KB_20260805_001",
        task_name="首次构建",
        units=[selected],
        semantic_contract_version="v1.0",
    )
    second_result = service.build_for_units(
        task_id="KB_20260805_002",
        task_name="二次构建",
        units=[selected],
        semantic_contract_version="v1.0",
    )

    assert first_result.change_set_id == change_set_id_for_task("KB_20260805_001")
    assert second_result.change_set_id == change_set_id_for_task("KB_20260805_002")
    assert first_result.change_set_id != second_result.change_set_id
    assert {item.build_task_id for item in store.list()} == {
        "KB_20260805_001",
        "KB_20260805_002",
    }


def test_task_candidate_id_cannot_collide_with_legacy_document_candidate_id() -> None:
    first = _leaf_ids()[0]
    workbench = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())]))
    unit = workbench.get_document("doc_1").units[0]
    selected = change_set_service.SelectedKnowledgeUnit(
        unit=unit,
        source_revision=change_set_models.SourceUnitRevision(
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            unit_id=unit.unit_id,
            unit_revision_id="UR_doc1_first_v3",
            path=unit.path,
        ),
    )
    store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, store)

    document_candidate = service.build_for_document("doc_1")
    task_candidate = service.build_for_units(
        task_id="doc_1",
        task_name="与文档 ID 同文本的构建任务",
        units=[selected],
        semantic_contract_version="v1.0",
    )

    assert document_candidate.change_set_id == change_set_id_for("doc_1")
    assert task_candidate.change_set_id == change_set_id_for_task("doc_1")
    assert change_set_id_for_task("doc_1") != change_set_id_for("task:doc_1")
    assert task_candidate.change_set_id != document_candidate.change_set_id
    assert len(store.list()) == 2


def test_build_for_units_rejects_blank_task_id_without_saving() -> None:
    first = _leaf_ids()[0]
    workbench = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())]))
    unit = workbench.get_document("doc_1").units[0]
    selected = change_set_service.SelectedKnowledgeUnit(
        unit=unit,
        source_revision=change_set_models.SourceUnitRevision(
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            unit_id=unit.unit_id,
            unit_revision_id="UR_doc1_first_v3",
            path=unit.path,
        ),
    )
    store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, store)

    with pytest.raises(ValueError, match="构建任务 ID 不能为空"):
        service.build_for_units(
            task_id="   ",
            task_name="空 ID 任务",
            units=[selected],
            semantic_contract_version="v1.0",
        )

    assert store.list() == []


def test_build_for_units_rejects_source_document_mismatch_without_saving() -> None:
    first = _leaf_ids()[0]
    workbench = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())]))
    unit = workbench.get_document("doc_1").units[0]
    selected = change_set_service.SelectedKnowledgeUnit(
        unit=unit,
        source_revision=change_set_models.SourceUnitRevision(
            doc_id="doc_other",
            doc_title=unit.doc_title,
            unit_id=unit.unit_id,
            unit_revision_id="UR_doc1_first_v3",
            path=unit.path,
        ),
    )
    store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, store)

    with pytest.raises(ValueError, match="来源修订的文档 ID 与所选单元不一致"):
        service.build_for_units(
            task_id="KB_20260805_DOC_MISMATCH",
            task_name="来源文档矛盾任务",
            units=[selected],
            semantic_contract_version="v1.0",
        )

    assert store.list() == []


def test_build_for_units_rejects_source_unit_mismatch_without_saving() -> None:
    first = _leaf_ids()[0]
    workbench = KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())]))
    unit = workbench.get_document("doc_1").units[0]
    selected = change_set_service.SelectedKnowledgeUnit(
        unit=unit,
        source_revision=change_set_models.SourceUnitRevision(
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            unit_id="unit_other",
            unit_revision_id="UR_doc1_first_v3",
            path=unit.path,
        ),
    )
    store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, store)

    with pytest.raises(ValueError, match="来源修订的单元 ID 与所选单元不一致"):
        service.build_for_units(
            task_id="KB_20260805_UNIT_MISMATCH",
            task_name="来源单元矛盾任务",
            units=[selected],
            semantic_contract_version="v1.0",
        )

    assert store.list() == []


def test_build_for_units_supports_units_from_multiple_documents() -> None:
    first, second = _leaf_ids()
    first_extraction = _extraction(first, _rules())
    second_extraction = _extraction(second, [_rules()[0]])
    second_extraction["extraction_id"] = "ext_2"
    workbench = KnowledgeWorkbenchService(
        FakePipelineStore([first_extraction, second_extraction])
    )
    source_units = workbench.get_document("doc_1").units
    second_doc_unit = source_units[1].model_copy(update={
        "doc_id": "doc_2",
        "doc_title": "居民医保待遇政策",
    })
    selections = [
        change_set_service.SelectedKnowledgeUnit(
            unit=unit,
            source_revision=change_set_models.SourceUnitRevision(
                doc_id=unit.doc_id,
                doc_title=unit.doc_title,
                unit_id=unit.unit_id,
                unit_revision_id=f"UR_{unit.doc_id}_{index}",
                path=unit.path,
            ),
        )
        for index, unit in enumerate([source_units[0], second_doc_unit], start=1)
    ]
    service = ChangeSetService(workbench, InMemoryChangeSetStore())

    result = service.build_for_units(
        task_id="KB_20260805_MULTI",
        task_name="跨文档待遇知识构建",
        units=selections,
        semantic_contract_version="v1.0",
    )

    assert result.doc_id == "MULTI"
    assert result.source_document_version_id == "doc_1|doc_2"
    assert {item.doc_id for item in result.items} == {"doc_1", "doc_2"}
    assert {item.unit_id for item in result.items} == {
        source_units[0].unit_id,
        second_doc_unit.unit_id,
    }
    assert {source.doc_id for source in result.source_units} == {"doc_1", "doc_2"}


def test_build_for_units_rejects_empty_selection() -> None:
    workbench = KnowledgeWorkbenchService(FakePipelineStore([]))
    service = ChangeSetService(workbench, InMemoryChangeSetStore())

    with pytest.raises(ValueError, match="构建任务至少需要一个已审核单元"):
        service.build_for_units(
            task_id="KB_20260805_EMPTY",
            task_name="空任务",
            units=[],
            semantic_contract_version="v1.0",
        )


def test_build_for_units_rejects_selected_units_without_candidate_knowledge() -> None:
    first = _leaf_ids()[0]
    workbench = KnowledgeWorkbenchService(
        FakePipelineStore([_extraction(first, _rules()[:1])])
    )
    unit = workbench.get_document("doc_1").units[0].model_copy(
        update={"knowledge_count": 0, "knowledge": []}
    )
    selected = change_set_service.SelectedKnowledgeUnit(
        unit=unit,
        source_revision=change_set_models.SourceUnitRevision(
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            unit_id=unit.unit_id,
            unit_revision_id="UR_EMPTY_KNOWLEDGE",
            path=unit.path,
        ),
    )
    store = InMemoryChangeSetStore()
    service = ChangeSetService(workbench, store)

    with pytest.raises(ValueError, match="构建结果未生成候选知识"):
        service.build_for_units(
            task_id="KB_EMPTY_KNOWLEDGE",
            task_name="零候选任务",
            units=[selected],
            semantic_contract_version="v1.0",
        )

    assert store.list() == []


def test_legacy_change_set_json_without_candidate_context_still_validates() -> None:
    legacy = change_set_models.KnowledgeChangeSet.model_validate({
        "change_set_id": "CS_legacy",
        "source_document_version_id": "doc_legacy",
        "doc_id": "doc_legacy",
        "doc_title": "历史政策",
    })

    assert legacy.build_task_id is None
    assert legacy.source_units == []
    assert legacy.semantic_contract_version is None
    assert legacy.supersedes_candidate_id is None


def test_change_set_status_supports_returned_for_rebuild() -> None:
    change_set = change_set_models.KnowledgeChangeSet(
        change_set_id="CS_returned",
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        status="RETURNED",
    )

    assert change_set.status == "RETURNED"


def test_return_for_rebuild_records_terminal_review_decision() -> None:
    first = _leaf_ids()[0]
    store = InMemoryChangeSetStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        store,
    )
    change_set = service.build_for_document("doc_1")

    returned = service.return_for_rebuild(
        change_set.change_set_id,
        "bob",
        "证据需要补充",
    )

    assert returned.status == "RETURNED"
    assert returned.review_decision == {
        "action": "returned",
        "reviewed_by": "bob",
        "reason": "证据需要补充",
    }


def test_needs_decision_change_set_can_be_returned_or_rejected() -> None:
    """NEEDS_DECISION（编译有 blocker）也允许退回重新构建/拒绝。

    复现前端 bug：退回重新构建按钮 disabled，因为变更集状态是 NEEDS_DECISION
    而非 PENDING_REVIEW。后端 return_for_rebuild/reject 必须接受 NEEDS_DECISION。
    """
    first = _leaf_ids()[0]
    store = InMemoryChangeSetStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        store,
    )
    change_set = service.build_for_document("doc_1")
    # 手动置为 NEEDS_DECISION（模拟编译有 blocker 的场景）
    store.update_status(change_set.change_set_id, "NEEDS_DECISION")

    returned = service.return_for_rebuild(change_set.change_set_id, "bob", "退回重建")
    assert returned.status == "RETURNED"

    # 重置回 NEEDS_DECISION 测 reject
    store.update_status(change_set.change_set_id, "NEEDS_DECISION")
    rejected = service.reject(change_set.change_set_id, "bob", "拒绝")
    assert rejected.status == "REJECTED"


def test_approved_change_set_cannot_be_returned_or_rejected() -> None:
    first = _leaf_ids()[0]
    store = InMemoryChangeSetStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        store,
    )
    change_set = service.build_for_document("doc_1")
    approved = service.approve(change_set.change_set_id, "alice", "通过")

    with pytest.raises(ValueError, match="不可退回"):
        service.return_for_rebuild(approved.change_set_id, "bob", "补充证据")
    with pytest.raises(ValueError, match="不可驳回"):
        service.reject(approved.change_set_id, "bob", "证据不足")

    assert store.get(approved.change_set_id).status == "APPROVED"


def test_concurrent_approve_and_reject_only_one_transition_succeeds() -> None:
    first = _leaf_ids()[0]
    store = InMemoryChangeSetStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        store,
    )
    change_set = service.build_for_document("doc_1")
    barrier = Barrier(2)

    def transition(action: str) -> str:
        barrier.wait()
        try:
            if action == "approve":
                return service.approve(change_set.change_set_id, "alice").status
            return service.reject(change_set.change_set_id, "bob", "证据不足").status
        except ValueError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(transition, ("approve", "reject")))

    assert results.count("CONFLICT") == 1
    assert set(results) & {"APPROVED", "REJECTED"}
    assert store.get(change_set.change_set_id).status in {"APPROVED", "REJECTED"}


def test_postgres_transition_uses_status_compare_and_swap() -> None:
    change_set = change_set_models.KnowledgeChangeSet(
        change_set_id="CS_pg_cas",
        source_document_version_id="doc_1",
        doc_id="doc_1",
        doc_title="职工医保待遇政策",
        status="PENDING_REVIEW",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.update_sql = ""
            self.update_params = ()

        def execute(self, sql, params=None):
            if sql.lstrip().startswith("SELECT payload"):
                return [{"payload": change_set.model_dump(mode="json")}]
            self.update_sql = " ".join(sql.split())
            self.update_params = params
            return []

    fake = FakeClient()
    store = PostgresChangeSetStore()
    store._client = fake

    result = store.transition_status(
        change_set.change_set_id,
        allowed_statuses={"PENDING_REVIEW"},
        target_status="APPROVED",
        decision={"action": "approved"},
    )

    assert result is None
    assert "WHERE change_set_id=%s AND status=%s" in fake.update_sql
    assert fake.update_params[-1] == "PENDING_REVIEW"


def test_change_set_state_transitions() -> None:
    """V4.1 S8a：DRAFT→PENDING_REVIEW→APPROVED/REJECTED 流转。"""
    first = _leaf_ids()[0]
    store = InMemoryChangeSetStore()
    service = ChangeSetService(
        KnowledgeWorkbenchService(FakePipelineStore([_extraction(first, _rules())])),
        store,
    )

    change_set = service.build_for_document("doc_1")
    # build 产物即为 PENDING_REVIEW（可直接进入审核）
    assert change_set.status == "PENDING_REVIEW"
    approved = service.approve(change_set.change_set_id, "alice", "通过")
    assert approved.status == "APPROVED"
    assert approved.review_decision["action"] == "approved"
    assert approved.review_decision["reviewed_by"] == "alice"
    # 同目标重复请求幂等，审核结果不被覆盖。
    assert service.approve(change_set.change_set_id, "bob").status == "APPROVED"
    # reprocess 重建回 PENDING_REVIEW
    rebuilt = service.reprocess(change_set.change_set_id)
    assert rebuilt.status == "PENDING_REVIEW"
    # reject 路径：新建后驳回
    cs2 = service.build_for_document("doc_1")
    cs2 = service.reject(cs2.change_set_id, "bob", "需补充证据")
    assert cs2.status == "REJECTED"


def test_decision_tasks_generated_from_change_set() -> None:
    """V4.1 S8c：从变更集生成决策任务（证据/值域/置信），可 resolve。"""
    from src.knowledge_extension.rule_explanation.change_set_models import KnowledgeChangeSet
    from src.knowledge_extension.rule_explanation.decision_task_service import DecisionTaskService
    from src.knowledge_extension.rule_explanation.decision_task_store import InMemoryDecisionTaskStore

    # 手工构造含问题的变更集：一条无证据、一条值域未映射、一条低置信
    def item(rule_id: str, *, evidence: bool, confidence: float, binding: dict | None = None):
        after = {
            "knowledge_id": rule_id,
            "confidence": {"overall": confidence},
            "evidences": [{"evidence_id": "ev_1"}] if evidence else [],
            "semantic_bindings": [binding] if binding else [],
        }
        return ChangeSetItem(item_id=f"ci_{rule_id}", change_type="ADD", rule_id=rule_id,
                             unit_id="u", doc_id="doc_1", after=after, risk_level="MEDIUM")

    change_set = KnowledgeChangeSet(
        change_set_id="CS_test", source_document_version_id="doc_1",
        doc_id="doc_1", doc_title="测试政策",
        items=[
            item("r_no_evidence", evidence=False, confidence=0.9),
            item("r_low_conf", evidence=True, confidence=0.6),
            item("r_unmapped", evidence=True, confidence=0.9,
                 binding={"policy_field": "psn_type", "status": "UNMAPPED"}),
        ],
    )
    task_store = InMemoryDecisionTaskStore()
    task_service = DecisionTaskService(task_store)

    tasks = task_service.generate_for_change_set(change_set)
    assert tasks, "应有决策任务生成"
    task_types = {task.task_type for task in tasks}
    assert "INSUFFICIENT_EVIDENCE" in task_types
    assert "REVIEW_CONFIRM" in task_types
    assert "NEW_STANDARD_VALUE" in task_types
    # 任务类型合法且阻塞范围为变更集
    assert all(task.blocking_scope == change_set.change_set_id for task in tasks)
    # 幂等：重复生成不产生重复 PENDING
    task_service.generate_for_change_set(change_set)
    pending = task_service.list_tasks(status="PENDING", scope=change_set.change_set_id)
    assert len(pending) == len(tasks)

    # resolve 一条
    resolved = task_service.resolve(tasks[0].task_id, {"action": "确认", "by": "alice"})
    assert resolved.status == "RESOLVED"
    assert resolved.decision["action"] == "确认"
    # 已处理不可重复处理
    try:
        task_service.resolve(tasks[0].task_id, {"action": "x"})
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_build_for_document_triggers_aggregate_conflict_partition_discovery() -> None:
    """变更集编译完成后必须触发聚合层 S5（跨单元塌缩此时才可见，S5 设计 §十二）。"""
    first = _leaf_ids()[0]
    extraction = _extraction(first, _rules())
    pipeline = FakePipelineStore([extraction])
    pipeline.get_extraction = lambda extraction_id: (
        extraction if extraction_id == extraction["extraction_id"] else None
    )
    service = ChangeSetService(
        KnowledgeWorkbenchService(pipeline),
        InMemoryChangeSetStore(),
        compilation_service=PolicyCompilationService(
            pipeline, PolicyRuleCompiler(), InMemoryCompilationTraceStore()
        ),
    )
    triggered: list[str] = []
    service._orchestrator = _RecordingOrchestrator(triggered)

    change_set = service.build_for_document("doc_1")

    assert change_set.change_set_id == change_set_id_for("doc_1")
    assert triggered == ["doc_1"]


class _RecordingOrchestrator:
    def __init__(self, triggered: list[str]) -> None:
        self._triggered = triggered

    def run_conflict_partition_discovery(self, doc_id: str) -> dict[str, object]:
        self._triggered.append(doc_id)
        return {"success": True, "doc_id": doc_id, "extractions": 1}


def test_aggregate_discovery_failure_does_not_block_change_set_build() -> None:
    """S5 聚合诊断失败只记日志，不阻断变更集产出（降级原则）。"""
    first = _leaf_ids()[0]
    pipeline = FakePipelineStore([_extraction(first, _rules())])
    service = ChangeSetService(
        KnowledgeWorkbenchService(pipeline),
        InMemoryChangeSetStore(),
    )

    class _BrokenOrchestrator:
        def run_conflict_partition_discovery(self, doc_id: str) -> dict[str, object]:
            raise RuntimeError("discovery unavailable")

    service._orchestrator = _BrokenOrchestrator()

    change_set = service.build_for_document("doc_1")

    assert change_set.change_set_id == change_set_id_for("doc_1")


def test_build_for_units_triggers_aggregate_conflict_partition_discovery() -> None:
    """任务型变更集（CS_TASK_*）编译完成后也必须触发聚合层 S5（S5 设计 §十二）。"""
    first = _leaf_ids()[0]
    pipeline = FakePipelineStore([_extraction(first, _rules())])
    workbench = KnowledgeWorkbenchService(pipeline)
    unit = workbench.get_document("doc_1").units[0]
    selected = change_set_service.SelectedKnowledgeUnit(
        unit=unit,
        source_revision=change_set_models.SourceUnitRevision(
            doc_id=unit.doc_id,
            doc_title=unit.doc_title,
            unit_id=unit.unit_id,
            unit_revision_id="UR_doc1_first_v3",
            path=unit.path,
        ),
    )
    service = ChangeSetService(workbench, InMemoryChangeSetStore())
    triggered: list[str] = []
    service._orchestrator = _RecordingOrchestrator(triggered)

    result = service.build_for_units(
        task_id="KB_20260815_S5",
        task_name="基金归属知识构建",
        units=[selected],
        semantic_contract_version="v1.0",
    )

    assert result.change_set_id == change_set_id_for_task("KB_20260815_S5")
    assert triggered == ["doc_1"]


def test_build_for_units_triggers_discovery_for_each_source_document() -> None:
    """跨文档任务按来源文档逐篇触发 S5，不再因 doc_id=MULTI 整组跳过。"""
    first, second = _leaf_ids()
    first_extraction = _extraction(first, _rules())
    second_extraction = _extraction(second, [_rules()[0]])
    second_extraction["extraction_id"] = "ext_2"
    workbench = KnowledgeWorkbenchService(
        FakePipelineStore([first_extraction, second_extraction])
    )
    source_units = workbench.get_document("doc_1").units
    second_doc_unit = source_units[1].model_copy(update={
        "doc_id": "doc_2",
        "doc_title": "居民医保待遇政策",
    })
    selections = [
        change_set_service.SelectedKnowledgeUnit(
            unit=unit,
            source_revision=change_set_models.SourceUnitRevision(
                doc_id=unit.doc_id,
                doc_title=unit.doc_title,
                unit_id=unit.unit_id,
                unit_revision_id=f"UR_{unit.doc_id}_{index}",
                path=unit.path,
            ),
        )
        for index, unit in enumerate([source_units[0], second_doc_unit], start=1)
    ]
    service = ChangeSetService(workbench, InMemoryChangeSetStore())
    triggered: list[str] = []
    service._orchestrator = _RecordingOrchestrator(triggered)

    result = service.build_for_units(
        task_id="KB_20260815_MULTI",
        task_name="跨文档待遇知识构建",
        units=selections,
        semantic_contract_version="v1.0",
    )

    assert result.doc_id == "MULTI"
    assert triggered == ["doc_1", "doc_2"]
