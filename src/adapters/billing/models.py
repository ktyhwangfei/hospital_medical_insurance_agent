from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class PreSettlementErrorType(str, Enum):
    NOT_CONFIGURED = "pre_settlement_not_configured"
    UNAVAILABLE = "pre_settlement_unavailable"


@dataclass(frozen=True)
class PartialRefundItemRequest:
    fee_detail_id: str
    refund_quantity: Decimal


@dataclass(frozen=True)
class SettlementAmountSnapshot:
    total_amount: Decimal
    fund_amount: Decimal
    personal_amount: Decimal


@dataclass(frozen=True)
class PreviewedRefundItem:
    fee_detail_id: str
    refund_quantity: Decimal
    refundable_quantity: Decimal
    refund_amount: Decimal


@dataclass(frozen=True)
class PartialRefundPreview:
    accepted: bool
    original_trade_no: str
    response_code: str
    response_message: str
    preview_id: str | None
    source_system: str
    source_reference: str
    items: tuple[PreviewedRefundItem, ...]
    before: SettlementAmountSnapshot | None
    after: SettlementAmountSnapshot | None
