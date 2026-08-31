"""门诊部分项目预退费分析的 Policy QA 完整 Flow 测试。"""

import json
import os
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

os.environ["USE_MEMORY_STORAGE"] = "1"

from src.adapters.base.models import AdapterCallContext
from src.adapters.base.service import failed_result, successful_result
from src.adapters.billing.models import (
    PartialRefundPreview,
    PreSettlementErrorType,
    PreviewedRefundItem,
    SettlementAmountSnapshot,
)
from src.runtime.api.app import create_app
from src.runtime.api.schemas import AgentResponse


def _events(body: str) -> list[tuple[str, dict]]:
    parsed = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event_name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data += line.removeprefix("data:").lstrip()
        if event_name and data:
            parsed.append((event_name, json.loads(data)))
    return parsed


class SequenceBillingAdapter:
    def __init__(self, *results):
        self._results = list(results)
        self.preview_calls = 0

    def query_billing_status(self, patient_id: str, encounter_id: str):
        raise AssertionError("预退费 Flow 不应查询旧收费状态")

    def preview_partial_refund(self, original_trade_no: str, items):
        self.preview_calls += 1
        return self._results.pop(0)


def _preview(*, accepted: bool = True, fee_detail_id: str = "F001"):
    if not accepted:
        return PartialRefundPreview(
            accepted=False,
            original_trade_no="OP-001",
            response_code="QTY_EXCEEDED",
            response_message="拟退数量超过可退数量",
            preview_id="PRE-REJECT-001",
            source_system="院端收费系统",
            source_reference="PRE-REJECT-001",
            items=(),
            before=None,
            after=None,
        )
    return PartialRefundPreview(
        accepted=True,
        original_trade_no="OP-001",
        response_code="0",
        response_message="预结算成功",
        preview_id="PRE-001",
        source_system="院端收费系统",
        source_reference="PRE-001",
        items=(
            PreviewedRefundItem(
                fee_detail_id=fee_detail_id,
                refund_quantity=Decimal("1"),
                refundable_quantity=Decimal("1"),
                refund_amount=Decimal("20"),
            ),
        ),
        before=SettlementAmountSnapshot(
            total_amount=Decimal("100"),
            fund_amount=Decimal("60"),
            personal_amount=Decimal("40"),
        ),
        after=SettlementAmountSnapshot(
            total_amount=Decimal("80"),
            fund_amount=Decimal("48"),
            personal_amount=Decimal("32"),
        ),
    )


def _success(*, accepted: bool = True, fee_detail_id: str = "F001"):
    return successful_result(
        context=AdapterCallContext(),
        source_system="billing",
        source_record_id="PRE-001",
        capability="preview_partial_refund",
        data={
            "preview": _preview(
                accepted=accepted,
                fee_detail_id=fee_detail_id,
            )
        },
    )


def _unavailable():
    return failed_result(
        context=AdapterCallContext(),
        source_system="billing",
        capability="preview_partial_refund",
        error_type=PreSettlementErrorType.UNAVAILABLE.value,
        message="院端预结算暂时不可用",
    )


@pytest.fixture(autouse=True)
def isolate_risk_rules(monkeypatch):
    monkeypatch.setattr(
        "src.runtime.policy_qa.pre_refund_flow.detect_blocked_actions",
        lambda question: [("退费", "hardcoded")] if "退费" in question else [],
    )


def _client(adapter=None) -> TestClient:
    from src.runtime.api import policy_qa_routes

    app = create_app()
    if adapter is not None:
        app.dependency_overrides[policy_qa_routes.get_pre_refund_billing_adapter] = (
            lambda: adapter
        )
    return TestClient(app)


def _post(client: TestClient, question: str = "部分项目预退费分析"):
    return client.post(
        "/api/v1/medical-insurance-ai-agent/policy-qa/stream",
        json={
            "question": question,
            "settlement_id": "OP-001",
            "pre_refund_items": [
                {"fee_detail_id": "F001", "refund_quantity": "1"}
            ],
        },
    )


