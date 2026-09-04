"""Skill 治理工作台的只读聚合服务。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.domain.skill.draft_models import (
    MetricInputSpec,
    SkillDraft,
    SkillDraftStatus,
    SkillExecutionContract,
)
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


class SkillGovernanceStage(StrEnum):
    EVALUATE = "evaluate"
    DIAGNOSE = "diagnose"
    MODIFY = "modify"
    REVIEW = "review"
    RELEASE = "release"
    HEALTHY = "healthy"


class SkillGovernancePriority(StrEnum):
    BLOCKED = "blocked"
    HIGH = "high"
    NORMAL = "normal"


class SkillNextAction(StrEnum):
    REGISTER_VERSION = "register_version"
    RUN_EVALUATION = "run_evaluation"
    CREATE_FIX_DRAFT = "create_fix_draft"
    CONTINUE_DRAFT = "continue_draft"
    MATERIALIZE_DRAFT = "materialize_draft"
    CREATE_CANDIDATE = "create_candidate"
    REQUEST_APPROVAL = "request_approval"
    REVIEW_APPROVAL = "review_approval"
    ACTIVATE_TEST_SHADOW = "activate_test_shadow"
    VIEW_EVIDENCE = "view_evidence"


class SkillWorkbenchSummary(BaseModel):
    """工作台顶部的可操作状态摘要。"""

    model_config = ConfigDict(frozen=True)

    total: int
    healthy: int
    needs_evaluation: int
    pending_approval: int
    test_active: int
    draft_only: int = 0
    updated_at: datetime


class SkillWorkbenchItem(BaseModel):
    """Skill 目录中的治理状态投影。"""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    skill_name: str
    business_action: str
    business_object: str
    description: str = ""
    execution_contract: SkillExecutionContract = Field(
        default_factory=SkillExecutionContract
    )
    semantic_version: str
    artifact_status: str
    validation_status: str
    latest_eval_status: str | None = None
    test_release_status: str | None = None
    test_active_version: str | None = None
    governance_status: SkillGovernanceStatus
    attention_reason: str | None = None
    current_stage: SkillGovernanceStage = SkillGovernanceStage.EVALUATE
    priority: SkillGovernancePriority = SkillGovernancePriority.NORMAL
    latest_eval_run_id: str | None = None
    candidate_version: str | None = None
    baseline_version: str | None = None
    regression_count: int = 0
    required_failure_count: int = 0
    linked_draft_id: str | None = None
    linked_draft_status: str | None = None
    waiting_since: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    next_action: SkillNextAction = SkillNextAction.RUN_EVALUATION
    next_action_reason: str | None = None


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


class _DraftView(Protocol):
    def list_drafts(
        self,
        *,
        include_deleted: bool = False,
        skill_id: str | None = None,
        status: SkillDraftStatus | None = None,
    ) -> list[SkillDraft]: ...


_ACTION_ORDER = {
    SkillNextAction.CREATE_FIX_DRAFT: 0,
    SkillNextAction.CONTINUE_DRAFT: 0,
    SkillNextAction.MATERIALIZE_DRAFT: 0,
    SkillNextAction.REVIEW_APPROVAL: 1,
    SkillNextAction.ACTIVATE_TEST_SHADOW: 1,
    SkillNextAction.REQUEST_APPROVAL: 1,
    SkillNextAction.CREATE_CANDIDATE: 2,
    SkillNextAction.RUN_EVALUATION: 2,
    SkillNextAction.REGISTER_VERSION: 3,
    SkillNextAction.VIEW_EVIDENCE: 4,
}


def _fill_metric_aliases(contract: "SkillExecutionContract") -> "SkillExecutionContract":
    """alias 缺失时回填语义层中文名（前端展示用；英文编码只作回退）。

    只读 best-effort：语义层不可用/指标未注册时保持原样。
    """
    try:
        from src.semantic_layer.registry import get_semantic_registry
        reg = get_semantic_registry()

        def fill(metric: "MetricInputSpec") -> "MetricInputSpec":
            if metric.alias and metric.alias.strip():
                return metric
            m = reg.get_metric(metric.metric_code)
            if m is None or not (m.name or "").strip():
                return metric
            return metric.model_copy(update={"alias": m.name})

        return contract.model_copy(update={
            "common": contract.common.model_copy(update={
                "metric_inputs": [fill(m) for m in contract.common.metric_inputs],
            }),
            "profiles": [
                p.model_copy(update={
                    "metric_inputs": [fill(m) for m in (p.metric_inputs or [])],
                })
                for p in contract.profiles
            ],
        })
    except Exception:
        return contract


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
        draft_service: _DraftView | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._version_service = version_service
        self._governance_service = governance_service
        self._draft_service = draft_service
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _semantic_version(self, skill_id: str, version_id: str | None) -> str | None:
        if version_id is None:
            return None
        try:
            return self._version_service.get_version(
                skill_id,
                version_id,
            ).semantic_version
        except (LookupError, ValueError):
            return version_id

    def _active_semantic_version(
        self,
        skill_id: str,
        active_release: SkillRelease | None,
    ) -> str | None:
        if active_release is None:
            return None
        return self._semantic_version(skill_id, active_release.version_id)

    def _derive_workflow(
        self,
        *,
        artifact_status: str,
        registered_version: SkillVersion | None,
        latest_run: SkillEvalRun | None,
        latest_release: SkillRelease | None,
        linked_draft: SkillDraft | None,
    ) -> tuple[
        SkillGovernanceStage,
        SkillGovernancePriority,
        SkillNextAction,
        str | None,
        datetime,
    ]:
        now = self._now()
        evaluation_failed = latest_run is not None and (
            latest_run.status in (SkillEvalRunStatus.FAILED, SkillEvalRunStatus.ERROR)
            or latest_run.metrics.required_passed < latest_run.metrics.required_total
        )
        if evaluation_failed and linked_draft is not None:
            action = (
                SkillNextAction.CONTINUE_DRAFT
                if linked_draft.status == SkillDraftStatus.EDITING
                else SkillNextAction.MATERIALIZE_DRAFT
            )
            return (
                SkillGovernanceStage.MODIFY,
                SkillGovernancePriority.HIGH,
                action,
                "评测门禁未通过，已有修复草稿",
                linked_draft.updated_at,
            )
        if evaluation_failed:
            return (
                SkillGovernanceStage.DIAGNOSE,
                SkillGovernancePriority.BLOCKED,
                SkillNextAction.CREATE_FIX_DRAFT,
                "评测门禁未通过，需要先定位回归案例",
                latest_run.completed_at or latest_run.created_at,
            )

        release_status = latest_release.status if latest_release is not None else None
        if release_status == SkillReleaseStatus.APPROVAL_PENDING:
            return (
                SkillGovernanceStage.REVIEW,
                SkillGovernancePriority.HIGH,
                SkillNextAction.REVIEW_APPROVAL,
                "候选版本等待人工复审",
                latest_release.created_at,
            )
        if release_status == SkillReleaseStatus.APPROVED:
            return (
                SkillGovernanceStage.RELEASE,
                SkillGovernancePriority.HIGH,
                SkillNextAction.ACTIVATE_TEST_SHADOW,
                "人工复审已通过，等待激活 Test Shadow",
                latest_release.created_at,
            )
        if release_status == SkillReleaseStatus.CANDIDATE:
            return (
                SkillGovernanceStage.REVIEW,
                SkillGovernancePriority.HIGH,
                SkillNextAction.REQUEST_APPROVAL,
                "候选版本等待发起审批",
                latest_release.created_at,
            )
        if release_status == SkillReleaseStatus.ACTIVE:
            return (
                SkillGovernanceStage.HEALTHY,
                SkillGovernancePriority.NORMAL,
                SkillNextAction.VIEW_EVIDENCE,
                None,
                latest_release.activated_at or latest_release.created_at,
            )
        if latest_run is not None and latest_run.status == SkillEvalRunStatus.PASSED:
            return (
                SkillGovernanceStage.RELEASE,
                SkillGovernancePriority.HIGH,
                SkillNextAction.CREATE_CANDIDATE,
                "评测已通过，等待创建候选版本",
                latest_run.completed_at or latest_run.created_at,
            )
        if artifact_status != "registered":
            return (
                SkillGovernanceStage.MODIFY,
                SkillGovernancePriority.HIGH,
                SkillNextAction.REGISTER_VERSION,
                "当前制品尚未登记或已发生变更",
                registered_version.created_at if registered_version is not None else now,
            )
        return (
            SkillGovernanceStage.EVALUATE,
            SkillGovernancePriority.NORMAL,
            SkillNextAction.RUN_EVALUATION,
            "当前版本尚未完成评测",
            latest_run.created_at
            if latest_run is not None
            else registered_version.created_at
            if registered_version is not None
            else now,
        )

    def _build_item(
        self,
        entry,
        linked_draft: SkillDraft | None,
    ) -> tuple[SkillWorkbenchItem, bool]:
        registered_version = entry.registered_version
        legacy_version_id = (
            registered_version.version_id if registered_version is not None else None
        )
        workflow_version_id = (
            registered_version.version_id
            if registered_version is not None and entry.artifact_status == "registered"
            else None
        )
        legacy_runs = [
            run
            for run in self._governance_service.list_eval_runs(entry.skill_id)
            if legacy_version_id is not None and run.version_id == legacy_version_id
        ]
        legacy_latest_run = max(
            legacy_runs,
            key=lambda run: run.created_at,
            default=None,
        )
        latest_run = legacy_latest_run if workflow_version_id is not None else None

        releases = self._governance_service.list_releases(
            entry.skill_id,
            SkillReleaseEnvironment.TEST,
        )
        legacy_releases = [
            release
            for release in releases
            if release.status != SkillReleaseStatus.RETIRED
        ]
        legacy_latest_release = max(
            legacy_releases,
            key=lambda release: release.created_at,
            default=None,
        )
        current_releases = [
            release
            for release in releases
            if workflow_version_id is not None
            and release.version_id == workflow_version_id
            and release.status != SkillReleaseStatus.RETIRED
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
        legacy_eval_status = (
            legacy_latest_run.status if legacy_latest_run is not None else None
        )
        legacy_release_status = (
            legacy_latest_release.status if legacy_latest_release is not None else None
        )
        governance_status, attention_reason = _resolve_status(
            artifact_status=entry.artifact_status,
            latest_eval_status=legacy_eval_status,
            latest_release_status=legacy_release_status,
        )
        validation_status = (
            registered_version.validation_status
            if registered_version is not None
            else SkillValidationStatus.PENDING
        )
        current_stage, priority, next_action, next_action_reason, waiting_since = (
            self._derive_workflow(
                artifact_status=entry.artifact_status,
                registered_version=registered_version,
                latest_run=latest_run,
                latest_release=latest_release,
                linked_draft=linked_draft,
            )
        )
        metrics = latest_run.metrics if latest_run is not None else None
        return (
            SkillWorkbenchItem(
                skill_id=entry.skill_id,
                skill_name=entry.skill_name,
                business_action=entry.business_action,
                business_object=entry.business_object,
                description=entry.description,
                execution_contract=_fill_metric_aliases(entry.execution_contract),
                semantic_version=entry.semantic_version,
                artifact_status=entry.artifact_status,
                validation_status=validation_status,
                latest_eval_status=legacy_eval_status,
                test_release_status=legacy_release_status,
                test_active_version=self._active_semantic_version(
                    entry.skill_id,
                    active_release,
                ),
                governance_status=governance_status,
                attention_reason=attention_reason,
                current_stage=current_stage,
                priority=priority,
                latest_eval_run_id=(latest_run.run_id if latest_run is not None else None),
                candidate_version=(
                    registered_version.semantic_version
                    if registered_version is not None
                    else None
                ),
                baseline_version=(
                    latest_run.baseline_version_id
                    if latest_run is not None
                    else None
                ),
                regression_count=(metrics.regression_count if metrics is not None else 0),
                required_failure_count=(
                    max(0, metrics.required_total - metrics.required_passed)
                    if metrics is not None
                    else 0
                ),
                linked_draft_id=(
                    linked_draft.draft_id if linked_draft is not None else None
                ),
                linked_draft_status=(
                    linked_draft.status if linked_draft is not None else None
                ),
                waiting_since=waiting_since,
                next_action=next_action,
                next_action_reason=next_action_reason,
            ),
            active_release is not None,
        )

    def _build_draft_only_item(self, draft: SkillDraft) -> SkillWorkbenchItem:
        """从纯草稿（无物化制品）构造工作台投影项。

        纯草稿没有版本/评测/发布记录，governance_status 复用 ARTIFACT_CHANGED，
        current_stage 设为 MODIFY，next_action 按 draft 状态决定继续编辑或物化。
        execution_contract 从草稿 structured_config 解析，让概览页展示已配置的场景与指标。
        """
        bm = draft.structured_config.get("business_mounting", {}) or {}
        business_action = str(bm.get("business_action", "")) if isinstance(bm, dict) else ""
        business_object = str(bm.get("business_object", "")) if isinstance(bm, dict) else ""
        is_validated = draft.status == SkillDraftStatus.VALIDATED
        ec_data = draft.structured_config.get("execution_contract", {}) or {}
        try:
            execution_contract = SkillExecutionContract.model_validate(ec_data)
        except Exception:
            execution_contract = SkillExecutionContract()
        return SkillWorkbenchItem(
            skill_id=draft.skill_id,
            skill_name=draft.skill_name,
            business_action=business_action,
            business_object=business_object,
            description=str(draft.structured_config.get("basic", {}).get("description", "")),
            execution_contract=execution_contract,
            semantic_version="",
            artifact_status="unregistered",
            validation_status=SkillValidationStatus.PENDING,
            governance_status=SkillGovernanceStatus.ARTIFACT_CHANGED,
            attention_reason="draft_only",
            current_stage=SkillGovernanceStage.MODIFY,
            priority=SkillGovernancePriority.HIGH,
            next_action=(
                SkillNextAction.MATERIALIZE_DRAFT
                if is_validated
                else SkillNextAction.CONTINUE_DRAFT
            ),
            next_action_reason=(
                "草稿已校验，可物化为正式版本"
                if is_validated
                else "草稿编辑中，继续完善配置"
            ),
            linked_draft_id=draft.draft_id,
            linked_draft_status=draft.status,
            waiting_since=draft.updated_at,
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
        linked_drafts: dict[str, SkillDraft] = {}
        if self._draft_service is not None:
            for draft in self._draft_service.list_drafts():
                current = linked_drafts.get(draft.skill_id)
                if draft.status in (
                    SkillDraftStatus.EDITING,
                    SkillDraftStatus.VALIDATED,
                ) and (current is None or draft.updated_at > current.updated_at):
                    linked_drafts[draft.skill_id] = draft
        projected = [
            self._build_item(entry, linked_drafts.get(entry.skill_id))
            for entry in catalog.items
        ]
        all_items = [item for item, _ in projected]
        # 纯草稿：有草稿但 catalog 中无对应制品的 skill_id，补充为工作台项
        catalog_skill_ids = {entry.skill_id for entry in catalog.items}
        draft_only_items: list[SkillWorkbenchItem] = []
        if self._draft_service is not None:
            for skill_id, draft in linked_drafts.items():
                if skill_id not in catalog_skill_ids:
                    draft_only_items.append(self._build_draft_only_item(draft))
        all_items.extend(draft_only_items)
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
                _ACTION_ORDER[item.next_action],
                0 if item.required_failure_count > 0 else 1,
                item.waiting_since,
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
                draft_only=len(draft_only_items),
                updated_at=self._now(),
            ),
            items=filtered_items[start : start + page_size],
            total=total,
            page=page,
            page_size=page_size,
        )
