class InMemoryPreAuditAdapter:
    def query_audit_result(self, patient_id: str, encounter_id: str) -> dict:
        return {'risk': '合规拒付风险', 'patient_id': patient_id, 'encounter_id': encounter_id}