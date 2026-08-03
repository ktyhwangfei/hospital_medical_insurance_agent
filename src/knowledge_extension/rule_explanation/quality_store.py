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


class PolicyQualityStore(Protocol):
    def save_test_case(self, case: PolicyQATestCase) -> PolicyQATestCase: ...
    def list_test_cases(self, active_only: bool = True) -> list[PolicyQATestCase]: ...
    def current_case_set_version(self) -> int: ...
    def save_release(self, release: KnowledgeRelease) -> KnowledgeRelease: ...
    def get_release(self, release_id: str) -> KnowledgeRelease | None: ...
    def get_active_release(self) -> KnowledgeRelease | None: ...
    def promote_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease: ...
    def rollback_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease: ...
    def save_run(self, run: QualityRun) -> QualityRun: ...
    def save_case_results(self, results: list[QualityCaseResult]) -> None: ...


@dataclass
class InMemoryPolicyQualityStore:
    test_cases: dict[str, PolicyQATestCase] = field(default_factory=dict)
    releases: dict[str, KnowledgeRelease] = field(default_factory=dict)
    runs: dict[str, QualityRun] = field(default_factory=dict)
    case_results: list[QualityCaseResult] = field(default_factory=list)
    active_release_id: str | None = None
    _case_set_version: int = 0
    _lock: RLock = field(default_factory=RLock)

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
                    "case_set_version", "config_hash",
                )
                if any(getattr(existing, key) != getattr(release, key) for key in immutable):
                    raise ValueError(f"release {release.release_id} 的版本身份不可修改")
            self.releases[release.release_id] = release.model_copy(deep=True)
            return release.model_copy(deep=True)

    def get_release(self, release_id: str) -> KnowledgeRelease | None:
        item = self.releases.get(release_id)
        return item.model_copy(deep=True) if item else None

    def get_active_release(self) -> KnowledgeRelease | None:
        return self.get_release(self.active_release_id) if self.active_release_id else None

    def promote_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease:
        with self._lock:
            target = self.releases.get(release_id)
            if target is None:
                raise ValueError(f"release 不存在: {release_id}")
            if target.status != "passed":
                raise ValueError(f"release {release_id} 未通过质量门禁")
            return self._switch_active(target, promoted_by)

    def rollback_release(self, release_id: str, promoted_by: str) -> KnowledgeRelease:
        with self._lock:
            target = self.releases.get(release_id)
            if target is None or target.status not in {"retired", "passed"}:
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
        self.runs[run.run_id] = run.model_copy(deep=True)
        return run.model_copy(deep=True)

    def save_case_results(self, results: list[QualityCaseResult]) -> None:
        self.case_results.extend(item.model_copy(deep=True) for item in results)

