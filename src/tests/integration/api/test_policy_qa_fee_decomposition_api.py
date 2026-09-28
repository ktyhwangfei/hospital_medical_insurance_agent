"""门诊费用分解接入 policy-qa SSE 的 API 测试（Issue #78 设计 §13/§15 步骤 5）。

覆盖：
- 默认（未配置 FEE_DECOMPOSITION_* 门控）→ 公开结果不携带 fee_decomposition；
- 门控开启但 provider 无连接工厂 → 不携带（fail-closed 不影响主链路）；
- 分解成功 → result 事件携带 fee_decomposition（契约字段、金额字符串、文本已消毒），
  且原有字段与 SSE 结束语义不回归。
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.runtime.api import policy_qa_routes
from src.runtime.api.app import create_app
from src.runtime.policy_qa.fee_decomposition.integration import DecompositionPresentation
from src.runtime.policy_qa.fee_decomposition.result import (
    AnswerConstraints,
    CoverageSummary,
    DecompositionProfile,
    FieldExplanationModel,
    SettlementDecompositionResult,
    UncertaintyModel,
)

_TRADE_NO = "011100030X240311000031"


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


_DJH = "604"


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
    )


class TestFeeDecompositionPublicContract:
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
        assert view["schema_version"] == "1.0"
        assert view["algorithm_version"] == "employee_outpatient_v1"
        assert view["execution_status"] == "partial"
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
             "message": "取整规则 EOP-RND-001 待确认。"}
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
            return _canned_presentation().result

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
        provider 连接复用；profile 未签核（ESP-CODE-001/002）时为 None（fail-closed）。
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
            profile=None, cycle_context_override=None, allow_observed_deductible=False,
        ):
            captured["djh"] = djh
            captured["hospital_code"] = hospital_code
            captured["profile"] = profile
            return _canned_presentation().result

        monkeypatch.setattr(
            integration, "decompose_outpatient_special_settlement", fake_special_decompose)
        monkeypatch.setattr(
            integration, "polish_summary", lambda text: (text, "template"))

        response = client.post(
            "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
            json={"question": "这次门特门诊费用怎么算的", "settlement_id": "604"},
        )
        assert response.status_code == 200
        events = _sse_events(response.text)
        result = next(data["result"] for name, data in events if name == "result")

        # 门特 djh 路由命中：走 special 服务，profile 未签核保持 None
        assert captured["djh"] == "604"
        assert captured["hospital_code"] == "H001"
        assert captured["profile"] is None
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
