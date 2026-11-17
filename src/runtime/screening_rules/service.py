"""筛查规则管理服务 — issue #86 规则管理（管理入口）。

职责：上传清单分类与候选规则落库、批准/修改/关闭、批准门禁下的批次执行、
批次与两本名单（mismatch / insufficient_material）查询。

批准门禁（issue #86 硬性）：只有 status=approved 且 class=executable 的规则
可进入执行批次；请求显式指定未批准规则时整批拒绝（RuleNotApprovedError），
结果表不出现该规则的新命中。关闭（disabled）规则不再进入后续批次。

执行数据面通过 ``fee_line_loader`` 注入（生产侧查 bjyb 的
dbo.o_Trade × dbo.o_FeeItem，测试注入 fake），服务本身不拼 SQL。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Callable

from src.data_platform.storage.screening_rules.ports import ScreeningRuleStorage
from src.domain.screening_rules.classifier import classify_checklist
from src.domain.screening_rules.executor import (
    FeeLine,
    SettlementContext,
    execute_rule,
)
from src.domain.screening_rules.models import (
    ChecklistItem,
    FindingType,
    NoApprovedRulesError,
    RuleClass,
    RuleNotApprovedError,
    RuleStatus,
    RunStatus,
    ScreeningFinding,
    ScreeningRule,
    ScreeningRun,
    VerifyStatus,
    new_rule_id,
    new_run_id,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


FeeLineLoader = Callable[[datetime, datetime], list[FeeLine]]
SettlementContextLoader = Callable[[datetime, datetime], dict[str, SettlementContext]]


class ScreeningRuleService:
    def __init__(
        self,
        storage: ScreeningRuleStorage,
        *,
        fee_line_loader: FeeLineLoader | None = None,
        context_loader: SettlementContextLoader | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._storage = storage
        self._fee_line_loader = fee_line_loader
        self._context_loader = context_loader
        self._now = now

    # ── 上传与分类 ──

    def upload_checklist(
        self, *, source_doc: str, content: str
    ) -> tuple[list[ChecklistItem], list[ScreeningRule]]:
        """上传政策/问题清单：逐条分类，可执行条目生成带原条款的候选规则。"""
        items, rules = classify_checklist(
            content, source_doc=source_doc, now=self._now()
        )
        for rule in rules:
            self._storage.insert_rule(rule)
        return items, rules

    # ── 规则生命周期 ──

    def create_rule(
        self,
        *,
        source_doc: str,
        source_clause: str,
        title: str,
        condition_text: str,
        rule_class: RuleClass,
        condition_spec: dict | None = None,
        mapping_gap: str | None = None,
        source_item_ref: str | None = None,
    ) -> ScreeningRule:
        """手工录入规则（两库知识点等非「重复收取」句式的条款）。

        与上传生成的候选同样遵守证据纪律：source_clause 原条款必填；
        executable 必须有结构化 condition_spec；一律以 candidate 落库，
        批准后才可跑数。
        """
        if not source_clause.strip():
            raise ValueError("原条款（source_clause）必填")
        if rule_class is RuleClass.EXECUTABLE and not condition_spec:
            raise ValueError("可执行规则必须提供结构化条件 condition_spec")
        if rule_class is RuleClass.NEEDS_MAPPING and not (mapping_gap or "").strip():
            raise ValueError("差一层映射必须写清缺什么（mapping_gap）")
        rule = ScreeningRule(
            rule_id=new_rule_id(),
            source_doc=source_doc,
            source_clause=source_clause,
            title=title,
            condition_text=condition_text,
            rule_class=rule_class,
            mapping_gap=mapping_gap,
            condition_spec=condition_spec,
            source_item_ref=source_item_ref,
            created_at=self._now(),
            updated_at=self._now(),
        )
        return self._storage.insert_rule(rule)

    def list_rules(
        self,
        *,
        rule_class: RuleClass | None = None,
        status: RuleStatus | None = None,
    ) -> list[ScreeningRule]:
        return self._storage.list_rules(rule_class=rule_class, status=status)

    def get_rule(self, rule_id: str) -> ScreeningRule:
        return self._storage.get_rule(rule_id)

    def update_rule(
        self,
        rule_id: str,
        *,
        title: str | None = None,
        condition_text: str | None = None,
        mapping_gap: str | None = None,
    ) -> ScreeningRule:
        """修改规则；已批准规则被修改后回到候选，需重新批准才能跑数。"""
        rule = self._storage.get_rule(rule_id)
        updates: dict = {"updated_at": self._now()}
        if title is not None:
            updates["title"] = title
        if condition_text is not None:
            updates["condition_text"] = condition_text
        if mapping_gap is not None:
            updates["mapping_gap"] = mapping_gap
        if rule.status is RuleStatus.APPROVED:
            # 修改已批准规则的条件 → 退回候选，批准记录作废
            updates["status"] = RuleStatus.CANDIDATE
            updates["approved_at"] = None
            updates["approved_by"] = None
        return self._storage.update_rule(rule.model_copy(update=updates))

    def approve_rule(self, rule_id: str, *, approved_by: str) -> ScreeningRule:
        rule = self._storage.get_rule(rule_id)
        if rule.rule_class is not RuleClass.EXECUTABLE:
            raise ValueError(
                f"仅可执行（executable）条目可批准跑数；该条目为 {rule.rule_class.value}"
                + (f"，缺口：{rule.mapping_gap}" if rule.mapping_gap else "")
            )
        if not rule.source_clause.strip():
            raise ValueError("规则缺少原条款，禁止批准")
        return self._storage.update_rule(
            rule.model_copy(
                update={
                    "status": RuleStatus.APPROVED,
                    "approved_at": self._now(),
                    "approved_by": approved_by,
                    "updated_at": self._now(),
                }
            )
        )

    def disable_rule(self, rule_id: str) -> ScreeningRule:
        """关闭规则：不再进入后续执行批次。"""
        rule = self._storage.get_rule(rule_id)
        return self._storage.update_rule(
            rule.model_copy(
                update={"status": RuleStatus.DISABLED, "updated_at": self._now()}
            )
        )

    # ── 执行 ──

    def start_run(
        self,
        *,
        time_range_start: datetime,
        time_range_end: datetime,
        created_by: str,
        rule_ids: list[str] | None = None,
    ) -> ScreeningRun:
        """对已批准规则执行跑数。

        - 未指定 rule_ids 时执行全部已批准的可执行规则；
        - 显式指定的规则必须全部已批准，否则整批拒绝（批准门禁）；
        - 无命中也算执行完成：批次 status=succeeded 且命中为 0。
        """
        if time_range_end <= time_range_start:
            raise ValueError("time_range_end 必须晚于 time_range_start")
        if time_range_end - time_range_start > timedelta(days=92):
            raise ValueError("一次只跑一小段历史诊次，时间范围请不超过 92 天")
        if rule_ids is not None:
            rules = [self._storage.get_rule(rule_id) for rule_id in rule_ids]
            not_approved = [
                rule.rule_id for rule in rules if rule.status is not RuleStatus.APPROVED
            ]
            if not_approved:
                raise RuleNotApprovedError(not_approved)
            not_executable = [
                rule.rule_id
                for rule in rules
                if rule.rule_class is not RuleClass.EXECUTABLE
            ]
            if not_executable:
                raise RuleNotApprovedError(not_executable)
        else:
            rules = [
                rule
                for rule in self._storage.list_approved_rules()
                if rule.rule_class is RuleClass.EXECUTABLE
            ]
            if not rules:
                raise NoApprovedRulesError()
        loader = self._fee_line_loader
        if loader is None:
            from src.runtime.screening_rules.fee_line_loader import load_fee_lines

            loader = load_fee_lines

        run = ScreeningRun(
            run_id=new_run_id(),
            started_at=self._now(),
            status=RunStatus.RUNNING,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            created_by=created_by,
        )
        self._storage.insert_run(run, [rule.rule_id for rule in rules])
        try:
            fee_lines = loader(time_range_start, time_range_end)
            needs_context = any(
                (rule.condition_spec or {}).get("kind") == "drug_age_indication"
                for rule in rules
            )
            context_loader = self._context_loader
            if needs_context and context_loader is None:
                from src.runtime.screening_rules.fee_line_loader import (
                    load_settlement_contexts,
                )

                context_loader = load_settlement_contexts
            contexts = (
                context_loader(time_range_start, time_range_end)
                if needs_context and context_loader is not None
                else None
            )
            seen: dict[tuple[str, str], str] = {}
            for rule in rules:
                for finding in execute_rule(
                    rule, fee_lines, run_id=run.run_id, now=self._now(),
                    seen_fee_lines=seen, settlement_contexts=contexts,
                ):
                    self._storage.insert_finding(finding)
            run = run.model_copy(
                update={"status": RunStatus.SUCCEEDED, "finished_at": self._now()}
            )
        except Exception as exc:
            run = run.model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "finished_at": self._now(),
                    "error_message": str(exc)[:500],
                }
            )
            self._storage.finish_run(run)
            raise
        self._storage.finish_run(run)
        return run

    # ── 批次与名单 ──

    def list_runs(self, *, limit: int = 20) -> list[ScreeningRun]:
        return self._storage.list_runs(limit=limit)

    def get_run(self, run_id: str) -> tuple[ScreeningRun, list[str], dict[str, int]]:
        run = self._storage.get_run(run_id)
        return (
            run,
            self._storage.list_run_rule_ids(run_id),
            self._storage.count_run_findings(run_id),
        )

    def latest_succeeded_run(self) -> ScreeningRun | None:
        return self._storage.latest_succeeded_run()

    def list_findings(
        self,
        *,
        run_id: str | None = None,
        rule_id: str | None = None,
        finding_type: FindingType | None = None,
        limit: int = 200,
    ) -> list[ScreeningFinding]:
        return self._storage.list_findings(
            run_id=run_id, rule_id=rule_id, finding_type=finding_type, limit=limit
        )

    def verify_finding(self, finding_id: str, verify_status: VerifyStatus) -> ScreeningFinding:
        """医保办核实结论（跟/不跟/材料不足）记在疑点上。"""
        finding = self._storage.get_finding(finding_id)
        return self._storage.update_finding(
            finding.model_copy(update={"verify_status": verify_status})
        )
