class InMemoryBillingAdapter:
    def query_billing_status(self, patient_id: str, encounter_id: str) -> dict:
        return {'billing_status': 'waiting_retry', 'patient_id': patient_id, 'encounter_id': encounter_id}
