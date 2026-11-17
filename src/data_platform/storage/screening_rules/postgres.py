"""筛查规则的 PostgreSQL 存储。

生产默认已改走 SQL Server 的 dbo.ai_screen_*（见 sqlserver.py）。
本模块不再作为问数读取面。
"""
from __future__ import annotations

import json
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.screening_rules.schema import SCREENING_TABLE_SCHEMAS
from src.domain.screening_rules.models import (
    FindingType,
    RuleClass,
    RuleStatus,
    RunStatus,
    ScreeningFinding,
    ScreeningFindingNotFoundError,
    ScreeningRule,
    ScreeningRuleNotFoundError,
    ScreeningRun,
    ScreeningRunNotFoundError,
    VerifyStatus,
)

_RULE_COLUMNS = (
    "rule_id, source_doc, source_clause, title, condition_text, class, mapping_gap, "
    "status, condition_spec, source_item_ref, created_at, updated_at, approved_at, approved_by"
)
_RUN_COLUMNS = (
    "run_id, started_at, finished_at, status, time_range_start, time_range_end, "
    "error_message, created_by"
)
_FINDING_COLUMNS = (
    "finding_id, run_id, rule_id, settlement_key, fee_line_id, item_code, item_name, "
    "amount, finding_type, primary_finding_id, evidence_clause, evidence_facts, "
    "verify_status, created_at"
)


