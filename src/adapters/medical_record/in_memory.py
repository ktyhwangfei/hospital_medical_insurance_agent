from src.adapters.base import AdapterCallContext, successful_result
from src.adapters.ports import MedicalRecordPort


class InMemoryMedicalRecordAdapter(MedicalRecordPort):
    def query_homepage(self, patient_id: str, encounter_id: str):
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='medical_record',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_homepage',
            data={'risk': '病案首页风险', 'patient_id': patient_id, 'encounter_id': encounter_id},
        )
