"""筛查结果读取。默认走与 bjyb 相同的 SQL Server 连接，测试可换内存实现。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, NoReturn, Protocol

from src.interaction.ops_screening.models import (
    ScreeningFinding,
    ScreeningReadError,
    ScreeningResultsMissing,
    ScreeningResultsUnreadable,
    ScreeningRun,
    VerifyMark,
)
from src.interaction.ops_screening.sql import findings_sql, latest_run_sql, verify_sql

_SUCCEEDED = "succeeded"


class ScreeningReader(Protocol):
    def latest_succeeded(
        self,
        asked_start: datetime | None,
        asked_end: datetime | None,
    ) -> ScreeningRun | None: ...

    def findings(self, run_id: str, finding_type: str) -> list[ScreeningFinding]: ...

    def record_verify(self, finding_id: str, mark: VerifyMark) -> bool: ...


class MemoryScreeningReader:
    """测试与无库演练。过滤规则与 SQL 口径相同：成功批次、类型、主疑点。"""

    def __init__(
        self,
        runs: Sequence[ScreeningRun] = (),
        findings: Sequence[ScreeningFinding] = (),
        *,
        missing: bool = False,
        unreadable: bool = False,
    ) -> None:
        self._runs = list(runs)
        self._findings = list(findings)
        self._missing = missing
        self._unreadable = unreadable

    def latest_succeeded(
        self,
        asked_start: datetime | None,
        asked_end: datetime | None,
    ) -> ScreeningRun | None:
        self._guard()
        matched = [
            run for run in self._runs
            if run.status == _SUCCEEDED and _overlaps(run, asked_start, asked_end)
        ]
        if not matched:
            return None
        return max(matched, key=_run_sort_key)

    def findings(self, run_id: str, finding_type: str) -> list[ScreeningFinding]:
        self._guard()
        return [
            row for row in self._findings
            if row.run_id == run_id
            and row.finding_type == finding_type
            and row.is_primary
        ]

    def record_verify(self, finding_id: str, mark: VerifyMark) -> bool:
        self._guard()
        if mark not in VerifyMark:
            return False
        updated = False
        rewritten: list[ScreeningFinding] = []
        for row in self._findings:
            if row.finding_id == finding_id:
                rewritten.append(_replace_verify(row, mark.value))
                updated = True
            else:
                rewritten.append(row)
        self._findings = rewritten
        return updated

    def _guard(self) -> None:
        if self._missing:
            raise ScreeningResultsMissing("结果表不存在")
        if self._unreadable:
            raise ScreeningResultsUnreadable("读库失败")


class SqlServerScreeningReader:
    """只读查询 bjyb。表不存在时抛 ScreeningResultsMissing，不把异常当成 0 条。"""

    def __init__(self, connect: Callable[[], Any] | None = None) -> None:
        self._connect = connect or connect_bjyb

    def latest_succeeded(
        self,
        asked_start: datetime | None,
        asked_end: datetime | None,
    ) -> ScreeningRun | None:
        bounded = asked_start is not None or asked_end is not None
        sql, names = latest_run_sql(bounded=bounded)
        params: list[Any] = [_SUCCEEDED]
        if bounded:
            params.append(asked_end)
            params.append(asked_start)
        if len(params) != len(names):
            raise ScreeningResultsUnreadable("批次查询参数与语句不一致")
        rows = self._fetch(sql, params)
        if not rows:
            return None
        return _map_run(rows[0])

    def findings(self, run_id: str, finding_type: str) -> list[ScreeningFinding]:
        rows = self._fetch(findings_sql(), [run_id, finding_type])
        mapped = [_map_finding(row) for row in rows]
        # SQL 已按口径过滤。再挡一层：丢掉从属行，并按疑点编号去重，
        # 避免规则连接把同一条疑点乘进条数和金额。
        unique: list[ScreeningFinding] = []
        seen: set[str] = set()
        for row in mapped:
            if row.run_id != run_id or row.finding_type != finding_type or not row.is_primary:
                continue
            if row.finding_id in seen:
                continue
            seen.add(row.finding_id)
            unique.append(row)
        return unique

    def record_verify(self, finding_id: str, mark: VerifyMark) -> bool:
        if mark not in VerifyMark:
            return False
        # 连接是自动提交。用 OUTPUT 的返回行判断是否写上，不看 rowcount。
        written = self._fetch(verify_sql(), [mark.value, finding_id])
        return len(written) == 1

    def _fetch(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        conn = self._open()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, list(params))
            if cursor.description is None:
                return []
            columns = [col[0] for col in cursor.description]
            return [
                {columns[index]: value for index, value in enumerate(record)}
                for record in cursor.fetchall()
            ]
        except ScreeningResultsMissing:
            raise
        except Exception as exc:
            _raise_read_error(exc)
        finally:
            conn.close()
        return []

    def _open(self) -> Any:
        try:
            return self._connect()
        except ScreeningResultsMissing:
            raise
        except Exception as exc:
            raise ScreeningResultsUnreadable("暂时读不到筛查结果") from exc


def connect_bjyb() -> Any:
    """复用发现模块的 bjyb 环境变量连接，不另起数据源。"""
    from src.runtime.discovery.sqlserver_source import _connect, _env_fallback_conn_str

    conn_str = _env_fallback_conn_str()
    if not conn_str:
        raise ScreeningResultsUnreadable("未配置 bjyb 连接")
    return _connect(conn_str)


def get_reader() -> ScreeningReader:
    return SqlServerScreeningReader()


def _overlaps(run: ScreeningRun, start: datetime | None, end: datetime | None) -> bool:
    if start is None and end is None:
        return True
    if run.time_range_start is None or run.time_range_end is None:
        return False
    asked_start = start or datetime.min
    asked_end = end or datetime.max
    return run.time_range_start <= asked_end and run.time_range_end >= asked_start


def _run_sort_key(run: ScreeningRun) -> tuple[datetime, str]:
    return (run.finished_at or run.started_at or datetime.min, run.run_id)


def _replace_verify(row: ScreeningFinding, status: str) -> ScreeningFinding:
    return ScreeningFinding(
        finding_id=row.finding_id,
        primary_finding_id=row.primary_finding_id,
        run_id=row.run_id,
        rule_id=row.rule_id,
        rule_title=row.rule_title,
        source_clause=row.source_clause,
        settlement_key=row.settlement_key,
        fee_line_id=row.fee_line_id,
        item_code=row.item_code,
        item_name=row.item_name,
        amount=row.amount,
        finding_type=row.finding_type,
        evidence_clause=row.evidence_clause,
        evidence_facts=row.evidence_facts,
        verify_status=status,
        department_name=row.department_name,
        fee_item_name=row.fee_item_name,
        fee_amount=row.fee_amount,
        fee_item_code=row.fee_item_code,
    )


def _map_run(row: dict[str, Any]) -> ScreeningRun:
    return ScreeningRun(
        run_id=str(row.get("run_id") or ""),
        started_at=_as_datetime(row.get("started_at")),
        finished_at=_as_datetime(row.get("finished_at")),
        time_range_start=_as_datetime(row.get("time_range_start")),
        time_range_end=_as_datetime(row.get("time_range_end")),
    )


def _map_finding(row: dict[str, Any]) -> ScreeningFinding:
    return ScreeningFinding(
        finding_id=str(row.get("finding_id") or ""),
        primary_finding_id=str(row.get("primary_finding_id") or ""),
        run_id=str(row.get("run_id") or ""),
        rule_id=str(row.get("rule_id") or ""),
        rule_title=str(row.get("rule_title") or "未命名规则"),
        source_clause=str(row.get("source_clause") or ""),
        settlement_key=str(row.get("settlement_key") or ""),
        fee_line_id=str(row.get("fee_line_id") or ""),
        item_code=str(row.get("item_code") or ""),
        item_name=str(row.get("item_name") or ""),
        amount=_money(row.get("amount")),
        finding_type=str(row.get("finding_type") or ""),
        evidence_clause=str(row.get("evidence_clause") or ""),
        evidence_facts=str(row.get("evidence_facts") or ""),
        verify_status=str(row.get("verify_status") or "pending"),
        department_name=str(row.get("department_name") or "未关联科室"),
        fee_item_name=str(row.get("fee_item_name") or ""),
        fee_amount=_money(row.get("fee_amount")),
        fee_item_code=str(row.get("fee_item_code") or ""),
    )


def _money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _as_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if " " in fmt else text[:10], fmt)
        except ValueError:
            continue
    return None


def _missing_object(exc: Exception) -> bool:
    text = str(exc).lower()
    return "invalid object name" in text or "42s02" in text


def _raise_read_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ScreeningReadError):
        raise exc
    if _missing_object(exc):
        raise ScreeningResultsMissing("结果表不存在") from exc
    raise ScreeningResultsUnreadable("暂时读不到筛查结果") from exc
