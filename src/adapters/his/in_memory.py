class InMemoryHisAdapter:
    def query_orders(self, patient_id: str, encounter_id: str) -> dict:
        return {'orders': ['抗菌药物医嘱', '检查项目医嘱'], 'patient_id': patient_id, 'encounter_id': encounter_id}