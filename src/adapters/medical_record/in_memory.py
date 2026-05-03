class InMemoryMedicalRecordAdapter:
    def query_homepage(self, patient_id: str, encounter_id: str) -> dict:
        return {'risk': '病案首页风险', 'patient_id': patient_id, 'encounter_id': encounter_id}