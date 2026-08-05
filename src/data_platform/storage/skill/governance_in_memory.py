"""开发与测试使用的 Skill 治理内存存储。"""

from datetime import datetime, timezone

from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
    SkillGovernanceNotFoundError,
)
from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillEvalRun,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)


class InMemorySkillGovernanceStorage:
    def __init__(self) -> None:
        self._cases: dict[str, SkillEvalCase] = {}
        self._runs: dict[str, SkillEvalRun] = {}
        self._releases: dict[str, SkillRelease] = {}
        self._approvals: dict[str, SkillReleaseApproval] = {}

    @staticmethod
    def _copy[T](value: T) -> T:
        return value.model_copy(deep=True)  # type: ignore[attr-defined, no-any-return]

    def save_case(self, case: SkillEvalCase) -> SkillEvalCase:
        existing = self._cases.get(case.case_id)
        if existing is not None and case.suite_version <= existing.suite_version:
            raise SkillGovernanceConflictError("评测用例 suite_version 必须递增")
        stored = self._copy(case)
        self._cases[case.case_id] = stored
        return self._copy(stored)

    def get_case(self, case_id: str) -> SkillEvalCase | None:
        case = self._cases.get(case_id)
        return None if case is None else self._copy(case)

    def list_cases(self, *, enabled_only: bool = False) -> list[SkillEvalCase]:
        cases = [
            self._copy(case)
            for case in self._cases.values()
            if not enabled_only or case.enabled
        ]
        return sorted(cases, key=lambda item: (item.suite_version, item.case_id))

    def save_run(self, run: SkillEvalRun) -> SkillEvalRun:
        if run.run_id in self._runs:
            raise SkillGovernanceConflictError(f"评测运行已存在: {run.run_id}")
        stored = self._copy(run)
        self._runs[run.run_id] = stored
        return self._copy(stored)

    def get_run(self, skill_id: str, run_id: str) -> SkillEvalRun | None:
        run = self._runs.get(run_id)
        if run is None or run.skill_id != skill_id:
            return None
        return self._copy(run)

    def list_runs(self, skill_id: str) -> list[SkillEvalRun]:
        runs = [
            self._copy(run)
            for run in self._runs.values()
            if run.skill_id == skill_id
        ]
        return sorted(runs, key=lambda item: item.created_at, reverse=True)

    def save_release(self, release: SkillRelease) -> SkillRelease:
        if release.release_id in self._releases:
            raise SkillGovernanceConflictError(f"发布已存在: {release.release_id}")
        if release.status == SkillReleaseStatus.ACTIVE and self.list_active_releases(
            release.skill_id, release.environment
        ):
            raise SkillGovernanceConflictError("同一 Skill 和环境只能有一个 active release")
        stored = self._copy(release)
        self._releases[release.release_id] = stored
        return self._copy(stored)

    def get_release(self, release_id: str) -> SkillRelease | None:
        release = self._releases.get(release_id)
        return None if release is None else self._copy(release)

    def list_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str | None = None,
    ) -> list[SkillRelease]:
        normalized_environment = None if environment is None else str(environment)
        releases = [
            self._copy(release)
            for release in self._releases.values()
            if release.skill_id == skill_id
            and (
                normalized_environment is None
                or release.environment.value == normalized_environment
            )
        ]
        return sorted(releases, key=lambda item: item.created_at, reverse=True)

    def list_active_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str,
    ) -> list[SkillRelease]:
        return [
            release
            for release in self.list_releases(skill_id, environment)
            if release.status == SkillReleaseStatus.ACTIVE
        ]

    def update_release(
        self, release: SkillRelease, *, expected_revision: int
    ) -> SkillRelease:
        current = self._releases.get(release.release_id)
        if current is None:
            raise SkillGovernanceNotFoundError(f"发布不存在: {release.release_id}")
        if current.revision != expected_revision:
            raise SkillGovernanceConflictError("发布 revision 已变化")
        if release.revision != expected_revision + 1:
            raise SkillGovernanceConflictError("新 revision 必须递增 1")
        stored = self._copy(release)
        self._releases[release.release_id] = stored
        return self._copy(stored)

    def activate_release(
        self, release_id: str, *, expected_revision: int
    ) -> SkillRelease:
        candidate = self._releases.get(release_id)
        if candidate is None:
            raise SkillGovernanceNotFoundError(f"发布不存在: {release_id}")
        if candidate.revision != expected_revision:
            raise SkillGovernanceConflictError("发布 revision 已变化")
        if candidate.status != SkillReleaseStatus.APPROVED:
            raise SkillGovernanceConflictError("只有 approved release 可以激活")

        now = datetime.now(timezone.utc)
        active_ids = [
            release.release_id
            for release in self._releases.values()
            if release.skill_id == candidate.skill_id
            and release.environment == candidate.environment
            and release.status == SkillReleaseStatus.ACTIVE
        ]
        for active_id in active_ids:
            current = self._releases[active_id]
            self._releases[active_id] = current.model_copy(
                update={
                    "status": SkillReleaseStatus.RETIRED,
                    "revision": current.revision + 1,
                    "retired_at": now,
                },
                deep=True,
            )
        activated = candidate.model_copy(
            update={
                "status": SkillReleaseStatus.ACTIVE,
                "revision": candidate.revision + 1,
                "rollout_percent": 100,
                "activated_at": now,
            },
            deep=True,
        )
        self._releases[release_id] = activated
        return self._copy(activated)

    def save_approval(
        self, approval: SkillReleaseApproval
    ) -> SkillReleaseApproval:
        if approval.release_id in self._approvals:
            raise SkillGovernanceConflictError("该发布已经存在审批证据")
        stored = self._copy(approval)
        self._approvals[approval.release_id] = stored
        return self._copy(stored)

    def get_approval(self, release_id: str) -> SkillReleaseApproval | None:
        approval = self._approvals.get(release_id)
        return None if approval is None else self._copy(approval)
