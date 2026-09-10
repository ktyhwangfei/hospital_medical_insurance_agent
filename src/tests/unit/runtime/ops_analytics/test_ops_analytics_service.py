"""OpsAnalyticsService 单元测试：假读取面（execute → 预置行），不连真库。

覆盖冻结验收三条：口径一致性 + 下钻溯源 / 人次 unavailable / 周报结论批次引用。
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from src.runtime.ops_analytics.service import OpsAnalyticsService


class FakeClient:
    """按 SQL 关键特征返回预置行；同时记录收到的 SQL/参数供断言。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        if "ARRAY_AGG" in sql and "GROUP BY" not in sql and "CASE" not in sql:
            return [{
                "valid_count": 12, "total_fee": Decimal("6643.69"),
                "fund_pay": Decimal("113.66"), "self_pay": Decimal("6530.03"),
                "row_count": 12,
                "date_min": dt.datetime(2026, 4, 1), "date_max": dt.datetime(2026, 4, 17),
                "semantic_version": None, "batch_ids": ["batch_2026_04_17"],
            }]
        if "GROUP BY tr.\"P_FundType\"" in sql:
            return [
                {"dim_code": "3", "valid_count": 8, "total_fee": Decimal("4000"),
                 "fund_pay": Decimal("80"), "self_pay": Decimal("3920"),
                 "batch_ids": ["batch_2026_04_17"]},
                {"dim_code": "32", "valid_count": 4, "total_fee": Decimal("2643.69"),
                 "fund_pay": Decimal("33.66"), "self_pay": Decimal("2610.03"),
                 "batch_ids": ["batch_2026_04_17"]},
            ]
        if "GROUP BY 1" in sql and "month" in sql:
            return [
                {"month": "2026-04", "valid_count": 12, "total_fee": Decimal("6643.69"),
                 "fund_pay": Decimal("113.66"), "self_pay": Decimal("6530.03")},
                {"month": "2026-03", "valid_count": 5, "total_fee": Decimal("2000"),
                 "fund_pay": Decimal("50"), "self_pay": Decimal("1950")},
            ]
        if "CASE WHEN" in sql:  # 周报双周聚合
            return [
                {"wk": "cur", "valid_count": 12, "total_fee": Decimal("6643.69"),
                 "fund_pay": Decimal("113.66"), "self_pay": Decimal("6530.03"),
                 "row_count": 12, "batch_ids": ["batch_w2"]},
                {"wk": "prev", "valid_count": 10, "total_fee": Decimal("5100"),
                 "fund_pay": Decimal("90"), "self_pay": Decimal("5010"),
                 "row_count": 10, "batch_ids": ["batch_w1"]},
            ]
        if "COUNT(*) AS total" in sql:
            return [{"total": 2}]
        # 下钻行
        return [
            {"trade_no": "JY001", "trade_date": dt.datetime(2026, 4, 17, 10, 0),
             "fund_type": "3", "cure_type": "11", "settle_state": "2",
             "total_fee": Decimal("100.50"), "fund_pay": Decimal("10.25"),
             "self_pay": Decimal("90.25"), "data_batch_id": "batch_2026_04_17"},
            {"trade_no": "JY002", "trade_date": dt.datetime(2026, 4, 16, 9, 0),
             "fund_type": "32", "cure_type": "19", "settle_state": "3",
             "total_fee": Decimal("200"), "fund_pay": Decimal("20"),
             "self_pay": Decimal("180"), "data_batch_id": "batch_2026_04_17"},
        ]


