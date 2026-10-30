"""GET /policy-qa/sessions/{session_id}/decomposition 会话共享分解实例 API 测试（阶段 A）。

覆盖：
- 鉴权复用 ensure_fee_decomposition_read：缺 token 401 / 权限不足 403；
- 门控未配置 → 503 FEE_DECOMPOSITION_NOT_CONFIGURED（与工作台同码）；
- 身份证格式 settlement_id → 422（不误判为交易号）；
- 同 (session, settlement) 两次请求字段级相等且只计算一次；
  换 settlement_id / 换 session_id → 新键新实例；
- FEE_DECOMPOSITION_EVAL_CALIBERS=1 时新端点仍 fail-closed，工作台端点行为不变；
- policy-qa 主流与新端点共享同一实例：聊天模型回写 summary 只作用于该消息，
  端点返回的共享实例仍是模板摘要；金额/规则/计算/来源字段级一致；
- chain 显式传入时优先于自动识别；分解不可用 → 200 + unavailable 语义。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus
from src.runtime.api import policy_qa_routes
from src.runtime.api.app import create_app
from src.runtime.api.fee_decomposition_routes import get_fee_decomposition_provider
from src.runtime.policy_qa.fee_decomposition import followup_target, integration
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
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

BASE = "/api/v1/medical-insurance-ai-agent/policy-qa/sessions"
WORKBENCH = "/api/v1/medical-insurance-ai-agent/fee-decomposition"
JWT_SECRET = "session-decomposition-test-secret"
TRADE_NO = "011100030X240311000031"
DJH = "604"


def _headers(permission: str = "fee_decomposition:read") -> dict[str, str]:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "session-decomposition-tester",
        "roles": ["information_department"],
        "permissions": [permission],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    b = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(
        JWT_SECRET.encode(), f"{h}.{b}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return {"Authorization": f"Bearer {h}.{b}.{sig}"}


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event_name = ""
        data_lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            if line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").lstrip())
        if event_name and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
    return events


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


def _canned_facts() -> SettlementFactsView:
    return SettlementFactsView(
        chain="outpatient", identifier=TRADE_NO, trade_date="2024-06-01",
        medical_category="11", insurance_type="3", person_type="11",
        hospital_level=None,
        items=[SettlementFactsItem(label="费用总金额", value="100.00")],
        payment_items=[SettlementFactsItem(label="个人账户支付", value="0.00")],
    )


class _FakeConn:
    def close(self):
        pass


class _FakeProvider:
    _connect = lambda self, _db: _FakeConn()  # noqa: E731


@pytest.fixture(autouse=True)
def clear_cache():
    integration.clear_session_decomposition_cache()
    followup_target.clear_followup_targets()
    yield
    integration.clear_session_decomposition_cache()
    followup_target.clear_followup_targets()


@pytest.fixture
def api(monkeypatch) -> TestClient:
    monkeypatch.setenv("AUTH_JWT_SECRET", JWT_SECRET)
    app = create_app()
    provider = _FakeProvider()
    app.dependency_overrides[get_fee_decomposition_provider] = lambda: provider
    monkeypatch.setattr(policy_qa_routes, "create_settlement_data_provider", lambda: provider)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
    monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "01110003")
    monkeypatch.delenv("FEE_DECOMPOSITION_EVAL_CALIBERS", raising=False)


def _get(api: TestClient, session_id: str, settlement_id: str, chain: str = "auto"):
    return api.get(
        f"{BASE}/{session_id}/decomposition",
        params={"settlement_id": settlement_id, "chain": chain},
        headers=_headers(),
    )


def _kernel_spy(monkeypatch, calls: list, **result_overrides):
    def fake_decompose(_conn, trade_no, hospital_code, rounding_mode,
                       profile_resolver=None, accumulation_caliber_confirmed=False,
                       derive_eligibility_from_codes=False):
        calls.append({
            "trade_no": trade_no,
            "accumulation": accumulation_caliber_confirmed,
            "eligibility": derive_eligibility_from_codes,
        })
        if profile_resolver is not None:
            profile_resolver({"p_fundtype": "3"})
        return DecompositionOutcome(_canned_result(**result_overrides), _canned_facts())

    monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)


class TestAuth:
    def test_missing_token_401(self, api: TestClient):
        resp = api.get(f"{BASE}/sess-1/decomposition", params={"settlement_id": TRADE_NO})
        assert resp.status_code == 401

    def test_wrong_permission_403(self, api: TestClient):
        resp = api.get(
            f"{BASE}/sess-1/decomposition",
            params={"settlement_id": TRADE_NO},
            headers=_headers("ops:read"),
        )
        assert resp.status_code == 403


class TestGateAndValidation:
    def test_gate_off_503_same_code_as_workbench(self, api: TestClient, monkeypatch):
        monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
        monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)
        resp = _get(api, "sess-1", TRADE_NO)
        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "FEE_DECOMPOSITION_NOT_CONFIGURED"

    def test_id_card_identifier_422(self, api: TestClient, gate_on):
        resp = _get(api, "sess-1", "110101199001011234")
        assert resp.status_code == 422
        assert "110101199001011234" not in resp.text


class TestSharedInstance:
    def test_same_session_same_settlement_field_level_identical(
            self, api: TestClient, monkeypatch, gate_on):
        calls: list = []
        _kernel_spy(monkeypatch, calls)
        first = _get(api, "sess-1", TRADE_NO)
        second = _get(api, "sess-1", TRADE_NO)
        assert first.status_code == 200 and second.status_code == 200
        # 只计算一次，两次响应字段级相等（金额/规则/计算/来源/meta 全字段）
        assert calls == [calls[0]] and len(calls) == 1
        assert first.json() == second.json()
        body = first.json()
        assert body["fields"][0]["observed_amount"] == "100.00"
        assert body["meta"]["identifier"] == TRADE_NO
        assert body["meta"]["chain"] == "outpatient"
        assert body["meta"]["caliber"] == "fail_closed"
        assert body["settlement_facts"]["identifier"] == TRADE_NO

    def test_new_settlement_or_new_session_recomputes(
            self, api: TestClient, monkeypatch, gate_on):
        calls: list = []
        _kernel_spy(monkeypatch, calls)
        other_trade = "011100030X240311000032"
        assert _get(api, "sess-1", TRADE_NO).status_code == 200
        assert _get(api, "sess-1", other_trade).status_code == 200
        assert _get(api, "sess-2", TRADE_NO).status_code == 200
        assert [c["trade_no"] for c in calls] == [TRADE_NO, other_trade, TRADE_NO]

    def test_eval_calibers_env_does_not_leak_into_session_endpoint(
            self, api: TestClient, monkeypatch, gate_on):
        """EVAL_CALIBERS=1 只作用于工作台；会话端点与主链恒 fail-closed。"""
        monkeypatch.setenv("FEE_DECOMPOSITION_EVAL_CALIBERS", "1")
        calls: list = []
        _kernel_spy(monkeypatch, calls)
        resp = _get(api, "sess-1", TRADE_NO)
        assert resp.status_code == 200
        assert calls[0]["accumulation"] is False
        assert calls[0]["eligibility"] is False
        assert resp.json()["meta"]["caliber"] == "fail_closed"
        # 工作台端点行为不变：仍按 env 启用候选口径
        workbench = api.post(
            f"{WORKBENCH}/decompose",
            json={"identifier": TRADE_NO, "chain": "outpatient"}, headers=_headers())
        assert workbench.status_code == 200
        assert calls[1]["accumulation"] is True
        assert workbench.json()["meta"]["caliber"] == "eval_calibers"

    def test_unavailable_is_200_and_not_cached(self, api: TestClient, monkeypatch, gate_on):
        """unavailable 不可复用：数据源恢复后同键重算成功（评审问题 7）。"""
        calls: list = []
        _kernel_spy(monkeypatch, calls,
                    execution_status="unavailable",
                    reconciliation_status="not_verifiable",
                    fields=[],
                    uncertainties=[UncertaintyModel(
                        id="u.read.trade_not_found", code="TRADE_NOT_FOUND",
                        message="交易号在该院区未找到")],
                    answer_constraints=AnswerConstraints(may_claim_full_explanation=False))
        first = _get(api, "sess-1", TRADE_NO)
        assert first.status_code == 200
        assert first.json()["execution_status"] == "unavailable"
        assert first.json()["uncertainties"][0]["code"] == "TRADE_NOT_FOUND"
        # 失败不写缓存 → 同会话再取必须重算（不被旧 unavailable 固化）
        assert _get(api, "sess-1", TRADE_NO).status_code == 200
        assert len(calls) == 2

    def test_wrong_chain_failure_then_corrected_chain_succeeds(
            self, api: TestClient, monkeypatch, gate_on):
        """同 session 先 outpatient 失败、再显式 special 成功：链路冲突当未命中。"""
        outpatient_calls: list = []
        _kernel_spy(monkeypatch, outpatient_calls,
                    execution_status="unavailable",
                    reconciliation_status="not_verifiable",
                    fields=[],
                    uncertainties=[UncertaintyModel(
                        id="u.read.trade_not_found", code="TRADE_NOT_FOUND",
                        message="交易号在该院区未找到")],
                    answer_constraints=AnswerConstraints(may_claim_full_explanation=False))
        failed = _get(api, "sess-1", DJH, chain="outpatient")
        assert failed.json()["execution_status"] == "unavailable"
        assert failed.json()["meta"]["chain"] == "outpatient"

        def fake_special_core(_conn, djh, _hospital_code, _rounding_mode, profile, **_kwargs):
            return DecompositionOutcome(
                _canned_result(
                    settlement_ref=f"settlement:{djh}",
                    profile=DecompositionProfile(
                        insurance_type="employee", medical_category="special")),
                _canned_facts()), ("employee", "outpatient_special")

        monkeypatch.setattr(integration, "_decompose_special_core", fake_special_core)
        corrected = _get(api, "sess-1", DJH, chain="special")
        assert corrected.status_code == 200
        body = corrected.json()
        assert body["meta"]["chain"] == "special"
        assert body["execution_status"] == "complete"
        # 正确链路结果不被后续错链路请求覆盖
        assert _get(api, "sess-1", DJH, chain="special").json() == body

    def test_explicit_chain_overrides_auto_detection(
            self, api: TestClient, monkeypatch, gate_on):
        """chain=special 显式传入优先：长交易号形态也走门特登记消歧。"""
        def _locate(match_status: str):
            return AdapterCallResult(
                status=AdapterCallStatus.SUCCESS, source_system="test", capability="test",
                data={"match_status": match_status, "registration_row": None, "row_count": 0})

        monkeypatch.setattr(
            integration, "locate_special_mz_registration", lambda _c, _d: _locate("not_found"))
        monkeypatch.setattr(
            integration, "locate_special_mz_resident_registration", lambda _c, _d: _locate("not_found"))
        monkeypatch.setattr(
            integration, "locate_special_fixed_kidney_registration", lambda _c, _d: _locate("not_found"))
        resp = _get(api, "sess-1", TRADE_NO, chain="special")
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["chain"] == "special"
        assert body["execution_status"] == "unavailable"
        assert body["uncertainties"][0]["code"] == "REGISTRATION_NOT_FOUND"


class TestMainChainSharesInstance:
    """policy-qa 结算解释主流与新端点共享同一分解实例。"""

    @pytest.fixture
    def stream_dependencies(self, monkeypatch):
        from skills.mzsettlement_verify_skill.assembler import (
            OutpatientSettlementVerifierAssembler,
        )
        monkeypatch.setattr(
            policy_qa_routes, "route_question", lambda _q: "mzsettlement_verify_skill")
        monkeypatch.setattr(
            policy_qa_routes, "get_assembler",
            lambda _skill_id: OutpatientSettlementVerifierAssembler())
        monkeypatch.setattr(
            policy_qa_routes, "retrieve_policy_evidence",
            lambda **_kwargs: SimpleNamespace(
                selected_evidence=[], missing_required_rules=["政策证据"]))

    def test_chat_answer_does_not_pollute_shared_instance(
            self, api: TestClient, monkeypatch, gate_on, stream_dependencies):
        calls: list = []
        _kernel_spy(monkeypatch, calls)
        # 模型替身返回自由文本：费用分解正文不再调用模型，该文本不得进入回答或共享实例
        monkeypatch.setattr(
            "src.model_service.gateway.ModelGateway.generate",
            lambda *a, **k: SimpleNamespace(content="本单总费用100.00元，按实际计算依据说明。"))

        stream = api.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            headers=_headers(),
            json={
                "question": "解释这笔结算", "mode": "settlement_explain",
                "settlement_id": TRADE_NO, "decomposition_chain": "outpatient",
                "session_id": "sess-shared-1",
            })
        assert stream.status_code == 200
        events = _sse_events(stream.text)
        result = next(payload["result"] for name, payload in events if name == "result")
        chat_fee = result["fee_decomposition"]
        # 聊天与面板共用同一模板摘要（不再回写模型文本）
        assert chat_fee["summary_source"] == "template"
        assert "按实际计算依据说明" not in result["answer"]

        panel = _get(api, "sess-shared-1", TRADE_NO)
        assert panel.status_code == 200
        panel_fee = panel.json()
        # 端点复用缓存实例：内核只算一次；金额/字段/不确定性逐字段一致
        assert len(calls) == 1
        assert panel_fee["summary_source"] == "template"
        assert panel_fee["fields"] == chat_fee["fields"]
        assert panel_fee["uncertainties"] == chat_fee["uncertainties"]
        assert panel_fee["settlement_facts"] == chat_fee["settlement_facts"]

    def test_second_turn_same_session_reuses_instance(
            self, api: TestClient, monkeypatch, gate_on, stream_dependencies):
        """同会话同单第二次提问不再重算分解。"""
        calls: list = []
        _kernel_spy(monkeypatch, calls)
        monkeypatch.setattr(
            "src.model_service.gateway.ModelGateway.generate",
            lambda *a, **k: SimpleNamespace(content="本单总费用100.00元。"))
        payload = {
            "question": "解释这笔结算", "mode": "settlement_explain",
            "settlement_id": TRADE_NO, "decomposition_chain": "outpatient",
            "session_id": "sess-shared-2",
        }
        first = api.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            headers=_headers(), json=payload)
        second = api.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            headers=_headers(), json=payload)
        assert first.status_code == 200 and second.status_code == 200
        first_fee = next(p["result"] for n, p in _sse_events(first.text) if n == "result")["fee_decomposition"]
        second_fee = next(p["result"] for n, p in _sse_events(second.text) if n == "result")["fee_decomposition"]
        assert len(calls) == 1
        # 两轮字段级一致（summary 同为当轮模型回写，内容确定性相同）
        assert first_fee == second_fee

    def test_model_failure_keeps_deterministic_partial_answer(
            self, api: TestClient, monkeypatch, gate_on, stream_dependencies):
        """评审问题 1：模型不可用不能改变可信事实块——回答仍为确定性证据正文，partial。"""
        from src.model_service.exceptions import ModelTimeoutError

        calls: list = []
        _kernel_spy(monkeypatch, calls)

        def fail(*_args, **_kwargs):
            raise ModelTimeoutError("timeout")

        monkeypatch.setattr("src.model_service.gateway.ModelGateway.generate", fail)
        stream = api.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            headers=_headers(),
            json={
                "question": "解释这笔结算", "mode": "settlement_explain",
                "settlement_id": TRADE_NO, "decomposition_chain": "outpatient",
                "session_id": "sess-fallback-1",
            })
        assert stream.status_code == 200
        result = next(p["result"] for n, p in _sse_events(stream.text) if n == "result")
        # 确定性证据正文（总费用 100.00 元）不受模型故障影响
        assert "100.00" in result["answer"]
        assert result["answer_status"] == "partial"


class TestFollowupTargetInheritance:
    """阶段 D：会话级追问目标继承——同 session 同单，指代问题继承上一问显式目标。"""

    @pytest.fixture
    def stream_dependencies(self, monkeypatch):
        from skills.mzsettlement_verify_skill.assembler import (
            OutpatientSettlementVerifierAssembler,
        )
        monkeypatch.setattr(
            policy_qa_routes, "route_question", lambda _q: "mzsettlement_verify_skill")
        monkeypatch.setattr(
            policy_qa_routes, "get_assembler",
            lambda _skill_id: OutpatientSettlementVerifierAssembler())
        monkeypatch.setattr(
            policy_qa_routes, "retrieve_policy_evidence",
            lambda **_kwargs: SimpleNamespace(
                selected_evidence=[], missing_required_rules=["政策证据"]))

    def _post(self, api: TestClient, question: str, session_id: str, settlement_id: str):
        return api.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            headers=_headers(),
            json={
                "question": question, "mode": "settlement_explain",
                "settlement_id": settlement_id, "decomposition_chain": "outpatient",
                "session_id": session_id,
            })

    def test_referent_question_inherits_previous_summary_target(
            self, api: TestClient, monkeypatch, gate_on, stream_dependencies):
        calls: list = []
        _kernel_spy(monkeypatch, calls, fields=[
            FieldExplanationModel(
                field_code="T_FeeAll", label="总费用", check_type="detail_aggregation",
                check_status="matched", observed_amount="100.00",
                calculated_amount="100.00", difference="0.00",
                explanation_level="amount_reconciled"),
            FieldExplanationModel(
                field_code="T_SelfPay2", label="自付二", check_type="independent_recalculation",
                check_status="matched", observed_amount="60.00",
                calculated_amount="60.00", difference="0.00",
                explanation_level="amount_reconciled"),
        ])
        seen_targets: list = []
        from src.runtime.policy_qa.fee_decomposition import model_explanation as _me
        _original_explain = _me.explain_decomposition

        def spy_explain(public, question, question_target=None):
            seen_targets.append(question_target)
            return _original_explain(public, question, question_target=question_target)

        monkeypatch.setattr(policy_qa_routes, "explain_decomposition", spy_explain)
        # 模型替身文本不得进入费用分解正文（主链不再调用模型生成正文）
        monkeypatch.setattr(
            "src.model_service.gateway.ModelGateway.generate",
            lambda *a, **k: SimpleNamespace(content="自由文本不应进入正文"))

        first = self._post(api, "自付二为什么这么多", "sess-followup-1", TRADE_NO)
        assert first.status_code == 200
        assert seen_targets[0].kind == "summary_fields"
        assert seen_targets[0].field_codes == ["T_SelfPay2"]

        # 同 session 同单：指代问题继承上一问的 summary_fields 目标
        second = self._post(api, "那这项为什么这么多", "sess-followup-1", TRADE_NO)
        assert second.status_code == 200
        assert seen_targets[1].kind == "summary_fields"
        assert seen_targets[1].field_codes == ["T_SelfPay2"]

        # 换单：不继承（回到整单目标）
        other_trade = "011100030X240311000032"
        third = self._post(api, "那这项为什么这么多", "sess-followup-1", other_trade)
        assert third.status_code == 200
        assert seen_targets[2].kind == "whole_settlement"


class TestPublicAnswerEligibilityAndPrecision:
    """R2/R3 公开行为：最终 SSE 正文保留公式输入精度、不夹带不可解释候选。"""

    @pytest.fixture
    def stream_dependencies(self, monkeypatch):
        from skills.mzsettlement_verify_skill.assembler import (
            OutpatientSettlementVerifierAssembler,
        )
        monkeypatch.setattr(
            policy_qa_routes, "route_question", lambda _q: "mzsettlement_verify_skill")
        monkeypatch.setattr(
            policy_qa_routes, "get_assembler",
            lambda _skill_id: OutpatientSettlementVerifierAssembler())
        monkeypatch.setattr(
            policy_qa_routes, "retrieve_policy_evidence",
            lambda **_kwargs: SimpleNamespace(
                selected_evidence=[], missing_required_rules=["政策证据"]))

    @staticmethod
    def _precision_outcome():
        from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
        result = _canned_result(
            fields=[
                FieldExplanationModel(
                    field_code="T_FeeAll", label="费用总金额",
                    check_type="independent_recalculation", check_status="mismatched",
                    observed_amount="60.00", calculated_amount="50.00", difference="-10.00",
                    explanation_level="observed", calculation_refs=["calc.fund.part"]),
            ],
            calculations=[],
            fee_items=[FeeItemExplanation(
                line_id="0", item_name="精度测试项目", unit_price="80.00", quantity="0.125",
                total_fee="10.00", observed_in_scope="439.00", observed_out_scope="0.00",
                observed_self_pay_2="0.00", calculated_in_scope="440.00",
                calculated_out_scope="0.00", calculated_self_pay_2="0.00",
                status="calculated", verification_status="verified",
                formulas=["本行全部纳入医保内：440.00 元"])],
        )
        return DecompositionOutcome(result, _canned_facts())

    def _post(self, api: TestClient, question: str, session_id: str):
        return api.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            headers=_headers(),
            json={
                "question": question, "mode": "settlement_explain",
                "settlement_id": TRADE_NO, "decomposition_chain": "outpatient",
                "session_id": session_id,
            })

    def test_unexplained_field_formula_is_not_in_public_answer(
            self, api: TestClient, monkeypatch, gate_on, stream_dependencies):
        monkeypatch.setattr(
            integration, "decompose_outpatient_trade",
            lambda *_a, **_k: self._precision_outcome())
        response = self._post(api, "费用总金额是怎么算的？", "sess-eligibility-1")
        assert response.status_code == 200
        result = next(p["result"] for n, p in _sse_events(response.text) if n == "result")
        answer = result["answer"]
        assert "60.00" in answer            # 原单事实仍交付
        assert "50.00 元" not in answer     # 候选计算不得作为本项原因
        assert "100.00" not in answer

    def test_line_answer_keeps_precision_and_hides_candidate_formula(
            self, api: TestClient, monkeypatch, gate_on, stream_dependencies):
        monkeypatch.setattr(
            integration, "decompose_outpatient_trade",
            lambda *_a, **_k: self._precision_outcome())
        response = self._post(api, "第1行的医保内外怎么算？", "sess-eligibility-2")
        result = next(p["result"] for n, p in _sse_events(response.text) if n == "result")
        answer = result["answer"]
        assert "0.125" in answer            # 数量精度保留（R2）
        assert "0.13" not in answer
        assert "439.00" in answer           # 原单事实
        assert "440.00" not in answer       # 候选公式不进正文（R3）


class TestGrzif1TerminalCompositionOverSse:
    """F1 公开行为：GRZIF1 构成按终端/依赖选择，计算结果顺序不影响 SSE 正文。"""

    @pytest.fixture
    def stream_dependencies(self, monkeypatch):
        from skills.mzsettlement_verify_skill.assembler import (
            OutpatientSettlementVerifierAssembler,
        )
        monkeypatch.setattr(
            policy_qa_routes, "route_question", lambda _q: "mzsettlement_verify_skill")
        monkeypatch.setattr(
            policy_qa_routes, "get_assembler",
            lambda _skill_id: OutpatientSettlementVerifierAssembler())
        monkeypatch.setattr(
            policy_qa_routes, "retrieve_policy_evidence",
            lambda **_kwargs: SimpleNamespace(
                selected_evidence=[], missing_required_rules=["政策证据"]))

    @staticmethod
    def _outcome(reversed_calcs: bool = False):
        from src.runtime.policy_qa.fee_decomposition.result import CalculationOperandModel
        from src.runtime.policy_qa.fee_decomposition.result import CalculationRecordModel

        def calc(cid, fid, pairs, result, explainable=True):
            return CalculationRecordModel(
                calculation_id=cid, formula_id=fid, formula_version="v1",
                operands=[CalculationOperandModel(ref=ref, value=value) for ref, value in pairs],
                result=result, explainable=explainable)

        calculations = [
            calc("calc.pay.parts", "special_pool_self_pay_v1",
                 [("input.base", "1723.0000")], "1723.0000"),
            calc("calc.self_pay_1.parts", "self_pay_1_components_v1",
                 [("calc.pay.parts", "1723.0000")], "1723.0000", explainable=False),
            calc("calc.unrelated", "catalog_total_fee_v1",
                 [("input.a", "100.00")], "100.00"),
        ]
        if reversed_calcs:
            calculations = list(reversed(calculations))
        result = _canned_result(
            fields=[FieldExplanationModel(
                field_code="GRZIF1", label="个人支付自付（一）金额",
                check_type="independent_recalculation", check_status="not_verifiable",
                observed_amount=None, calculated_amount="1723.0000", difference=None,
                explanation_level="observed",
                reason_code="SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED",
                calculation_refs=["calc.self_pay_1.parts"])],
            calculations=calculations,
            fee_items=[])
        return DecompositionOutcome(result, _canned_facts())

    def _ask(self, api: TestClient, question: str, session_id: str):
        response = api.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            headers=_headers(),
            json={
                "question": question, "mode": "settlement_explain",
                "settlement_id": TRADE_NO, "decomposition_chain": "outpatient",
                "session_id": session_id,
            })
        assert response.status_code == 200
        return next(p["result"] for n, p in _sse_events(response.text) if n == "result")

    @pytest.mark.parametrize("reversed_calcs", [False, True])
    def test_grzif1_answer_is_order_independent_and_has_no_unrelated_formula(
            self, api: TestClient, monkeypatch, gate_on, stream_dependencies, reversed_calcs):
        monkeypatch.setattr(
            integration, "decompose_outpatient_trade",
            lambda *_a, **_k: self._outcome(reversed_calcs))
        result = self._ask(api, "个人支付自付（一）金额是怎么算的？", f"sess-grzif1-{reversed_calcs}")
        answer = result["answer"]
        assert "1723" in answer
        assert "不作账面核对" in answer
        assert "100.00" not in answer
