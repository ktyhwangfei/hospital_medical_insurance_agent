"""门诊运营分析 /ops-analytics API 测试 — issue #40 P3。

鉴权（ops:read 签名 JWT）+ 五端点契约 + 依赖注入 override 假读取面。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.runtime.api.ops_analytics_routes import get_ops_analytics_service
from src.runtime.ops_analytics.service import OpsAnalyticsService

BASE = "/api/v1/medical-insurance-ai-agent/ops-analytics"
JWT_SECRET = "ops-analytics-test-secret"


def _token(permissions: list[str]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "ops-admin-1",
        "roles": ["system_admin"],
        "permissions": permissions,
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signing_input = f"{encoded_header}.{encoded_payload}"
    signature = base64.urlsafe_b64encode(hmac.new(
        JWT_SECRET.encode(), signing_input.encode(), hashlib.sha256
    ).digest()).decode().rstrip("=")
    return f"Bearer {signing_input}.{signature}"


def _headers(permission: str = "ops:read") -> dict[str, str]:
    return {"Authorization": _token([permission])}


class FakeClient:
    """假读取面：总览 / 拆分 / 趋势 / 双周 / 下钻 各回固定行。"""

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if "ARRAY_AGG" in sql and "GROUP BY" not in sql and "CASE" not in sql:
            return [{
                "valid_count": 12, "total_fee": Decimal("6643.69"),
                "fund_pay": Decimal("113.66"), "self_pay": Decimal("6530.03"),
                "row_count": 12, "date_min": datetime(2026, 4, 1),
                "date_max": datetime(2026, 4, 17),
                "semantic_version": None, "batch_ids": ["batch_2026_04_17"],
            }]
        if "GROUP BY tr." in sql:
            return [
                {"dim_code": "3", "valid_count": 8, "total_fee": Decimal("4000"),
                 "fund_pay": Decimal("80"), "self_pay": Decimal("3920"),
                 "batch_ids": ["batch_2026_04_17"]},
            ]
        if "GROUP BY 1" in sql and "month" in sql:
            return [{"month": "2026-04", "valid_count": 12,
                     "total_fee": Decimal("6643.69"), "fund_pay": Decimal("113.66"),
                     "self_pay": Decimal("6530.03")}]
        if "CASE WHEN" in sql:
            return [
                {"wk": "cur", "valid_count": 12, "total_fee": Decimal("6643.69"),
                 "fund_pay": Decimal("113.66"), "self_pay": Decimal("6530.03"),
                 "row_count": 12, "batch_ids": ["batch_w2"]},
                {"wk": "prev", "valid_count": 10, "total_fee": Decimal("5100"),
                 "fund_pay": Decimal("90"), "self_pay": Decimal("5010"),
                 "row_count": 10, "batch_ids": ["batch_w1"]},
            ]
        if "COUNT(*) AS total" in sql:
            return [{"total": 1}]
        return [
            {"trade_no": "JY001", "trade_date": datetime(2026, 4, 17, 10, 0),
             "fund_type": "3", "cure_type": "11", "settle_state": "2",
             "total_fee": Decimal("100.50"), "fund_pay": Decimal("10.25"),
             "self_pay": Decimal("90.25"), "data_batch_id": "batch_2026_04_17"},
        ]


@pytest.fixture
def api(monkeypatch) -> TestClient:
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    # 模型网关传 None：周报 AI 摘要诚实降级（本测试只验 API 契约）
    service = OpsAnalyticsService(FakeClient(), model_gateway=None)
    app = create_app()
    app.dependency_overrides[get_ops_analytics_service] = lambda: service
    return TestClient(app, raise_server_exceptions=False)


class TestAuth:
    def test_missing_token_401(self, api: TestClient):
        assert api.get(f"{BASE}/overview").status_code == 401

    def test_wrong_permission_403(self, api: TestClient):
        assert api.get(f"{BASE}/overview", headers=_headers("question_library:read")).status_code == 403

    def test_invalid_token_401(self, api: TestClient):
        assert api.get(
            f"{BASE}/overview", headers={"Authorization": "Bearer bad.token.sig"}
        ).status_code == 401


class TestOverview:
    def test_six_cards_with_frozen_status(self, api: TestClient):
        resp = api.get(f"{BASE}/overview", headers=_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["result_status"] == "complete"
        assert body["data_batch_ids"] == ["batch_2026_04_17"]
        cards = {c["metric_code"]: c for c in body["cards"]}
        assert len(cards) == 6
        assert cards["mzjyxx.insured_encounter_count"]["result_status"] == "unavailable"
        assert cards["mzjyxx.insured_encounter_count"]["halt_reason"] == "data_unavailable"
        assert cards["mzjyxx.op_total_fee"]["value"] == 6643.69


class TestBreakdown:
    def test_fund_type_breakdown(self, api: TestClient):
        resp = api.get(
            f"{BASE}/breakdown", params={"dimension": "fund_type"}, headers=_headers()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dimension_name"] == "险种"
        assert body["items"][0]["label"] == "城镇职工"

    def test_department_dimension_unavailable(self, api: TestClient):
        resp = api.get(
            f"{BASE}/breakdown", params={"dimension": "department"}, headers=_headers()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result_status"] == "unavailable"
        assert body["halt_reason"] == "data_unavailable"
        assert body["items"] == []

    def test_unknown_dimension_422(self, api: TestClient):
        resp = api.get(
            f"{BASE}/breakdown", params={"dimension": "doctor"}, headers=_headers()
        )
        assert resp.status_code == 422


class TestTrendAndDrill:
    def test_trend_points_ascending(self, api: TestClient):
        resp = api.get(f"{BASE}/trend", params={"months": 6}, headers=_headers())
        assert resp.status_code == 200
        points = resp.json()["points"]
        assert points[-1]["month"] == "2026-04"

    def test_drill_rows_with_batch_provenance(self, api: TestClient):
        resp = api.get(
            f"{BASE}/drill",
            params={"dimension": "fund_type", "value": "3", "limit": 10},
            headers=_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result_status"] == "complete"
        assert body["rows"][0]["trade_no"] == "JY001"
        assert body["rows"][0]["data_batch_id"] == "batch_2026_04_17"

    def test_drill_bad_dimension_422(self, api: TestClient):
        resp = api.get(
            f"{BASE}/drill", params={"dimension": "department"}, headers=_headers()
        )
        assert resp.status_code == 422


class TestWeeklyReport:
    def test_report_with_batch_citations_and_degraded_summary(self, api: TestClient):
        resp = api.get(
            f"{BASE}/weekly-report",
            params={"week_start": "2026-04-13"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["result_status"] == "complete"
        assert body["summary"] is None  # 模型未配置 → 降级
        assert body["uncertainties"]
        for conclusion in body["conclusions"]:
            refs = [c for c in conclusion["citations"] if c["type"] == "metric_batch"]
            assert refs, "每条结论必须引用指标批次"

    def test_report_invalid_week_start_422(self, api: TestClient):
        resp = api.get(
            f"{BASE}/weekly-report",
            params={"week_start": "2026/04/13"},
            headers=_headers(),
        )
        assert resp.status_code == 422
