"""筛查规则内存存储 — issue #86（USE_MEMORY_STORAGE=1 回退 / 测试注入）。"""
from __future__ import annotations

from src.domain.screening_rules.models import (
    FindingType,
    RuleClass,
    RuleStatus,
    ScreeningFinding,
    ScreeningFindingNotFoundError,
    ScreeningRule,
    ScreeningRuleNotFoundError,
    ScreeningRun,
    ScreeningRunNotFoundError,
)


class InMemoryScreeningRuleStorage:
    def __init__(self) -> None:
        self._rules: dict[str, ScreeningRule] = {}
        self._runs: dict[str, ScreeningRun] = {}
        self._run_rules: dict[str, list[str]] = {}
        self._findings: dict[str, ScreeningFinding] = {}

    # ── 规则 ──

    def insert_rule(self, rule: ScreeningRule) -> ScreeningRule:
        self._rules[rule.rule_id] = rule
        return rule

    def get_rule(self, rule_id: str) -> ScreeningRule:
        rule = self._rules.get(rule_id)
        if rule is None:
            raise ScreeningRuleNotFoundError(rule_id)
        return rule

    def update_rule(self, rule: ScreeningRule) -> ScreeningRule:
        if rule.rule_id not in self._rules:
            raise ScreeningRuleNotFoundError(rule.rule_id)
        self._rules[rule.rule_id] = rule
        return rule

    def list_rules(
        self,
        *,
        rule_class: RuleClass | None = None,
        status: RuleStatus | None = None,
    ) -> list[ScreeningRule]:
        rules = list(self._rules.values())
        if rule_class is not None:
            rules = [r for r in rules if r.rule_class is rule_class]
        if status is not None:
            rules = [r for r in rules if r.status is status]
        return sorted(rules, key=lambda r: r.created_at, reverse=True)

    def list_approved_rules(self) -> list[ScreeningRule]:
        return self.list_rules(status=RuleStatus.APPROVED)

    # ── 执行批次 ──

    def insert_run(self, run: ScreeningRun, rule_ids: list[str]) -> ScreeningRun:
        self._runs[run.run_id] = run
        self._run_rules[run.run_id] = list(rule_ids)
        return run

    def get_run(self, run_id: str) -> ScreeningRun:
        run = self._runs.get(run_id)
        if run is None:
            raise ScreeningRunNotFoundError(run_id)
        return run

    def finish_run(self, run: ScreeningRun) -> ScreeningRun:
        if run.run_id not in self._runs:
            raise ScreeningRunNotFoundError(run.run_id)
        self._runs[run.run_id] = run
        return run

    def list_runs(self, *, limit: int = 20) -> list[ScreeningRun]:
        runs = sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)
        return runs[:limit]

    def list_run_rule_ids(self, run_id: str) -> list[str]:
        if run_id not in self._runs:
            raise ScreeningRunNotFoundError(run_id)
        return sorted(self._run_rules.get(run_id, []))

    def latest_succeeded_run(self) -> ScreeningRun | None:
        succeeded = [r for r in self._runs.values() if r.status is RunStatus.SUCCEEDED]
        if not succeeded:
            return None
        return max(succeeded, key=lambda r: r.finished_at or r.started_at)

    # ── 疑点 ──

    def insert_finding(self, finding: ScreeningFinding) -> ScreeningFinding:
        self._findings[finding.finding_id] = finding
        return finding

    def update_finding(self, finding: ScreeningFinding) -> ScreeningFinding:
        if finding.finding_id not in self._findings:
            raise ScreeningFindingNotFoundError(finding.finding_id)
        self._findings[finding.finding_id] = finding
        return finding

    def get_finding(self, finding_id: str) -> ScreeningFinding:
        finding = self._findings.get(finding_id)
        if finding is None:
            raise ScreeningFindingNotFoundError(finding_id)
        return finding

    def list_findings(
        self,
        *,
        run_id: str | None = None,
        rule_id: str | None = None,
        finding_type: FindingType | None = None,
        limit: int = 200,
    ) -> list[ScreeningFinding]:
        findings = list(self._findings.values())
        if run_id is not None:
            findings = [f for f in findings if f.run_id == run_id]
        if rule_id is not None:
            findings = [f for f in findings if f.rule_id == rule_id]
        if finding_type is not None:
            findings = [f for f in findings if f.finding_type is finding_type]
        findings.sort(key=lambda f: (-(f.amount or 0.0), f.created_at))
        return findings[:limit]

    def count_run_findings(self, run_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self._findings.values():
            if finding.run_id == run_id:
                key = finding.finding_type.value
                counts[key] = counts.get(key, 0) + 1
        return counts
