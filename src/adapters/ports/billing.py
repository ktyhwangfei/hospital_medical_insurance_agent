from typing import Protocol, runtime_checkable

from src.adapters.base.models import AdapterCallResult
from src.adapters.billing.models import PartialRefundItemRequest


@runtime_checkable
class BillingPort(Protocol):
    """收费系统适配器端口。

    封装与医院收费/HIS计费子系统的交互职责。
    负责费用查询、计费状态确认、退费冲正等收费域业务能力。
    """

    def query_billing_status(self, patient_id: str, encounter_id: str) -> AdapterCallResult:
        """查询收费状态。

        Args:
            patient_id: 患者ID
            encounter_id: 就诊ID

        Returns:
            收费状态及明细数据
        """
        ...

    def preview_partial_refund(
        self,
        original_trade_no: str,
        items: tuple[PartialRefundItemRequest, ...],
    ) -> AdapterCallResult:
        """调用收费系统的只读部分退费预结算能力。"""
        ...
