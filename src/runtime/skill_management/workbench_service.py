"""Skill 治理工作台的只读聚合服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from src.domain.skill.governance_models import (
    SkillEvalRun,
    SkillEvalRunStatus,
    SkillRelease,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)
from src.domain.skill.version_models import SkillValidationStatus, SkillVersion
from src.runtime.skill_management.version_service import SkillCatalogPage


class SkillGovernanceStatus(StrEnum):
    """工作台用于排序和筛选的治理状态。"""

    GATE_FAILED = "gate_failed"
    PENDING_APPROVAL = "pending_approval"
    NEEDS_EVALUATION = "needs_evaluation"
    ARTIFACT_CHANGED = "artifact_changed"
    HEALTHY = "healthy"


class SkillWorkbenchSummary(BaseModel):
    """工作台顶部的可操作状态摘要。"""

    model_config = ConfigDict(frozen=True)

    total: int
    healthy: int
    needs_evaluation: int
    pending_approval: int
    test_active: int
    updated_at: datetime


class SkillWorkbenchItem(BaseModel):
    """Skill 目录中的治理状态投影。"""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    skill_name: str
    business_action: str
    business_object: str
    semantic_version: str
    artifact_status: str
    validation_status: str
    latest_eval_status: str | None = None
    test_release_status: str | None = None
    test_active_version: str | None = None
    governance_status: SkillGovernanceStatus
    attention_reason: str | None = None


class SkillWorkbenchPage(BaseModel):
    """Skill 治理工作台分页结果。"""

    model_config = ConfigDict(frozen=True)

    summary: SkillWorkbenchSummary
    items: list[SkillWorkbenchItem]
    total: int
    page: int
    page_size: int


class _VersionCatalogView(Protocol):
    def list_catalog(
        self,
        *,
        page: int,
        page_size: int,
        business_action: str = "",
        business_object: str = "",
        artifact_status: str = "",
        query: str = "",
    ) -> SkillCatalogPage: ...

    def get_version(self, skill_id: str, version_id: str) -> SkillVersion: ...


class _GovernanceView(Protocol):
    def list_eval_runs(self, skill_id: str) -> list[SkillEvalRun]: ...

    def list_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str | None = None,
    ) -> list[SkillRelease]: ...


_STATUS_ORDER = {
    SkillGovernanceStatus.GATE_FAILED: 0,
    SkillGovernanceStatus.PENDING_APPROVAL: 1,
    SkillGovernanceStatus.NEEDS_EVALUATION: 2,
    SkillGovernanceStatus.ARTIFACT_CHANGED: 3,
    SkillGovernanceStatus.HEALTHY: 4,
}


def _resolve_status(
    *,
    artifact_status: str,
    latest_eval_status: SkillEvalRunStatus | str | None,
    latest_release_status: SkillReleaseStatus | str | None,
) -> tuple[SkillGovernanceStatus, str | None]:
    """按照固定优先级合成一个目录治理状态。"""

    if latest_eval_status in (SkillEvalRunStatus.FAILED, SkillEvalRunStatus.ERROR):
        return SkillGovernanceStatus.GATE_FAILED, "latest_evaluation_failed"
    if latest_release_status == SkillReleaseStatus.APPROVAL_PENDING:
        return SkillGovernanceStatus.PENDING_APPROVAL, "approval_required"
    if latest_eval_status != SkillEvalRunStatus.PASSED:
        return SkillGovernanceStatus.NEEDS_EVALUATION, "passed_evaluation_required"
    if artifact_status != "registered":
        return SkillGovernanceStatus.ARTIFACT_CHANGED, "artifact_not_registered"
    return SkillGovernanceStatus.HEALTHY, None


class SkillWorkbenchService:
    """组合版本、评测与 test release，生成页面只读模型。"""

    def __init__(
        self,
        version_service: _VersionCatalogView,
        governance_service: _GovernanceView,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._version_service = version_service
        self._governance_service = governance_service
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _active_semantic_version(
        self,
        skill_id: str,
        active_release: SkillRelease | None,
    ) -> str | None:
        if active_release is None:
            return None
        try:
            return self._version_service.get_version(
                skill_id,
                active_release.version_id,
            ).semantic_version
        except (LookupError, ValueError):
            return active_release.version_id

    def _build_item(self, entry) -> tuple[SkillWorkbenchItem, bool]:
        registered_version = entry.registered_version
        version_id = registered_version.version_id if registered_version is not None else None
        runs = [
            run
            for run in self._governance_service.list_eval_runs(entry.skill_id)
            if version_id is not None and run.version_id == version_id
        ]
        latest_run = max(runs, key=lambda run: run.created_at, default=None)

        releases = self._governance_service.list_releases(
            entry.skill_id,
            SkillReleaseEnvironment.TEST,
        )
        current_releases = [
            release
            for release in releases
            if release.status != SkillReleaseStatus.RETIRED
        ]
        latest_release = max(
            current_releases,
            key=lambda release: release.created_at,
            default=None,
        )
        active_release = max(
            (
                release
                for release in releases
                if release.status == SkillReleaseStatus.ACTIVE
            ),
            key=lambda release: release.activated_at or release.created_at,
            default=None,
        )
        latest_eval_status = latest_run.status if latest_run is not None else None
        latest_release_status = (
            latest_release.status if latest_release is not None else None
        )
        governance_status, attention_reason = _resolve_status(
            artifact_status=entry.artifact_status,
            latest_eval_status=latest_eval_status,
            latest_release_status=latest_release_status,
        )
        validation_status = (
            registered_version.validation_status
            if registered_version is not None
            else SkillValidationStatus.PENDING
        )
        return (
            SkillWorkbenchItem(
                skill_id=entry.skill_id,
                skill_name=entry.skill_name,
                business_action=entry.business_action,
                business_object=entry.business_object,
                semantic_version=entry.semantic_version,
                artifact_status=entry.artifact_status,
                validation_status=validation_status,
                latest_eval_status=latest_eval_status,
                test_release_status=latest_release_status,
                test_active_version=self._active_semantic_version(
                    entry.skill_id,
                    active_release,
                ),
                governance_status=governance_status,
                attention_reason=attention_reason,
            ),
            active_release is not None,
        )

    def list_workbench(
        self,
        *,
        page: int,
        page_size: int,
        business_action: str = "",
        business_object: str = "",
        artifact_status: str = "",
        governance_status: SkillGovernanceStatus | str | None = None,
        query: str = "",
    ) -> SkillWorkbenchPage:
        catalog = self._version_service.list_catalog(
            page=1,
            page_size=10_000,
            business_action=business_action,
            business_object=business_object,
            artifact_status=artifact_status,
            query=query,
        )
        projected = [self._build_item(entry) for entry in catalog.items]
        all_items = [item for item, _ in projected]
        requested_status = (
            SkillGovernanceStatus(governance_status)
            if governance_status
            else None
        )
        filtered_items = [
            item
            for item in all_items
            if requested_status is None or item.governance_status == requested_status
        ]
        filtered_items.sort(
            key=lambda item: (
                _STATUS_ORDER[item.governance_status],
                item.skill_name,
                item.skill_id,
            )
        )
        total = len(filtered_items)
        start = (page - 1) * page_size
        return SkillWorkbenchPage(
            summary=SkillWorkbenchSummary(
                total=len(all_items),
                healthy=sum(
                    item.governance_status == SkillGovernanceStatus.HEALTHY
                    for item in all_items
                ),
                needs_evaluation=sum(
                    item.governance_status == SkillGovernanceStatus.NEEDS_EVALUATION
                    for item in all_items
                ),
                pending_approval=sum(
                    item.governance_status == SkillGovernanceStatus.PENDING_APPROVAL
                    for item in all_items
                ),
                test_active=sum(active for _, active in projected),
                updated_at=self._now(),
            ),
            items=filtered_items[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )
