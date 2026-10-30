"""二次保障和原单取证的真实游标列名、时点与安全降级契约。"""
from datetime import date
from decimal import Decimal

import pytest

from src.adapters.data_supply.outpatient_special_mz_queries import (
    derive_secondary_coverage_context, load_special_mz_fee_items,
)
from src.domain.insurance.fee_decomposition import RoundingMode
from src.runtime.policy_qa.fee_decomposition import snapshot_service
from types import SimpleNamespace
from src.adapters.base.models import AdapterCallStatus
from src.runtime.policy_qa.fee_decomposition.resident_special_catalog import adapt_mz_items_to_fee_line_items
from src.tests.unit.adapters.test_outpatient_decomposition_queries import _RoutingConn
from src.tests.unit.runtime.policy_qa.fee_decomposition import test_snapshot_service as helpers


@pytest.mark.parametrize("resident", [False, True])
def test_missing_special_fee_details_are_unavailable_in_both_services(monkeypatch, resident):
    from src.runtime.policy_qa.fee_decomposition import snapshot_service_special_mz as employee_service
    from src.runtime.policy_qa.fee_decomposition import snapshot_service_special_mz_resident as resident_service
    module = resident_service if resident else employee_service
    locate_name = "locate_special_mz_resident_registration" if resident else "locate_special_mz_registration"
    def result(data):
        return SimpleNamespace(status=AdapterCallStatus.SUCCESS, data=data)
    monkeypatch.setattr(module, locate_name, lambda *args: result(
        {"match_status": "unique_match", "registration_row": {"djh": "test"}}))
    monkeypatch.setattr(module, "load_special_mz_settlement", lambda *args: result(
        {"settlement_row": {"fyfs": "0", "jyrq": "2024-05-06"}}))
    monkeypatch.setattr(module, "load_special_mz_fee_items", lambda *args: result(
        {"item_rows": [], "row_count": 0}))
    if not resident:
        monkeypatch.setattr(module, "load_special_institution_level", lambda *args: result({"h_level": "02"}))
    from src.runtime.policy_qa.fee_decomposition import special_catalog_service
    monkeypatch.setattr(special_catalog_service, "read_special_catalog", lambda *args: pytest.fail("空明细应先终止"))
    monkeypatch.setattr(module, "load_special_mz_cycle", lambda *args: pytest.fail("空明细应先终止"))
    service = module.decompose_special_mz_resident_settlement if resident else module.decompose_special_mz_settlement
    decomposition = service(object(), "test", "H001", RoundingMode.HALF_UP).result
    assert decomposition.execution_status == "unavailable"
    assert "DETAIL_MISSING" in {u.code for u in decomposition.uncertainties}


def test_physical_uppercase_cursor_columns_preserve_proportional_and_price_limits():
    conn = _RoutingConn({"yb_mzfymx": (
        ("xh", "xmdm", "xmlb", "zje", "FEE_MEDIC_L", "FEE_SP_SCALE"),
        [(1, "D001", "0", Decimal("100"), Decimal("0.1"), Decimal("9.8"))])})
    rows = load_special_mz_fee_items(conn, "814").data["item_rows"]
    item, = adapt_mz_items_to_fee_line_items(rows, settle_date=date(2024, 5, 6))
    assert item.medic_l == Decimal("0.1")
    assert item.sp_scale == Decimal("9.8")
    assert conn.cursor_instance.executed[0][1] == ["814"]


@pytest.mark.parametrize("year,last,confirmed", [(2024, "current", True), (2023, "current", False),
                                                   (2024, "other", False), (2024, None, False)])
def test_secondary_annual_source_requires_year_and_current_transaction(year, last, confirmed):
    context = derive_secondary_coverage_context(
        {"fynd": year, "bnmcjylsh": last, "big_ill_sum_in": "30604", "civil_sum_pay": None},
        {"jyrq": "2024-05-06", "jylsh": "current"})
    assert (context.evidence_status == "confirmed") is confirmed
    assert context.is_post_trade is (True if confirmed else None)
    assert context.civil_fund_payment_total is None


@pytest.mark.parametrize("original_rows,card,fund,expected", [
    (1, "same", "91", True), (0, "same", "91", False), (2, "same", "91", False),
    (1, "other", "91", False), (1, "same", "92", False),
])
def test_refund_reads_unique_same_identity_original_without_current_year_fallback(
    monkeypatch, original_rows, card, fund, expected,
):
    current = helpers._trade_row(P_FundType="91", PN_PersonType="91", P_ICNo="same", TB_Year=2024,
        T_OraginalTradeNo="ORIGINAL", T_FeeAll="-100", T_FeeIn="-100")
    original = helpers._trade_row(T_TradeNo="ORIGINAL", P_FundType=fund, PN_PersonType="91",
        P_ICNo=card, TB_Year=2024)
    current.update(p_icno="same", tb_year=2024)
    original.update(p_icno=card, tb_year=2024)
    trade_columns = (*helpers._TRADE_COLS, "P_ICNo", "TB_Year")
    conn = helpers._service_conn(item_rows=[helpers._item_row(Fee="-100", Count="-1")])
    cursor = conn.cursor()
    original_execute = cursor.execute
    calls = []
    def execute(sql, params):
        calls.append((sql, list(params)))
        if "o_Trade" in sql:
            records = [original] * original_rows if params[0] == "ORIGINAL" else [current]
            cursor._active = (trade_columns,
                [tuple(row[c.lower()] for c in trade_columns) for row in records])
        else:
            original_execute(sql, params)
    cursor.execute = execute
    monkeypatch.setattr(snapshot_service, "derive_in_hospital_accumulation",
        lambda *args: pytest.fail("退费不能用当前年度历史兜底"))
    captured = []
    kernel = snapshot_service._KERNEL_BY_PROFILE[("resident", "outpatient")]
    def capture(snapshot):
        captured.append(snapshot)
        return kernel(snapshot)
    monkeypatch.setitem(snapshot_service._KERNEL_BY_PROFILE, ("resident", "outpatient"), capture)
    result = snapshot_service.decompose_outpatient_trade(conn, "T001", "H001", RoundingMode.HALF_UP,
        profile_resolver=lambda row: ("resident", "outpatient"), accumulation_caliber_confirmed=True).result
    assert captured
    assert (captured[0].original_policy_context is not None) is expected
    assert any("o_Trade" in sql and params[0] == "ORIGINAL" for sql, params in calls)
    if not expected:
        assert "ORIGINAL_POLICY_CONTEXT_UNCONFIRMED" in {u.code for u in result.uncertainties}
