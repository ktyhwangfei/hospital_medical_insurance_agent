from importlib.util import find_spec
from decimal import Decimal

import pytest

from src.adapters.base.models import AdapterCallContext
from src.adapters.base.service import failed_result, successful_result
from src.adapters.billing.models import (
    PartialRefundItemRequest,
    PartialRefundPreview,
    PreSettlementErrorType,
    PreviewedRefundItem,
    SettlementAmountSnapshot,
)
from src.runtime.api.schemas import AgentResponse
from skill_drafts.outpatient_pre_refund_analysis_skill.scripts.pre_refund_flow import (
    refund_execution_actions,
    run_pre_refund_flow,
)


def test_pre_refund_core_flow_module_exists():
    assert find_spec(
        "skill_drafts.outpatient_pre_refund_analysis_skill.scripts.pre_refund_flow"
    ) is not None


class StubBillingAdapter:
    def __init__(self, *results):
        self._results = list(results)
        self.preview_calls = 0

    def query_billing_status(self, patient_id: str, encounter_id: str):
        raise AssertionError("预退费流程不应查询旧收费状态")

    def preview_partial_refund(self, original_trade_no: str, items):
        self.preview_calls += 1
        return self._results.pop(0)


def _items() -> tuple[PartialRefundItemRequest, ...]:
    return (
        PartialRefundItemRequest(
            fee_detail_id="F001",
            refund_quantity=Decimal("1"),
        ),
    )


async def _run(
    adapter: StubBillingAdapter,
    question: str = "请做部分项目预退费分析",
    items: tuple[PartialRefundItemRequest, ...] | None = None,
):
    return await run_pre_refund_flow(
        question=question,
        settlement_id="OP-001",
        items=_items() if items is None else items,
        billing_adapter=adapter,
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

    outcome = await _run(adapter)

    assert outcome.state == "completed"
    assert outcome.skill_result is not None
    assert outcome.skill_result.verified_external_result is True
    assert outcome.attempt_count == 1
    assert outcome.recovery_count == 0
    assert adapter.preview_calls == 1


@pytest.mark.asyncio
async def test_missing_or_duplicate_items_do_not_call_adapter():
    adapter = StubBillingAdapter()

    missing = await _run(adapter, items=())
    duplicate = await _run(
        adapter,
        items=(
            PartialRefundItemRequest("F001", Decimal("1")),
            PartialRefundItemRequest("F001", Decimal("1")),
        ),
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

    outcome = await _run(adapter)

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

    outcome = await _run(adapter)

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

    outcome = await _run(adapter)

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
        "skill_drafts.outpatient_pre_refund_analysis_skill.scripts.pre_refund_flow.build_human_confirmation_response",
        lambda actions: confirmation,
    )

    outcome = await _run(adapter, "请立即执行退费")

    assert outcome.state == "waiting_human_confirmation"
    assert outcome.confirmation is confirmation
    assert outcome.attempt_count == 0
    assert adapter.preview_calls == 0


@pytest.mark.asyncio
async def test_preview_wording_is_not_treated_as_execution():
    adapter = StubBillingAdapter(_success_result())

    outcome = await _run(adapter, "请做预退费分析")

    assert outcome.state == "completed"
    assert adapter.preview_calls == 1


def test_preview_wording_does_not_bypass_other_high_risk_actions(monkeypatch):
    monkeypatch.setattr(
        "skill_drafts.outpatient_pre_refund_analysis_skill.scripts.pre_refund_flow.detect_blocked_actions",
        lambda question: [("退费", "refund-rule"), ("病案首页修改", "record-rule")],
    )

    actions = refund_execution_actions("预退费分析并修改病案首页")

    assert actions == [("病案首页修改", "record-rule")]
