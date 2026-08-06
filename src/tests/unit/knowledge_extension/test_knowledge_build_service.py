from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation import knowledge_build_models as models
from src.knowledge_extension.rule_explanation.change_set_models import (
    ChangeSetItem,
    KnowledgeChangeSet,
)
from src.knowledge_extension.rule_explanation.change_set_service import ChangeSetService
from src.knowledge_extension.rule_explanation.change_set_store import (
    InMemoryChangeSetStore,
)
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
    KnowledgeBuildTaskVersionConflict,
    UnitRevisionClaimed,
)
from src.knowledge_extension.rule_explanation.knowledge_workbench_models import (
    ApprovedUnit,
    KnowledgeWorkbenchDocument,
    WorkbenchDocumentList,
    WorkbenchDocumentSummary,
)


def _build_service_module() -> Any:
    return importlib.import_module(
        "src.knowledge_extension.rule_explanation.knowledge_build_service"
    )


def _unit(
    *,
    doc_id: str,
    doc_title: str,
    unit_id: str,
    source_text: str,
    order_no: int = 1,
    path: list[str] | None = None,
    status: str = "reviewed",
) -> ApprovedUnit:
    return ApprovedUnit(
        unit_id=unit_id,
        doc_id=doc_id,
        doc_title=doc_title,
        path=path or [],
        source_text=source_text,
        order_no=order_no,
        status=status,
        knowledge_count=0,
        knowledge=[],
    )


def _document(
    doc_id: str,
    doc_title: str,
    units: list[ApprovedUnit],
    *,
    contract_version: str | None = "contract-v1",
) -> KnowledgeWorkbenchDocument:
    return KnowledgeWorkbenchDocument(
        doc_id=doc_id,
        doc_title=doc_title,
        contract_version=contract_version,
        units=units,
    )


class _Workbench:
    def __init__(self, documents: Iterable[KnowledgeWorkbenchDocument]) -> None:
        self.documents = {document.doc_id: document for document in documents}
        self.get_document_calls = 0

    def list_documents(self) -> WorkbenchDocumentList:
        items = [
            WorkbenchDocumentSummary(
                doc_id=document.doc_id,
                doc_title=document.doc_title,
                approved_unit_count=len(document.units),
                knowledge_count=sum(unit.knowledge_count for unit in document.units),
            )
            for document in self.documents.values()
        ]
        return WorkbenchDocumentList(items=items, total=len(items))

    def list_document_ids(self) -> list[str]:
        return list(self.documents.keys())

    def get_document(
        self, doc_id: str, *, include_knowledge: bool = True
    ) -> KnowledgeWorkbenchDocument:
        self.get_document_calls += 1
        return self.documents[doc_id].model_copy(deep=True)


