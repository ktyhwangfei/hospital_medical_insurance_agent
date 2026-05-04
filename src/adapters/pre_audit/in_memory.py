from src.adapters.base import AdapterCallContext, successful_result


class InMemoryPreAuditAdapter:
    def query_audit_result(self, patient_id: str, encounter_id: str):
        return successful_result(
            context=AdapterCallContext(input_summary={'patient_id': patient_id, 'encounter_id': encounter_id}),
            source_system='pre_audit',
            source_record_id=f'{patient_id}:{encounter_id}',
            capability='query_audit_result',
            data={'risk': '合规拒付风险', 'patient_id': patient_id, 'encounter_id': encounter_id},
        )
