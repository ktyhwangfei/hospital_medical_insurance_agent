from datetime import datetime, timedelta, timezone

import pytest

from src.domain.skill.governance_models import (
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
) -> SkillEvalRun:
    passed = status == SkillEvalRunStatus.PASSED
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
            required_total=1,
            required_passed=int(passed),
            top1_accuracy=float(passed),
            baseline_top1_accuracy=0.0,
            regression_count=int(not passed),
            new_false_takeover_count=0,
            gate_passed=passed,
        ),
        created_by="quality-user",
        created_at=created_at,
        completed_at=created_at,
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


def _service(
    entries: list[SkillCatalogEntry],
    *,
    runs: dict[str, list[SkillEvalRun]],
    releases: dict[str, list[SkillRelease]],
) -> SkillWorkbenchService:
    return SkillWorkbenchService(
        version_service=_VersionCatalogService(entries),
        governance_service=_GovernanceView(runs=runs, releases=releases),
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
