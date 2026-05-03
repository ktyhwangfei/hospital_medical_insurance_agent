from dataclasses import asdict

from src.adapters.base import AdapterCallContext, successful_result
from src.data_platform.data_access.in_memory import build_sample_store


class InMemoryInsuranceInterfaceAdapter:
    def query_transaction(self, patient_id: str, encounter_id: str):
        tx = build_sample_store().get_insurance_transaction(patient_id, encounter_id)
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='insurance_interface',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_transaction',
            data=asdict(tx),
        )
