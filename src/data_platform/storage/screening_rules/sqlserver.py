"""筛查规则写在 bjyb 的 SQL Server 上，和问数读的 dbo.ai_screen_* 是同一套表。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable

from src.data_platform.storage.screening_rules.sqlserver_schema import (
    EXPECTED_SCREENING_TABLES,
    SQLSERVER_SCREENING_DDL,
)
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

_RULE_SELECT = (
    "rule_id, source_doc, source_clause, title, condition_text, [class] AS rule_class, "
    "mapping_gap, status, condition_spec, source_item_ref, created_at, updated_at, "
    "approved_at, approved_by"
)
_RUN_SELECT = (
    "run_id, started_at, finished_at, status, time_range_start, time_range_end, "
    "error_message, created_by"
)
_FINDING_SELECT = (
    "finding_id, run_id, rule_id, settlement_key, fee_line_id, item_code, item_name, "
    "amount, finding_type, primary_finding_id, evidence_clause, evidence_facts, "
    "verify_status, created_at"
)


def open_bjyb() -> Any:
    """复用发现模块的 bjyb 环境变量连接，不另起数据源。"""
    from src.runtime.discovery.sqlserver_source import _connect, _env_fallback_conn_str

    conn_str = _env_fallback_conn_str()
    if not conn_str:
        raise RuntimeError("未配置 bjyb 连接（MSSQL_HOST / MSSQL_DATABASE / MSSQL_USER / MSSQL_PASSWORD）")
    return _connect(conn_str)


def bind_datetime(value: datetime | None) -> datetime | None:
    """pyodbc 不接受带时区的时间。带时区的先折成 UTC 再去掉时区。"""
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _limit(value: int, *, cap: int) -> int:
    return max(1, min(int(value), cap))


def _row_to_rule(row: dict[str, Any]) -> ScreeningRule:
    spec = _json_load(row.get("condition_spec"))
    return ScreeningRule(
        rule_id=row["rule_id"],
        source_doc=row["source_doc"],
        source_clause=row["source_clause"],
        title=row["title"],
        condition_text=row["condition_text"],
        rule_class=RuleClass(row["rule_class"]),
        mapping_gap=row.get("mapping_gap"),
        status=RuleStatus(row["status"]),
        condition_spec=dict(spec) if isinstance(spec, dict) else None,
        source_item_ref=row.get("source_item_ref"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        approved_at=row.get("approved_at"),
        approved_by=row.get("approved_by"),
    )


def _row_to_run(row: dict[str, Any]) -> ScreeningRun:
    return ScreeningRun(
        run_id=row["run_id"],
        started_at=row["started_at"],
        finished_at=row.get("finished_at"),
        status=RunStatus(row["status"]),
        time_range_start=row["time_range_start"],
        time_range_end=row["time_range_end"],
        error_message=row.get("error_message"),
        created_by=row["created_by"],
    )


def _row_to_finding(row: dict[str, Any]) -> ScreeningFinding:
    facts = _json_load(row.get("evidence_facts")) or {}
    amount = row.get("amount")
    return ScreeningFinding(
        finding_id=row["finding_id"],
        run_id=row["run_id"],
        rule_id=row["rule_id"],
        settlement_key=row["settlement_key"],
        fee_line_id=row.get("fee_line_id"),
        item_code=row.get("item_code"),
        item_name=row.get("item_name"),
        amount=float(amount) if amount is not None else None,
        finding_type=FindingType(row["finding_type"]),
        primary_finding_id=row["primary_finding_id"],
        evidence_clause=row["evidence_clause"],
        evidence_facts=dict(facts),
        verify_status=VerifyStatus(row["verify_status"]),
        created_at=row["created_at"],
    )


class SqlServerScreeningRuleStorage:
    """dbo.ai_screen_* 四表。用户输入只进参数。"""

    def __init__(self, connect: Callable[[], Any] | None = None, *, ensure: bool = True) -> None:
        self._connect = connect or open_bjyb
        if ensure:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            for statement in SQLSERVER_SCREENING_DDL:
                cursor.execute(statement)
        finally:
            conn.close()

    def missing_tables(self) -> list[str]:
        placeholders = ", ".join("?" for _ in EXPECTED_SCREENING_TABLES)
        rows = self._fetch(
            "SELECT TABLE_NAME AS table_name FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = N'dbo' AND TABLE_NAME IN ({placeholders})",
            list(EXPECTED_SCREENING_TABLES),
        )
        existing = {str(row["table_name"]).lower() for row in rows}
        return [name for name in EXPECTED_SCREENING_TABLES if name not in existing]

    def insert_rule(self, rule: ScreeningRule) -> ScreeningRule:
        self._execute(
            "INSERT INTO dbo.ai_screen_rule ("
            "rule_id, source_doc, source_clause, title, condition_text, [class], mapping_gap, "
            "status, condition_spec, source_item_ref, created_at, updated_at, approved_at, approved_by"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                rule.rule_id, rule.source_doc, rule.source_clause, rule.title,
                rule.condition_text, rule.rule_class.value, rule.mapping_gap,
                rule.status.value, _json_text(rule.condition_spec), rule.source_item_ref,
                bind_datetime(rule.created_at), bind_datetime(rule.updated_at),
                bind_datetime(rule.approved_at), rule.approved_by,
            ],
        )
        return rule

    def get_rule(self, rule_id: str) -> ScreeningRule:
        rows = self._fetch(
            f"SELECT {_RULE_SELECT} FROM dbo.ai_screen_rule WHERE rule_id = ?",
            [rule_id],
        )
        if not rows:
            raise ScreeningRuleNotFoundError(rule_id)
        return _row_to_rule(rows[0])

    def update_rule(self, rule: ScreeningRule) -> ScreeningRule:
        self._execute(
            "UPDATE dbo.ai_screen_rule SET title = ?, condition_text = ?, condition_spec = ?, "
            "mapping_gap = ?, status = ?, updated_at = ?, approved_at = ?, approved_by = ? "
            "WHERE rule_id = ?",
            [
                rule.title, rule.condition_text, _json_text(rule.condition_spec),
                rule.mapping_gap, rule.status.value, bind_datetime(rule.updated_at),
                bind_datetime(rule.approved_at), rule.approved_by, rule.rule_id,
            ],
        )
        return rule

    def list_rules(
        self,
        *,
        rule_class: RuleClass | None = None,
        status: RuleStatus | None = None,
    ) -> list[ScreeningRule]:
        sql = f"SELECT {_RULE_SELECT} FROM dbo.ai_screen_rule"
        conditions: list[str] = []
        params: list[Any] = []
        if rule_class is not None:
            conditions.append("[class] = ?")
            params.append(rule_class.value)
        if status is not None:
            conditions.append("status = ?")
            params.append(status.value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        return [_row_to_rule(row) for row in self._fetch(sql, params)]

    def list_approved_rules(self) -> list[ScreeningRule]:
        return self.list_rules(status=RuleStatus.APPROVED)

    def insert_run(self, run: ScreeningRun, rule_ids: list[str]) -> ScreeningRun:
        self._execute(
            "INSERT INTO dbo.ai_screen_run ("
            "run_id, started_at, finished_at, status, time_range_start, time_range_end, "
            "error_message, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run.run_id, bind_datetime(run.started_at), bind_datetime(run.finished_at),
                run.status.value, bind_datetime(run.time_range_start),
                bind_datetime(run.time_range_end), run.error_message, run.created_by,
            ],
        )
        try:
            for rule_id in rule_ids:
                self._execute(
                    "INSERT INTO dbo.ai_screen_run_rule (run_id, rule_id) VALUES (?, ?)",
                    [run.run_id, rule_id],
                )
        except Exception:
            self.finish_run(run.model_copy(update={
                "status": RunStatus.FAILED,
                "finished_at": run.started_at,
                "error_message": "批次与规则的关联没有写完",
            }))
            raise
        return run

    def get_run(self, run_id: str) -> ScreeningRun:
        rows = self._fetch(
            f"SELECT {_RUN_SELECT} FROM dbo.ai_screen_run WHERE run_id = ?",
            [run_id],
        )
        if not rows:
            raise ScreeningRunNotFoundError(run_id)
        return _row_to_run(rows[0])

    def finish_run(self, run: ScreeningRun) -> ScreeningRun:
        self._execute(
            "UPDATE dbo.ai_screen_run SET status = ?, finished_at = ?, error_message = ? "
            "WHERE run_id = ?",
            [run.status.value, bind_datetime(run.finished_at), run.error_message, run.run_id],
        )
        return run

    def list_runs(self, *, limit: int = 20) -> list[ScreeningRun]:
        top = _limit(limit, cap=100)
        rows = self._fetch(
            f"SELECT TOP ({top}) {_RUN_SELECT} FROM dbo.ai_screen_run ORDER BY started_at DESC",
            [],
        )
        return [_row_to_run(row) for row in rows]

    def list_run_rule_ids(self, run_id: str) -> list[str]:
        rows = self._fetch(
            "SELECT rule_id FROM dbo.ai_screen_run_rule WHERE run_id = ? ORDER BY rule_id",
            [run_id],
        )
        return [row["rule_id"] for row in rows]

    def latest_succeeded_run(self) -> ScreeningRun | None:
        rows = self._fetch(
            f"SELECT TOP (1) {_RUN_SELECT} FROM dbo.ai_screen_run WHERE status = ? "
            "ORDER BY finished_at DESC, run_id DESC",
            [RunStatus.SUCCEEDED.value],
        )
        return _row_to_run(rows[0]) if rows else None

    def insert_finding(self, finding: ScreeningFinding) -> ScreeningFinding:
        self._execute(
            "INSERT INTO dbo.ai_screen_finding ("
            "finding_id, run_id, rule_id, settlement_key, fee_line_id, item_code, item_name, "
            "amount, finding_type, primary_finding_id, evidence_clause, evidence_facts, "
            "verify_status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                finding.finding_id, finding.run_id, finding.rule_id, finding.settlement_key,
                finding.fee_line_id, finding.item_code, finding.item_name, finding.amount,
                finding.finding_type.value, finding.primary_finding_id, finding.evidence_clause,
                _json_text(finding.evidence_facts) or "{}", finding.verify_status.value,
                bind_datetime(finding.created_at),
            ],
        )
        return finding

    def update_finding(self, finding: ScreeningFinding) -> ScreeningFinding:
        self._execute(
            "UPDATE dbo.ai_screen_finding SET verify_status = ? WHERE finding_id = ?",
            [finding.verify_status.value, finding.finding_id],
        )
        return finding

    def get_finding(self, finding_id: str) -> ScreeningFinding:
        rows = self._fetch(
            f"SELECT {_FINDING_SELECT} FROM dbo.ai_screen_finding WHERE finding_id = ?",
            [finding_id],
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
        sql = f"SELECT TOP ({_limit(limit, cap=1000)}) {_FINDING_SELECT} FROM dbo.ai_screen_finding"
        conditions: list[str] = []
        params: list[Any] = []
        if run_id is not None:
            conditions.append("run_id = ?")
            params.append(run_id)
        if rule_id is not None:
            conditions.append("rule_id = ?")
            params.append(rule_id)
        if finding_type is not None:
            conditions.append("finding_type = ?")
            params.append(finding_type.value)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY CASE WHEN amount IS NULL THEN 1 ELSE 0 END, amount DESC, created_at"
        return [_row_to_finding(row) for row in self._fetch(sql, params)]

    def count_run_findings(self, run_id: str) -> dict[str, int]:
        rows = self._fetch(
            "SELECT finding_type, COUNT(*) AS n FROM dbo.ai_screen_finding "
            "WHERE run_id = ? GROUP BY finding_type",
            [run_id],
        )
        return {row["finding_type"]: int(row["n"]) for row in rows}

    def _execute(self, sql: str, params: list[Any] | None = None) -> None:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
        finally:
            conn.close()

    def _fetch(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            if cursor.description is None:
                return []
            names = [str(col[0]).lower() for col in cursor.description]
            return [
                dict(zip(names, record, strict=True))
                for record in cursor.fetchall()
            ]
        finally:
            conn.close()
