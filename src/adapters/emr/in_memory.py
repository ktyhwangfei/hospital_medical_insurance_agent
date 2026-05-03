class InMemoryEmrAdapter:
    def query_record_summary(self, patient_id: str, encounter_id: str) -> dict:
        return {'summary': '病历记录存在可补充证据', 'patient_id': patient_id, 'encounter_id': encounter_id}