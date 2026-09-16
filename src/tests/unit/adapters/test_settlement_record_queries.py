"""结算事实记录查询适配器单元测试：只读守卫 + 行映射（无数据库依赖）。"""

import pytest

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply import settlement_record_queries as queries


def test_assert_read_only_select_rejects_non_select_and_multi_statement() -> None:
    assert queries.assert_read_only_select(" SELECT 1 ") == "SELECT 1"
    assert queries.assert_read_only_select("(SELECT 1)") == "(SELECT 1)"

    with pytest.raises(ValueError, match="非只读单语句"):
        queries.assert_read_only_select("DELETE FROM dbo.o_Trade")
    with pytest.raises(ValueError, match="非只读单语句"):
        queries.assert_read_only_select("SELECT 1; DROP TABLE dbo.o_Trade")
    with pytest.raises(ValueError, match="非只读单语句"):
        queries.assert_read_only_select("UPDATE dbo.o_Trade SET T_FeeAll = 0")


class _FakeCursor:
    """最小游标桩：记录 SQL/参数，返回预置行。"""

    def __init__(self, cols, rows):
        self._cols = cols
        self._rows = rows
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql, params))

    @property
    def description(self):
        return [(c,) for c in self._cols]

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cols, rows):
        self._cursor = _FakeCursor(cols, rows)

    def cursor(self):
        return self._cursor


def test_query_inpatient_refund_records_maps_rows() -> None:
    conn = _FakeConn(
        ["djh", "jylsh", "jyrq", "zje", "tflydjh", "STMT_STATE"],
        [(1001, "JL001", "2026-01-02", -5.0, 1001, "1")],
    )

    result = queries.query_inpatient_refund_records(conn, "1001")

    assert result.status == AdapterCallStatus.SUCCESS
    assert result.data["refunded_count"] == 1
    record = result.data["records"][0]
    assert record["original_trade_no"] == "1001"
    assert record["refund_side"] == "yb_inpatient"


def test_query_outpatient_refund_records_requires_identity_and_masks_it() -> None:
    conn = _FakeConn(
        ["T_TradeNo", "T_TradeDate", "T_FeeAll", "T_FeeIn", "T_FundPay", "T_HasRefundmented",
         "TR_OraginalTradeNo", "TR_RefundmentTradeNo", "T_PartialReturnFlag", "T_OraginalTradeNo"],
        [("T100", "2026-01-02 10:00:00", -5.0, 0.0, 0.0, 1, "T099", "", "", "")],
    )

    result = queries.query_outpatient_refund_records(conn, id_card="110101199001011234")

    assert result.status == AdapterCallStatus.SUCCESS
    assert result.data["refunded_count"] == 1
    assert result.data["records"][0]["original_trade_no"] == "T099"
    # 输出不含身份证原文
    assert "110101199001011234" not in str(result.data)


def test_query_fee_detail_projects_safe_fields() -> None:
    conn = _FakeConn(
        ["xh", "xmdm", "xmmc", "NATION_CODE", "sflb", "sl", "dj", "zje", "ybnje", "ybwje",
         "txfy", "grziftw", "fsrq"],
        [(1, "X001", "达克罗宁", "86978998000012", "西药", 1, 100.0, 100.0, 85.0, 15.0, 0.0, 0.0,
          "2026-01-02")],
    )

    result = queries.query_fee_detail(conn, "1001")

    assert result.status == AdapterCallStatus.SUCCESS
    item = result.data["items"][0]
    assert item["nation_code"] == "86978998000012"
    assert item["insurance_inner_amount"] == 85.0
    assert item["service_type"] == "普通住院"


def test_resolve_settlements_by_person_multiple_candidates_never_auto_selects() -> None:
    class _RoutingCursor:
        """仅门诊侧（o_Trade）命中两笔，住院侧（yb_brdjxx）无登记。"""

        def __init__(self):
            self._active = None

        def execute(self, sql, params):
            if "yb_brdjxx" in sql:
                self._active = ("djh", "ryrq", "cyrq", "yllb", "zje"), []
            else:
                self._active = ("T_TradeNo", "T_TradeDate", "T_FeeAll", "T_FundPay"), \
                    [("T100", "2026-01-02", 100.0, 85.0), ("T101", "2026-01-02", 200.0, 170.0)]

        @property
        def description(self):
            return [(c,) for c in self._active[0]]

        def fetchall(self):
            return self._active[1]

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _RoutingCursor()

    result = queries.resolve_settlements_by_person(
        _Conn(), id_card="x", visit_date="2026-01-02"
    )

    assert result.data["match_status"] == "multiple_candidates"
    assert len(result.data["settlement_candidates"]) == 2
    assert "澄清" in result.data["resolve_note"]


def test_query_benefit_stacking_reports_low_income_uncertainty() -> None:
    class _RoutingCursor:
        """按 SQL 文本路由：登记查询（yb_brdjxx）返回 reg 行，分摊查询返回 ben 行。"""

        def __init__(self):
            self._active = None

        def execute(self, sql, params):
            if "yb_brdjxx" in sql:
                self._active = ("tsb1", "tsb2", "tsb3", "tsbqsrq", "tsbjzrq", "dbzbs", "CIVIL_TYPE", "rylx"), \
                    [("TE01", "", "", "2026-01-01", "", "", "", "1")]
            else:
                self._active = ("BIG_ILL_PAY", "CIVIL_IN", "DB_PAY_TRUE", "MAF_PAY_TRUE"), \
                    [(500.0, 300.0, 0.0, 0.0)]

        @property
        def description(self):
            return [(c,) for c in self._active[0]]

        def fetchall(self):
            return self._active[1]

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _RoutingCursor()

    result = queries.query_benefit_stacking(_Conn(), "1001")

    assert result.data["special_disease_registered"] is True
    assert result.data["special_disease_codes"] == ["TE01"]
    assert result.data["big_ill_pay"] == 500.0
    assert any("低保" in u for u in result.data["uncertainties"])
