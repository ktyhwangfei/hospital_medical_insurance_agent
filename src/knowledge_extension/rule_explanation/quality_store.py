"""政策知识质量存储端口与内存实现。"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol

from src.knowledge_extension.rule_explanation.quality_models import (
    KnowledgeRelease,
    PolicyQATestCase,
    QualityCaseResult,
    QualityRun,
    utc_now,
)


DEFAULT_TEST_CASES: list[PolicyQATestCase] = [
    PolicyQATestCase(
        case_id="default_policy_inpatient_deductible",
        name="职工医保住院起付线",
        query="职工基本医疗保险住院起付线是多少",
        mode="semantic",
        required=True,
        case_set_version=0,
    ),
    PolicyQATestCase(
        case_id="default_policy_outpatient_ratio",
        name="职工医保门诊报销比例",
        query="职工基本医疗保险门诊医疗费用的报销比例是多少",
        mode="semantic",
        required=True,
        case_set_version=0,
    ),
    PolicyQATestCase(
        case_id="default_policy_resident_inpatient",
        name="城乡居民医保住院报销",
        query="城乡居民基本医疗保险住院费用的报销比例是多少",
        mode="semantic",
        required=True,
        case_set_version=0,
    ),
    PolicyQATestCase(
        case_id="default_policy_serious_illness",
        name="大病保险报销",
        query="大病医疗保险的报销范围与报销比例是什么",
        mode="semantic",
        required=True,
        case_set_version=0,
    ),
    PolicyQATestCase(
        case_id="default_policy_drug_catalog",
        name="医保目录药品报销",
        query="基本医疗保险药品目录内药品的报销规定是什么",
        mode="semantic",
        required=True,
        case_set_version=0,
    ),
]


class PolicyQualityStore(Protocol):
    def ensure_default_test_cases(self) -> None: ...
    def save_test_case(self, case: PolicyQATestCase) -> PolicyQATestCase: ...
    def list_test_cases(self, active_only: bool = True) -> list[PolicyQATestCase]: ...
    def current_case_set_version(self) -> int: ...
    def create_release(self, release: KnowledgeRelease) -> KnowledgeRelease: ...
    def save_release(self, release: KnowledgeRelease) -> KnowledgeRelease: ...
    def get_release(self, release_id: str) -> KnowledgeRelease | None: ...
    def list_releases(self) -> list[KnowledgeRelease]: ...
    def get_active_release(self) -> KnowledgeRelease | None: ...
    def claim_quality_run(self, release_id: str, run_id: str) -> str: ...
    def reclaim_stale_runs(self, release_id: str, stale_after_seconds: int = 1800) -> int: ...
    def complete_quality_run(
        self,
        release_id: str,
        run_id: str,
        *,
        status: str,
        quality_score: float,
        consistency_score: float,
    ) -> KnowledgeRelease: ...
    def restore_quality_run(
        self, release_id: str, run_id: str, original_status: str
    ) -> KnowledgeRelease: ...
    def promote_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease: ...
    def rollback_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease: ...
    def save_run(self, run: QualityRun) -> QualityRun: ...
    def get_run(self, run_id: str) -> QualityRun | None: ...
    def get_latest_run(self, release_id: str) -> QualityRun | None: ...
    def save_case_results(self, results: list[QualityCaseResult]) -> None: ...
    def list_case_results(self, run_id: str) -> list[QualityCaseResult]: ...


@dataclass
class InMemoryPolicyQualityStore:
    test_cases: dict[str, PolicyQATestCase] = field(default_factory=dict)
    releases: dict[str, KnowledgeRelease] = field(default_factory=dict)
    runs: dict[str, QualityRun] = field(default_factory=dict)
    _run_sequences: dict[str, int] = field(default_factory=dict, init=False)
    _next_run_sequence: int = field(default=0, init=False)
    case_results: list[QualityCaseResult] = field(default_factory=list)
    active_release_id: str | None = None
    _case_set_version: int = 0
    _lock: RLock = field(default_factory=RLock)

    def ensure_default_test_cases(self) -> None:
        with self._lock:
            if self.test_cases:
                return
            for case in DEFAULT_TEST_CASES:
                self.test_cases[case.case_id] = case.model_copy(deep=True)

    def save_test_case(self, case: PolicyQATestCase) -> PolicyQATestCase:
        with self._lock:
            self._case_set_version += 1
            saved = case.model_copy(update={
                "case_set_version": self._case_set_version,
                "updated_at": utc_now(),
            }, deep=True)
            self.test_cases[saved.case_id] = saved
            return saved.model_copy(deep=True)

    def list_test_cases(self, active_only: bool = True) -> list[PolicyQATestCase]:
        items = self.test_cases.values()
        if active_only:
            items = [item for item in items if item.active]
        return [item.model_copy(deep=True) for item in items]

    def current_case_set_version(self) -> int:
        return self._case_set_version

    def save_release(self, release: KnowledgeRelease) -> KnowledgeRelease:
        with self._lock:
            existing = self.releases.get(release.release_id)
            if existing is not None:
                immutable = (
                    "facts_collection", "rules_collection", "contract_version",
                    "case_set_version", "config_hash", "source_change_set_id",
                )
                if any(getattr(existing, key) != getattr(release, key) for key in immutable):
                    raise ValueError(f"release {release.release_id} 的版本身份不可修改")
            self.releases[release.release_id] = release.model_copy(deep=True)
            return release.model_copy(deep=True)

    def create_release(self, release: KnowledgeRelease) -> KnowledgeRelease:
        with self._lock:
            if release.release_id in self.releases:
                raise ValueError(f"release {release.release_id} 已存在")
            self.releases[release.release_id] = release.model_copy(deep=True)
            return release.model_copy(deep=True)

    def get_release(self, release_id: str) -> KnowledgeRelease | None:
        item = self.releases.get(release_id)
        return item.model_copy(deep=True) if item else None

    def list_releases(self) -> list[KnowledgeRelease]:
        return [item.model_copy(deep=True) for item in reversed(self.releases.values())]

    def get_active_release(self) -> KnowledgeRelease | None:
        return self.get_release(self.active_release_id) if self.active_release_id else None

    def claim_quality_run(self, release_id: str, run_id: str) -> str:
        with self._lock:
            release = self.releases.get(release_id)
            if (
                release is None
                or release.status not in {"ready", "failed"}
                or release.quality_run_id is not None
            ):
                raise ValueError(f"release {release_id} 已有质量运行或状态不可运行")
            previous_status = release.status
            self.releases[release_id] = release.model_copy(
                update={"status": "testing", "quality_run_id": run_id}
            )
            return previous_status

    def reclaim_stale_runs(self, release_id: str, stale_after_seconds: int = 1800) -> int:
        """回收孤儿运行：running 超时则置 failed 并释放 release（内存实现）。"""
        import datetime as _dt

        cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=stale_after_seconds)
        reclaimed = 0
        with self._lock:
            for run in self.runs.values():
                if run.release_id == release_id and run.status == "running" and run.created_at < cutoff:
                    self.runs[run.run_id] = run.model_copy(update={
                        "status": "failed",
                        "blocked_reasons": ["后端中断孤儿运行自动回收"],
                    })
                    reclaimed += 1
            release = self.releases.get(release_id)
            if (
                reclaimed
                and release is not None
                and release.status == "testing"
            ):
                self.releases[release_id] = release.model_copy(
                    update={"status": "failed", "quality_run_id": None}
                )
        return reclaimed

    def complete_quality_run(
        self,
        release_id: str,
        run_id: str,
        *,
        status: str,
        quality_score: float,
        consistency_score: float,
    ) -> KnowledgeRelease:
        if status not in {"passed", "failed"}:
            raise ValueError(f"不支持的质量运行终态: {status}")
        with self._lock:
            release = self.releases.get(release_id)
            if (
                release is None
                or release.status != "testing"
                or release.quality_run_id != run_id
            ):
                raise ValueError(f"release {release_id} 的质量运行所有权不匹配")
            completed = release.model_copy(update={
                "status": status,
                "quality_run_id": None,
                "quality_score": quality_score,
                "consistency_score": consistency_score,
            })
            self.releases[release_id] = completed
            return completed.model_copy(deep=True)

    def restore_quality_run(
        self, release_id: str, run_id: str, original_status: str
    ) -> KnowledgeRelease:
        if original_status not in {"ready", "failed"}:
            raise ValueError(f"不支持恢复到状态: {original_status}")
        with self._lock:
            release = self.releases.get(release_id)
            if (
                release is None
                or release.status != "testing"
                or release.quality_run_id != run_id
            ):
                raise ValueError(f"release {release_id} 的质量运行所有权不匹配")
            restored = release.model_copy(
                update={"status": original_status, "quality_run_id": None}
            )
            self.releases[release_id] = restored
            return restored.model_copy(deep=True)

    def promote_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease:
        with self._lock:
            target = self.releases.get(release_id)
            if target is None:
                raise ValueError(f"release 不存在: {release_id}")
            if target.status != "passed":
                raise ValueError(f"release {release_id} 未通过质量门禁")
            latest = self.get_latest_run(release_id)
            if latest is None or latest.status != "passed":
                raise ValueError(f"release {release_id} 缺少最新通过的质量运行")
            if latest.case_set_version != self.current_case_set_version():
                raise ValueError(f"release {release_id} 未通过最新用例集")
            if latest.config_hash != target.config_hash:
                raise ValueError(f"release {release_id} 的测试配置与质量运行不一致")
            if latest.baseline_release_id != self.active_release_id:
                raise ValueError(f"release {release_id} 的质量运行活动基线已过期")
            return self._switch_active(target, promoted_by)

    def rollback_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease:
        with self._lock:
            target = self.releases.get(release_id)
            if target is None or target.status != "retired" or target.promoted_at is None:
                raise ValueError(f"release {release_id} 不可回滚")
            return self._switch_active(target, promoted_by)

    def _switch_active(self, target: KnowledgeRelease, promoted_by: str) -> KnowledgeRelease:
        if self.active_release_id and self.active_release_id != target.release_id:
            current = self.releases[self.active_release_id]
            self.releases[current.release_id] = current.model_copy(update={"status": "retired"})
        active = target.model_copy(update={
            "status": "active",
            "promoted_at": utc_now(),
            "promoted_by": promoted_by,
        })
        self.releases[active.release_id] = active
        self.active_release_id = active.release_id
        return active.model_copy(deep=True)

    def save_run(self, run: QualityRun) -> QualityRun:
        with self._lock:
            if run.run_id not in self._run_sequences:
                self._next_run_sequence += 1
                self._run_sequences[run.run_id] = self._next_run_sequence
            self.runs[run.run_id] = run.model_copy(deep=True)
            return run.model_copy(deep=True)

    def get_run(self, run_id: str) -> QualityRun | None:
        run = self.runs.get(run_id)
        return run.model_copy(deep=True) if run else None

    def get_latest_run(self, release_id: str) -> QualityRun | None:
        with self._lock:
            matching_ids = [
                run_id
                for run_id, run in self.runs.items()
                if run.release_id == release_id
            ]
            latest_id = max(
                matching_ids,
                key=lambda run_id: self._run_sequences[run_id],
                default=None,
            )
            latest = self.runs.get(latest_id) if latest_id is not None else None
            return latest.model_copy(deep=True) if latest else None

    def save_case_results(self, results: list[QualityCaseResult]) -> None:
        self.case_results.extend(item.model_copy(deep=True) for item in results)

    def list_case_results(self, run_id: str) -> list[QualityCaseResult]:
        return [item.model_copy(deep=True) for item in self.case_results if item.run_id == run_id]