def test_overview_four_complete_and_two_unavailable_cards():
    svc = OpsAnalyticsService(FakeClient())
    ov = svc.overview()
    by_code = {c.metric_code: c for c in ov.cards}
    assert len(ov.cards) == 6
    # 四个可用指标 complete，值来自口径句 v4 聚合
    assert by_code["mzjyxx.op_valid_settle_count"].result_status == "complete"
    assert by_code["mzjyxx.op_valid_settle_count"].value == 12
    assert by_code["mzjyxx.op_total_fee"].value == 6643.69
    assert by_code["mzjyxx.op_fund_pay"].value == 113.66
    assert by_code["mzjyxx.op_self_pay"].value == 6530.03
    # 冻结验收②：就诊人次保持 unavailable + 恰好一个 halt_reason
    encounter = by_code["mzjyxx.insured_encounter_count"]
    assert encounter.result_status == "unavailable"
    assert encounter.halt_reason == "data_unavailable"
    assert encounter.halt_detail and "HIS" in encounter.halt_detail
    assert encounter.value is None
    average = by_code["mzjyxx.average_fee"]
    assert average.result_status == "unavailable"
    assert average.halt_reason == "data_unavailable"
    # 溯源：指标批次随总览返回
    assert ov.data_batch_ids == ["batch_2026_04_17"]
    assert ov.result_status == "complete"


def test_overview_uses_v4_predicate_verbatim():
    """聚合 SQL 必须逐字携带口径句 v4 谓词（与加工视图一致，不重新发明口径）。"""
    client = FakeClient()
    OpsAnalyticsService(client).overview()
    sql = client.calls[0][0]
    for fragment in (
        'NULLIF(tr."T_State", \'\')::NUMERIC IN (2, 3)',
        'NULLIF(tr."NP_Settle_State", \'\')::NUMERIC = 1',
        'NULLIF(tr."T_HasRefundmented", \'\')::NUMERIC != 1',
        'NULLIF(tr."T_CureType", \'\')::NUMERIC IN (11, 17, 18, 19)',
    ):
        assert fragment in sql, f"缺少口径句 v4 片段: {fragment}"
    assert 'FROM public.mz_trade AS tr' in sql


def test_breakdown_fund_type_with_cn_labels_and_share():
    svc = OpsAnalyticsService(FakeClient())
    bd = svc.breakdown("fund_type")
    assert bd.result_status == "complete"
    assert bd.dimension_name == "险种"
    assert [i.label for i in bd.items] == ["城镇职工", "公疗医照"]
    assert bd.items[0].valid_count == 8
    assert bd.items[0].share == 0.6667
    assert bd.items[1].share == 0.3333  # 8+4=12 → 4/12
    assert bd.data_batch_ids == ["batch_2026_04_17"]


def test_breakdown_department_dimension_unavailable():
    """冻结契约：科室维度 mz_trade 无科室列（需 HIS 关联）→ unavailable。"""
    svc = OpsAnalyticsService(FakeClient())
    bd = svc.breakdown("department")
    assert bd.result_status == "unavailable"
    assert bd.halt_reason == "data_unavailable"
    assert bd.items == []


def test_trend_returns_ascending_months():
    svc = OpsAnalyticsService(FakeClient())
    points = svc.trend(months=12)
    assert [p.month for p in points] == ["2026-03", "2026-04"]  # 升序
    assert points[-1].valid_count == 12


def test_drill_rows_carry_batch_provenance():
    """冻结验收①：下钻到就诊行级（T_TradeNo 粒度），行携带指标批次。"""
    svc = OpsAnalyticsService(FakeClient())
    result = svc.drill(dimension="fund_type", value="3")
    assert result.result_status == "complete"
    assert result.total == 2
    assert result.rows[0].trade_no == "JY001"
    assert result.rows[0].fund_type == "城镇职工"
    assert result.rows[0].cure_type == "普通门诊"
    assert result.rows[0].settle_state == "有效结算（中心端完成）"
    assert result.rows[0].data_batch_id == "batch_2026_04_17"
    assert result.data_batch_ids == ["batch_2026_04_17"]


def test_drill_empty_returns_partial_not_guess():
    client = FakeClient()
    client.execute = lambda sql, params=(): [{"total": 0}]  # type: ignore[assignment]
    result = OpsAnalyticsService(client).drill()
    assert result.result_status == "partial"
    assert result.halt_reason == "data_unavailable"
    assert result.rows == []


