from src.adapters.base import AdapterCallContext, successful_result


class InMemoryEmrAdapter:
    def query_record_summary(self, patient_id: str, encounter_id: str):
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='emr',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_record_summary',
            data={'summary': '病历记录存在可补充证据', 'patient_id': patient_id, 'encounter_id': encounter_id},
        )
