from importlib.util import find_spec
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.adapters.base.models import AdapterCallContext
from src.adapters.base.service import failed_result, successful_result
from src.adapters.billing.models import (
    PartialRefundPreview,
    PreSettlementErrorType,
    PreviewedRefundItem,
    SettlementAmountSnapshot,
)
from src.runtime.api.schemas import AgentResponse
from src.runtime.policy_qa import models
from src.runtime.policy_qa.models import PolicyQARequest, PreRefundItemInput
from src.runtime.policy_qa.pre_refund_flow import (
    refund_execution_actions,
    run_pre_refund_flow,
)


def test_policy_qa_models_expose_structured_pre_refund_item():
    assert hasattr(models, "PreRefundItemInput")


def test_pre_refund_core_flow_module_exists():
    assert find_spec("src.runtime.policy_qa.pre_refund_flow") is not None


@pytest.mark.parametrize(
    ("fee_detail_id", "refund_quantity"),
    [("", "1"), ("   ", "1"), ("F001", "0"), ("F001", "-1")],
)
def test_pre_refund_item_rejects_invalid_values(fee_detail_id, refund_quantity):
    with pytest.raises(ValidationError):
        PreRefundItemInput(
            fee_detail_id=fee_detail_id,
            refund_quantity=refund_quantity,
        )


class StubBillingAdapter:
    def __init__(self, *results):
        self._results = list(results)
        self.preview_calls = 0

    def query_billing_status(self, patient_id: str, encounter_id: str):
        raise AssertionError("预退费流程不应查询旧收费状态")

    def preview_partial_refund(self, original_trade_no: str, items):
        self.preview_calls += 1
        return self._results.pop(0)


def _request(
    question: str = "请做部分项目预退费分析",
    items: list[PreRefundItemInput] | None = None,
) -> PolicyQARequest:
    return PolicyQARequest(
        question=question,
        settlement_id="OP-001",
        pre_refund_items=items
        if items is not None
        else [PreRefundItemInput(fee_detail_id="F001", refund_quantity="1")],
    )


def _preview() -> PartialRefundPreview:
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
                fee_detail_id="F001",
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


def _success_result():
    return successful_result(
        context=AdapterCallContext(),
        source_system="billing",
        source_record_id="PRE-001",
        capability="preview_partial_refund",
        data={"preview": _preview()},
    )


def _failed_result(error_type: PreSettlementErrorType):
    return failed_result(
        context=AdapterCallContext(),
        source_system="billing",
        capability="preview_partial_refund",
        error_type=error_type.value,
        message="院端预结算不可用",
    )


@pytest.mark.asyncio
async def test_successful_preview_is_assembled_once():
    adapter = StubBillingAdapter(_success_result())

    outcome = await run_pre_refund_flow(_request(), adapter)

    assert outcome.state == "completed"
    assert outcome.skill_result is not None
    assert outcome.skill_result.verified_external_result is True
    assert outcome.attempt_count == 1
    assert outcome.recovery_count == 0
    assert adapter.preview_calls == 1


@pytest.mark.asyncio
async def test_missing_or_duplicate_items_do_not_call_adapter():
    adapter = StubBillingAdapter()

    missing = await run_pre_refund_flow(_request(items=[]), adapter)
    duplicate = await run_pre_refund_flow(
        _request(
            items=[
                PreRefundItemInput(fee_detail_id="F001", refund_quantity="1"),
                PreRefundItemInput(fee_detail_id="F001", refund_quantity="1"),
            ]
        ),
        adapter,
    )

    assert missing.state == "unavailable"
    assert duplicate.state == "unavailable"
    assert "重复" in duplicate.message
    assert adapter.preview_calls == 0


@pytest.mark.asyncio
async def test_not_configured_failure_is_not_retried():
    adapter = StubBillingAdapter(
        _failed_result(PreSettlementErrorType.NOT_CONFIGURED)
    )

    outcome = await run_pre_refund_flow(_request(), adapter)

    assert outcome.state == "unavailable"
    assert outcome.attempt_count == 1
    assert outcome.recovery_count == 0
    assert adapter.preview_calls == 1


@pytest.mark.asyncio
async def test_transient_failure_recovers_once():
    adapter = StubBillingAdapter(
        _failed_result(PreSettlementErrorType.UNAVAILABLE),
        _success_result(),
    )

    outcome = await run_pre_refund_flow(_request(), adapter)

    assert outcome.state == "completed"
    assert outcome.attempt_count == 2
    assert outcome.recovery_count == 1
    assert adapter.preview_calls == 2


@pytest.mark.asyncio
async def test_repeated_transient_failure_stops_after_two_attempts():
    adapter = StubBillingAdapter(
        _failed_result(PreSettlementErrorType.UNAVAILABLE),
        _failed_result(PreSettlementErrorType.UNAVAILABLE),
    )

    outcome = await run_pre_refund_flow(_request(), adapter)

    assert outcome.state == "unavailable"
    assert outcome.attempt_count == 2
    assert outcome.recovery_count == 1
    assert adapter.preview_calls == 2


@pytest.mark.asyncio
async def test_explicit_refund_execution_waits_for_human_before_adapter(monkeypatch):
    adapter = StubBillingAdapter(_success_result())
    confirmation = AgentResponse(
        scenario="high_risk_action_confirmation",
        status="waiting_human_confirmation",
        blocked_actions=["执行退费"],
    )
    monkeypatch.setattr(
        "src.runtime.policy_qa.pre_refund_flow.build_human_confirmation_response",
        lambda actions: confirmation,
    )

    outcome = await run_pre_refund_flow(_request("请立即执行退费"), adapter)

    assert outcome.state == "waiting_human_confirmation"
    assert outcome.confirmation is confirmation
    assert outcome.attempt_count == 0
    assert adapter.preview_calls == 0


@pytest.mark.asyncio
async def test_preview_wording_is_not_treated_as_execution():
    adapter = StubBillingAdapter(_success_result())

    outcome = await run_pre_refund_flow(_request("请做预退费分析"), adapter)

    assert outcome.state == "completed"
    assert adapter.preview_calls == 1


def test_preview_wording_does_not_bypass_other_high_risk_actions(monkeypatch):
    monkeypatch.setattr(
        "src.runtime.policy_qa.pre_refund_flow.detect_blocked_actions",
        lambda question: [("退费", "refund-rule"), ("病案首页修改", "record-rule")],
    )

    actions = refund_execution_actions("预退费分析并修改病案首页")

    assert actions == [("病案首页修改", "record-rule")]