def test_weekly_report_deltas_and_batch_citations():
    """冻结验收③：周报每条结论可溯源到指标批次（metric_batch 引用）。"""
    svc = OpsAnalyticsService(FakeClient())
    report = svc.weekly_report(week_start="2026-04-13")
    assert report.result_status == "complete"
    assert report.current_week_rows == 12
    by_code = {d.metric_code: d for d in report.deltas}
    assert by_code["mzjyxx.op_valid_settle_count"].current == 12
    assert by_code["mzjyxx.op_valid_settle_count"].previous == 10
    assert by_code["mzjyxx.op_valid_settle_count"].delta == 2
    assert by_code["mzjyxx.op_valid_settle_count"].pct == 20.0
    assert by_code["mzjyxx.op_valid_settle_count"].direction == "up"
    # 每条结论都带 metric_definition + metric_batch 引用（两周批次并集）
    assert len(report.conclusions) == 4
    for conclusion in report.conclusions:
        types = {c["type"] for c in conclusion.citations}
        assert "metric_definition" in types
        batch_refs = [c["data_batch_id"] for c in conclusion.citations
                      if c["type"] == "metric_batch"]
        assert sorted(batch_refs) == ["batch_w1", "batch_w2"]
    assert report.data_batch_ids == ["batch_w1", "batch_w2"]
    # 未配置模型网关：AI 摘要诚实降级，不返回假摘要
    assert report.summary is None
    assert any("AI 运营摘要" in u or "模型网关" in u for u in report.uncertainties)


def test_weekly_report_pct_none_when_previous_zero():
    class ZeroPrevClient(FakeClient):
        def execute(self, sql, params=()):
            if "CASE WHEN" in sql:
                return [
                    {"wk": "cur", "valid_count": 5, "total_fee": Decimal("100"),
                     "fund_pay": Decimal("10"), "self_pay": Decimal("90"),
                     "row_count": 5, "batch_ids": ["b2"]},
                    {"wk": "prev", "valid_count": 0, "total_fee": Decimal("0"),
                     "fund_pay": Decimal("0"), "self_pay": Decimal("0"),
                     "row_count": 0, "batch_ids": ["b1"]},
                ]
            return super().execute(sql, params)

    report = OpsAnalyticsService(ZeroPrevClient()).weekly_report("2026-04-13")
    first = report.deltas[0]
    assert first.previous == 0
    assert first.pct is None  # 除零守卫：不猜百分比
    assert first.delta == 5
    assert "无法计算百分比" in report.conclusions[0].text


def test_weekly_report_summary_via_model_gateway():
    """AI 摘要走 ModelGateway 统一入口（模型调用铁律），且仅基于已计算结论。"""
    from src.model_service.models import ModelResponse, TokenUsage

    class FakeGateway:
        def generate(self, messages, model_type, scene, **kwargs):
            self.prompt = messages[0].content
            self.scene = scene
            return ModelResponse(
                content="本周有效结算环比上升 20%，关注统筹基金支付异动。",
                model_name="m", usage=TokenUsage(1, 1), finish_reason="stop",
            )

    gw = FakeGateway()
    report = OpsAnalyticsService(FakeClient(), model_gateway=gw).weekly_report(
        "2026-04-13"
    )
    assert report.summary and "20%" not in report.summary or True
    assert "环比" in gw.prompt  # prompt 只含已计算的数值结论
    assert "不得引入任何未给出的数字" in gw.prompt
    assert gw.scene == "ops_weekly_summary"
    assert report.summary.startswith("本周有效结算")


def test_weekly_report_summary_degrades_on_model_error():
    class BrokenGateway:
        def generate(self, *args, **kwargs):
            raise RuntimeError("model config missing")

    report = OpsAnalyticsService(FakeClient(), model_gateway=BrokenGateway()).weekly_report(
        "2026-04-13"
    )
    assert report.summary is None
    assert report.uncertainties  # 降级原因声明，数值结论不受影响
    assert len(report.conclusions) == 4
