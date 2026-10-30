"""费用分解工作台 /fee-decomposition API 测试（Issue #78 四链路页面可用化 Phase 1）。

覆盖：
- 鉴权：缺 token 401 / 伪签名 401 / 权限不足 403（scope fee_decomposition:read）；
- 门控未配置 → 503 FEE_DECOMPOSITION_NOT_CONFIGURED（带缺失 env 名）；
- 普通门诊 happy path（stub 连接 + stub 内核）：公开契约全字段 + meta；
- 门特 djh 路径（auto 识别 short djh → special）：登记消歧分发 + profile 回传；
- 分解不可用 → 200 + execution_status=unavailable + uncertainties（诚实降级语义）；
- 非法入参 422（缺 identifier / 空 identifier / 非法 chain）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus
from src.runtime.api.app import create_app
from src.runtime.api.fee_decomposition_routes import get_fee_decomposition_provider
from src.runtime.policy_qa.fee_decomposition import integration
from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    BranchConditionModel,
    BranchTraceModel,
    CalculationRecordModel,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
    UncertaintyModel,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    DecompositionOutcome,
    SettlementFactsItem,
    SettlementFactsView,
)


def _canned_facts() -> SettlementFactsView:
    return SettlementFactsView(
        chain="outpatient", identifier=TRADE_NO, trade_date="2024-06-01",
        medical_category="11", insurance_type="3", person_type="11",
        hospital_level=None, metadata_names={"medical_category": "普通门诊", "insurance_type": "基本医疗保险"},
        items=[SettlementFactsItem(label="费用总金额", value="100.00")],
        payment_items=[SettlementFactsItem(label="个人账户支付", value="0.00")],
    )


def test_template_names_and_safe_binding_cross_workbench_api(api, monkeypatch, gate_on):
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import build_outpatient_facts
    facts = build_outpatient_facts({'p_fundtype': '3', 't_feein': '1812.37', 't_beyondbig': '0.00'})
    monkeypatch.setattr(integration, 'decompose_outpatient_trade',
        lambda *_args, **_kwargs: DecompositionOutcome(_canned_result(), facts))
    response = api.post(f'{BASE}/decompose', json={'identifier': TRADE_NO}, headers=_headers())
    assert response.status_code == 200
    template = response.json()['settlement_facts']['display_template']
    fields = {field['key']: field for field in template['fields']}
    assert fields['fee_in']['label'] == '医疗保险范围内金额'
    assert fields['fee_in']['value'] == '1812.37'
    assert fields['beyond_cap']['value'] == '0.00'
    assert fields['fee_in']['field_code'] == 'T_FeeIn'
    assert 'column_keys' not in json.dumps(template)
    assert 'outpatient_trade_table' not in json.dumps(template)
    assert 'T_BeyondBig' not in json.dumps(template)

BASE = "/api/v1/medical-insurance-ai-agent/fee-decomposition"
JWT_SECRET = "fee-decomposition-test-secret"
TRADE_NO = "011100030X240311000031"
DJH = "604"


def _token(permissions: list[str]) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "fee-decomposition-tester",
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


def _headers(permission: str = "fee_decomposition:read") -> dict[str, str]:
    return {"Authorization": _token([permission])}


class _FakeConn:
    def close(self):
        pass


class _FakeProvider:
    """带数据供给连接工厂的 provider 桩（_connect 返回假连接）。"""

    _connect = lambda self, _db: _FakeConn()  # noqa: E731


@pytest.fixture
def api(monkeypatch) -> TestClient:
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    app = create_app()
    app.dependency_overrides[get_fee_decomposition_provider] = lambda: _FakeProvider()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
    monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "01110003")
    monkeypatch.delenv("FEE_DECOMPOSITION_EVAL_CALIBERS", raising=False)


@pytest.fixture
def gate_off(monkeypatch):
    monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
    monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)


def _canned_result(**overrides) -> SettlementDecompositionResult:
    base = dict(
        settlement_ref=f"settlement:{TRADE_NO}",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status="complete",
        reconciliation_status="matched",
        algorithm_version="employee_outpatient_v1",
        fields=[FieldExplanationModel(
            field_code="T_FeeAll", label="总费用", check_type="detail_aggregation",
            check_status="matched", observed_amount="100.00",
            calculated_amount="100.00", difference="0.00",
            explanation_level="amount_reconciled")],
        uncertainties=[UncertaintyModel(
            id="u.rounding.rule", code="ROUNDING_RULE_PENDING_CONFIRMATION",
            message="取整规则 EOP-RND-001 待确认。")],
        coverage=CoverageSummary(
            target_field_count=1, independently_explained_count=0,
            amount_reconciled_count=1, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=True),
    )
    base.update(overrides)
    return SettlementDecompositionResult(**base)


def _locate(match_status: str, row: dict | None = None) -> AdapterCallResult:
    return AdapterCallResult(
        status=AdapterCallStatus.SUCCESS, source_system="test", capability="test",
        data={"match_status": match_status, "registration_row": row,
              "row_count": 1 if match_status == "unique_match" else 0})


class TestAuth:
    def test_missing_token_401(self, api: TestClient):
        resp = api.post(f"{BASE}/decompose", json={"identifier": TRADE_NO})
        assert resp.status_code == 401

    def test_invalid_token_401(self, api: TestClient):
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": TRADE_NO},
            headers={"Authorization": "Bearer bad.token.sig"})
        assert resp.status_code == 401

    def test_wrong_permission_403(self, api: TestClient):
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": TRADE_NO},
            headers=_headers("ops:read"))
        assert resp.status_code == 403


class TestNotConfigured:
    def test_gate_off_503_with_missing_env(self, api: TestClient, gate_off):
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": TRADE_NO}, headers=_headers())
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert detail["error_code"] == "FEE_DECOMPOSITION_NOT_CONFIGURED"
        assert "FEE_DECOMPOSITION_ROUNDING_MODE" in detail["message"]
        assert "FEE_DECOMPOSITION_HOSPITAL_CODE" in detail["message"]

    def test_invalid_rounding_mode_503(self, api: TestClient, monkeypatch):
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "bogus")
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "01110003")
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": TRADE_NO}, headers=_headers())
        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "FEE_DECOMPOSITION_NOT_CONFIGURED"


class TestValidation:
    def test_missing_identifier_422(self, api: TestClient):
        resp = api.post(f"{BASE}/decompose", json={}, headers=_headers())
        assert resp.status_code == 422

    def test_blank_identifier_422(self, api: TestClient):
        resp = api.post(f"{BASE}/decompose", json={"identifier": ""}, headers=_headers())
        assert resp.status_code == 422

    def test_invalid_chain_422(self, api: TestClient):
        resp = api.post(
            f"{BASE}/decompose",
            json={"identifier": TRADE_NO, "chain": "inpatient"}, headers=_headers())
        assert resp.status_code == 422


class TestOutpatientHappyPath:
    def test_formula_inputs_and_candidate_rules_cross_public_contract(self, api: TestClient, monkeypatch, gate_on):
        from src.tests.unit.runtime.policy_qa.fee_decomposition.test_employee_outpatient import _snapshot
        from src.runtime.policy_qa.fee_decomposition.employee_outpatient import decompose_employee_outpatient
        from src.runtime.policy_qa.fee_decomposition.explanation_evidence import attach_evidence
        snapshot = _snapshot()
        decomposed = attach_evidence(decompose_employee_outpatient(snapshot), snapshot)
        monkeypatch.setattr(integration, "decompose_outpatient_trade", lambda *_args, **_kwargs: DecompositionOutcome(decomposed, _canned_facts()))
        response = api.post(f"{BASE}/decompose", json={"identifier": TRADE_NO}, headers=_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["formula_inputs"]
        assert body["rule_choices"]
        assert any(node.get("rule_id") for node in body["formula_inputs"] if node.get("rule_group_ref"))
        assert all(c["verification_status"] in ("verified", "unverified", "conflict", "missing") for c in body["calculations"])
        assert any(o["calculation_ref"] == "calc.deductible.copay_base" for c in body["calculations"] for o in c["operands"])
        assert "explanation_evidence" not in body
        assert "fact.trade.prior_in_scope_fee" not in str(body)

    def test_trade_no_decompose(self, api: TestClient, monkeypatch, gate_on):
        captured = {}

        def fake_decompose(_conn, trade_no, hospital_code, rounding_mode,
                           profile_resolver=None, accumulation_caliber_confirmed=False,
                           derive_eligibility_from_codes=False):
            captured.update(
                trade_no=trade_no, hospital_code=hospital_code,
                accumulation=accumulation_caliber_confirmed,
                eligibility=derive_eligibility_from_codes,
            )
            assert profile_resolver({"p_fundtype": "3"}) == ("employee", "outpatient")
            return DecompositionOutcome(_canned_result(
                branches=[BranchTraceModel(
                    step_id="deductible.split", module_id="deductible", outcome="true",
                    condition=BranchConditionModel(
                        code="c", description="起付条件", operator="eq",
                        actual_value="1", expected_ref="规则"),
                    calculation_refs=["calc.deductible.split"])],
                calculations=[CalculationRecordModel(
                    calculation_id="calc.deductible.split", formula_id="f",
                    formula_version="v1", result="1.00")],
                fee_items=[FeeItemExplanation(line_id="1", item_name="测试药品", total_fee="100.00",
                    observed_in_scope="90.00", observed_out_scope="10.00", observed_self_pay_2="10.00", calculated_self_pay_2="10.00",
                    calculated_in_scope="90.00", calculated_out_scope="10.00", status="calculated",
                    division_method="ratio", self_pay_ratio="0.1",
                    conditions=["乙类自付比例 0.1"], formulas=["先行负担＝100.00×0.1＝10.00 元"])]), _canned_facts())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        resp = api.post(
            f"{BASE}/decompose",
            json={"identifier": TRADE_NO, "chain": "auto"}, headers=_headers())

        assert resp.status_code == 200
        body = resp.json()
        # FeeDecompositionPublic 全字段（解释投影 1.1）
        assert body["schema_version"] == "1.10"
        assert body["algorithm_version"] == "employee_outpatient_v1"
        assert body["fee_items"][0]["division_method"] == "ratio"
        assert body["fee_items"][0]["self_pay_ratio"] == "0.1"
        assert body["execution_status"] == "complete"
        assert body["reconciliation_status"] == "matched"
        assert body["summary_source"] == "template"
        assert body["may_claim_full_explanation"] is False  # 无输入证据的运算不能宣称完整独立解释。
        field = body["fields"][0]
        assert field["field_code"] == "T_FeeAll"
        assert field["observed_amount"] == "100.00"  # 金额十进制字符串透传
        # 解释投影 1.1 新键：引用关联默认空、brief 为确定性说明或 null
        assert field["calculation_refs"] == []
        assert field["source_refs"] == []
        assert field["gap_refs"] == []
        assert body["uncertainties"] == [
            {"code": "ROUNDING_RULE_PENDING_CONFIRMATION",
             "message": "取整规则 EOP-RND-001 待确认。",
             "id": "u.rounding.rule", "affected_fields": [], "scope": "global"}]
        assert body["coverage"]["target_field_count"] == 1
        # meta
        assert body["meta"]["identifier"] == TRADE_NO
        assert body["meta"]["chain"] == "outpatient"
        assert body["meta"]["profile"] == "employee/outpatient"
        assert body["meta"]["algorithm_version"] == "employee_outpatient_v1"
        # 1.2 新块：结算事实侧车（来自 presentation.settlement_facts）+ 正向结算路径
        facts = body["settlement_facts"]
        assert facts["chain"] == "outpatient"
        assert facts["identifier"] == TRADE_NO
        assert facts["items"] == [{"label": "费用总金额", "value": "100.00"}]
        assert facts["payment_items"] == [{"label": "个人账户支付", "value": "0.00"}]
        assert facts["metadata_names"]["medical_category"] == "普通门诊"
        assert body["fee_items"][0]["calculated_in_scope"] == "90.00"
        assert body["fee_items"][0]["explainable"] is True
        assert all(check["check_status"] == "matched" for check in body["fee_items"][0]["reconciliations"])
        assert body["fee_items"][0]["formulas"] == ["先行负担＝100.00×0.1＝10.00 元"]
        assert body["path_steps"] == [{
            "step_id": "path.deductible", "name": "起付", "status": "applied",
            "amount": "1.00", "calculation_refs": ["calc.deductible.split"],
            "field_refs": [], "reason": "起付条件（实际 1，期望 规则）→ 命中",
            "condition_refs": ["deductible.split"],
        }]
        # 候选口径默认关闭
        assert captured["accumulation"] is False
        assert captured["eligibility"] is False
        assert captured["hospital_code"] == "01110003"

    def test_eval_calibers_env_passed_through(self, api: TestClient, monkeypatch, gate_on):
        monkeypatch.setenv("FEE_DECOMPOSITION_EVAL_CALIBERS", "1")
        captured = {}

        def fake_decompose(_conn, _t, _h, _r, profile_resolver=None,
                           accumulation_caliber_confirmed=False,
                           derive_eligibility_from_codes=False):
            captured.update(
                accumulation=accumulation_caliber_confirmed,
                eligibility=derive_eligibility_from_codes)
            return DecompositionOutcome(_canned_result())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        resp = api.post(
            f"{BASE}/decompose",
            json={"identifier": TRADE_NO, "chain": "outpatient"}, headers=_headers())
        assert resp.status_code == 200
        assert captured["accumulation"] is True
        assert captured["eligibility"] is True


class TestSpecialPath:
    def test_djh_auto_routes_to_special(self, api: TestClient, monkeypatch, gate_on):
        monkeypatch.setattr(
            integration, "locate_special_mz_registration",
            lambda _c, _d: _locate("unique_match", {"fund_type": "3", "yllb": "12"}))
        monkeypatch.setattr(
            integration, "locate_special_mz_resident_registration",
            lambda _c, _d: _locate("not_found"))
        monkeypatch.setattr(
            integration, "locate_special_fixed_kidney_registration",
            lambda _c, _d: _locate("not_found"))
        captured = {}

        def fake_mz(_conn, djh, hospital_code, rounding_mode, **kwargs):
            captured.update(djh=djh, **kwargs)
            return DecompositionOutcome(_canned_result(
                settlement_ref=f"special_mz_settlement:{djh}",
                algorithm_version="employee_outpatient_special_v1"))

        monkeypatch.setattr(integration, "decompose_special_mz_settlement", fake_mz)
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": DJH, "chain": "auto"},
            headers=_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert captured["djh"] == DJH
        assert captured["allow_observed_deductible"] is False
        assert body["meta"]["chain"] == "special"
        assert body["meta"]["profile"] == "employee/outpatient_special"
        assert body["algorithm_version"] == "employee_outpatient_special_v1"


class TestUnavailableSemantics:
    def test_unavailable_with_located_record_keeps_facts(self, api: TestClient, monkeypatch, gate_on):
        monkeypatch.setattr(integration, "decompose_outpatient_trade", lambda *a, **k: DecompositionOutcome(
            _canned_result(execution_status="unavailable", fields=[]), _canned_facts()))
        response = api.post(f"{BASE}/decompose", json={"identifier": TRADE_NO}, headers=_headers())
        assert response.status_code == 200
        body = response.json()
        assert body["execution_status"] == "unavailable"
        assert body["settlement_facts"]["items"][0]["value"] == "100.00"

    def test_unavailable_is_200_with_uncertainties(self, api: TestClient, monkeypatch, gate_on):
        monkeypatch.setattr(
            integration, "decompose_outpatient_trade",
            lambda *args, **kwargs: DecompositionOutcome(_canned_result(
                execution_status="unavailable",
                reconciliation_status="not_verifiable",
                fields=[],
                uncertainties=[UncertaintyModel(
                    id="u.read.trade_not_found", code="TRADE_NOT_FOUND",
                    message="交易号在该院区未找到")],
                answer_constraints=AnswerConstraints(may_claim_full_explanation=False),
            )))
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": TRADE_NO}, headers=_headers())
        # 诚实降级语义：数据不可用不是 HTTP 错误
        assert resp.status_code == 200
        body = resp.json()
        assert body["execution_status"] == "unavailable"
        assert body["uncertainties"][0]["code"] == "TRADE_NOT_FOUND"
        assert body["fields"] == []


# ── 按身份证号定位（resolve-person）与 decompose 防误判 ──────────────

ID_CARD = "110101199001011234"

_PERSON_TRADE_COLS = ("T_TradeNo", "T_TradeDate", "T_FeeAll", "P_FundType")
_PERSON_SPECIAL_COLS = ("djh", "ryrq", "FUND_TYPE", "tsb1", "tsb2", "tsb3")


class _RoutingCursor:
    """按 SQL 中表名分发的游标桩（路由到门诊交易表或门特登记表）。"""

    def __init__(self, routes):
        self._routes = routes
        self._active = ((), [])

    def execute(self, sql, params):
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
        self._cursor = _RoutingCursor(routes)

    def cursor(self):
        return self._cursor

    def close(self):
        pass


class _RoutingProvider:
    def __init__(self, conn):
        self._connect = lambda _db: conn


def _person_api(monkeypatch, conn) -> TestClient:
    """带路由假连接的 app：override provider 工厂返回路由连接。"""
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    app = create_app()
    provider = _RoutingProvider(conn)
    app.dependency_overrides[get_fee_decomposition_provider] = lambda: provider
    return TestClient(app, raise_server_exceptions=False)


def _person_conn(trade_rows=(), special_rows=()) -> _RoutingConn:
    return _RoutingConn({
        "o_Trade": (_PERSON_TRADE_COLS, list(trade_rows)),
        "yb_brdjxx": (_PERSON_SPECIAL_COLS, list(special_rows)),
    })


class TestResolvePersonAuth:
    def test_missing_token_401(self, api: TestClient):
        resp = api.post(f"{BASE}/resolve-person", json={"id_card": ID_CARD})
        assert resp.status_code == 401

    def test_invalid_token_401(self, api: TestClient):
        resp = api.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD},
            headers={"Authorization": "Bearer bad.token.sig"})
        assert resp.status_code == 401

    def test_wrong_permission_403(self, api: TestClient):
        resp = api.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD},
            headers=_headers("ops:read"))
        assert resp.status_code == 403


class TestResolvePersonValidation:
    @pytest.mark.parametrize("bad", [
        "11010119900101123",      # 17 位
        "1101011990010112345",    # 19 位
        "11010119900101A234",     # 中间含字母
        "11010119900101123A",     # 末位非 X
        "123",                    # 过短
        "",                       # 空
    ])
    def test_invalid_id_card_422(self, api: TestClient, bad: str):
        resp = api.post(
            f"{BASE}/resolve-person", json={"id_card": bad}, headers=_headers())
        assert resp.status_code == 422

    def test_valid_15_and_18_with_x_accepted(self, monkeypatch):
        conn = _person_conn()
        client = _person_api(monkeypatch, conn)
        for value in ("110101900101123", "11010119900101123X", "11010119900101123x"):
            resp = client.post(
                f"{BASE}/resolve-person", json={"id_card": value}, headers=_headers())
            assert resp.status_code == 200, value


class TestResolvePersonStates:
    def test_unique_match_outpatient(self, monkeypatch):
        conn = _person_conn(trade_rows=[("T001", "2024-06-01", "100.00", "3")])
        client = _person_api(monkeypatch, conn)
        resp = client.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD}, headers=_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["match_status"] == "unique_match"
        assert body["truncated"] is False
        candidate = body["candidates"][0]
        assert candidate == {
            "chain": "outpatient", "identifier": "T001",
            "chain_label": "普通门诊", "profile_label": "城镇职工",
            "service_date": "2024-06-01", "total_amount": "100.00",
        }
        # 响应不回显身份证原文
        assert ID_CARD not in resp.text

    def test_multiple_candidates_mixed_chains(self, monkeypatch):
        conn = _person_conn(
            trade_rows=[("T001", "2024-06-01", "100.00", "3")],
            special_rows=[
                ("9001", "2024-03-01", "3", "503", None, None),   # 肾移植定额
                ("9002", "2024-04-01", "92", None, None, None),   # 居民门特
            ])
        client = _person_api(monkeypatch, conn)
        resp = client.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD}, headers=_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["match_status"] == "multiple_candidates"
        assert len(body["candidates"]) == 3
        by_id = {c["identifier"]: c for c in body["candidates"]}
        assert by_id["9001"]["chain"] == "special"
        assert by_id["9001"]["chain_label"] == "门诊特殊病·肾移植定额"
        assert by_id["9001"]["profile_label"] == "城镇职工"
        assert by_id["9001"]["total_amount"] is None
        assert by_id["9002"]["chain_label"] == "门诊特殊病"
        assert by_id["9002"]["profile_label"] == "城乡居民"
        assert ID_CARD not in resp.text

    def test_no_match(self, monkeypatch):
        client = _person_api(monkeypatch, _person_conn())
        resp = client.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD}, headers=_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["match_status"] == "no_match"
        assert body["candidates"] == []
        assert ID_CARD not in resp.text

    def test_truncated_flag(self, monkeypatch):
        rows = [(f"T{i:03d}", "2024-06-01", "1.00", "3") for i in range(51)]
        client = _person_api(monkeypatch, _person_conn(trade_rows=rows))
        resp = client.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD}, headers=_headers())
        body = resp.json()
        assert body["truncated"] is True
        assert len(body["candidates"]) == 50

    def test_query_failure_503(self, monkeypatch):
        class _BoomCursor:
            def execute(self, sql, params):
                raise RuntimeError("db down")

            def close(self):
                pass

        class _BoomConn:
            def cursor(self):
                return _BoomCursor()

            def close(self):
                pass

        client = _person_api(monkeypatch, _RoutingProvider(_BoomConn()))
        resp = client.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD}, headers=_headers())
        assert resp.status_code == 503
        assert ID_CARD not in resp.text

    def test_provider_without_connect_503(self, monkeypatch):
        monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
        app = create_app()
        app.dependency_overrides[get_fee_decomposition_provider] = lambda: object()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            f"{BASE}/resolve-person", json={"id_card": ID_CARD}, headers=_headers())
        assert resp.status_code == 503


class TestDecomposeIdCardGuard:
    @pytest.mark.parametrize("identifier", [ID_CARD, "110101900101123",
                                            "11010119900101123X"])
    def test_id_card_identifier_422(self, api: TestClient, identifier: str):
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": identifier}, headers=_headers())
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error_code"] == "IDENTIFIER_IS_ID_CARD"
        assert "resolve-person" in detail["message"]
        # 报错信息不回显身份证原文
        assert identifier not in resp.text

    def test_trade_no_not_misjudged(self, api: TestClient, gate_off):
        """正常交易号不受防误判影响（门控未配置仍走 503 而非 422）。"""
        resp = api.post(
            f"{BASE}/decompose", json={"identifier": TRADE_NO}, headers=_headers())
        assert resp.status_code == 503
