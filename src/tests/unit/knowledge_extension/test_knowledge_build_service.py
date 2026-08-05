from __future__ import annotations

import hashlib
import importlib
from collections.abc import Iterable
from typing import Any

import pytest
from pydantic import ValidationError

from src.knowledge_extension.rule_explanation import knowledge_build_models as models
from src.knowledge_extension.rule_explanation.knowledge_build_store import (
    InMemoryKnowledgeBuildStore,
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

    def get_document(self, doc_id: str) -> KnowledgeWorkbenchDocument:
        self.get_document_calls += 1
        return self.documents[doc_id].model_copy(deep=True)


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
