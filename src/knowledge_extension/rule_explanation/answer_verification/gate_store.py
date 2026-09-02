"""答案验证发布门禁存储端口与内存实现。"""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Protocol

from src.knowledge_extension.rule_explanation.answer_verification.gate_models import (
    AnswerVerificationCaseResult,
    AnswerVerificationRun,
)


class AnswerVerificationGateStore(Protocol):
    def save_run(self, run: AnswerVerificationRun) -> AnswerVerificationRun: ...
    def get_run(self, run_id: str) -> AnswerVerificationRun | None: ...
    def get_latest_run(self, release_id: str) -> AnswerVerificationRun | None: ...
    def save_case_results(self, results: list[AnswerVerificationCaseResult]) -> None: ...
    def list_case_results(self, run_id: str) -> list[AnswerVerificationCaseResult]: ...


@dataclass
class InMemoryAnswerVerificationGateStore:
    """测试/开发用内存门禁存储，按保存顺序确定 latest run。"""

    runs: dict[str, AnswerVerificationRun] = field(default_factory=dict)
    case_results: list[AnswerVerificationCaseResult] = field(default_factory=list)
    _run_sequences: dict[str, int] = field(default_factory=dict, init=False)
    _next_run_sequence: int = field(default=0, init=False)
    _lock: RLock = field(default_factory=RLock)

    def save_run(self, run: AnswerVerificationRun) -> AnswerVerificationRun:
        with self._lock:
            if run.run_id not in self._run_sequences:
                self._next_run_sequence += 1
                self._run_sequences[run.run_id] = self._next_run_sequence
            self.runs[run.run_id] = run.model_copy(deep=True)
            return run.model_copy(deep=True)

    def get_run(self, run_id: str) -> AnswerVerificationRun | None:
        run = self.runs.get(run_id)
        return run.model_copy(deep=True) if run else None

    def get_latest_run(self, release_id: str) -> AnswerVerificationRun | None:
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

    def save_case_results(self, results: list[AnswerVerificationCaseResult]) -> None:
        with self._lock:
            incoming = {(item.run_id, item.case_id) for item in results}
            self.case_results = [
                item
                for item in self.case_results
                if (item.run_id, item.case_id) not in incoming
            ]
            self.case_results.extend(item.model_copy(deep=True) for item in results)

    def list_case_results(self, run_id: str) -> list[AnswerVerificationCaseResult]:
        return [
            item.model_copy(deep=True)
            for item in self.case_results
            if item.run_id == run_id
        ]
