from decimal import Decimal

from src.adapters.billing.models import (
    PartialRefundItemRequest,
    PartialRefundPreview,
    PreviewedRefundItem,
    SettlementAmountSnapshot,
)
from skills.outpatient_pre_refund_analysis_skill.assembler import load


def _request(quantity: str = "1") -> tuple[PartialRefundItemRequest, ...]:
    return (
        PartialRefundItemRequest(
            fee_detail_id="F001",
            refund_quantity=Decimal(quantity),
        ),
    )


def _accepted_preview(
    *,
    after_fund: str = "48",
    after_personal: str = "32",
    refund_amount: str = "20",
    fee_detail_id: str = "F001",
    refund_quantity: str = "1",
    refundable_quantity: str = "2",
) -> PartialRefundPreview:
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
                refund_quantity=Decimal(refund_quantity),
                refundable_quantity=Decimal(refundable_quantity),
                refund_amount=Decimal(refund_amount),
            ),
        ),
        before=SettlementAmountSnapshot(
            total_amount=Decimal("100"),
            fund_amount=Decimal("60"),
            personal_amount=Decimal("40"),
        ),
        after=SettlementAmountSnapshot(
            total_amount=Decimal("80"),
            fund_amount=Decimal(after_fund),
            personal_amount=Decimal(after_personal),
        ),
    )


def test_explains_expected_patient_refund_from_official_preview():
    result = load().execute("OP-001", _request(), _accepted_preview())

    assert result.can_answer is True
    assert result.verified_external_result is True
    assert "预计退还" in result.answer
    assert "8.00" in result.answer
    assert len(result.calculation_steps) >= 3
    assert result.case_context.total_amount == 80.0
    assert result.source_citations[0].title == "院端收费系统预结算"


def test_explains_expected_patient_supplement_after_recalculation():
    preview = _accepted_preview(after_fund="35", after_personal="45")

    result = load().execute("OP-001", _request(), preview)

    assert result.can_answer is True
    assert "预计补缴" in result.answer
    assert "5.00" in result.answer


def test_official_rejection_is_a_verified_answer():
    preview = PartialRefundPreview(
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

    result = load().execute("OP-001", _request(), preview)

    assert result.can_answer is True
    assert result.verified_external_result is True
    assert "QTY_EXCEEDED" in result.answer
    assert "拟退数量超过可退数量" in result.answer
    assert result.source_citations


def test_rejects_preview_with_mismatched_fee_detail():
    result = load().execute(
        "OP-001",
        _request(),
        _accepted_preview(fee_detail_id="F999"),
    )

    assert result.can_answer is False
    assert result.verified_external_result is False
    assert any("明细" in warning for warning in result.warnings)


def test_rejects_quantity_above_official_refundable_quantity():
    result = load().execute(
        "OP-001",
        _request("2"),
        _accepted_preview(refund_quantity="2", refundable_quantity="1"),
    )

    assert result.can_answer is False
    assert any("可退数量" in warning for warning in result.warnings)


def test_rejects_inconsistent_official_amounts():
    result = load().execute(
        "OP-001",
        _request(),
        _accepted_preview(refund_amount="19"),
    )

    assert result.can_answer is False
    assert result.verified_external_result is False
    assert any("金额" in warning for warning in result.warnings)