def test_successful_official_preview_completes_end_to_end():
    adapter = SequenceBillingAdapter(_success())

    events = _events(_post(_client(adapter)).text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")
    completed_steps = [
        data["step"]
        for name, data in events
        if name == "step" and data["status"] == "done"
    ]

    assert completed_steps == [
        "intent_detection",
        "skill_routing",
        "pre_refund_analysis",
        "verification",
    ]
    assert result["answer_status"] == "complete"
    assert result["verification_summary"] == {
        "settlement_checked": True,
        "calculation_checked": True,
        "policy_count": 0,
        "message": "院端官方预结算结果及来源已完成核对。",
    }
    assert result["citations"]
    assert result["uncertainties"] == []
    assert done["attempt_count"] == 1
    assert done["halt_reason"] == "official_pre_settlement_verified"
    assert adapter.preview_calls == 1


def test_default_adapter_returns_unavailable_without_fake_amounts():
    events = _events(_post(_client()).text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["answer_status"] == "unavailable"
    assert result["case_context"] is None
    assert result["calculation_steps"] == []
    assert result["citations"] == []
    assert done["attempt_count"] == 1
    assert done["halt_reason"] == PreSettlementErrorType.NOT_CONFIGURED.value


def test_transient_failure_recovers_once_then_completes():
    adapter = SequenceBillingAdapter(_unavailable(), _success())

    events = _events(_post(_client(adapter)).text)
    done = next(data for name, data in events if name == "done")

    assert any(
        name == "step" and data["step"] == "recovery"
        for name, data in events
    )
    assert done["answer_status"] == "complete"
    assert done["attempt_count"] == 2
    assert adapter.preview_calls == 2


def test_repeated_transient_failure_stops_after_two_attempts():
    adapter = SequenceBillingAdapter(_unavailable(), _unavailable())

    events = _events(_post(_client(adapter)).text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["answer_status"] == "unavailable"
    assert done["attempt_count"] == 2
    assert done["halt_reason"] == PreSettlementErrorType.UNAVAILABLE.value
    assert adapter.preview_calls == 2


def test_official_rejection_is_a_complete_traced_result():
    adapter = SequenceBillingAdapter(_success(accepted=False))

    result = next(
        data["result"]
        for name, data in _events(_post(_client(adapter), "退费试算").text)
        if name == "result"
    )

    assert result["answer_status"] == "complete"
    assert "QTY_EXCEEDED" in result["answer"]
    assert result["citations"]


def test_mismatched_official_item_is_unavailable_without_retry():
    adapter = SequenceBillingAdapter(_success(fee_detail_id="F999"))

    events = _events(_post(_client(adapter)).text)
    result = next(data["result"] for name, data in events if name == "result")
    done = next(data for name, data in events if name == "done")

    assert result["answer_status"] == "unavailable"
    assert done["halt_reason"] == "pre_settlement_verification_failed"
    assert adapter.preview_calls == 1


def test_actual_refund_waits_for_human_with_zero_adapter_calls(monkeypatch):
    adapter = SequenceBillingAdapter(_success())
    monkeypatch.setattr(
        "src.runtime.policy_qa.pre_refund_flow.build_human_confirmation_response",
        lambda actions: AgentResponse(
            scenario="high_risk_action_confirmation",
            status="waiting_human_confirmation",
            blocked_actions=[action for action, _rule in actions],
            uncertainties=["AI 不会自动执行退费"],
        ),
    )

    events = _events(_post(_client(adapter), "请立即执行退费").text)
    done = next(data for name, data in events if name == "done")

    assert done["status"] == "waiting_human_confirmation"
    assert done["attempt_count"] == 0
    assert done["halt_reason"] == "high_risk_action_requires_human_confirmation"
    assert adapter.preview_calls == 0
