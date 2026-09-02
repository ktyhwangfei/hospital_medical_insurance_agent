from src.adapters.base import AdapterCallContext, failed_result, successful_result
from src.adapters.base.models import AdapterCallResult
from src.adapters.billing.models import PartialRefundItemRequest, PreSettlementErrorType
from src.adapters.ports import BillingPort


class InMemoryBillingAdapter(BillingPort):
    def query_billing_status(self, patient_id: str, encounter_id: str):
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='billing',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_billing_status',
            data={'billing_status': 'waiting_retry', 'patient_id': patient_id, 'encounter_id': encounter_id},
        )

    def preview_partial_refund(
        self,
        original_trade_no: str,
        items: tuple[PartialRefundItemRequest, ...],
    ) -> AdapterCallResult:
        return failed_result(
            context=AdapterCallContext(
                input_summary={
                    "original_trade_no": original_trade_no,
                    "item_count": len(items),
                }
            ),
            source_system="billing",
            capability="preview_partial_refund",
            error_type=PreSettlementErrorType.NOT_CONFIGURED.value,
            message="院端门诊部分退费预结算接口未配置",
        )
