"""筛查规则管理 /rule-management API 测试 — issue #86。

覆盖：鉴权（401/403）、上传分类、批准门禁（未批准跑数被拒且结果表无新命中）、
执行批次、两本名单、关闭规则、核实结论。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.screening_rules.in_memory import (
    InMemoryScreeningRuleStorage,
)
from src.domain.screening_rules.executor import FeeLine
from src.runtime.api.app import create_app
from src.runtime.api.screening_rule_routes import get_screening_rule_service
from src.runtime.screening_rules.service import ScreeningRuleService

BASE = "/api/v1/medical-insurance-ai-agent/rule-management"
JWT_SECRET = "rule-management-test-secret"
DOC = "国家定点医疗机构违法违规使用医疗保障基金典型问题清单（2025版）"
THYROID_CLAUSE = "开展甲状腺癌扩大根治术，重复收取甲状腺癌根治术和（或）淋巴结清扫术费用"


def _token(permissions):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "rm-admin-1",
        "roles": ["information_department"],
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


READ_HEADERS = {"Authorization": _token(["rule_management:read"])}
WRITE_HEADERS = {"Authorization": _token(["rule_management:read", "rule_management:write"])}
WRONG_HEADERS = {"Authorization": _token(["ops:read"])}

HIT_LINES = [
    FeeLine("T1", "1:1", "A1", "甲状腺癌扩大根治术", 5000.0),
    FeeLine("T1", "1:2", "A2", "甲状腺癌根治术", 3000.0),
]

RUN_BODY = {"time_range_start": "2026-01-01T00:00:00Z", "time_range_end": "2026-02-01T00:00:00Z"}


@pytest.fixture()
def http(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    app = create_app()
    service = ScreeningRuleService(
        InMemoryScreeningRuleStorage(),
        fee_line_loader=lambda _start, _end: list(HIT_LINES),
    )
    app.dependency_overrides[get_screening_rule_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _upload(http: TestClient) -> str:
    response = http.post(
        f"{BASE}/checklists",
        headers=WRITE_HEADERS,
        json={"source_doc": DOC, "content": THYROID_CLAUSE},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["items"][0]["rule_class"] == "executable"
    assert len(body["candidate_rule_ids"]) == 1
    return body["candidate_rule_ids"][0]


class TestAuth:
    def test_requires_auth(self, http):
        assert http.get(f"{BASE}/rules").status_code == 401

    def test_requires_permission(self, http):
        assert http.get(f"{BASE}/rules", headers=WRONG_HEADERS).status_code == 403

    def test_write_requires_write_permission(self, http):
        response = http.post(
            f"{BASE}/checklists", headers=READ_HEADERS,
            json={"source_doc": DOC, "content": THYROID_CLAUSE},
        )
        assert response.status_code == 403


class TestChecklistUpload:
    def test_classify_and_candidate_with_source_clause(self, http):
        response = http.post(
            f"{BASE}/checklists", headers=WRITE_HEADERS,
            json={
                "source_doc": DOC,
                "content": f"1. {THYROID_CLAUSE}\n2. 对存在基因突变的患者超说明书用药\n",
            },
        )
        assert response.status_code == 201
        items = response.json()["items"]
        assert items[0]["rule_class"] == "executable"
        assert items[1]["rule_class"] == "not_executable"
        assert items[1]["mapping_gap"]  # 材料缺失原因写清
        # 候选规则带原条款
        rules = http.get(f"{BASE}/rules", headers=READ_HEADERS).json()
        assert rules[0]["source_clause"] == THYROID_CLAUSE
        assert rules[0]["source_doc"] == DOC
        assert rules[0]["status"] == "candidate"


class TestApprovalGate:
    def test_run_refused_before_approval(self, http):
        """批准门禁：未批准时执行被拒绝，结果表不出现该规则的新命中。"""
        rule_id = _upload(http)
        response = http.post(f"{BASE}/runs", headers=WRITE_HEADERS, json=RUN_BODY)
        assert response.status_code == 409
        assert response.json()["detail"]["error_code"] == "NO_APPROVED_RULES"
        assert http.get(f"{BASE}/runs", headers=READ_HEADERS).json() == []
        assert http.get(f"{BASE}/findings", headers=READ_HEADERS).json() == []

        explicit = http.post(
            f"{BASE}/runs", headers=WRITE_HEADERS,
            json={**RUN_BODY, "rule_ids": [rule_id]},
        )
        assert explicit.status_code == 409
        assert explicit.json()["detail"]["error_code"] == "RULE_NOT_APPROVED"

    def test_disabled_rule_excluded(self, http):
        """关掉的规则不再进入后续执行批次。"""
        rule_id = _upload(http)
        http.post(f"{BASE}/rules/{rule_id}/approve", headers=WRITE_HEADERS)
        http.post(f"{BASE}/rules/{rule_id}/disable", headers=WRITE_HEADERS)
        response = http.post(f"{BASE}/runs", headers=WRITE_HEADERS, json=RUN_BODY)
        assert response.status_code == 409


class TestRunAndFindings:
    def test_full_cycle(self, http):
        rule_id = _upload(http)
        approve = http.post(f"{BASE}/rules/{rule_id}/approve", headers=WRITE_HEADERS)
        assert approve.status_code == 200
        assert approve.json()["status"] == "approved"
        assert approve.json()["approved_by"] == "rm-admin-1"

        run_response = http.post(f"{BASE}/runs", headers=WRITE_HEADERS, json=RUN_BODY)
        assert run_response.status_code == 201, run_response.text
        run = run_response.json()
        assert run["status"] == "succeeded"
        assert run["finding_counts"] == {"mismatch": 1}
        assert run["rule_ids"] == [rule_id]
        assert run["created_by"] == "rm-admin-1"

        mismatch = http.get(
            f"{BASE}/findings", headers=READ_HEADERS,
            params={"run_id": run["run_id"], "finding_type": "mismatch"},
        ).json()
        assert len(mismatch) == 1
        finding = mismatch[0]
        assert finding["settlement_key"] == "T1"
        assert finding["fee_line_id"] == "1:2"
        assert finding["evidence_clause"] == THYROID_CLAUSE
        assert finding["amount"] == 3000.0
        assert finding["primary_finding_id"] == finding["finding_id"]

        # 材料不足是另一本名单，不混进默认待办
        insufficient = http.get(
            f"{BASE}/findings", headers=READ_HEADERS,
            params={"run_id": run["run_id"], "finding_type": "insufficient_material"},
        ).json()
        assert insufficient == []

        # 核实结论
        verify = http.post(
            f"{BASE}/findings/{finding['finding_id']}/verify",
            headers=WRITE_HEADERS, json={"verify_status": "follow"},
        )
        assert verify.status_code == 200
        assert verify.json()["verify_status"] == "follow"

    def test_edit_approved_rule_requires_reapproval(self, http):
        rule_id = _upload(http)
        http.post(f"{BASE}/rules/{rule_id}/approve", headers=WRITE_HEADERS)
        edited = http.patch(
            f"{BASE}/rules/{rule_id}", headers=WRITE_HEADERS,
            json={"title": "修改后的标题"},
        )
        assert edited.status_code == 200
        assert edited.json()["status"] == "candidate"
        response = http.post(
            f"{BASE}/runs", headers=WRITE_HEADERS,
            json={**RUN_BODY, "rule_ids": [rule_id]},
        )
        assert response.status_code == 409


# ── 手工录入（两库知识点）+ drug_age_indication 执行 ──

from datetime import timedelta

from src.domain.screening_rules.executor import SettlementContext

FACTOR8_CLAUSE = "注射用重组人凝血因子Ⅷ：限儿童甲(A)型血友病；成人甲(A)型血友病限出血时使用。"
FACTOR8_SPEC = {
    "kind": "drug_age_indication",
    "drug_name_contains": "凝血因子Ⅷ",
    "diagnosis_contains": ["血友病A", "甲型血友病"],
    "child_max_age": 18,
    "adult_requires_diagnosis_contains": ["出血"],
}

_ADULT_BLEEDING_CTX = {
    "T1": SettlementContext(
        settlement_key="T1",
        trade_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
        birthday=datetime(2026, 1, 15, tzinfo=timezone.utc) - timedelta(days=int(48 * 365.25)),
        sex="1",
        diagnoses=("血友病A型", "下消化道出血"),
    ),
}


@pytest.fixture()
def http_factor8(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    app = create_app()
    service = ScreeningRuleService(
        InMemoryScreeningRuleStorage(),
        fee_line_loader=lambda _s, _e: list(HIT_LINES) + [
            FeeLine("T1", "1:9", "D1", "人凝血因子Ⅷ", 2990.0),
        ],
        context_loader=lambda _s, _e: dict(_ADULT_BLEEDING_CTX),
    )
    app.dependency_overrides[get_screening_rule_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestManualCreate:
    def test_create_and_run_factor8_compliant(self, http_factor8):
        """手工录入两库知识点 → 批准 → 跑数：成人+出血符合条件，0 命中但批次成功。"""
        create = http_factor8.post(
            f"{BASE}/rules", headers=WRITE_HEADERS,
            json={
                "source_doc": "国家医保智能监管“两库”规则和知识点（第十三批）",
                "source_clause": FACTOR8_CLAUSE,
                "title": "注射用重组人凝血因子Ⅷ限儿童甲(A)型血友病；成人限出血时使用",
                "condition_text": "儿童甲型血友病不受限；成人需诊断同时出现甲型血友病与出血",
                "rule_class": "executable",
                "condition_spec": FACTOR8_SPEC,
                "source_item_ref": "第十三批-序号64",
            },
        )
        assert create.status_code == 201, create.text
        rule = create.json()
        assert rule["status"] == "candidate"
        assert rule["source_clause"] == FACTOR8_CLAUSE

        http_factor8.post(f"{BASE}/rules/{rule['rule_id']}/approve", headers=WRITE_HEADERS)
        run = http_factor8.post(
            f"{BASE}/runs", headers=WRITE_HEADERS,
            json={**RUN_BODY, "rule_ids": [rule["rule_id"]]},
        )
        assert run.status_code == 201, run.text
        body = run.json()
        assert body["status"] == "succeeded"
        assert body["finding_counts"] == {}  # 合规，0 命中

    def test_create_executable_requires_spec(self, http):
        response = http.post(
            f"{BASE}/rules", headers=WRITE_HEADERS,
            json={
                "source_doc": "两库", "source_clause": "某条款",
                "title": "t", "condition_text": "c", "rule_class": "executable",
            },
        )
        assert response.status_code == 422

    def test_create_needs_mapping_requires_gap(self, http):
        response = http.post(
            f"{BASE}/rules", headers=WRITE_HEADERS,
            json={
                "source_doc": "两库", "source_clause": "某条款",
                "title": "t", "condition_text": "c", "rule_class": "needs_mapping",
            },
        )
        assert response.status_code == 422

    def test_create_requires_source_clause(self, http):
        response = http.post(
            f"{BASE}/rules", headers=WRITE_HEADERS,
            json={
                "source_doc": "两库", "source_clause": "  ",
                "title": "t", "condition_text": "c", "rule_class": "not_executable",
            },
        )
        assert response.status_code == 422
