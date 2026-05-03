class InMemoryDrgDipAdapter:
    def query_group_result(self, patient_id: str, encounter_id: str) -> dict:
        return {'risk': 'DRG/DIP 支付风险', 'patient_id': patient_id, 'encounter_id': encounter_id}