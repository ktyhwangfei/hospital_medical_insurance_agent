from src.adapters.base import AdapterCallContext, successful_result


class InMemoryHisAdapter:
    def query_orders(self, patient_id: str, encounter_id: str):
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='his',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_orders',
            data={'orders': ['抗菌药物医嘱', '检查项目医嘱'], 'patient_id': patient_id, 'encounter_id': encounter_id},
        )
