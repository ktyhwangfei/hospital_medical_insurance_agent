"""按人定位费用分解候选查询适配器单元测试（fake conn 模式，无数据库依赖）。

覆盖（ Issue #78 费用分解工作台「按身份证号定位」）：
- 身份证格式判定（15 位 / 18 位末位 X/x；交易号、djh、非法长度不误判）；
- SQL 参数化（身份证号只进参数不进 SQL 文本）；
- 身份列只进 WHERE 不进 SELECT（输出绝不回显身份原文）；
- 职工/居民/肾移植定额标签映射；多候选/唯一/空结果三态；
- LIMIT 50 截断标记；查询失败统一 FAILED；日志不含身份证原文。
"""
from __future__ import annotations

import logging

import pytest

from src.adapters.base.models import AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply import decomposition_person_queries as q

ID_CARD = "110101199001011234"
ID_CARD_15 = "110101900101123"

_TRADE_COLS = ("T_TradeNo", "T_TradeDate", "T_FeeAll", "P_FundType")
_SPECIAL_COLS = ("djh", "ryrq", "FUND_TYPE", "tsb1", "tsb2", "tsb3")


def _trade_row(trade_no="T001", trade_date="2024-06-01", fee_all="100.00",
               fund_type="3") -> tuple:
    return (trade_no, trade_date, fee_all, fund_type)


def _special_row(djh="9001", ryrq="2024-03-01", fund_type="3",
                 tsb1=None, tsb2=None, tsb3=None) -> tuple:
    return (djh, ryrq, fund_type, tsb1, tsb2, tsb3)


class _RoutingCursor:
    """按 SQL 中表名分发的游标桩；routes: {表名片段: (cols, rows)}。"""

    def __init__(self, routes):
        self._routes = routes
        self._active = ((), [])
        self.executed: list[tuple[str, list]] = []

    def execute(self, sql, params):
        self.executed.append((sql, list(params)))
        for fragment, spec in self._routes.items():
            if fragment in sql:
                self._active = spec
                return
        self._active = ((), [])

    @property
    def description(self):
        return [(c,) for c in self._active[0]]

    def fetchall(self):
        return self._active[1]

    def close(self):
        pass


class _RoutingConn:
    def __init__(self, routes):
        self.cursor_instance = _RoutingCursor(routes)

    def cursor(self):
        return self.cursor_instance


def _conn(trade_rows=(), special_rows=()) -> _RoutingConn:
    return _RoutingConn({
        "o_Trade": (_TRADE_COLS, list(trade_rows)),
        "yb_brdjxx": (_SPECIAL_COLS, list(special_rows)),
    })


def _executed(conn: _RoutingConn, fragment: str) -> tuple[str, list]:
    """取含指定表名片段的那条已执行 SQL。"""
    for sql, params in conn.cursor_instance.executed:
        if fragment in sql:
            return sql, params
    raise AssertionError(f"未执行含 {fragment} 的 SQL: {conn.cursor_instance.executed}")


# ── 身份证格式判定 ────────────────────────────────────────────


class TestIdCardFormat:
    @pytest.mark.parametrize("value", [ID_CARD, "11010119900101123X",
                                       "11010119900101123x", ID_CARD_15])
    def test_valid_formats(self, value):
        assert q.is_id_card_format(value) is True

    @pytest.mark.parametrize("value", [
        "011100030X240311000031",  # 24 位门诊交易号（历史误判源）
        "604",                      # 门特登记号 djh
        "11010119900101123",        # 17 位
        "1101011990010112345",      # 19 位
        "11010119900101123A",       # 末位非 X
        "11010119900101A234",       # 中间含字母
        "",                         # 空
    ])
    def test_invalid_formats(self, value):
        assert q.is_id_card_format(value) is False


# ── SQL 构造：参数化 + 身份列只进 WHERE ────────────────────────


class TestSqlConstruction:
    def test_id_card_parameterized_never_in_sql(self):
        conn = _conn(trade_rows=[_trade_row()])
        q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        for sql, params in conn.cursor_instance.executed:
            assert ID_CARD not in sql  # 防注入：身份原文只进参数
        _, op_params = _executed(conn, "o_Trade")
        assert op_params == [ID_CARD, ID_CARD, ID_CARD]  # P_IDNo/P_ICNo/P_CardNo
        _, sp_params = _executed(conn, "yb_brdjxx")
        assert ID_CARD in sp_params  # sfz/kh 各一次

    def test_identity_columns_only_in_where_not_select(self):
        """铁律：WHERE 过滤可以用身份列，SELECT 输出绝不回显身份列。"""
        conn = _conn(trade_rows=[_trade_row()])
        q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        op_sql, _ = _executed(conn, "o_Trade")
        select_part, where_part = op_sql.split("WHERE", 1)
        for col in ("P_IDNo", "P_ICNo", "P_CardNo"):
            assert col not in select_part
            assert col in where_part
        sp_sql, _ = _executed(conn, "yb_brdjxx")
        sp_select, sp_where = sp_sql.split("WHERE", 1)
        for col in ("sfz", "kh"):
            assert col not in sp_select
            assert col in sp_where

    def test_outpatient_ordered_by_trade_date_desc_with_limit(self):
        conn = _conn(trade_rows=[_trade_row()])
        q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        op_sql, _ = _executed(conn, "o_Trade")
        assert "ORDER BY" in op_sql and "DESC" in op_sql
        assert "T_TradeDate" in op_sql.split("ORDER BY", 1)[1]
        assert "TOP" in op_sql.upper()  # 有界枚举（LIMIT 50 + 1 探测截断）

    def test_special_filters_yllb_and_fyfs(self):
        conn = _conn(special_rows=[_special_row()])
        q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        sp_sql, sp_params = _executed(conn, "yb_brdjxx")
        assert "yb_mzjyxx" in sp_sql  # JOIN 结算表过滤 fyfs='0'
        # yllb='12' 与 fyfs='0' 参数化
        assert "12" in sp_params and "0" in sp_params


