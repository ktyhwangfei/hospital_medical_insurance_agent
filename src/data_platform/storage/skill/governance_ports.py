from typing import Protocol

from src.domain.skill.governance_models import (
    SkillEvalCase,
    SkillEvalRun,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
)


class SkillGovernanceConflictError(ValueError):
    """治理对象 revision、状态或唯一性发生冲突。"""


class SkillGovernanceNotFoundError(LookupError):
    """治理对象不存在。"""


class SkillGovernanceStorage(Protocol):
    def save_case(self, case: SkillEvalCase) -> SkillEvalCase: ...

    def get_case(self, case_id: str) -> SkillEvalCase | None: ...

    def list_cases(self, *, enabled_only: bool = False) -> list[SkillEvalCase]: ...

    def save_run(self, run: SkillEvalRun) -> SkillEvalRun: ...

    def get_run(self, skill_id: str, run_id: str) -> SkillEvalRun | None: ...

    def list_runs(self, skill_id: str) -> list[SkillEvalRun]: ...

    def save_release(self, release: SkillRelease) -> SkillRelease: ...

    def get_release(self, release_id: str) -> SkillRelease | None: ...

    def list_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str | None = None,
    ) -> list[SkillRelease]: ...

    def list_active_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str,
    ) -> list[SkillRelease]: ...

    def update_release(
        self, release: SkillRelease, *, expected_revision: int
    ) -> SkillRelease: ...

    def activate_release(
        self, release_id: str, *, expected_revision: int
    ) -> SkillRelease: ...

    def save_approval(
        self, approval: SkillReleaseApproval
    ) -> SkillReleaseApproval: ...

    def get_approval(self, release_id: str) -> SkillReleaseApproval | None: ...