class _ChangeSetOnlyBuilder:
    """Task-scoped fake deliberately exposes no document-wide build method."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []
        self.results: list[KnowledgeChangeSet] = []

    def build_for_units(
        self,
        *,
        task_id: str,
        task_name: str,
        units: list[Any],
        semantic_contract_version: str,
        supersedes_candidate_id: str | None = None,
    ) -> KnowledgeChangeSet:
        self.calls.append(
            {
                "task_id": task_id,
                "task_name": task_name,
                "units": list(units),
                "semantic_contract_version": semantic_contract_version,
                "supersedes_candidate_id": supersedes_candidate_id,
            }
        )
        if self.failure is not None:
            raise self.failure
        items = [
            ChangeSetItem(
                item_id=f"ci_{selected.unit.doc_id}_{selected.unit.unit_id}",
                change_type="ADD",
                rule_id=f"rule_{selected.unit.doc_id}_{selected.unit.unit_id}",
                doc_id=selected.unit.doc_id,
                unit_id=selected.unit.unit_id,
            )
            for selected in units
        ]
        result = KnowledgeChangeSet(
            change_set_id=f"CS_{task_id}",
            source_document_version_id="|".join(
                sorted({selected.unit.doc_id for selected in units})
            ),
            doc_id=(
                units[0].unit.doc_id
                if len({selected.unit.doc_id for selected in units}) == 1
                else "MULTI"
            ),
            doc_title=task_name,
            build_task_id=task_id,
            source_units=[selected.source_revision for selected in units],
            semantic_contract_version=semantic_contract_version,
            supersedes_candidate_id=supersedes_candidate_id,
            summary={
                "additions": len(items),
                "modifications": 0,
                "replacements": 0,
                "expirations": 0,
                "unchanged": 0,
            },
            items=items,
        )
        self.results.append(result)
        return result


class _FailingCandidateInvalidation:
    def __init__(
        self,
        delegate: ChangeSetService,
        failure: Exception,
    ) -> None:
        self.delegate = delegate
        self.failure = failure

    def build_for_units(self, **kwargs: Any) -> KnowledgeChangeSet:
        return self.delegate.build_for_units(**kwargs)

    def fail_candidate(self, change_set_id: str, *, reason: str) -> None:
        raise self.failure


class _CommitThenRaiseChangeSetStore(InMemoryChangeSetStore):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure

    def save(self, change_set: KnowledgeChangeSet) -> KnowledgeChangeSet:
        super().save(change_set)
        raise self.failure


class _RecordingStore:
    def __init__(
        self,
        *,
        running_save_failure: Exception | None = None,
        final_save_failure: Exception | None = None,
    ) -> None:
        self.inner = InMemoryKnowledgeBuildStore()
        self.running_save_failure = running_save_failure
        self.final_save_failure = final_save_failure
        self.transitions: list[str] = []
        self.snapshots: list[models.KnowledgeBuildTask] = []
        self.get_calls = 0
        self.fail_and_release_calls = 0

    def create_with_claims(
        self, task: models.KnowledgeBuildTask
    ) -> models.KnowledgeBuildTask:
        self.transitions.append(task.status)
        self.snapshots.append(task.model_copy(deep=True))
        return self.inner.create_with_claims(task)

    def save(self, task: models.KnowledgeBuildTask) -> models.KnowledgeBuildTask:
        self.transitions.append(task.status)
        self.snapshots.append(task.model_copy(deep=True))
        if task.status == "RUNNING" and self.running_save_failure is not None:
            failure = self.running_save_failure
            self.running_save_failure = None
            raise failure
        if task.status == "WAITING_REVIEW" and self.final_save_failure is not None:
            failure = self.final_save_failure
            self.final_save_failure = None
            raise failure
        return self.inner.save(task)

    def get(self, task_id: str) -> models.KnowledgeBuildTask | None:
        self.get_calls += 1
        return self.inner.get(task_id)

    def list(self) -> list[models.KnowledgeBuildTask]:
        return self.inner.list()

    def get_claim(self, doc_id: str, unit_id: str) -> Any:
        return self.inner.get_claim(doc_id, unit_id)

    def list_claims(self) -> Any:
        return self.inner.list_claims()

    def get_many(self, task_ids: list[str]) -> Any:
        return self.inner.get_many(task_ids)

    def release_claims(self, task_id: str) -> None:
        self.inner.release_claims(task_id)

    def fail_and_release(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        result_change_set_id: str | None = None,
    ) -> models.KnowledgeBuildTask:
        self.fail_and_release_calls += 1
        result = self.inner.fail_and_release(
            task_id,
            error_code=error_code,
            error_message=error_message,
            result_change_set_id=result_change_set_id,
        )
        self.transitions.append(result.status)
        return result


class _ClaimRaceStore(_RecordingStore):
    def __init__(self, failure: UnitRevisionClaimed) -> None:
        super().__init__()
        self.failure = failure

    def create_with_claims(
        self, task: models.KnowledgeBuildTask
    ) -> models.KnowledgeBuildTask:
        self.transitions.append(task.status)
        self.snapshots.append(task.model_copy(deep=True))
        raise self.failure


class _ConcurrentRunningSaveStore(_RecordingStore):
    def __init__(self, failure: KnowledgeBuildTaskVersionConflict) -> None:
        super().__init__()
        self.failure = failure

    def save(self, task: models.KnowledgeBuildTask) -> models.KnowledgeBuildTask:
        if task.status == "RUNNING":
            self.transitions.append(task.status)
            self.snapshots.append(task.model_copy(deep=True))
            self.inner.save(task)
            raise self.failure
        return super().save(task)


class _CommitThenRaiseFinalSaveStore(_RecordingStore):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure

    def save(self, task: models.KnowledgeBuildTask) -> models.KnowledgeBuildTask:
        if task.status == "WAITING_REVIEW":
            self.transitions.append(task.status)
            self.snapshots.append(task.model_copy(deep=True))
            self.inner.save(task)
            raise self.failure
        return super().save(task)


class _FailingCompensationStore(_RecordingStore):
    def __init__(self, failure: Exception) -> None:
        super().__init__()
        self.failure = failure

    def fail_and_release(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        result_change_set_id: str | None = None,
    ) -> models.KnowledgeBuildTask:
        self.fail_and_release_calls += 1
        raise self.failure


def _create_service(
    documents: Iterable[KnowledgeWorkbenchDocument],
    *,
    store: Any | None = None,
    builder: Any | None = None,
    clock: Any | None = None,
    task_id_factory: Any | None = None,
) -> tuple[Any, _Workbench, Any, Any]:
    module = _build_service_module()
    workbench = _Workbench(documents)
    build_store = store if store is not None else _RecordingStore()
    change_set_builder = builder or _ChangeSetOnlyBuilder()
    kwargs: dict[str, Any] = {}
    if clock is not None:
        kwargs["clock"] = clock
    if task_id_factory is not None:
        kwargs["task_id_factory"] = task_id_factory
    service = module.KnowledgeBuildService(
        workbench_service=workbench,
        change_set_service=change_set_builder,
        store=build_store,
        **kwargs,
    )
    return service, workbench, build_store, change_set_builder


def _service(
    documents: Iterable[KnowledgeWorkbenchDocument],
    *,
    store: InMemoryKnowledgeBuildStore | None = None,
) -> tuple[Any, _Workbench, InMemoryKnowledgeBuildStore]:
    module = _build_service_module()
    workbench = _Workbench(documents)
    build_store = store or InMemoryKnowledgeBuildStore()
    service = module.KnowledgeBuildService(
        workbench_service=workbench,
        change_set_service=object(),
        store=build_store,
    )
    return service, workbench, build_store


def _selection(doc_id: str, unit_id: str, source_text: str) -> Any:
    module = _build_service_module()
    return models.KnowledgeBuildUnitRevision(
        doc_id=doc_id,
        unit_id=unit_id,
        unit_revision_id=module.unit_revision_id_for(
            doc_id=doc_id,
            unit_id=unit_id,
            source_text=source_text,
        ),
    )


def _request(
    selections: list[Any],
    *,
    build_mode: str = "INITIAL",
    rebuild_reason: str | None = None,
) -> Any:
    payload: dict[str, Any] = {
        "name": "测试构建任务",
        "created_by": "tester",
        "build_mode": build_mode,
        "unit_revisions": selections,
    }
    if rebuild_reason is not None:
        payload["rebuild_reason"] = rebuild_reason
    return models.CreateKnowledgeBuildTaskRequest(**payload)


def _claim_task(
    *,
    store: InMemoryKnowledgeBuildStore,
    task_id: str,
    unit: ApprovedUnit,
    status: str,
    result_change_set_id: str | None = None,
) -> None:
    module = _build_service_module()
    store.create_with_claims(
        models.KnowledgeBuildTask(
            task_id=task_id,
            name=f"任务 {task_id}",
            status=status,
            build_mode="INITIAL",
            semantic_contract_version="contract-v1",
            pipeline_version="policy-workbench-v1",
            model_scene="policy_structuring",
            config_hash="config",
            created_by="tester",
            result_change_set_id=result_change_set_id,
            units=[
                models.KnowledgeBuildTaskUnit(
                    doc_id=unit.doc_id,
                    doc_title=unit.doc_title,
                    unit_id=unit.unit_id,
                    unit_revision_id=module.unit_revision_id_for(
                        doc_id=unit.doc_id,
                        unit_id=unit.unit_id,
                        source_text=unit.source_text,
                    ),
                    path=unit.path,
                )
            ],
        )
    )


def test_unit_revision_id_is_stable_and_sensitive_to_exact_source_content() -> None:
    module = _build_service_module()
    expected = "UR_" + hashlib.sha256(b"doc-1\0unit-1\0source text").hexdigest()[:24]

    first = module.unit_revision_id_for(
        doc_id="doc-1", unit_id="unit-1", source_text="source text"
    )
    second = module.unit_revision_id_for(
        doc_id="doc-1", unit_id="unit-1", source_text="source text"
    )
    changed = module.unit_revision_id_for(
        doc_id="doc-1", unit_id="unit-1", source_text="source text "
    )

    assert first == expected
    assert second == first
    assert changed != first


def test_create_request_trims_identity_fields_and_allows_missing_rebuild_reason() -> None:
    request = models.CreateKnowledgeBuildTaskRequest(
        name="  构建任务  ",
        created_by="  reviewer  ",
        build_mode="REBUILD",
        rebuild_reason="  政策修订  ",
        unit_revisions=[
            models.KnowledgeBuildUnitRevision(
                doc_id="doc-1",
                unit_id="unit-1",
                unit_revision_id="revision-1",
            )
        ],
    )
    missing_reason = request.model_copy(update={"rebuild_reason": None})

    assert request.name == "构建任务"
    assert request.created_by == "reviewer"
    assert request.rebuild_reason == "政策修订"
    assert missing_reason.rebuild_reason is None


def test_build_request_and_nested_selections_are_immutable() -> None:
    selection = models.KnowledgeBuildUnitRevision(
        doc_id="doc-1",
        unit_id="unit-1",
        unit_revision_id="revision-1",
    )
    request = models.CreateKnowledgeBuildTaskRequest(
        name="构建任务",
        created_by="reviewer",
        build_mode="INITIAL",
        unit_revisions=[selection],
    )

    assert isinstance(request.unit_revisions, tuple)
    with pytest.raises(ValidationError):
        selection.doc_id = "doc-2"
    with pytest.raises(ValidationError):
        request.name = "替换任务"
    with pytest.raises(ValidationError):
        request.unit_revisions[0].unit_id = "unit-2"
    with pytest.raises(AttributeError):
        request.unit_revisions.append(selection)
    with pytest.raises(TypeError):
        request.unit_revisions[0] = selection


def test_unit_revision_identity_preserves_nonblank_text_unchanged() -> None:
    selection = models.KnowledgeBuildUnitRevision(
        doc_id=" doc-1 ",
        unit_id=" unit-1 ",
        unit_revision_id=" revision-1 ",
    )

    assert selection.doc_id == " doc-1 "
    assert selection.unit_id == " unit-1 "
    assert selection.unit_revision_id == " revision-1 "


@pytest.mark.parametrize("field_name", ["doc_id", "unit_id", "unit_revision_id"])
def test_unit_revision_identity_rejects_blank_text(field_name: str) -> None:
    payload = {
        "doc_id": "doc-1",
        "unit_id": "unit-1",
        "unit_revision_id": "revision-1",
    }
    payload[field_name] = " \n\t "

    with pytest.raises(ValidationError):
        models.KnowledgeBuildUnitRevision(**payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "   "},
        {"created_by": "\n\t"},
        {"unit_revisions": []},
        {
            "unit_revisions": [
                {"doc_id": "doc-1", "unit_id": "unit-1", "unit_revision_id": "r1"},
                {"doc_id": "doc-1", "unit_id": "unit-1", "unit_revision_id": "r2"},
            ]
        },
    ],
)
def test_create_request_rejects_blank_identity_empty_or_duplicate_units(
    overrides: dict[str, Any],
) -> None:
    payload: dict[str, Any] = {
        "name": "任务",
        "created_by": "reviewer",
        "build_mode": "INITIAL",
        "unit_revisions": [
            {"doc_id": "doc-1", "unit_id": "unit-1", "unit_revision_id": "r1"}
        ],
    }
    payload.update(overrides)

    with pytest.raises(ValidationError):
        models.CreateKnowledgeBuildTaskRequest(**payload)


def test_list_eligible_units_sorts_previews_and_builds_claim_targets() -> None:
    store = InMemoryKnowledgeBuildStore()
    units = [
        _unit(
            doc_id="doc-b",
            doc_title="B policy",
            unit_id="unit-running",
            source_text="running",
            order_no=3,
            path=["C"],
        ),
        _unit(
            doc_id="doc-b",
            doc_title="B policy",
            unit_id="unit-release",
            source_text="release",
            order_no=2,
            path=["B"],
        ),
        _unit(
            doc_id="doc-b",
            doc_title="B policy",
            unit_id="unit-review",
            source_text="review",
            order_no=1,
            path=["A"],
        ),
    ]
    available = _unit(
        doc_id="doc-a",
        doc_title="A policy",
        unit_id="unit-available",
        source_text="  first\n\tsecond  " + "x" * 150,
        order_no=2,
        path=["Z"],
    )
    published = _unit(
        doc_id="doc-a",
        doc_title="A policy",
        unit_id="unit-published",
        source_text="published",
        order_no=1,
        path=["A"],
        status="published",
    )
    tie_unit_b = _unit(
        doc_id="doc-a",
        doc_title="A policy",
        unit_id="unit-tie-b",
        source_text="tie b",
        order_no=1,
        path=["B"],
    )
    tie_unit_a = _unit(
        doc_id="doc-a",
        doc_title="A policy",
        unit_id="unit-tie-a",
        source_text="tie a",
        order_no=1,
        path=["B"],
    )
    final_tie_z = _unit(
        doc_id="doc-z",
        doc_title="C policy",
        unit_id="unit-final-tie",
        source_text="final z",
        order_no=1,
        path=["same"],
    )
    final_tie_c = _unit(
        doc_id="doc-c",
        doc_title="C policy",
        unit_id="unit-final-tie",
        source_text="final c",
        order_no=1,
        path=["same"],
    )
    for task_id, unit, status, result_id in [
        ("task-review", units[2], "WAITING_REVIEW", "change-set-1"),
        ("task-release", units[1], "APPROVED_PENDING_RELEASE", "change-set-2"),
        ("task-running", units[0], "RUNNING", None),
    ]:
        _claim_task(
            store=store,
            task_id=task_id,
            unit=unit,
            status=status,
            result_change_set_id=result_id,
        )
    service, _workbench, _store = _service(
        [
            _document("doc-b", "B policy", units),
            _document(
                "doc-a",
                "A policy",
                [available, tie_unit_b, published, tie_unit_a],
            ),
            _document("doc-z", "C policy", [final_tie_z]),
            _document("doc-c", "C policy", [final_tie_c]),
        ],
        store=store,
    )

    eligible = service.list_eligible_units()

    assert [(item.doc_id, item.unit_id) for item in eligible] == [
        ("doc-a", "unit-published"),
        ("doc-a", "unit-tie-a"),
        ("doc-a", "unit-tie-b"),
        ("doc-a", "unit-available"),
        ("doc-b", "unit-review"),
        ("doc-b", "unit-release"),
        ("doc-b", "unit-running"),
        ("doc-c", "unit-final-tie"),
        ("doc-z", "unit-final-tie"),
    ]
    by_id = {item.unit_id: item for item in eligible}
    assert by_id["unit-published"].availability == "REBUILD_REQUIRED"
    assert by_id["unit-published"].status == "published"
    assert by_id["unit-available"].availability == "AVAILABLE"
    assert by_id["unit-available"].status == "reviewed"
    assert "\n" not in by_id["unit-available"].source_preview
    assert "\t" not in by_id["unit-available"].source_preview
    assert len(by_id["unit-available"].source_preview) == 120
    assert by_id["unit-review"].availability == "CLAIMED"
    assert by_id["unit-review"].occupied_by == "task-review"
    assert by_id["unit-review"].target_href == (
        "/policy-knowledge/knowledge/review/change-set-1"
    )
    assert by_id["unit-release"].target_href == (
        "/policy-knowledge/knowledge/releases"
    )
    assert by_id["unit-running"].target_href == (
        "/policy-knowledge/knowledge/build?task_id=task-running"
    )


def test_preflight_blocks_unknown_stale_and_claimed_units() -> None:
    stale = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="stale",
        source_text="current text",
    )
    claimed = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="claimed",
        source_text="claimed text",
    )
    store = InMemoryKnowledgeBuildStore()
    _claim_task(
        store=store,
        task_id="task-review",
        unit=claimed,
        status="WAITING_REVIEW",
        result_change_set_id="change-set-1",
    )
    service, _workbench, _store = _service(
        [_document("doc-1", "Policy", [stale, claimed])],
        store=store,
    )
    request = _request(
        [
            models.KnowledgeBuildUnitRevision(
                doc_id="doc-1",
                unit_id="stale",
                unit_revision_id="outdated",
            ),
            models.KnowledgeBuildUnitRevision(
                doc_id="doc-1",
                unit_id="unknown",
                unit_revision_id="unknown-revision",
            ),
            _selection("doc-1", "claimed", "claimed text"),
        ]
    )

    result = service.preflight(request)

    assert [blocker.code for blocker in result.blockers] == [
        "UNIT_REVISION_CHANGED",
        "UNIT_NOT_APPROVED",
        "UNIT_ALREADY_CLAIMED",
    ]
    assert result.selected_count == 3
    assert result.buildable_count == 0
    assert result.blocking_count == 3
    assert result.can_submit is False
    claim_blocker = result.blockers[-1]
    assert claim_blocker.task_id == "task-review"
    assert claim_blocker.target_href == (
        "/policy-knowledge/knowledge/review/change-set-1"
    )


@pytest.mark.parametrize(
    "contract_versions",
    [(None, None), ("contract-v1", "contract-v2")],
)
def test_preflight_requires_one_shared_nonempty_semantic_contract(
    contract_versions: tuple[str | None, str | None],
) -> None:
    first = _unit(
        doc_id="doc-1",
        doc_title="First",
        unit_id="unit-1",
        source_text="one",
    )
    second = _unit(
        doc_id="doc-2",
        doc_title="Second",
        unit_id="unit-2",
        source_text="two",
    )
    service, _workbench, _store = _service(
        [
            _document(
                "doc-1", "First", [first], contract_version=contract_versions[0]
            ),
            _document(
                "doc-2", "Second", [second], contract_version=contract_versions[1]
            ),
        ]
    )

    result = service.preflight(
        _request(
            [
                _selection("doc-1", "unit-1", "one"),
                _selection("doc-2", "unit-2", "two"),
            ]
        )
    )

    assert [blocker.code for blocker in result.blockers] == [
        "SEMANTIC_CONTRACT_MISMATCH"
    ]
    assert result.semantic_contract_version is None
    assert result.buildable_count == 2


def test_preflight_reports_contract_mismatch_even_when_one_unit_is_stale() -> None:
    valid = _unit(
        doc_id="doc-a",
        doc_title="First",
        unit_id="valid",
        source_text="current a",
    )
    stale = _unit(
        doc_id="doc-b",
        doc_title="Second",
        unit_id="stale",
        source_text="current b",
    )
    service, _workbench, _store = _service(
        [
            _document("doc-a", "First", [valid], contract_version="contract-a"),
            _document("doc-b", "Second", [stale], contract_version="contract-b"),
        ]
    )
    request = _request(
        [
            _selection("doc-a", "valid", "current a"),
            models.KnowledgeBuildUnitRevision(
                doc_id="doc-b",
                unit_id="stale",
                unit_revision_id="outdated",
            ),
        ]
    )

    result = service.preflight(request)

    assert [blocker.code for blocker in result.blockers] == [
        "UNIT_REVISION_CHANGED",
        "SEMANTIC_CONTRACT_MISMATCH",
    ]
    assert result.selected_count == 2
    assert result.buildable_count == 1
    assert result.blocking_count == 2
    assert result.semantic_contract_version is None


def test_initial_build_blocks_published_unit() -> None:
    published = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="published",
        source_text="published text",
        status="published",
    )
    service, _workbench, _store = _service(
        [_document("doc-1", "Policy", [published])]
    )

    result = service.preflight(
        _request([_selection("doc-1", "published", "published text")])
    )

    assert [blocker.code for blocker in result.blockers] == [
        "REBUILD_MODE_REQUIRED"
    ]
    assert result.buildable_count == 0
    assert result.rebuild_count == 0


def test_rebuild_requires_reason_without_request_validation_failure() -> None:
    reviewed = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="reviewed",
        source_text="reviewed text",
    )
    service, _workbench, _store = _service(
        [_document("doc-1", "Policy", [reviewed])]
    )
    request = _request(
        [_selection("doc-1", "reviewed", "reviewed text")],
        build_mode="REBUILD",
        rebuild_reason="   ",
    )

    result = service.preflight(request)

    assert request.rebuild_reason == ""
    assert [blocker.code for blocker in result.blockers] == [
        "REBUILD_REASON_REQUIRED"
    ]
    assert result.buildable_count == 1
    assert result.can_submit is False


def test_valid_rebuild_warns_for_published_unit_and_counts_it() -> None:
    published = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="published",
        source_text="published text",
        status="published",
    )
    reviewed = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="reviewed",
        source_text="reviewed text",
    )
    service, _workbench, _store = _service(
        [_document("doc-1", "Policy", [published, reviewed])]
    )

    result = service.preflight(
        _request(
            [
                _selection("doc-1", "published", "published text"),
                _selection("doc-1", "reviewed", "reviewed text"),
            ],
            build_mode="REBUILD",
            rebuild_reason="政策内容修订",
        )
    )

    assert result.blockers == []
    assert [warning.code for warning in result.warnings] == [
        "REBUILDING_PUBLISHED_UNIT"
    ]
    assert result.selected_count == 2
    assert result.buildable_count == 2
    assert result.rebuild_count == 1
    assert result.can_submit is True
    assert result.semantic_contract_version == "contract-v1"


def test_preflight_reloads_source_after_listing_and_performs_no_writes() -> None:
    unit = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="original",
    )
    service, workbench, store = _service([_document("doc-1", "Policy", [unit])])
    eligible = service.list_eligible_units()
    selection = models.KnowledgeBuildUnitRevision(
        doc_id=eligible[0].doc_id,
        unit_id=eligible[0].unit_id,
        unit_revision_id=eligible[0].unit_revision_id,
    )
    workbench.documents["doc-1"] = _document(
        "doc-1",
        "Policy",
        [unit.model_copy(update={"source_text": "changed"})],
    )
    calls_after_list = workbench.get_document_calls

    result = service.preflight(_request([selection]))

    assert [blocker.code for blocker in result.blockers] == [
        "UNIT_REVISION_CHANGED"
    ]
    assert workbench.get_document_calls > calls_after_list
    assert store.list() == []
    assert store.get_claim("doc-1", "unit-1") is None


def test_service_exposes_deterministic_pipeline_configuration() -> None:
    module = _build_service_module()
    service_a, _workbench_a, _store_a = _service([])
    service_b, _workbench_b, _store_b = _service([])

    assert module._PIPELINE_VERSION == "policy-workbench-v1"
    assert module._MODEL_SCENE == "policy_structuring"
    assert module._CONFIG_HASH == service_a.config_hash
    assert not hasattr(module, "pipeline_version")
    assert not hasattr(module, "model_scene")
    assert not hasattr(module, "config_hash")
    assert service_a.pipeline_version == "policy-workbench-v1"
    assert service_a.model_scene == "policy_structuring"
    assert service_a.config_hash == service_b.config_hash
    assert len(service_a.config_hash) == 64
    int(service_a.config_hash, 16)


def test_create_task_orchestrates_exact_selected_snapshot_to_review() -> None:
    fixed_time = datetime(2026, 8, 5, 9, 30, tzinfo=timezone.utc)
    first = _unit(
        doc_id="doc-a",
        doc_title="Policy A",
        unit_id="shared-unit",
        source_text="exact source A",
        path=["Chapter A"],
    )
    excluded = _unit(
        doc_id="doc-a",
        doc_title="Policy A",
        unit_id="unit-excluded",
        source_text="must not build",
    )
    second = _unit(
        doc_id="doc-b",
        doc_title="Policy B",
        unit_id="shared-unit",
        source_text="exact source B",
        path=["Chapter B"],
    )
    store = _RecordingStore()
    service, workbench, _store, builder = _create_service(
        [
            _document("doc-a", "Policy A", [first, excluded]),
            _document("doc-b", "Policy B", [second]),
        ],
        store=store,
        clock=lambda: fixed_time,
        task_id_factory=lambda: "KB_20260805_fixed000001",
    )
    request = models.CreateKnowledgeBuildTaskRequest(
        name="Selected policy build",
        created_by="reviewer-a",
        build_mode="REBUILD",
        rebuild_reason="Policy source refreshed",
        unit_revisions=[
            _selection("doc-a", "shared-unit", "exact source A"),
            _selection("doc-b", "shared-unit", "exact source B"),
        ],
    )

    result = service.create_task(request)

    assert store.transitions == ["QUEUED", "RUNNING", "WAITING_REVIEW"]
    queued = store.snapshots[0]
    assert queued.task_id == "KB_20260805_fixed000001"
    assert queued.name == request.name
    assert queued.build_mode == request.build_mode
    assert queued.rebuild_reason == request.rebuild_reason
    assert queued.created_by == request.created_by
    assert queued.semantic_contract_version == "contract-v1"
    assert queued.pipeline_version == service.pipeline_version
    assert queued.model_scene == service.model_scene
    assert queued.config_hash == service.config_hash
    assert queued.created_at == fixed_time
    assert queued.updated_at == fixed_time
    assert queued.processed_units == 0
    assert queued.result_change_set_id is None
    assert queued.result_summary == {}
    assert queued.issue_count == 0
    assert queued.started_at is None
    assert queued.finished_at is None
    assert [unit.model_dump() for unit in queued.units] == [
        {
            "doc_id": "doc-a",
            "doc_title": "Policy A",
            "unit_id": "shared-unit",
            "unit_revision_id": _selection(
                "doc-a", "shared-unit", "exact source A"
            ).unit_revision_id,
            "path": ["Chapter A"],
            "status": "PENDING",
            "candidate_result_ids": [],
            "error_code": None,
            "error_message": None,
        },
        {
            "doc_id": "doc-b",
            "doc_title": "Policy B",
            "unit_id": "shared-unit",
            "unit_revision_id": _selection(
                "doc-b", "shared-unit", "exact source B"
            ).unit_revision_id,
            "path": ["Chapter B"],
            "status": "PENDING",
            "candidate_result_ids": [],
            "error_code": None,
            "error_message": None,
        },
    ]
    assert workbench.get_document_calls == 2
    assert len(builder.calls) == 1
    call = builder.calls[0]
    assert call["task_id"] == queued.task_id
    assert call["task_name"] == request.name
    assert call["semantic_contract_version"] == "contract-v1"
    assert call["supersedes_candidate_id"] is None
    assert [
        (selected.unit.doc_id, selected.unit.unit_id, selected.unit.source_text)
        for selected in call["units"]
    ] == [
        ("doc-a", "shared-unit", "exact source A"),
        ("doc-b", "shared-unit", "exact source B"),
    ]
    candidate = builder.results[0]
    assert [(item.doc_id, item.unit_id) for item in candidate.items] == [
        ("doc-a", "shared-unit"),
        ("doc-b", "shared-unit"),
    ]
    assert [
        (source.doc_id, source.unit_id, source.unit_revision_id)
        for source in candidate.source_units
    ] == [
        ("doc-a", "shared-unit", queued.units[0].unit_revision_id),
        ("doc-b", "shared-unit", queued.units[1].unit_revision_id),
    ]
    assert result.status == "WAITING_REVIEW"
    assert result.started_at == fixed_time
    assert result.finished_at == fixed_time
    assert result.processed_units == 2
    assert result.issue_count == 0
    assert result.result_change_set_id == candidate.change_set_id
    assert result.result_summary == candidate.summary
    assert [unit.status for unit in result.units] == ["BUILT", "BUILT"]
    assert [unit.candidate_result_ids for unit in result.units] == [
        ["ci_doc-a_shared-unit"],
        ["ci_doc-b_shared-unit"],
    ]
    assert store.get_claim("doc-a", "shared-unit") is not None
    assert store.get_claim("doc-b", "shared-unit") is not None
    assert store.get_claim("doc-a", "unit-excluded") is None


def test_create_task_default_id_uses_utc_date_and_lowercase_uuid_prefix() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    local_time = datetime(
        2026,
        8,
        6,
        1,
        15,
        tzinfo=timezone(timedelta(hours=8)),
    )
    service, _workbench, _store, _builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        clock=lambda: local_time,
    )

    result = service.create_task(
        _request([_selection("doc-1", "unit-1", "source")])
    )

    assert re.fullmatch(r"KB_20260805_[0-9a-f]{12}", result.task_id)


def test_create_task_rejects_blank_injected_id_before_any_write() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    service, _workbench, store, builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        task_id_factory=lambda: " \t ",
    )

    with pytest.raises(ValueError, match="ID"):
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert store.transitions == []
    assert store.list() == []
    assert builder.calls == []


def test_create_task_raises_typed_preflight_blocker_without_state() -> None:
    module = _build_service_module()
    service, _workbench, store, builder = _create_service([])
    request = _request(
        [
            models.KnowledgeBuildUnitRevision(
                doc_id="unknown-doc",
                unit_id="unknown-unit",
                unit_revision_id="unknown-revision",
            )
        ]
    )

    with pytest.raises(module.KnowledgeBuildPreflightBlocked) as exc_info:
        service.create_task(request)

    assert [blocker.code for blocker in exc_info.value.result.blockers] == [
        "UNIT_NOT_APPROVED"
    ]
    assert store.transitions == []
    assert store.list() == []
    assert builder.calls == []


def test_create_task_revalidates_after_public_preflight_against_fresh_source() -> None:
    module = _build_service_module()
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="version one",
    )
    service, workbench, store, builder = _create_service(
        [_document("doc-1", "Policy", [source])]
    )
    request = _request([_selection("doc-1", "unit-1", "version one")])
    assert service.preflight(request).can_submit is True
    workbench.documents["doc-1"] = _document(
        "doc-1",
        "Policy",
        [source.model_copy(update={"source_text": "version two"})],
    )

    with pytest.raises(module.KnowledgeBuildPreflightBlocked) as exc_info:
        service.create_task(request)

    assert [blocker.code for blocker in exc_info.value.result.blockers] == [
        "UNIT_REVISION_CHANGED"
    ]
    assert workbench.get_document_calls == 2
    assert store.transitions == []
    assert builder.calls == []


def test_create_task_preserves_atomic_claim_race_and_skips_build_or_cleanup() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    race = UnitRevisionClaimed(
        doc_id="doc-1",
        unit_id="unit-1",
        unit_revision_id=_selection(
            "doc-1", "unit-1", "source"
        ).unit_revision_id,
        task_id="KB_competing",
    )
    store = _ClaimRaceStore(race)
    service, workbench, _store, builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        task_id_factory=lambda: "KB_race_attempt",
    )

    with pytest.raises(UnitRevisionClaimed) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is race
    assert workbench.get_document_calls == 1
    assert store.transitions == ["QUEUED"]
    assert store.inner.list() == []
    assert store.get_calls == 0
    assert builder.calls == []


def test_create_task_build_failure_marks_failed_releases_claim_and_reraises() -> None:
    fixed_time = datetime(2026, 8, 5, 11, 0, tzinfo=timezone.utc)
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    failure = RuntimeError("candidate generation failed")
    store = _RecordingStore()
    builder = _ChangeSetOnlyBuilder(failure=failure)
    service, _workbench, _store, _builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        builder=builder,
        clock=lambda: fixed_time,
        task_id_factory=lambda: "KB_build_failure",
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is failure
    failed = store.inner.get("KB_build_failure")
    assert failed is not None
    assert failed.status == "FAILED"
    assert failed.finished_at is not None
    assert failed.finished_at.tzinfo is not None
    assert failed.processed_units == 0
    assert [unit.status for unit in failed.units] == ["FAILED"]
    assert [unit.error_code for unit in failed.units] == ["RuntimeError"]
    assert [unit.error_message for unit in failed.units] == [str(failure)]
    assert store.transitions == ["QUEUED", "RUNNING", "FAILED"]
    assert store.get_claim("doc-1", "unit-1") is None


def test_create_task_running_save_failure_attempts_failed_cleanup() -> None:
    fixed_time = datetime(2026, 8, 5, 11, 30, tzinfo=timezone.utc)
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    failure = RuntimeError("running save failed")
    store = _RecordingStore(running_save_failure=failure)
    service, _workbench, _store, builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        clock=lambda: fixed_time,
        task_id_factory=lambda: "KB_running_failure",
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is failure
    failed = store.inner.get("KB_running_failure")
    assert failed is not None
    assert failed.status == "FAILED"
    assert [unit.error_code for unit in failed.units] == ["RuntimeError"]
    assert [unit.error_message for unit in failed.units] == [str(failure)]
    assert store.transitions == ["QUEUED", "RUNNING", "FAILED"]
    assert store.get_claim("doc-1", "unit-1") is None
    assert builder.calls == []


def test_create_task_final_save_failure_attempts_failed_cleanup() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    failure = RuntimeError("final save failed")
    store = _RecordingStore(final_save_failure=failure)
    candidate_store = InMemoryChangeSetStore()
    builder = ChangeSetService(object(), candidate_store)
    service, _workbench, _store, builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        builder=builder,
        task_id_factory=lambda: "KB_final_failure",
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is failure
    failed = store.inner.get("KB_final_failure")
    assert failed is not None
    assert failed.status == "FAILED"
    candidate = candidate_store.list()[0]
    assert failed.result_change_set_id == candidate.change_set_id
    assert candidate.status == "FAILED"
    assert [unit.error_code for unit in failed.units] == ["RuntimeError"]
    assert [unit.error_message for unit in failed.units] == [str(failure)]
    assert store.transitions == [
        "QUEUED",
        "RUNNING",
        "WAITING_REVIEW",
        "FAILED",
    ]
    assert store.get_claim("doc-1", "unit-1") is None
    with pytest.raises(ValueError):
        builder.approve(candidate.change_set_id, "reviewer")


def test_create_task_clock_failure_after_claim_uses_safe_failure_timestamp() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    initial_time = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    clock_calls = 0

    def failing_clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        if clock_calls == 1:
            return initial_time
        raise RuntimeError("injected clock unavailable")

    store = _RecordingStore()
    service, _workbench, _store, builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        clock=failing_clock,
        task_id_factory=lambda: "KB_clock_failure",
    )

    with pytest.raises(RuntimeError, match="injected clock unavailable") as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    failed = store.inner.get("KB_clock_failure")
    assert failed is not None
    assert failed.status == "FAILED"
    assert failed.finished_at is not None
    assert failed.finished_at.tzinfo is not None
    assert [unit.error_message for unit in failed.units] == [str(exc_info.value)]
    assert store.fail_and_release_calls == 1
    assert store.get_claim("doc-1", "unit-1") is None
    assert builder.calls == []


def test_create_task_cas_conflict_uses_transactional_failure_cleanup() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    failure = KnowledgeBuildTaskVersionConflict("KB_cas_conflict")
    store = _ConcurrentRunningSaveStore(failure)
    service, _workbench, _store, builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        task_id_factory=lambda: "KB_cas_conflict",
    )

    with pytest.raises(KnowledgeBuildTaskVersionConflict) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is failure
    failed = store.inner.get("KB_cas_conflict")
    assert failed is not None
    assert failed.status == "FAILED"
    assert store.fail_and_release_calls == 1
    assert store.get_claim("doc-1", "unit-1") is None
    assert builder.calls == []


def test_create_task_duplicate_id_preserves_existing_task_and_claim() -> None:
    existing_unit = _unit(
        doc_id="doc-old",
        doc_title="Old Policy",
        unit_id="old-unit",
        source_text="old source",
    )
    new_unit = _unit(
        doc_id="doc-new",
        doc_title="New Policy",
        unit_id="new-unit",
        source_text="new source",
    )
    store = _RecordingStore()
    _claim_task(
        store=store.inner,
        task_id="KB_duplicate",
        unit=existing_unit,
        status="QUEUED",
    )
    existing_before = store.inner.get("KB_duplicate")
    claim_before = store.inner.get_claim("doc-old", "old-unit")
    service, _workbench, _store, builder = _create_service(
        [_document("doc-new", "New Policy", [new_unit])],
        store=store,
        task_id_factory=lambda: "KB_duplicate",
    )

    with pytest.raises(ValueError, match="KB_duplicate"):
        service.create_task(
            _request([_selection("doc-new", "new-unit", "new source")])
        )

    assert store.inner.get("KB_duplicate") == existing_before
    assert store.inner.get_claim("doc-old", "old-unit") == claim_before
    assert store.inner.get_claim("doc-new", "new-unit") is None
    assert store.fail_and_release_calls == 0
    assert builder.calls == []


def test_candidate_invalidation_failure_preserves_original_exception_with_note() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    original = RuntimeError("final task save failed")
    invalidation = RuntimeError("candidate invalidation failed")
    store = _RecordingStore(final_save_failure=original)
    candidate_store = InMemoryChangeSetStore()
    actual_builder = ChangeSetService(object(), candidate_store)
    builder = _FailingCandidateInvalidation(actual_builder, invalidation)
    service, _workbench, _store, _builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        builder=builder,
        task_id_factory=lambda: "KB_invalidation_failure",
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is original
    assert any(
        "candidate invalidation failed" in note
        for note in getattr(original, "__notes__", [])
    )
    failed = store.inner.get("KB_invalidation_failure")
    assert failed is not None
    assert failed.status == "FAILED"
    assert failed.result_change_set_id == candidate_store.list()[0].change_set_id
    assert store.get_claim("doc-1", "unit-1") is None
    assert candidate_store.list()[0].status == "PENDING_REVIEW"


def test_failure_cleanup_error_preserves_original_exception_with_note() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    original = RuntimeError("candidate build failed")
    cleanup = RuntimeError("transactional cleanup failed")
    store = _FailingCompensationStore(cleanup)
    builder = _ChangeSetOnlyBuilder(failure=original)
    service, _workbench, _store, _builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        builder=builder,
        task_id_factory=lambda: "KB_cleanup_failure",
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is original
    assert any(
        "transactional cleanup failed" in note
        for note in getattr(original, "__notes__", [])
    )
    assert store.fail_and_release_calls == 1
    assert store.get_claim("doc-1", "unit-1") is not None


def test_candidate_save_commit_then_raise_recovers_and_invalidates_candidate() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    original = RuntimeError("candidate save response lost")
    candidate_store = _CommitThenRaiseChangeSetStore(original)
    builder = ChangeSetService(object(), candidate_store)
    store = _RecordingStore()
    service, _workbench, _store, _builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        builder=builder,
        task_id_factory=lambda: "KB_candidate_commit_then_raise",
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is original
    candidate = candidate_store.list()[0]
    failed = store.inner.get("KB_candidate_commit_then_raise")
    assert failed is not None
    assert failed.status == "FAILED"
    assert failed.result_change_set_id == candidate.change_set_id
    assert candidate.status == "FAILED"
    assert store.get_claim("doc-1", "unit-1") is None


def test_final_task_save_commit_then_raise_preserves_review_state_and_claim() -> None:
    source = _unit(
        doc_id="doc-1",
        doc_title="Policy",
        unit_id="unit-1",
        source_text="source",
    )
    original = RuntimeError("final task save response lost")
    store = _CommitThenRaiseFinalSaveStore(original)
    candidate_store = InMemoryChangeSetStore()
    builder = ChangeSetService(object(), candidate_store)
    service, _workbench, _store, _builder = _create_service(
        [_document("doc-1", "Policy", [source])],
        store=store,
        builder=builder,
        task_id_factory=lambda: "KB_final_commit_then_raise",
    )

    with pytest.raises(RuntimeError) as exc_info:
        service.create_task(
            _request([_selection("doc-1", "unit-1", "source")])
        )

    assert exc_info.value is original
    latest = store.inner.get("KB_final_commit_then_raise")
    assert latest is not None
    assert latest.status == "WAITING_REVIEW"
    assert store.fail_and_release_calls == 1
    assert store.get_claim("doc-1", "unit-1") is not None
    candidate = candidate_store.list()[0]
    assert latest.result_change_set_id == candidate.change_set_id
    assert candidate.status == "PENDING_REVIEW"
