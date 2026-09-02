from typing import Protocol

from src.domain.skill.governance_models import (
    SkillEvalBenchmark,
    SkillEvalCase,
    SkillEvalDatasetVersion,
    SkillEvalRun,
    SkillEvalSuite,
    SkillEvalTask,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
)


class SkillGovernanceConflictError(ValueError):
    """治理对象 revision、状态或唯一性发生冲突。"""


class SkillGovernanceNotFoundError(LookupError):
    """治理对象不存在。"""


class SkillGovernanceStorage(Protocol):
    def save_suite(self, suite: SkillEvalSuite) -> SkillEvalSuite: ...

    def get_suite(self, suite_id: str) -> SkillEvalSuite | None: ...

    def list_suites(
        self,
        *,
        skill_id: str | None = None,
        include_inactive: bool = True,
    ) -> list[SkillEvalSuite]: ...

    def update_suite(
        self,
        suite: SkillEvalSuite,
        *,
        expected_revision: int,
    ) -> SkillEvalSuite: ...

    def delete_suite(self, suite_id: str) -> bool: ...

    def count_cases(self, suite_id: str) -> int: ...

    def save_task(self, task: SkillEvalTask) -> SkillEvalTask: ...

    def get_task(self, task_id: str) -> SkillEvalTask | None: ...

    def list_tasks(
        self,
        suite_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[SkillEvalTask]: ...

    def update_task(
        self,
        task: SkillEvalTask,
        *,
        expected_revision: int,
    ) -> SkillEvalTask: ...

    def save_dataset_version(
        self,
        version: SkillEvalDatasetVersion,
    ) -> SkillEvalDatasetVersion: ...

    def get_dataset_version(
        self,
        dataset_version_id: str,
    ) -> SkillEvalDatasetVersion | None: ...

    def list_dataset_versions(
        self,
        suite_id: str,
    ) -> list[SkillEvalDatasetVersion]: ...

    def save_benchmark(self, benchmark: SkillEvalBenchmark) -> SkillEvalBenchmark: ...

    def get_benchmark(self, benchmark_id: str) -> SkillEvalBenchmark | None: ...

    def list_benchmarks(
        self,
        skill_id: str | None = None,
    ) -> list[SkillEvalBenchmark]: ...

    def next_suite_version(self) -> int: ...

    def current_suite_version(self) -> int: ...

    def save_case_with_new_suite_version(
        self, case: SkillEvalCase
    ) -> SkillEvalCase: ...

    def snapshot_enabled_cases(self) -> tuple[int, list[SkillEvalCase]]: ...

    def save_case(self, case: SkillEvalCase) -> SkillEvalCase: ...

    def get_case(self, case_id: str) -> SkillEvalCase | None: ...

    def delete_case(self, case_id: str) -> bool: ...

    def list_cases(
        self,
        *,
        suite_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillEvalCase]: ...

    def save_run(self, run: SkillEvalRun) -> SkillEvalRun: ...

    def get_run(self, skill_id: str, run_id: str) -> SkillEvalRun | None: ...

    def list_runs(self, skill_id: str | None = None) -> list[SkillEvalRun]: ...

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
        self,
        release_id: str,
        *,
        expected_revision: int,
        expected_suite_version: int | None = None,
    ) -> SkillRelease: ...

    def approve_release(
        self,
        release: SkillRelease,
        approval: SkillReleaseApproval,
        *,
        expected_revision: int,
    ) -> SkillRelease: ...

    def save_approval(
        self, approval: SkillReleaseApproval
    ) -> SkillReleaseApproval: ...

    def get_approval(self, release_id: str) -> SkillReleaseApproval | None: ...
