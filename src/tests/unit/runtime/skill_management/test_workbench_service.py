from datetime import datetime, timedelta, timezone

import pytest

from src.domain.skill.draft_models import SkillDraft, SkillDraftSourceType, SkillDraftStatus
from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillEvalMetrics,
    SkillEvalRun,
    SkillEvalRunStatus,
    SkillRelease,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)
from src.domain.skill.version_models import SkillValidationStatus, SkillVersion
from src.runtime.skill_management.version_service import (
    SkillCatalogEntry,
    SkillCatalogPage,
)
from src.runtime.skill_management.workbench_service import (
    SkillGovernanceStatus,
    SkillWorkbenchService,
    _resolve_status,
)


NOW = datetime(2026, 8, 5, 6, 0, tzinfo=timezone.utc)
HASH = "a" * 64


def _version(skill_id: str, version_id: str, semantic_version: str) -> SkillVersion:
    return SkillVersion(
        version_id=version_id,
        skill_id=skill_id,
        semantic_version=semantic_version,
        source_commit="abc1234",
        source_path=f"skills/{skill_id}",
        artifact_hash=HASH,
        manifest_snapshot={"skill_id": skill_id, "version": semantic_version},
        dependency_snapshot={},
        file_count=2,
        validation_status=SkillValidationStatus.PASSED,
        created_by="developer",
        created_at=NOW,
    )


def _entry(
    skill_id: str,
    version: SkillVersion,
    *,
    artifact_status: str = "registered",
) -> SkillCatalogEntry:
    return SkillCatalogEntry(
        skill_id=skill_id,
        skill_name=f"{skill_id} name",
        business_action="explain",
        business_object="settlement",
        semantic_version=version.semantic_version,
        artifact_hash=version.artifact_hash,
        artifact_status=artifact_status,
        file_count=version.file_count,
        registered_version=version,
    )


def _run(
    skill_id: str,
    version_id: str,
    status: SkillEvalRunStatus,
    *,
    created_at: datetime = NOW,
    regression_count: int | None = None,
    required_total: int | None = None,
    required_passed: int | None = None,
    case_snapshots: list[SkillEvalCase] | None = None,
) -> SkillEvalRun:
    passed = status == SkillEvalRunStatus.PASSED
    required_total = 1 if required_total is None else required_total
    required_passed = int(passed) if required_passed is None else required_passed
    return SkillEvalRun(
        run_id=f"run-{skill_id}-{status}",
        skill_id=skill_id,
        version_id=version_id,
        suite_version=1,
        config_hash=HASH,
        routing_manifest_hash=HASH,
        status=status,
        metrics=SkillEvalMetrics(
            total=1,
            passed=int(passed),
            required_total=required_total,
            required_passed=required_passed,
            top1_accuracy=float(passed),
            baseline_top1_accuracy=0.0,
            regression_count=(
                int(not passed) if regression_count is None else regression_count
            ),
            new_false_takeover_count=0,
            gate_passed=passed,
        ),
        case_snapshots=case_snapshots or [],
        created_by="quality-user",
        created_at=created_at,
        completed_at=created_at,
    )


def _draft(
    draft_id: str,
    skill_id: str,
    status: SkillDraftStatus,
    *,
    updated_at: datetime = NOW,
) -> SkillDraft:
    return SkillDraft(
        draft_id=draft_id,
        skill_id=skill_id,
        skill_name=f"{skill_id} draft",
        source_type=SkillDraftSourceType.COPY,
        source_skill_id=skill_id,
        structured_config={},
        status=status,
        created_by="developer",
        created_at=updated_at,
        updated_at=updated_at,
    )


def _release(
    skill_id: str,
    version_id: str,
    status: SkillReleaseStatus,
    *,
    created_at: datetime = NOW,
) -> SkillRelease:
    return SkillRelease(
        release_id=f"release-{skill_id}-{status}",
        skill_id=skill_id,
        version_id=version_id,
        environment=SkillReleaseEnvironment.TEST,
        status=status,
        eval_run_id=f"run-{skill_id}",
        artifact_hash=HASH,
        config_hash=HASH,
        rollout_percent=100 if status == SkillReleaseStatus.ACTIVE else 0,
        runtime_mode="shadow",
        revision=1,
        created_by="developer",
        created_at=created_at,
        activated_at=created_at if status == SkillReleaseStatus.ACTIVE else None,
    )


class _VersionCatalogService:
    def __init__(self, entries: list[SkillCatalogEntry]) -> None:
        self.entries = entries
        self.versions = {
            entry.registered_version.version_id: entry.registered_version
            for entry in entries
            if entry.registered_version is not None
        }

    def list_catalog(self, **_: object) -> SkillCatalogPage:
        return SkillCatalogPage(
            items=self.entries,
            page=1,
            page_size=10_000,
            total=len(self.entries),
        )

    def get_version(self, skill_id: str, version_id: str) -> SkillVersion:
        version = self.versions.get(version_id)
        if version is None or version.skill_id != skill_id:
            raise LookupError(version_id)
        return version


