"""门诊运营分析活库冒烟 — issue #40 P3。

验证 OpsAnalyticsService 的常量聚合 SQL（口径句 v4 谓词、双引号列名、
ARRAY_AGG 批次聚合、参数化过滤）在真实 PostgreSQL（public.mz_trade）上成立，
且冻结语义在活库数据上保持：人次/次均/科室 unavailable、结论引用指标批次。
只读不写，无清理需求。
环境依赖: PostgreSQL（127.0.0.1:5432/hospital_mcp，与生产同构）；不可用时整组 skip。
"""
from __future__ import annotations

import pytest

from src.runtime.ops_analytics.service import OpsAnalyticsService


def _pg_ready() -> bool:
    try:
        from src.data_platform.storage.postgresql.client import PostgreSQLClient

        PostgreSQLClient().execute("SELECT 1")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _pg_ready(), reason="PostgreSQL 不可用，跳过活库冒烟")


@pytest.fixture
def service() -> OpsAnalyticsService:
    from src.data_platform.storage.postgresql.client import PostgreSQLClient

    return OpsAnalyticsService(PostgreSQLClient(), model_gateway=None)


def test_overview_runs_on_live_mz_trade(service: OpsAnalyticsService):
    ov = service.overview()
    by_code = {c.metric_code: c for c in ov.cards}
    # 四个可用卡 complete 且值非 None（活库 588 行，v4 范围内有数据）
    for code in (
        "mzjyxx.op_valid_settle_count", "mzjyxx.op_total_fee",
        "mzjyxx.op_fund_pay", "mzjyxx.op_self_pay",
    ):
        assert by_code[code].result_status == "complete", code
        assert by_code[code].value is not None, code
    # 冻结语义在活库上保持：人次/次均 unavailable
    assert by_code["mzjyxx.insured_encounter_count"].result_status == "unavailable"
    assert by_code["mzjyxx.average_fee"].result_status == "unavailable"
    # 与已签核加工视图对账：四指标值必须与 v_op_outpatient_processed 完全一致
    from src.data_platform.storage.postgresql.client import PostgreSQLClient

    view_row = PostgreSQLClient().execute("SELECT * FROM public.v_op_outpatient_processed")[0]
    assert by_code["mzjyxx.op_valid_settle_count"].value == view_row["op_valid_settle_count"]
    assert by_code["mzjyxx.op_total_fee"].value == float(view_row["op_total_fee"])
    assert by_code["mzjyxx.op_fund_pay"].value == float(view_row["op_fund_pay"])
    assert by_code["mzjyxx.op_self_pay"].value == float(view_row["op_self_pay"])
    # 指标批次溯源
    assert ov.data_batch_ids, "活库 mz_trade 应至少有一个 data_batch_id"


def test_breakdown_and_drill_run_on_live(service: OpsAnalyticsService):
    bd = service.breakdown("fund_type")
    assert bd.result_status == "complete"
    assert bd.items, "活库按险种拆分应有数据"
    assert bd.data_batch_ids

    drill = service.drill(dimension="fund_type", value=bd.items[0].code, limit=5)
    assert drill.result_status == "complete"
    assert 0 < len(drill.rows) <= 5
    assert all(r.data_batch_id for r in drill.rows), "每行必须携带指标批次"

    trend = service.trend(months=24)
    assert trend, "活库月度趋势应有数据"
    assert [p.month for p in trend] == sorted(p.month for p in trend)


def test_weekly_report_runs_on_live(service: OpsAnalyticsService):
    """用口径句 v4 有效范围内最后一天所在周，保证至少一周有数据。"""
    import datetime as dt

    # overview 的 date_max 是 v4 范围内的最大交易日期（全表 max 可能是无效结算行）
    date_max = service.overview().date_max
    assert date_max, "v4 范围内应有数据"
    max_date = dt.date.fromisoformat(date_max[:10])
    week_start = max_date - dt.timedelta(days=max_date.weekday())
    report = service.weekly_report(week_start=week_start.isoformat())
    assert report.result_status in ("complete", "partial")
    assert report.current_week_rows + report.previous_week_rows > 0
    for conclusion in report.conclusions:
        refs = [c for c in conclusion.citations if c["type"] == "metric_batch"]
        assert refs, "每条结论必须引用指标批次"
    # 模型未配置 → 摘要降级且声明不确定性
    assert report.summary is None
    assert report.uncertainties
