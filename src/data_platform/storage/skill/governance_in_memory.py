"""开发与测试使用的 Skill 治理内存存储。"""

from datetime import datetime, timezone
from threading import RLock

from src.data_platform.storage.skill.governance_ports import (
    SkillGovernanceConflictError,
    SkillGovernanceNotFoundError,
)
from src.domain.skill.governance_models import (
    DEFAULT_ROUTING_SUITE_ID,
    SkillEvalBenchmark,
    SkillEvalCase,
    SkillEvalDatasetVersion,
    SkillEvalRun,
    SkillEvalSuite,
    SkillEvalSuiteScope,
    SkillEvalSuiteStatus,
    SkillEvalTask,
    SkillRelease,
    SkillReleaseApproval,
    SkillReleaseEnvironment,
    SkillReleaseStatus,
)


class InMemorySkillGovernanceStorage:
    def __init__(self) -> None:
        default_suite = SkillEvalSuite(
            suite_id=DEFAULT_ROUTING_SUITE_ID,
            name="平台默认路由测评集",
            scope=SkillEvalSuiteScope.PLATFORM,
            purpose="兼容历史路由评测与发布门禁",
            created_by="system",
            updated_by="system",
        )
        self._suites: dict[str, SkillEvalSuite] = {
            default_suite.suite_id: default_suite,
        }
        self._cases: dict[str, SkillEvalCase] = {}
        self._tasks: dict[str, SkillEvalTask] = {}
        self._dataset_versions: dict[str, SkillEvalDatasetVersion] = {}
        self._benchmarks: dict[str, SkillEvalBenchmark] = {}
        self._runs: dict[str, SkillEvalRun] = {}
        self._releases: dict[str, SkillRelease] = {}
        self._approvals: dict[str, SkillReleaseApproval] = {}
        self._suite_version = 0
        self._suite_version_lock = RLock()

    @staticmethod
    def _copy[T](value: T) -> T:
        return value.model_copy(deep=True)  # type: ignore[attr-defined, no-any-return]

    def next_suite_version(self) -> int:
        with self._suite_version_lock:
            self._suite_version = max(
                self._suite_version,
                max((case.suite_version for case in self._cases.values()), default=0),
            ) + 1
            return self._suite_version

    def save_suite(self, suite: SkillEvalSuite) -> SkillEvalSuite:
        if suite.suite_id in self._suites:
            raise SkillGovernanceConflictError(f"测评集已存在: {suite.suite_id}")
        stored = self._copy(suite)
        self._suites[stored.suite_id] = stored
        return self._copy(stored)

    def get_suite(self, suite_id: str) -> SkillEvalSuite | None:
        suite = self._suites.get(suite_id)
        return None if suite is None else self._copy(suite)

    def list_suites(
        self,
        *,
        skill_id: str | None = None,
        include_inactive: bool = True,
    ) -> list[SkillEvalSuite]:
        suites = [
            self._copy(suite)
            for suite in self._suites.values()
            if (skill_id is None or suite.skill_id in {None, skill_id})
            and (include_inactive or suite.status == SkillEvalSuiteStatus.ACTIVE)
        ]
        return sorted(suites, key=lambda item: (item.scope.value, item.name, item.suite_id))

    def update_suite(
        self,
        suite: SkillEvalSuite,
        *,
        expected_revision: int,
    ) -> SkillEvalSuite:
        current = self._suites.get(suite.suite_id)
        if current is None:
            raise SkillGovernanceNotFoundError(f"测评集不存在: {suite.suite_id}")
        if current.revision != expected_revision:
            raise SkillGovernanceConflictError("测评集 revision 已变化")
        if suite.revision != expected_revision + 1:
            raise SkillGovernanceConflictError("新 revision 必须递增 1")
        stored = self._copy(suite)
        self._suites[stored.suite_id] = stored
        return self._copy(stored)

    def delete_suite(self, suite_id: str) -> bool:
        return self._suites.pop(suite_id, None) is not None

    def count_cases(self, suite_id: str) -> int:
        return sum(case.suite_id == suite_id for case in self._cases.values())

    def save_task(self, task: SkillEvalTask) -> SkillEvalTask:
        if task.suite_id not in self._suites:
            raise SkillGovernanceConflictError(f"测评集不存在: {task.suite_id}")
        if task.task_id in self._tasks:
            raise SkillGovernanceConflictError(f"评测任务已存在: {task.task_id}")
        stored = self._copy(task)
        self._tasks[stored.task_id] = stored
        return self._copy(stored)

    def get_task(self, task_id: str) -> SkillEvalTask | None:
        task = self._tasks.get(task_id)
        return None if task is None else self._copy(task)

    def list_tasks(
        self,
        suite_id: str,
        *,
        enabled_only: bool = False,
    ) -> list[SkillEvalTask]:
        tasks = [
            self._copy(task)
            for task in self._tasks.values()
            if task.suite_id == suite_id and (not enabled_only or task.enabled)
        ]
        return sorted(tasks, key=lambda item: item.task_id)

    def update_task(
        self,
        task: SkillEvalTask,
        *,
        expected_revision: int,
    ) -> SkillEvalTask:
        current = self._tasks.get(task.task_id)
        if current is None:
            raise SkillGovernanceNotFoundError(f"评测任务不存在: {task.task_id}")
        if current.revision != expected_revision:
            raise SkillGovernanceConflictError("评测任务 revision 已变化")
        if task.revision != expected_revision + 1:
            raise SkillGovernanceConflictError("新 revision 必须递增 1")
        if task.suite_id != current.suite_id:
            raise SkillGovernanceConflictError("评测任务不能移动到其他测评集")
        stored = self._copy(task)
        self._tasks[stored.task_id] = stored
        return self._copy(stored)

    def save_dataset_version(
        self,
        version: SkillEvalDatasetVersion,
    ) -> SkillEvalDatasetVersion:
        if version.suite_id not in self._suites:
            raise SkillGovernanceConflictError(f"测评集不存在: {version.suite_id}")
        duplicate = next(
            (
                current
                for current in self._dataset_versions.values()
                if current.dataset_version_id == version.dataset_version_id
                or (
                    current.suite_id == version.suite_id
                    and (
                        current.version_number == version.version_number
                        or current.content_hash == version.content_hash
                    )
                )
            ),
            None,
        )
        if duplicate is not None:
            raise SkillGovernanceConflictError(
                f"数据集版本已存在或版本内容重复: {version.dataset_version_id}"
            )
        stored = self._copy(version)
        self._dataset_versions[stored.dataset_version_id] = stored
        return self._copy(stored)

    def get_dataset_version(
        self,
        dataset_version_id: str,
    ) -> SkillEvalDatasetVersion | None:
        version = self._dataset_versions.get(dataset_version_id)
        return None if version is None else self._copy(version)

    def list_dataset_versions(
        self,
        suite_id: str,
    ) -> list[SkillEvalDatasetVersion]:
        versions = [
            self._copy(version)
            for version in self._dataset_versions.values()
            if version.suite_id == suite_id
        ]
        return sorted(versions, key=lambda item: item.version_number, reverse=True)

    def save_benchmark(self, benchmark: SkillEvalBenchmark) -> SkillEvalBenchmark:
        if benchmark.dataset_version_id not in self._dataset_versions:
            raise SkillGovernanceConflictError(
                f"数据集版本不存在: {benchmark.dataset_version_id}"
            )
        if benchmark.benchmark_id in self._benchmarks:
            raise SkillGovernanceConflictError(
                f"Benchmark 已存在: {benchmark.benchmark_id}"
            )
        stored = self._copy(benchmark)
        self._benchmarks[stored.benchmark_id] = stored
        return self._copy(stored)

    def get_benchmark(self, benchmark_id: str) -> SkillEvalBenchmark | None:
        benchmark = self._benchmarks.get(benchmark_id)
        return None if benchmark is None else self._copy(benchmark)

    def list_benchmarks(
        self,
        skill_id: str | None = None,
    ) -> list[SkillEvalBenchmark]:
        benchmarks = [
            self._copy(benchmark)
            for benchmark in self._benchmarks.values()
            if skill_id is None or benchmark.skill_id == skill_id
        ]
        return sorted(benchmarks, key=lambda item: item.created_at, reverse=True)

    def current_suite_version(self) -> int:
        with self._suite_version_lock:
            return max(
                self._suite_version,
                max((case.suite_version for case in self._cases.values()), default=0),
            )

    def save_case_with_new_suite_version(
        self, case: SkillEvalCase
    ) -> SkillEvalCase:
        with self._suite_version_lock:
            suite_version = self.next_suite_version()
            versioned_case = case.model_copy(
                update={"suite_version": suite_version}, deep=True
            )
            return self.save_case(versioned_case)

    def snapshot_enabled_cases(self) -> tuple[int, list[SkillEvalCase]]:
        with self._suite_version_lock:
            return self.current_suite_version(), self.list_cases(enabled_only=True)

    def save_case(self, case: SkillEvalCase) -> SkillEvalCase:
        existing = self._cases.get(case.case_id)
        if existing is not None and case.suite_version <= existing.suite_version:
            raise SkillGovernanceConflictError("评测用例 suite_version 必须递增")
        stored = self._copy(case)
        self._cases[case.case_id] = stored
        with self._suite_version_lock:
            self._suite_version = max(self._suite_version, case.suite_version)
        return self._copy(stored)

    def get_case(self, case_id: str) -> SkillEvalCase | None:
        case = self._cases.get(case_id)
        return None if case is None else self._copy(case)

    def delete_case(self, case_id: str) -> bool:
        with self._suite_version_lock:
            return self._cases.pop(case_id, None) is not None

    def list_cases(
        self,
        *,
        suite_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[SkillEvalCase]:
        cases = [
            self._copy(case)
            for case in self._cases.values()
            if (suite_id is None or case.suite_id == suite_id)
            and (not enabled_only or case.enabled)
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

    def list_runs(self, skill_id: str | None = None) -> list[SkillEvalRun]:
        runs = [
            self._copy(run)
            for run in self._runs.values()
            if skill_id is None or run.skill_id == skill_id
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
        self,
        release_id: str,
        *,
        expected_revision: int,
        expected_suite_version: int | None = None,
    ) -> SkillRelease:
        with self._suite_version_lock:
            if (
                expected_suite_version is not None
                and self.current_suite_version() != expected_suite_version
            ):
                raise SkillGovernanceConflictError("评测集版本已变化")
            return self._activate_release_unlocked(
                release_id, expected_revision=expected_revision
            )

    def _activate_release_unlocked(
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
        if len(active_ids) > 1:
            raise SkillGovernanceConflictError(
                "同一 Skill 和环境存在多个 active release"
            )
        active_id = active_ids[0] if active_ids else None
        if active_id != candidate.baseline_release_id:
            raise SkillGovernanceConflictError("活动基线已变化")
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

    def approve_release(
        self,
        release: SkillRelease,
        approval: SkillReleaseApproval,
        *,
        expected_revision: int,
    ) -> SkillRelease:
        current = self._releases.get(release.release_id)
        if current is None:
            raise SkillGovernanceNotFoundError(f"发布不存在: {release.release_id}")
        if current.revision != expected_revision:
            raise SkillGovernanceConflictError("发布 revision 已变化")
        if release.revision != expected_revision + 1:
            raise SkillGovernanceConflictError("新 revision 必须递增 1")
        if release.status != SkillReleaseStatus.APPROVED:
            raise SkillGovernanceConflictError("审批事务的目标状态必须是 approved")
        if approval.release_id != release.release_id:
            raise SkillGovernanceConflictError("审批证据与发布不匹配")
        if release.release_id in self._approvals:
            raise SkillGovernanceConflictError("该发布已经存在审批证据")
        stored_release = self._copy(release)
        stored_approval = self._copy(approval)
        self._releases[release.release_id] = stored_release
        self._approvals[release.release_id] = stored_approval
        return self._copy(stored_release)

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