class _GovernanceView:
    def __init__(
        self,
        *,
        runs: dict[str, list[SkillEvalRun]],
        releases: dict[str, list[SkillRelease]],
    ) -> None:
        self.runs = runs
        self.releases = releases

    def list_eval_runs(self, skill_id: str) -> list[SkillEvalRun]:
        return self.runs.get(skill_id, [])

    def list_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str | None = None,
    ) -> list[SkillRelease]:
        assert environment == SkillReleaseEnvironment.TEST
        return self.releases.get(skill_id, [])


class _DraftView:
    def __init__(self, drafts: dict[str, list[SkillDraft]]) -> None:
        self.drafts = drafts

    def list_drafts(
        self,
        *,
        include_deleted: bool = False,
        skill_id: str | None = None,
        status: SkillDraftStatus | None = None,
    ) -> list[SkillDraft]:
        assert include_deleted is False
        drafts = self.drafts.get(skill_id or "", [])
        return [draft for draft in drafts if status is None or draft.status == status]


def _service(
    entries: list[SkillCatalogEntry],
    *,
    runs: dict[str, list[SkillEvalRun]],
    releases: dict[str, list[SkillRelease]],
    drafts: dict[str, list[SkillDraft]] | None = None,
) -> SkillWorkbenchService:
    return SkillWorkbenchService(
        version_service=_VersionCatalogService(entries),
        governance_service=_GovernanceView(runs=runs, releases=releases),
        draft_service=_DraftView(drafts or {}),
        now=lambda: NOW,
    )


def test_workbench_prioritizes_gate_failure_and_counts_actionable_summary() -> None:
    failed_version = _version("settlement", "version-failed", "2.0.0")
    active_version = _version("policy", "version-active", "1.0.0")
    service = _service(
        [_entry("settlement", failed_version), _entry("policy", active_version)],
        runs={
            "settlement": [
                _run("settlement", failed_version.version_id, SkillEvalRunStatus.FAILED)
            ],
            "policy": [_run("policy", active_version.version_id, SkillEvalRunStatus.PASSED)],
        },
        releases={
            "settlement": [
                _release(
                    "settlement",
                    failed_version.version_id,
                    SkillReleaseStatus.APPROVAL_PENDING,
                )
            ],
            "policy": [
                _release("policy", active_version.version_id, SkillReleaseStatus.ACTIVE)
            ],
        },
    )

    page = service.list_workbench(page=1, page_size=20)

    failed = next(item for item in page.items if item.skill_id == "settlement")
    assert failed.governance_status == SkillGovernanceStatus.GATE_FAILED
    assert failed.attention_reason == "latest_evaluation_failed"
    assert page.summary.total == 2
    assert page.summary.healthy == 1
    assert page.summary.pending_approval == 0
    assert page.summary.test_active == 1
    assert page.summary.updated_at == NOW


def test_workbench_filters_by_governance_status_before_pagination() -> None:
    first = _version("first", "version-first", "1.0.0")
    second = _version("second", "version-second", "1.0.0")
    service = _service(
        [_entry("first", first), _entry("second", second)],
        runs={
            "first": [_run("first", first.version_id, SkillEvalRunStatus.PASSED)],
            "second": [_run("second", second.version_id, SkillEvalRunStatus.PASSED)],
        },
        releases={},
    )

    page = service.list_workbench(
        page=1,
        page_size=1,
        governance_status=SkillGovernanceStatus.HEALTHY,
    )

    assert page.total == 2
    assert len(page.items) == 1
    assert page.items[0].governance_status == SkillGovernanceStatus.HEALTHY


def test_workbench_keeps_active_version_when_newer_candidate_exists() -> None:
    version = _version("settlement", "version-current", "2.0.0")
    service = _service(
        [_entry("settlement", version)],
        runs={
            "settlement": [_run("settlement", version.version_id, SkillEvalRunStatus.PASSED)]
        },
        releases={
            "settlement": [
                _release("settlement", "version-active", SkillReleaseStatus.ACTIVE),
                _release(
                    "settlement",
                    version.version_id,
                    SkillReleaseStatus.CANDIDATE,
                    created_at=NOW + timedelta(minutes=1),
                ),
            ]
        },
    )

    page = service.list_workbench(page=1, page_size=20)

    assert page.items[0].test_release_status == SkillReleaseStatus.CANDIDATE
    assert page.items[0].test_active_version == "version-active"
    assert page.summary.test_active == 1


