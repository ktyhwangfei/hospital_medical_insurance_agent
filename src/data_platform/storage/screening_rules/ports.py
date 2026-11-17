"""筛查规则存储端口 — issue #86。

四张结果表（ai_screen_rule / ai_screen_run / ai_screen_run_rule /
ai_screen_finding）落在 bjyb 的 SQL Server（dbo），问数侧按表名只读直查。
"""
from __future__ import annotations

from typing import Protocol

from src.domain.screening_rules.models import (
    FindingType,
    RuleClass,
    RuleStatus,
    ScreeningFinding,
    ScreeningRule,
    ScreeningRun,
)


class ScreeningRuleStorage(Protocol):
    """筛查规则存储契约。

    - 规则生命周期（candidate→approved→disabled）由服务层裁定，存储只落行；
    - save_finding 由执行器在批次内调用；同一费用行只计一次金额的去重由
      执行器通过 primary_finding_id 保证，存储层不判重；
    - 关闭（disabled）规则不再进入后续批次由服务层在筛选执行规则时保证。
    """

    # ── 规则 ──
    def insert_rule(self, rule: ScreeningRule) -> ScreeningRule: ...

    def get_rule(self, rule_id: str) -> ScreeningRule: ...

    def update_rule(self, rule: ScreeningRule) -> ScreeningRule: ...

    def list_rules(
        self,
        *,
        rule_class: RuleClass | None = None,
        status: RuleStatus | None = None,
    ) -> list[ScreeningRule]: ...

    def list_approved_rules(self) -> list[ScreeningRule]: ...

    # ── 执行批次 ──
    def insert_run(self, run: ScreeningRun, rule_ids: list[str]) -> ScreeningRun: ...

    def get_run(self, run_id: str) -> ScreeningRun: ...

    def finish_run(self, run: ScreeningRun) -> ScreeningRun: ...

    def list_runs(self, *, limit: int = 20) -> list[ScreeningRun]: ...

    def list_run_rule_ids(self, run_id: str) -> list[str]: ...

    def latest_succeeded_run(self) -> ScreeningRun | None: ...

    # ── 疑点 ──
    def insert_finding(self, finding: ScreeningFinding) -> ScreeningFinding: ...

    def update_finding(self, finding: ScreeningFinding) -> ScreeningFinding: ...

    def get_finding(self, finding_id: str) -> ScreeningFinding: ...

    def list_findings(
        self,
        *,
        run_id: str | None = None,
        rule_id: str | None = None,
        finding_type: FindingType | None = None,
        limit: int = 200,
    ) -> list[ScreeningFinding]: ...

    def count_run_findings(self, run_id: str) -> dict[str, int]: ...
