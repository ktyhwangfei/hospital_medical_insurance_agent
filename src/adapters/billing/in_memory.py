from src.adapters.base import AdapterCallContext, successful_result


class InMemoryBillingAdapter:
    def query_billing_status(self, patient_id: str, encounter_id: str):
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='billing',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_billing_status',
            data={'billing_status': 'waiting_retry', 'patient_id': patient_id, 'encounter_id': encounter_id},
        )
