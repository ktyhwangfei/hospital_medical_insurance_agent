"""筛查结果写到 bjyb 的 SQL Server，语句带参数，费用行号对得上问数。"""
from __future__ import annotations

from datetime import datetime, timezone

from src.data_platform.storage.screening_rules.sqlserver import (
    SqlServerScreeningRuleStorage,
    bind_datetime,
)
from src.data_platform.storage.screening_rules.sqlserver_schema import SQLSERVER_SCREENING_DDL
from src.domain.screening_rules.models import (
    FindingType,
    RuleClass,
    RuleStatus,
    ScreeningFinding,
    ScreeningRule,
    VerifyStatus,
)
from src.runtime.screening_rules.fee_line_loader import FEE_LINE_SQL, load_fee_lines


class _Cursor:
    def __init__(self, conn: "_Conn") -> None:
        self.conn = conn
        self.description = None
        self._rows: list[tuple] = []

    def execute(self, sql, params=None):
        self.conn.calls.append((sql, list(params or [])))
        if sql.lstrip().upper().startswith("SELECT"):
            self.description = self.conn.select_description
            self._rows = list(self.conn.select_rows)
        else:
            self.description = None
            self._rows = []

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list]] = []
        self.select_description: list[tuple[str]] = []
        self.select_rows: list[tuple] = []

    def cursor(self):
        return _Cursor(self)

    def close(self):
        return None


def test_ddl_targets_sql_server_tables() -> None:
    text = "\n".join(SQLSERVER_SCREENING_DDL)
    for name in ("ai_screen_rule", "ai_screen_run", "ai_screen_run_rule", "ai_screen_finding"):
        assert f"dbo.{name}" in text
    assert "[class]" in text
    assert "IF OBJECT_ID" in text
    assert "JSONB" not in text
    assert "mz_trade" not in text


def test_insert_rule_keeps_the_id_in_parameters() -> None:
    conn = _Conn()
    store = SqlServerScreeningRuleStorage(connect=lambda: conn, ensure=False)
    now = datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc)
    store.insert_rule(ScreeningRule(
        rule_id="sr_thyroid",
        source_doc="清单",
        source_clause="开展甲状腺癌扩大根治术，重复收取甲状腺癌根治术费用",
        title="甲状腺重复收费",
        condition_text="同单同时收取",
        rule_class=RuleClass.EXECUTABLE,
        status=RuleStatus.CANDIDATE,
        condition_spec={"kind": "cocharge"},
        created_at=now,
        updated_at=now,
    ))
    sql, params = conn.calls[-1]
    assert "INSERT INTO dbo.ai_screen_rule" in sql
    assert "?" in sql
    assert "sr_thyroid" not in sql
    assert params[0] == "sr_thyroid"
    assert params[10] == bind_datetime(now)
    assert params[10].tzinfo is None


def test_get_rule_reads_the_class_alias() -> None:
    conn = _Conn()
    now = datetime(2026, 11, 17, 8, 0)
    conn.select_description = [
        ("rule_id",), ("source_doc",), ("source_clause",), ("title",), ("condition_text",),
        ("rule_class",), ("mapping_gap",), ("status",), ("condition_spec",),
        ("source_item_ref",), ("created_at",), ("updated_at",), ("approved_at",),
        ("approved_by",),
    ]
    conn.select_rows = [(
        "sr_thyroid", "清单", "原条款", "标题", "条件", "executable", None, "candidate",
        '{"kind": "cocharge"}', "1", now, now, None, None,
    )]
    store = SqlServerScreeningRuleStorage(connect=lambda: conn, ensure=False)
    rule = store.get_rule("sr_thyroid")
    assert rule.rule_class is RuleClass.EXECUTABLE
    assert rule.condition_spec == {"kind": "cocharge"}
    assert "sr_thyroid" not in conn.calls[-1][0]


def test_verify_update_touches_only_verify_status() -> None:
    conn = _Conn()
    store = SqlServerScreeningRuleStorage(connect=lambda: conn, ensure=False)
    now = datetime(2026, 11, 17, 8, 0)
    store.update_finding(ScreeningFinding(
        finding_id="sf_1",
        run_id="srun_1",
        rule_id="sr_1",
        settlement_key="T1",
        finding_type=FindingType.MISMATCH,
        primary_finding_id="sf_1",
        evidence_clause="原条款",
        verify_status=VerifyStatus.FOLLOW,
        created_at=now,
    ))
    sql, params = conn.calls[-1]
    assert sql.startswith("UPDATE dbo.ai_screen_finding SET verify_status = ?")
    assert "amount" not in sql
    assert "ai_screen_rule" not in sql
    assert params == ["follow", "sf_1"]


def test_fee_lines_come_from_bjyb_and_use_item_id() -> None:
    assert "dbo.o_FeeItem" in FEE_LINE_SQL
    assert "dbo.o_Trade" in FEE_LINE_SQL
    assert "CONVERT(nvarchar(64), fi.ItemId)" in FEE_LINE_SQL
    assert "mz_fee_item" not in FEE_LINE_SQL
    assert "?" in FEE_LINE_SQL

    conn = _Conn()
    conn.select_description = [
        ("settlement_key",), ("fee_line_id",), ("item_code",), ("item_name",), ("amount",),
    ]
    conn.select_rows = [("T001", "88", "A2", "甲状腺癌根治术", 120.5)]
    lines = load_fee_lines(
        datetime(2026, 1, 1),
        datetime(2026, 1, 2),
        connect=lambda: conn,
    )
    assert lines[0].settlement_key == "T001"
    assert lines[0].fee_line_id == "88"
    assert lines[0].amount == 120.5
    assert conn.calls[-1][1][0] == datetime(2026, 1, 1)