# ── 候选组装与标签映射 ────────────────────────────────────────


class TestCandidateAssembly:
    def test_unique_match(self):
        conn = _conn(trade_rows=[_trade_row()])
        result = q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        assert result.status == AdapterCallStatus.SUCCESS
        assert result.data["match_status"] == "unique_match"
        assert result.data["truncated"] is False
        candidate = result.data["candidates"][0]
        assert candidate["chain"] == "outpatient"
        assert candidate["identifier"] == "T001"
        assert candidate["chain_label"] == "普通门诊"
        assert candidate["profile_label"] == "城镇职工"
        assert candidate["service_date"] == "2024-06-01"
        assert candidate["total_amount"] == "100.00"

    def test_resident_fund_type_label(self):
        conn = _conn(trade_rows=[_trade_row(fund_type="92")])
        result = q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        assert result.data["candidates"][0]["profile_label"] == "城乡居民"

    def test_unknown_fund_type_label_none(self):
        conn = _conn(trade_rows=[_trade_row(fund_type="7")])
        result = q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        assert result.data["candidates"][0]["profile_label"] is None

    def test_special_employee_and_kidney_labels(self):
        conn = _conn(special_rows=[
            _special_row(djh="9001"),                    # 职工普通门特
            _special_row(djh="9002", tsb2="503"),        # 肾移植定额
            _special_row(djh="9003", fund_type="91"),    # 居民门特
        ])
        result = q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        assert result.data["match_status"] == "multiple_candidates"
        by_djh = {c["identifier"]: c for c in result.data["candidates"]}
        kidney = by_djh["9002"]
        assert kidney["chain"] == "special"
        assert kidney["chain_label"] == "门诊特殊病·肾移植定额"
        assert kidney["profile_label"] == "城镇职工"
        assert by_djh["9001"]["chain_label"] == "门诊特殊病"
        assert by_djh["9003"]["profile_label"] == "城乡居民"
        # 门特候选不带总金额（登记表无费用口径）
        assert kidney["total_amount"] is None
        assert kidney["service_date"] == "2024-03-01"

    def test_no_match(self):
        result = q.resolve_decomposition_targets_by_person(_conn(), ID_CARD)
        assert result.data["match_status"] == "no_match"
        assert result.data["candidates"] == []

    def test_candidates_never_carry_identity_columns(self):
        conn = _conn(trade_rows=[_trade_row()], special_rows=[_special_row()])
        result = q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        for candidate in result.data["candidates"]:
            for key in candidate:
                assert key not in ("p_idno", "p_icno", "p_cardno", "sfz", "kh")
            assert ID_CARD not in str(candidate)


# ── 截断与失败语义 ────────────────────────────────────────────


class TestTruncationAndFailure:
    def test_over_limit_truncated_and_noted(self):
        rows = [_trade_row(trade_no=f"T{i:03d}") for i in range(51)]
        conn = _conn(trade_rows=rows)
        result = q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        assert result.data["truncated"] is True
        assert len(result.data["candidates"]) == 50
        assert any("截断" in note for note in result.data["notes"])
        assert result.data["match_status"] == "multiple_candidates"

    def test_exactly_at_limit_not_truncated(self):
        rows = [_trade_row(trade_no=f"T{i:03d}") for i in range(50)]
        conn = _conn(trade_rows=rows)
        result = q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        assert result.data["truncated"] is False
        assert len(result.data["candidates"]) == 50

    def test_query_error_returns_failed_without_id_card(self):
        class _BoomCursor:
            def execute(self, sql, params):
                raise RuntimeError("db down")

            def close(self):
                pass

        class _BoomConn:
            def cursor(self):
                return _BoomCursor()

        result = q.resolve_decomposition_targets_by_person(_BoomConn(), ID_CARD)
        assert result.status == AdapterCallStatus.FAILED
        assert result.error_type == "DATASOURCE_QUERY_FAILED"
        assert result.data_quality == DataQualityStatus.MISSING
        assert ID_CARD not in (result.message or "")

    def test_blank_id_card_rejected(self):
        result = q.resolve_decomposition_targets_by_person(_conn(), "  ")
        assert result.status == AdapterCallStatus.FAILED


class TestLogMasking:
    def test_log_never_contains_raw_id_card(self, caplog):
        conn = _conn(trade_rows=[_trade_row()])
        with caplog.at_level(logging.INFO):
            q.resolve_decomposition_targets_by_person(conn, ID_CARD)
        assert ID_CARD not in caplog.text
        # 脱敏同款：前 3 后 4
        assert "110***********1234" in caplog.text
