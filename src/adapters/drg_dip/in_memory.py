from src.adapters.base import AdapterCallContext, successful_result


class InMemoryDrgDipAdapter:
    def query_group_result(self, patient_id: str, encounter_id: str):
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='drg_dip',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_group_result',
            data={'risk': 'DRG/DIP 支付风险', 'patient_id': patient_id, 'encounter_id': encounter_id},
        )