def _row_to_rule(row: dict[str, Any]) -> ScreeningRule:
    return ScreeningRule(
        rule_id=row["rule_id"],
        source_doc=row["source_doc"],
        source_clause=row["source_clause"],
        title=row["title"],
        condition_text=row["condition_text"],
        rule_class=RuleClass(row["class"]),
        mapping_gap=row["mapping_gap"],
        status=RuleStatus(row["status"]),
        condition_spec=dict(row["condition_spec"]) if row["condition_spec"] else None,
        source_item_ref=row["source_item_ref"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        approved_at=row["approved_at"],
        approved_by=row["approved_by"],
    )


def _row_to_run(row: dict[str, Any]) -> ScreeningRun:
    return ScreeningRun(
        run_id=row["run_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        status=RunStatus(row["status"]),
        time_range_start=row["time_range_start"],
        time_range_end=row["time_range_end"],
        error_message=row["error_message"],
        created_by=row["created_by"],
    )


def _row_to_finding(row: dict[str, Any]) -> ScreeningFinding:
    facts = row["evidence_facts"]
    if isinstance(facts, str):
        facts = json.loads(facts)
    return ScreeningFinding(
        finding_id=row["finding_id"],
        run_id=row["run_id"],
        rule_id=row["rule_id"],
        settlement_key=row["settlement_key"],
        fee_line_id=row["fee_line_id"],
        item_code=row["item_code"],
        item_name=row["item_name"],
        amount=float(row["amount"]) if row["amount"] is not None else None,
        finding_type=FindingType(row["finding_type"]),
        primary_finding_id=row["primary_finding_id"],
        evidence_clause=row["evidence_clause"],
        evidence_facts=dict(facts or {}),
        verify_status=VerifyStatus(row["verify_status"]),
        created_at=row["created_at"],
    )


class PostgresScreeningRuleStorage:
    """ai_screen_* 四表 PG 实现。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._client = PostgreSQLClient(database_url or DATABASE_URL)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        for schema in SCREENING_TABLE_SCHEMAS:
            for statement in schema:
                self._client.execute(statement)

    # ── 规则 ──

    def insert_rule(self, rule: ScreeningRule) -> ScreeningRule:
        self._client.execute(
            f"INSERT INTO ai_screen_rule ({_RULE_COLUMNS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                rule.rule_id, rule.source_doc, rule.source_clause, rule.title,
                rule.condition_text, rule.rule_class.value, rule.mapping_gap,
                rule.status.value,
                json.dumps(rule.condition_spec, ensure_ascii=False) if rule.condition_spec else None,
                rule.source_item_ref, rule.created_at, rule.updated_at,
                rule.approved_at, rule.approved_by,
            ),
        )
        return rule

    def get_rule(self, rule_id: str) -> ScreeningRule:
        rows = self._client.execute(
            f"SELECT {_RULE_COLUMNS} FROM ai_screen_rule WHERE rule_id = %s", (rule_id,)
        )
        if not rows:
            raise ScreeningRuleNotFoundError(rule_id)
        return _row_to_rule(rows[0])

    def update_rule(self, rule: ScreeningRule) -> ScreeningRule:
        self._client.execute(
            "UPDATE ai_screen_rule SET title = %s, condition_text = %s, "
            "condition_spec = %s, mapping_gap = %s, status = %s, updated_at = %s, "
            "approved_at = %s, approved_by = %s WHERE rule_id = %s",
            (
                rule.title, rule.condition_text,
                json.dumps(rule.condition_spec, ensure_ascii=False) if rule.condition_spec else None,
                rule.mapping_gap, rule.status.value, rule.updated_at,
                rule.approved_at, rule.approved_by, rule.rule_id,
            ),
        )
        return rule

    def list_rules(
        self,
        *,
        rule_class: RuleClass | None = None,
        status: RuleStatus | None = None,
    ) -> list[ScreeningRule]:
        sql = f"SELECT {_RULE_COLUMNS} FROM ai_screen_rule"
        conditions: list[str] = []
        params: list[Any] = []
        if rule_class is not None:
            conditions.append("class = %s")
            params.append(rule_class.value)
        if status is not None:
            conditions.append("status = %s")
            params.append(status.value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        return [_row_to_rule(row) for row in self._client.execute(sql, tuple(params))]

    def list_approved_rules(self) -> list[ScreeningRule]:
        return self.list_rules(status=RuleStatus.APPROVED)

    # ── 执行批次 ──

    def insert_run(self, run: ScreeningRun, rule_ids: list[str]) -> ScreeningRun:
        self._client.execute(
            f"INSERT INTO ai_screen_run ({_RUN_COLUMNS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                run.run_id, run.started_at, run.finished_at, run.status.value,
                run.time_range_start, run.time_range_end, run.error_message,
                run.created_by,
            ),
        )
        self._client.execute_many(
            "INSERT INTO ai_screen_run_rule (run_id, rule_id) VALUES (%s, %s)",
            [(run.run_id, rule_id) for rule_id in rule_ids],
        )
        return run

    def get_run(self, run_id: str) -> ScreeningRun:
        rows = self._client.execute(
            f"SELECT {_RUN_COLUMNS} FROM ai_screen_run WHERE run_id = %s", (run_id,)
        )
        if not rows:
            raise ScreeningRunNotFoundError(run_id)
        return _row_to_run(rows[0])

    def finish_run(self, run: ScreeningRun) -> ScreeningRun:
        self._client.execute(
            "UPDATE ai_screen_run SET status = %s, finished_at = %s, error_message = %s "
            "WHERE run_id = %s",
            (run.status.value, run.finished_at, run.error_message, run.run_id),
        )
        return run

    def list_runs(self, *, limit: int = 20) -> list[ScreeningRun]:
        rows = self._client.execute(
            f"SELECT {_RUN_COLUMNS} FROM ai_screen_run ORDER BY started_at DESC LIMIT %s",
            (limit,),
        )
        return [_row_to_run(row) for row in rows]

    def list_run_rule_ids(self, run_id: str) -> list[str]:
        rows = self._client.execute(
            "SELECT rule_id FROM ai_screen_run_rule WHERE run_id = %s ORDER BY rule_id",
            (run_id,),
        )
        return [row["rule_id"] for row in rows]

    def latest_succeeded_run(self) -> ScreeningRun | None:
        rows = self._client.execute(
            f"SELECT {_RUN_COLUMNS} FROM ai_screen_run WHERE status = %s "
            "ORDER BY finished_at DESC LIMIT 1",
            (RunStatus.SUCCEEDED.value,),
        )
        return _row_to_run(rows[0]) if rows else None

    # ── 疑点 ──

    def insert_finding(self, finding: ScreeningFinding) -> ScreeningFinding:
        self._client.execute(
            f"INSERT INTO ai_screen_finding ({_FINDING_COLUMNS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                finding.finding_id, finding.run_id, finding.rule_id,
                finding.settlement_key, finding.fee_line_id, finding.item_code,
                finding.item_name, finding.amount, finding.finding_type.value,
                finding.primary_finding_id, finding.evidence_clause,
                json.dumps(finding.evidence_facts, ensure_ascii=False),
                finding.verify_status.value, finding.created_at,
            ),
        )
        return finding

    def update_finding(self, finding: ScreeningFinding) -> ScreeningFinding:
        self._client.execute(
            "UPDATE ai_screen_finding SET verify_status = %s WHERE finding_id = %s",
            (finding.verify_status.value, finding.finding_id),
        )
        return finding

    def get_finding(self, finding_id: str) -> ScreeningFinding:
        rows = self._client.execute(
            f"SELECT {_FINDING_COLUMNS} FROM ai_screen_finding WHERE finding_id = %s",
            (finding_id,),
        )
        if not rows:
            raise ScreeningFindingNotFoundError(finding_id)
        return _row_to_finding(rows[0])

    def list_findings(
        self,
        *,
        run_id: str | None = None,
        rule_id: str | None = None,
        finding_type: FindingType | None = None,
        limit: int = 200,
    ) -> list[ScreeningFinding]:
        sql = f"SELECT {_FINDING_COLUMNS} FROM ai_screen_finding"
        conditions: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            conditions.append("run_id = %s")
            params.append(run_id)
        if rule_id is not None:
            conditions.append("rule_id = %s")
            params.append(rule_id)
        if finding_type is not None:
            conditions.append("finding_type = %s")
            params.append(finding_type.value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY amount DESC NULLS LAST, created_at LIMIT %s"
        params.append(limit)
        return [_row_to_finding(row) for row in self._client.execute(sql, tuple(params))]

    def count_run_findings(self, run_id: str) -> dict[str, int]:
        rows = self._client.execute(
            "SELECT finding_type, COUNT(*) AS n FROM ai_screen_finding "
            "WHERE run_id = %s GROUP BY finding_type",
            (run_id,),
        )
        return {row["finding_type"]: int(row["n"]) for row in rows}