@pytest.mark.parametrize(
    ("artifact_status", "eval_status", "release_status", "expected"),
    [
        (
            "registered",
            SkillEvalRunStatus.FAILED,
            SkillReleaseStatus.APPROVAL_PENDING,
            SkillGovernanceStatus.GATE_FAILED,
        ),
        (
            "registered",
            SkillEvalRunStatus.PASSED,
            SkillReleaseStatus.APPROVAL_PENDING,
            SkillGovernanceStatus.PENDING_APPROVAL,
        ),
        (
            "registered",
            None,
            None,
            SkillGovernanceStatus.NEEDS_EVALUATION,
        ),
        (
            "changed",
            SkillEvalRunStatus.PASSED,
            None,
            SkillGovernanceStatus.ARTIFACT_CHANGED,
        ),
        (
            "registered",
            SkillEvalRunStatus.PASSED,
            SkillReleaseStatus.ACTIVE,
            SkillGovernanceStatus.HEALTHY,
        ),
    ],
)
def test_resolve_status_uses_fixed_priority(
    artifact_status: str,
    eval_status: SkillEvalRunStatus | None,
    release_status: SkillReleaseStatus | None,
    expected: SkillGovernanceStatus,
) -> None:
    status, _ = _resolve_status(
        artifact_status=artifact_status,
        latest_eval_status=eval_status,
        latest_release_status=release_status,
    )

    assert status == expected


def test_failed_evaluation_is_a_blocked_diagnosis() -> None:
    version = _version("failed-skill", "version-failed", "2.0.0")
    service = _service(
        [_entry("failed-skill", version)],
        runs={
            "failed-skill": [
                _run(
                    "failed-skill",
                    version.version_id,
                    SkillEvalRunStatus.FAILED,
                    regression_count=2,
                    required_total=3,
                    required_passed=2,
                )
            ]
        },
        releases={},
    )

    item = service.list_workbench(page=1, page_size=20).items[0]

    assert item.current_stage == "diagnose"
    assert item.priority == "blocked"
    assert item.next_action == "create_fix_draft"
    assert item.regression_count == 2
    assert item.required_failure_count == 1
    assert item.next_action_reason == "评测门禁未通过，需要先定位回归案例"


def test_linked_newest_editing_draft_moves_failure_to_modify() -> None:
    version = _version("editing-skill", "version-editing", "2.0.0")
    service = _service(
        [_entry("editing-skill", version)],
        runs={
            "editing-skill": [
                _run(
                    "editing-skill",
                    version.version_id,
                    SkillEvalRunStatus.FAILED,
                )
            ]
        },
        releases={},
        drafts={
            "editing-skill": [
                _draft(
                    "draft-validated",
                    "editing-skill",
                    SkillDraftStatus.VALIDATED,
                    updated_at=NOW - timedelta(minutes=1),
                ),
                _draft(
                    "draft-editing",
                    "editing-skill",
                    SkillDraftStatus.EDITING,
                ),
            ]
        },
    )

    item = service.list_workbench(page=1, page_size=20).items[0]

    assert item.current_stage == "modify"
    assert item.linked_draft_id == "draft-editing"
    assert item.linked_draft_status == "editing"
    assert item.next_action == "continue_draft"


def test_required_failure_sorts_before_other_failure_and_approval() -> None:
    versions = {
        skill_id: _version(skill_id, f"version-{skill_id}", "1.0.0")
        for skill_id in ("normal-failure", "required-failure", "approval")
    }
    entries = [_entry(skill_id, version) for skill_id, version in versions.items()]
    service = _service(
        entries,
        runs={
            "normal-failure": [
                _run(
                    "normal-failure",
                    versions["normal-failure"].version_id,
                    SkillEvalRunStatus.FAILED,
                    required_total=0,
                    required_passed=0,
                )
            ],
            "required-failure": [
                _run(
                    "required-failure",
                    versions["required-failure"].version_id,
                    SkillEvalRunStatus.FAILED,
                    required_total=2,
                    required_passed=1,
                )
            ],
        },
        releases={
            "approval": [
                _release(
                    "approval",
                    versions["approval"].version_id,
                    SkillReleaseStatus.APPROVAL_PENDING,
                )
            ]
        },
    )

    page = service.list_workbench(page=1, page_size=20)

    assert [item.skill_id for item in page.items] == [
        "required-failure",
        "normal-failure",
        "approval",
    ]


def test_workbench_projection_has_no_sensitive_evidence() -> None:
    version = _version("safe-skill", "version-safe", "1.0.0")
    sensitive_case = SkillEvalCase(
        case_id="case-1",
        suite_version=1,
        question_template="patient_id=P001",
        expected_skill_id="safe-skill",
        created_by="quality-user",
    )
    service = _service(
        [_entry("safe-skill", version)],
        runs={
            "safe-skill": [
                _run(
                    "safe-skill",
                    version.version_id,
                    SkillEvalRunStatus.FAILED,
                    case_snapshots=[sensitive_case],
                )
            ]
        },
        releases={},
        drafts={
            "safe-skill": [
                _draft("draft-safe", "safe-skill", SkillDraftStatus.EDITING).model_copy(
                    update={
                        "structured_config": {
                            "approval_reason": "sensitive",
                            "patient_id": "P001",
                        }
                    }
                )
            ]
        },
    )

    payload = service.list_workbench(page=1, page_size=20).model_dump_json()

    assert "question_template" not in payload
    assert "approval_reason" not in payload
    assert "patient_id" not in payload
