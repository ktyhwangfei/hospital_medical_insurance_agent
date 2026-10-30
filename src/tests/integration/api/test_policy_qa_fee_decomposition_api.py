"""门诊费用分解接入 policy-qa SSE 的 API 测试（Issue #78 设计 §13/§15 步骤 5）。

覆盖：
- 默认（未配置 FEE_DECOMPOSITION_* 门控）→ 公开结果不携带 fee_decomposition；
- 门控开启但 provider 无连接工厂 → 不携带（fail-closed 不影响主链路）；
- 分解成功 → result 事件携带 fee_decomposition（契约字段、金额字符串、文本已消毒），
  且原有字段与 SSE 结束语义不回归。
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
from src.runtime.policy_qa.fee_decomposition.integration import DecompositionPresentation
from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
    DecompositionOutcome,
    SettlementFactsItem,
    SettlementFactsView,
)
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
    UncertaintyModel,
)

_TRADE_NO = "011100030X240311000031"
_AUTH_SECRET = "policy-qa-fee-test-secret"


def _fee_read_headers() -> dict[str, str]:
    """与 /fee-decomposition 同一 scope 的测试令牌。"""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "policy-qa-fee-tester",
        "roles": ["information_department"],
        "permissions": ["fee_decomposition:read"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    h = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    b = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(
        _AUTH_SECRET.encode(), f"{h}.{b}".encode(), hashlib.sha256).digest()).decode().rstrip("=")
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


class _Provider:
    """门诊预取语义查询桩（无 _connect 连接工厂）。"""

    async def run_semantic_query(self, _query):
        return SimpleNamespace(
            rows=[{
                "T_FeeAll": 100, "T_FeeIn": 80, "T_FeeOut": 20,
                "T_FundPay": 70, "T_SelfPayAll": 30,
                "P_FundType": "城镇职工基本医疗保险", "PN_PersonType": "在职",
                "T_CureType": "普通门诊", "HospitalLevel": "三级",
                "P_JCLevel": "不享受伤残待遇", "T_TradeDate": "2026-08-26",
            }],
            quality_status="complete",
        )


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def outpatient_dependencies(monkeypatch):
    from skills.mzsettlement_verify_skill.assembler import (
        OutpatientSettlementVerifierAssembler,
    )

    monkeypatch.setattr(
        policy_qa_routes, "create_settlement_data_provider", lambda: _Provider())
    monkeypatch.setattr(
        policy_qa_routes, "route_question", lambda _q: "mzsettlement_verify_skill")
    monkeypatch.setattr(
        policy_qa_routes, "get_assembler",
        lambda _skill_id: OutpatientSettlementVerifierAssembler())
    monkeypatch.setattr(
        policy_qa_routes,
        "retrieve_policy_evidence",
        lambda **_kwargs: SimpleNamespace(
            selected_evidence=[], missing_required_rules=["政策证据"]),
    )
    monkeypatch.delenv("FEE_DECOMPOSITION_ROUNDING_MODE", raising=False)
    monkeypatch.delenv("FEE_DECOMPOSITION_HOSPITAL_CODE", raising=False)


def _post(client) -> list[tuple[str, dict]]:
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "这次门诊费用怎么算的", "settlement_id": _TRADE_NO},
    )
    assert response.status_code == 200
    return _sse_events(response.text)


def test_uncomputed_target_does_not_inherit_whole_order_calculation_check(
        client, outpatient_dependencies, monkeypatch):
    """问“超封顶金额”没有独立计算：整单其它步骤成功不得让 calculation_checked=true。"""
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome
    presentation = DecompositionPresentation(_result(fields=[_field()]), '核对摘要', 'template',
        SettlementFactsView(chain='outpatient', items=[SettlementFactsItem(label='总费用', value='100.00')]))
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench',
                        lambda *a, **k: WorkbenchDecompositionOutcome(
                            status='ok', chain='outpatient', presentation=presentation), raising=False)
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: SimpleNamespace(content='本单大额支付60.00元。'))
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    response = client.post('/api/v1/medical-insurance-ai-agent/policy-qa/stream', headers=_fee_read_headers(), json={
        'question': '超封顶金额是多少', 'mode': 'settlement_explain', 'settlement_id': _TRADE_NO,
        'decomposition_chain': 'outpatient'})
    events = _sse_events(response.text)
    result = next(payload['result'] for name, payload in events if name == 'result')
    assert result['fee_decomposition']
    assert result['verification_summary']['calculation_checked'] is False


def test_unmapped_bill_target_does_not_pass_empty_calculation_check(
        client, outpatient_dependencies, monkeypatch):
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import build_outpatient_facts
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field
    presentation = DecompositionPresentation(
        _result(fields=[_field(field_code='T_SelfPay2', label='自付二')]),
        '核对摘要', 'template', build_outpatient_facts({'p_fundtype': '3'}))
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench',
                        lambda *a, **k: WorkbenchDecompositionOutcome(
                            status='ok', chain='outpatient', presentation=presentation), raising=False)
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: SimpleNamespace(content='大病支付和自付二均按原单记录列示。'))
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    response = client.post('/api/v1/medical-insurance-ai-agent/policy-qa/stream', headers=_fee_read_headers(), json={
        'question': '大病支付和自付二怎么算？', 'mode': 'settlement_explain',
        'settlement_id': _TRADE_NO, 'decomposition_chain': 'outpatient'})
    events = _sse_events(response.text)
    result = next(payload['result'] for name, payload in events if name == 'result')
    assert result['verification_summary']['calculation_checked'] is False


@pytest.mark.parametrize('mode', ['structured', 'adjust'])
def test_model_fee_explanation_reaches_sse_result(
        client, outpatient_dependencies, monkeypatch, mode):
    """生产两种配置共用解释入口；模型正文原样进入 result，诊断信息不进入公开契约。"""
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome

    presentation = DecompositionPresentation(
        _result(fields=[_field(field_code='T_FeeAll', label='总费用',
                               observed_amount='100.00', calculated_amount='100.00')]), '核对摘要', 'template',
        SettlementFactsView(chain='outpatient', items=[SettlementFactsItem(label='总费用', value='100.00')]))
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench',
                        lambda *a, **k: WorkbenchDecompositionOutcome(
                            status='ok', chain='outpatient', presentation=presentation))
    calls = []
    answer = '总费用 100.00 元，是本笔结算的全部费用。'
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: calls.append(k) or SimpleNamespace(content=answer))
    monkeypatch.setenv('FEE_EXPLANATION_MODE', mode)
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    response = client.post('/api/v1/medical-insurance-ai-agent/policy-qa/stream',
                           headers=_fee_read_headers(), json={
        'question': '总费用是多少', 'mode': 'settlement_explain',
        'settlement_id': _TRADE_NO, 'decomposition_chain': 'outpatient'})
    assert response.status_code == 200
    events = _sse_events(response.text)
    result = next(payload['result'] for name, payload in events if name == 'result')
    assert result['answer'] == answer
    assert len(calls) == 1
    assert events[-1][0] == 'done'
    assert 'fallback_reason' not in result and 'model_attempted' not in result


def test_settlement_mode_renders_workbench_decomposition_deterministically(client, outpatient_dependencies, monkeypatch):
    """评审问题 1：结算解释主流拿到工作台分解后由后端证据渲染正文，不再调用模型。"""
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome
    captured = {}
    presentation = DecompositionPresentation(_result(fields=[_field()]), '原始核对摘要', 'template',
        SettlementFactsView(chain='outpatient', items=[SettlementFactsItem(label='总费用', value='100.00')]))
    def workbench(identifier, chain, provider, **_kwargs):
        captured['target'] = (identifier, chain)
        return WorkbenchDecompositionOutcome(status='ok', chain='outpatient', presentation=presentation)
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench', workbench, raising=False)
    monkeypatch.setattr(
        policy_qa_routes,
        'selected_ratio_policy_evidence',
        lambda _public, _targets=None: [('京人社医发〔2010〕100号第三条', '本次采用70%比例。')],
    )
    model_calls = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: model_calls.append(k) or SimpleNamespace(content='模型自由文本不应进入正文'))
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    response = client.post('/api/v1/medical-insurance-ai-agent/policy-qa/stream', headers=_fee_read_headers(), json={
        'question': '解释这笔结算', 'mode': 'settlement_explain', 'settlement_id': _TRADE_NO, 'decomposition_chain': 'outpatient'})
    events = _sse_events(response.text)
    result = next(payload['result'] for name, payload in events if name == 'result')
    # 确定性正文：字段事实（大额支付 60.00 元），不调用模型、不混入模型自由文本
    assert model_calls == []
    assert '60.00' in result['answer']
    assert '模型自由文本' not in result['answer']
    assert result['citations'][0]['title'] == '京人社医发〔2010〕100号第三条'
    assert result['citations'][0]['excerpt'] == '本次采用70%比例。'
    assert captured['target'] == (_TRADE_NO, 'outpatient')
    assert result['fee_decomposition']['settlement_facts']['items'][0]['value'] == '100.00'
    assert events[-1][0] == 'done'


_DJH = "604"


@pytest.fixture(autouse=True)
def no_fixed_registration_by_default(monkeypatch):
    from src.runtime.policy_qa.fee_decomposition import integration
    monkeypatch.setattr(integration, "locate_special_fixed_kidney_registration", lambda *args:
        AdapterCallResult(status=AdapterCallStatus.SUCCESS, source_system="test", capability="test",
            data={"match_status": "not_found", "registration_row": None, "row_count": 0}))


@pytest.mark.parametrize("insurance,djh,fund", [("employee", "814", "3"), ("resident", "688", "93"), ("fixed", "609", "3")])
def test_special_secondary_payments_survive_sse_public_contract(
    client, monkeypatch, outpatient_dependencies, insurance, djh, fund,
):
    """真实算法结果经过 API 序列化仍保留二次保障字段、差异与来源。"""
    from src.runtime.policy_qa.fee_decomposition import integration
    from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import decompose_employee_outpatient_special
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import decompose_resident_outpatient_special
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import _snapshot_djh814
    from src.tests.unit.runtime.policy_qa.fee_decomposition import test_resident_outpatient_special as resident

    class Connection:
        def close(self):
            pass
    provider = _Provider()
    provider._connect = lambda db: Connection()
    monkeypatch.setattr(policy_qa_routes, "create_settlement_data_provider", lambda: provider)
    monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
    monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
    def locate(hit):
        return AdapterCallResult(status=AdapterCallStatus.SUCCESS, source_system="test", capability="test",
            data={"match_status": "unique_match" if hit else "not_found",
                "registration_row": {"fund_type": fund, "yllb": "12", "tsb1": "503" if insurance == "fixed" else "506"} if hit else None,
                "row_count": 1 if hit else 0})
    monkeypatch.setattr(integration, "locate_special_mz_registration", lambda *args: locate(insurance == "employee"))
    monkeypatch.setattr(integration, "locate_special_mz_resident_registration", lambda *args: locate(insurance == "resident"))
    monkeypatch.setattr(integration, "locate_special_fixed_kidney_registration", lambda *args: locate(insurance == "fixed"))
    calculation = (decompose_employee_outpatient_special(_snapshot_djh814()) if insurance == "employee" else
        decompose_resident_outpatient_special(resident._snapshot(), resident._split()))
    service = "decompose_special_mz_settlement" if insurance == "employee" else "decompose_special_mz_resident_settlement"
    if insurance == "fixed":
        from src.tests.unit.runtime.policy_qa.fee_decomposition.test_kidney_fixed_quota import kidney_snapshot
        from src.runtime.policy_qa.fee_decomposition.employee_special_fixed_kidney import decompose_kidney_fixed_quota
        calculation = decompose_kidney_fixed_quota(kidney_snapshot())
        service = "decompose_special_fixed_kidney_settlement"
    monkeypatch.setattr(
        integration, service, lambda *args, **kwargs: DecompositionOutcome(calculation))
    response = client.post("/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "这次门特门诊费用怎么算的", "settlement_id": djh})
    assert response.status_code == 200
    events = _sse_events(response.text)
    result = next(data["result"] for name, data in events if name == "result")
    decomposition = result["fee_decomposition"]
    fields = {field["field_code"]: field for field in decomposition["fields"]}
    expected = {field.field_code: field for field in calculation.fields}
    for code in ("BIG_ILL_PAY", "FEEIN_DB_PAY", "FEEOUT_DB_PAY", "CIVIL_IN", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY", "PERSON_PAYABLE"):
        assert fields[code]["calculated_amount"] == expected[code].calculated_amount
        assert fields[code]["check_status"] == expected[code].check_status
    assert result["citations"] or decomposition["uncertainties"]
    # “尚待核实”不再展示候选口径/待签核与“未检索到政策依据”这类无行动价值提示
    assert not any("未检索到可展示的政策依据" in item for item in result["uncertainties"])
    assert not any("待签核" in item for item in result["uncertainties"])
    assert decomposition["may_claim_full_explanation"] is False
    if insurance == "fixed":
        assert decomposition["algorithm_version"] == "employee_special_fixed_kidney_v1"
        assert fields["GRZIF1"]["calculated_amount"] == "1315.40"
        assert fields["PERSON_PAYABLE"]["calculated_amount"] == "68.85"
    assert events[-1][0] == "done"


def _post_special(client) -> list[tuple[str, dict]]:
    """门特问题 + djh 登记号（第二流程路由信号）。"""
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={"question": "这次门特门诊费用怎么算的", "settlement_id": _DJH},
    )
    assert response.status_code == 200
    return _sse_events(response.text)


def _canned_presentation() -> DecompositionPresentation:
    result = SettlementDecompositionResult(
        settlement_ref=f"settlement:{_TRADE_NO}",
        profile=DecompositionProfile(insurance_type="employee", medical_category="outpatient"),
        execution_status="partial",
        reconciliation_status="matched",
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
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False),
    )
    return DecompositionPresentation(
        result=result,
        summary_text="费用分解：部分解释。涉及 yb_ypzdml 目录核对。",
        summary_source="template",
        settlement_facts=_canned_facts(),
    )


def _canned_facts() -> SettlementFactsView:
    return SettlementFactsView(
        chain="outpatient", identifier=_TRADE_NO, trade_date="2024-06-01",
        medical_category="11", insurance_type="3", person_type="11",
        hospital_level=None,
        items=[SettlementFactsItem(label="费用总金额", value="100.00")],
        payment_items=[SettlementFactsItem(label="个人账户支付", value="0.00")],
    )


class TestFeeDecompositionPublicContract:
    def test_sse_carries_the_same_safe_display_template(self, client, monkeypatch, outpatient_dependencies):
        from dataclasses import replace
        from src.runtime.policy_qa.fee_decomposition.settlement_facts import build_outpatient_facts
        facts = build_outpatient_facts({'p_fundtype': '3', 't_feein': '1812.37', 't_beyondbig': '0.00'})
        presentation = replace(_canned_presentation(), settlement_facts=facts)
        monkeypatch.setattr(policy_qa_routes, 'maybe_decompose_outpatient', lambda *_args: presentation)
        events = _post(client)
        result = next(data['result'] for name, data in events if name == 'result')
        template = result['fee_decomposition']['settlement_facts']['display_template']
        fields = {field['key']: field for field in template['fields']}
        assert fields['fee_in']['label'] == '医疗保险范围内金额'
        assert fields['fee_in']['value'] == '1812.37'
        assert fields['fee_in']['field_code'] == 'T_FeeIn'
        assert template['template_id'] == 'employee_outpatient'
        assert 'source_table' not in json.dumps(template)
        assert events[-1][0] == 'done'

    def test_gate_disabled_by_default(
        self, client, monkeypatch, outpatient_dependencies
    ):
        events = _post(client)
        result = next(data["result"] for name, data in events if name == "result")
        assert "fee_decomposition" not in result
        assert events[-1][0] == "done"

    def test_gate_enabled_without_connection_factory_fails_closed(
        self, client, monkeypatch, outpatient_dependencies
    ):
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        events = _post(client)
        result = next(data["result"] for name, data in events if name == "result")
        assert "fee_decomposition" not in result
        assert events[-1][0] == "done"

    def test_decomposition_result_carried_in_public_contract(
        self, client, monkeypatch, outpatient_dependencies
    ):
        monkeypatch.setattr(
            policy_qa_routes, "maybe_decompose_outpatient",
            lambda *_args: _canned_presentation())

        events = _post(client)
        result = next(data["result"] for name, data in events if name == "result")

        view = result["fee_decomposition"]
        assert view["schema_version"] == "1.10"
        assert view["algorithm_version"] == "employee_outpatient_v1"
        assert view["execution_status"] == "partial"
        # 1.2 新块：结算事实侧车随主链透传（文本已消毒）
        assert view["settlement_facts"]["identifier"] == _TRADE_NO
        assert view["settlement_facts"]["items"] == [
            {"label": "费用总金额", "value": "100.00"}]
        assert view["reconciliation_status"] == "matched"
        assert view["may_claim_full_explanation"] is False
        assert view["summary_source"] == "template"
        # 文本经公开消毒：物理表名被替换
        assert "yb_ypzdml" not in view["summary_text"]
        assert "结算数据字段" in view["summary_text"]
        # 金额十进制字符串透传
        field = view["fields"][0]
        assert field["field_code"] == "T_FeeAll"
        assert field["label"] == "总费用"
        assert field["observed_amount"] == "100.00"
        assert field["calculated_amount"] == "100.00"
        assert field["difference"] == "0.00"
        assert view["uncertainties"] == [
            {"code": "ROUNDING_RULE_PENDING_CONFIRMATION",
             "message": "取整规则 EOP-RND-001 待确认。",
             "id": "u.rounding.rule", "affected_fields": [], "scope": "global"}
        ]
        assert view["coverage"]["target_field_count"] == 1
        # 既有字段与 SSE 结束语义不回归
        assert result["scenario_id"] == "overall-settlement-verification"
        assert events[-1][0] == "done"
        done = events[-1][1]
        assert done["success"] is True
        assert done["halt_reason"] == "verified"

    def test_gate_enabled_runs_real_integration_path(
        self, client, monkeypatch, outpatient_dependencies
    ):
        """门控开启 + provider 带连接工厂：走真实 integration（env 门控 → 连接 →
        decompose → 渲染 → 公开契约），仅替换最内层分解调用与模型润色。"""
        from src.runtime.policy_qa.fee_decomposition import integration

        class _Conn:
            def close(self):
                pass

        class _ConnectableProvider(_Provider):
            _connect = lambda self, _db: _Conn()  # noqa: E731

        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider",
            lambda: _ConnectableProvider())
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        captured = {}

        def fake_decompose(_conn, trade_no, hospital_code, rounding_mode,
                           profile_resolver=None):
            captured["trade_no"] = trade_no
            captured["hospital_code"] = hospital_code
            # 预取上下文为职工+普通门诊，resolver 应精确命中
            captured["resolved"] = profile_resolver({}) if profile_resolver else None
            return DecompositionOutcome(_canned_presentation().result, _canned_facts())

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))

        events = _post(client)
        result = next(data["result"] for name, data in events if name == "result")

        assert captured["trade_no"] == _TRADE_NO
        assert captured["hospital_code"] == "H001"
        assert captured["resolved"] == ("employee", "outpatient")
        assert result["fee_decomposition"]["execution_status"] == "partial"
        assert events[-1][0] == "done"

    def test_special_djh_question_runs_special_integration_path(
        self, client, monkeypatch, outpatient_dependencies
    ):
        """门特问题 + djh 输入：走 maybe_decompose_special_outpatient（第二流程）。

        仅替换最内层分解调用与模型润色，验证路由信号（问题含门特 + djh）与
        provider 连接复用；profile 由唯一登记的原始险种和医疗类别确认。
        """
        from src.runtime.policy_qa.fee_decomposition import integration

        class _Conn:
            def close(self):
                pass

        class _ConnectableProvider(_Provider):
            _connect = lambda self, _db: _Conn()  # noqa: E731

        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider",
            lambda: _ConnectableProvider())
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        captured = {}

        def fake_special_decompose(
            _conn, djh, hospital_code, rounding_mode,
            profile=None, allow_observed_deductible=False,
        ):
            captured["djh"] = djh
            captured["hospital_code"] = hospital_code
            captured["profile"] = profile
            return DecompositionOutcome(_canned_presentation().result)

        def _locate(match_status: str):
            return AdapterCallResult(
                status=AdapterCallStatus.SUCCESS, source_system="test",
                capability="test",
                data={"match_status": match_status,
                      "registration_row": {"fund_type": "3", "yllb": "12"} if match_status == "unique_match" else None,
                      "row_count": 1 if match_status == "unique_match" else 0})

        monkeypatch.setattr(
            integration, "locate_special_mz_registration",
            lambda _conn, _djh: _locate("unique_match"))
        # 居民门特定位桩（Issue #81 三路消歧扩展）：本用例不命中
        monkeypatch.setattr(
            integration, "locate_special_mz_resident_registration",
            lambda _conn, _djh: _locate("not_found"))
        monkeypatch.setattr(
            integration, "decompose_special_mz_settlement", fake_special_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "这次门特门诊费用怎么算的", "settlement_id": "567"},
        )
        assert response.status_code == 200
        events = _sse_events(response.text)
        result = next(data["result"] for name, data in events if name == "result")

        # 门特登记事实确认职工险种，不依赖缺失的问答预取上下文。
        assert captured["djh"] == "567"
        assert captured["hospital_code"] == "H001"
        assert captured["profile"] == ("employee", "outpatient_special")
        assert result["fee_decomposition"]["execution_status"] == "partial"
        assert events[-1][0] == "done"

    def test_special_djh_question_gate_disabled_fails_closed(
        self, client, monkeypatch, outpatient_dependencies
    ):
        """门控未配置：门特问题 + djh → 无 fee_decomposition（fail-closed）。"""
        events = _post_special(client)
        result = next(data["result"] for name, data in events if name == "result")
        assert "fee_decomposition" not in result
        assert events[-1][0] == "done"

    def test_special_djh_question_without_connect_fails_closed(
        self, client, monkeypatch, outpatient_dependencies
    ):
        """门控开启但 provider 无连接工厂：门特问题 + djh → 不携带（fail-closed）。"""
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        events = _post_special(client)
        result = next(data["result"] for name, data in events if name == "result")
        assert "fee_decomposition" not in result
        assert events[-1][0] == "done"

    def test_resident_profile_resolved_and_dispatched(
        self, client, monkeypatch, outpatient_dependencies
    ):
        """Issue #80：居民险种（城乡居民基本医疗保险）预取上下文 → resolver 命中
        ("resident","outpatient")，分发到居民内核（algorithm_version=resident_outpatient_v1）。"""
        from src.runtime.policy_qa.fee_decomposition import integration

        class _ResidentProvider(_Provider):
            async def run_semantic_query(self, _query):
                return SimpleNamespace(
                    rows=[{
                        "T_FeeAll": 180, "T_FeeIn": 168, "T_FeeOut": 12,
                        "T_FundPay": 72.5, "T_SelfPayAll": 107.5,
                        "P_FundType": "城乡居民基本医疗保险", "PN_PersonType": "城镇学生",
                        "T_CureType": "普通门诊", "HospitalLevel": "三级",
                        "P_JCLevel": "不享受伤残待遇", "T_TradeDate": "2024-09-13",
                    }],
                    quality_status="complete",
                )

        class _Conn:
            def close(self):
                pass

        class _ConnectableProvider(_ResidentProvider):
            _connect = lambda self, _db: _Conn()  # noqa: E731

        monkeypatch.setattr(
            policy_qa_routes, "create_settlement_data_provider",
            lambda: _ConnectableProvider())
        monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
        monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "H001")
        captured = {}

        def fake_decompose(_conn, trade_no, hospital_code, rounding_mode,
                           profile_resolver=None):
            captured["resolved"] = profile_resolver({}) if profile_resolver else None
            result = _canned_presentation().result.model_copy(
                update={"algorithm_version": "resident_outpatient_v1"})
            return DecompositionOutcome(result)

        monkeypatch.setattr(integration, "decompose_outpatient_trade", fake_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))

        events = _post(client)
        result = next(data["result"] for name, data in events if name == "result")

        assert captured["resolved"] == ("resident", "outpatient")
        assert result["fee_decomposition"]["algorithm_version"] == "resident_outpatient_v1"
        assert events[-1][0] == "done"



# ── 明细行目标：calculation_checked 与来源筛选走本行口径（Issue #78 用户故事步骤 5） ──


def _line_target_presentation() -> DecompositionPresentation:
    """两行同名人工晶体的居民门诊分解：第 2 行限价拆分（1835/100）、可解释。"""
    from src.runtime.policy_qa.fee_decomposition.fee_items import (
        FeeItemDecision,
        FeeItemExplanation,
    )
    from src.runtime.policy_qa.fee_decomposition.result import (
        BranchTraceModel,
        CalculationRecordModel,
        CitationModel,
    )
    result = SettlementDecompositionResult(
        settlement_ref=f"settlement:{_TRADE_NO}",
        profile=DecompositionProfile(insurance_type="resident", medical_category="outpatient"),
        execution_status="complete",
        reconciliation_status="matched",
        fields=[FieldExplanationModel(
            field_code="T_FeeAll", label="费用总金额", check_type="detail_aggregation",
            check_status="matched", observed_amount="2135.00",
            calculated_amount="2135.00", difference="0.00",
            explanation_level="amount_reconciled")],
        calculations=[CalculationRecordModel(
            calculation_id="calc.catalog.material_price_limit.1",
            formula_id="material_price_limit_v1", formula_version="v1",
            operands=[], result="1835.00")],
        branches=[BranchTraceModel(
            step_id="catalog.material_price_limit.1", module_id="catalog_split",
            outcome="true", rule_refs=["EOP-MAT-005"],
            calculation_refs=["calc.catalog.material_price_limit.1"])],
        citations=[CitationModel(
            id="rule.EOP-MAT-005", kind="policy_document",
            ref="mz.docx 城乡居民基本医疗保险-门诊§材料限价",
            value="EOP-MAT-005", values=["V2021-01-01"],
            approval_status="文档明确-待官方核证")],
        fee_items=[
            FeeItemExplanation(
                line_id="0", item_code="C08010415101001",
                item_name="单焦点散光型白内障人工晶体",
                unit_price="200.00", quantity="1.00", total_fee="200.00",
                observed_in_scope="200.00", observed_out_scope="0.00",
                observed_self_pay_2="0.00", calculated_in_scope="200.00",
                calculated_out_scope="0.00", calculated_self_pay_2="0.00",
                status="calculated", division_method="full_in"),
            FeeItemExplanation(
                line_id="1", item_code="C08010415101001",
                item_name="单焦点散光型白内障人工晶体",
                unit_price="1935.00", quantity="1.00", total_fee="1935.00",
                observed_in_scope="1835.00", observed_out_scope="100.00",
                observed_self_pay_2="100.00", calculated_in_scope="1835.00",
                calculated_out_scope="100.00", calculated_self_pay_2="100.00",
                status="calculated", division_method="limit",
                unit_price_limit="1835.00", limit_source="明细结算时限价",
                calculation_refs=["calc.catalog.material_price_limit.1"],
                decision_path=[FeeItemDecision(
                    code="material_price_limit",
                    label="材料单价超结算时限价：限内纳入、超限自担",
                    operator="gt", actual="1935.00", expected="1835.00",
                    outcome="true", rule_refs=["EOP-MAT-005"],
                    calculation_refs=["calc.catalog.material_price_limit.1"])]),
        ],
        coverage=CoverageSummary(
            target_field_count=1, independently_explained_count=0,
            amount_reconciled_count=1, observed_only_count=0),
        answer_constraints=AnswerConstraints(may_claim_full_explanation=False),
    )
    return DecompositionPresentation(
        result=result,
        summary_text="费用分解：完整解释。",
        summary_source="template",
        settlement_facts=SettlementFactsView(
            chain="outpatient", identifier=_TRADE_NO,
            items=[SettlementFactsItem(label="费用总金额", value="2135.00")]),
    )


def _post_line_question(client, question: str) -> dict:
    response = client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        headers=_fee_read_headers(),
        json={"question": question, "mode": "settlement_explain",
              "settlement_id": _TRADE_NO, "decomposition_chain": "outpatient"})
    assert response.status_code == 200
    events = _sse_events(response.text)
    result = next(payload["result"] for name, payload in events if name == "result")
    assert events[-1][0] == "done"
    return result


def test_fee_line_question_scopes_check_and_citations_to_the_line(
        client, outpatient_dependencies, monkeypatch):
    """fee_line 问题：calculation_checked = 目标行 explainable；来源围绕本行限价路径。"""
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome
    presentation = _line_target_presentation()
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench',
                        lambda *a, **k: WorkbenchDecompositionOutcome(
                            status='ok', chain='outpatient', presentation=presentation),
                        raising=False)
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: SimpleNamespace(
                            content='第2行人工晶体医保内1835.00元，医保外100.00元。'))
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    result = _post_line_question(client, '第 2 行人工晶体为什么贵')
    assert result['verification_summary']['calculation_checked'] is True
    titles = [citation['title'] for citation in result['citations']]
    assert any('材料限价' in title for title in titles)
    # 本行限价路径来源，不带整单待遇比例口径
    excerpts = "；".join(citation['excerpt'] for citation in result['citations'])
    assert '本行实际执行' in excerpts or '限价' in excerpts


def test_ambiguous_line_question_is_not_marked_checked(
        client, outpatient_dependencies, monkeypatch):
    """同名两行只报名称：ambiguous 定位提示直出，calculation_checked=False，不调模型。"""
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome
    presentation = _line_target_presentation()
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench',
                        lambda *a, **k: WorkbenchDecompositionOutcome(
                            status='ok', chain='outpatient', presentation=presentation),
                        raising=False)
    called = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: called.append(1) or SimpleNamespace(content='x'))
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    result = _post_line_question(client, '人工晶体为什么贵')
    assert called == []
    assert result['verification_summary']['calculation_checked'] is False
    assert '第 1 行' in result['answer'] and '第 2 行' in result['answer']
    assert '200.00' in result['answer'] and '1935.00' in result['answer']


# ── 评审问题 2/8：混合目标与 bill.* 的 SSE 契约 ──


def _mixed_presentation():
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_public_view import _result, _field
    from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
    from src.runtime.policy_qa.fee_decomposition.result import (
        CalculationOperandModel, CalculationRecordModel)
    from src.runtime.policy_qa.fee_decomposition.settlement_facts import (
        SettlementDisplayField, SettlementDisplayView)
    result = _result(fields=[
        _field(field_code='T_FeeAll', label='费用总金额', observed_amount='100.00',
               calculated_amount='100.00', check_type='detail_aggregation',
               calculation_refs=['calc.catalog.total_fee']),
        _field(field_code='T_FeeIn', label='医疗保险范围内金额', observed_amount='80.00',
               calculated_amount='80.00', calculation_refs=['calc.catalog.total_in_scope']),
    ]).model_copy(update={
        'calculations': [
            CalculationRecordModel(
                calculation_id='calc.catalog.total_fee', formula_id='catalog_total_fee_v1',
                formula_version='v1', result='100.00',
                operands=[CalculationOperandModel(ref='fact.items.fee', value='100.00')]),
            CalculationRecordModel(
                calculation_id='calc.catalog.total_in_scope', formula_id='catalog_total_in_scope_v1',
                formula_version='v1', result='80.00',
                operands=[CalculationOperandModel(ref='calc.catalog.lines.in_scope', value='80.00')]),
        ],
        'fee_items': [FeeItemExplanation(
            line_id='0', item_name='测试药品', unit_price='80.00', quantity='1.00', total_fee='80.00',
            observed_in_scope='80.00', observed_out_scope='0.00', observed_self_pay_2='0.00',
            calculated_in_scope='80.00', calculated_out_scope='0.00', calculated_self_pay_2='0.00',
            status='calculated', verification_status='verified', explainable=True,
            division_method='full_in')],
    })
    facts = SettlementFactsView(
        chain='outpatient',
        items=[SettlementFactsItem(label='费用总金额', value='100.00')],
        display_template=SettlementDisplayView(
            template_id='employee_outpatient', version='1.0', title='职工门诊结算单',
            layout_status='provisional',
            fields=[
                SettlementDisplayField(
                    key='fee_all', label='费用总金额', section='transaction', row=1, column=1,
                    scope='patient_actual', value='100.00', field_code='T_FeeAll',
                    source_kind='record', status='available'),
                SettlementDisplayField(
                    key='fee_in', label='医疗保险范围内金额', section='transaction', row=1, column=2,
                    scope='patient_actual', value='80.00', field_code='T_FeeIn',
                    source_kind='record', status='available'),
                SettlementDisplayField(
                    key='beyond_cap', label='大额超封顶金额', section='transaction', row=2, column=1,
                    scope='patient_actual', value='0.00', field_code=None,
                    source_kind='unmapped', status='unmapped'),
            ]))
    return DecompositionPresentation(result, '核对摘要', 'template', facts)


def _post_fee_question(client, monkeypatch, question: str):
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench',
                        lambda *a, **k: WorkbenchDecompositionOutcome(
                            status='ok', chain='outpatient', presentation=_mixed_presentation()),
                        raising=False)
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    response = client.post('/api/v1/medical-insurance-ai-agent/policy-qa/stream',
                           headers=_fee_read_headers(), json={
                               'question': question, 'mode': 'settlement_explain',
                               'settlement_id': _TRADE_NO, 'decomposition_chain': 'outpatient'})
    assert response.status_code == 200
    events = _sse_events(response.text)
    return next(payload['result'] for name, payload in events if name == 'result')


def test_mixed_question_covers_summary_field_and_line(client, outpatient_dependencies, monkeypatch):
    """评审问题 2："费用总金额和第1行医保内各是多少"两个目标都交付、均可核对。"""
    result = _post_fee_question(client, monkeypatch, '费用总金额和第1行医保内各是多少')
    assert '100.00' in result['answer']
    assert '80.00' in result['answer']
    assert '测试药品' in result['answer']
    assert result['verification_summary']['calculation_checked'] is True


def test_cover_all_with_uncheckable_bill_field_is_not_calculation_checked(
        client, outpatient_dependencies, monkeypatch):
    """评审问题 2/8：全覆盖含不可核对模板字段（bill.*）时 calculation_checked=False；
    但正文仍交付全部可见金额与全部行。"""
    result = _post_fee_question(client, monkeypatch, '解释全部费用')
    assert result['verification_summary']['calculation_checked'] is False
    assert '100.00' in result['answer']
    assert '大额超封顶金额' in result['answer']
    assert '测试药品' in result['answer']


def test_bill_target_answer_lists_book_fact_without_calculation_check(
        client, outpatient_dependencies, monkeypatch):
    """bill.* 单独提问：列示原单金额与明确边界（有效事实回答），但不计独立核对完成。"""
    result = _post_fee_question(client, monkeypatch, '大额超封顶金额是多少')
    assert '大额超封顶金额 0.00 元' in result['answer']
    assert '仅按原单列示' in result['answer']
    assert result['verification_summary']['calculation_checked'] is False


@pytest.mark.parametrize(('question', 'code', 'reason', 'answer'), [
    ('残疾军人补助支付金额为什么是0', 'T_JCPay', 'NO_MILITARY_DISABILITY_BENEFIT',
     '残疾军人补助支付金额为0元，本单伤残待遇等级登记为不享受，因此本项不适用。'),
    ('单位补充医疗保险（原公疗）支付金额为什么是0', 'T_OfficalPay', 'PUBLIC_MEDICAL_CHANNEL_NOT_SELECTED',
     '单位补充医疗保险（原公疗）支付金额为0元，本笔待遇类别为未选择该通道；这不代表患者永久没有资格。'),
])
def test_zero_benefit_branch_and_source_reach_model_and_sse(
        client, outpatient_dependencies, monkeypatch, question, code, reason, answer):
    from src.runtime.policy_qa.fee_decomposition.integration import WorkbenchDecompositionOutcome
    from src.tests.unit.runtime.policy_qa.fee_decomposition.test_zero_benefit_reasons import _result

    _, decomposition = _result(military_disability_level_code='0', public_medical_flag='0',
                               public_medical_treatment_code='0')
    presentation = DecompositionPresentation(decomposition, '', 'template', SettlementFactsView(
        chain='outpatient', items=[SettlementFactsItem(label='费用总金额', value='3000.00')]))
    monkeypatch.setattr(policy_qa_routes, 'decompose_for_workbench',
                        lambda *a, **k: WorkbenchDecompositionOutcome(
                            status='ok', chain='outpatient', presentation=presentation))
    calls = []
    monkeypatch.setattr('src.model_service.gateway.ModelGateway.generate',
                        lambda *a, **k: calls.append(k) or SimpleNamespace(content=answer))
    monkeypatch.setenv('FEE_EXPLANATION_MODE', 'structured')
    monkeypatch.setenv('AUTH_JWT_SECRET', _AUTH_SECRET)
    response = client.post('/api/v1/medical-insurance-ai-agent/policy-qa/stream',
                           headers=_fee_read_headers(), json={
                               'question': question, 'mode': 'settlement_explain',
                               'settlement_id': _TRADE_NO, 'decomposition_chain': 'outpatient'})
    assert response.status_code == 200
    events = _sse_events(response.text)
    result = next(payload['result'] for name, payload in events if name == 'result')
    assert len(calls) == 1
    assert result['answer'] == answer
    public = result['fee_decomposition']
    field = next(field for field in public['fields'] if field['field_code'] == code)
    assert field['reason_code'] == reason
    assert field['source_refs']
    assert any(condition['actual_display'] == '0' for condition in public['conditions'])
    assert not any(code in gap['affected_fields'] for gap in public['uncertainties'])
    assert events[-1][0] == 'done'
