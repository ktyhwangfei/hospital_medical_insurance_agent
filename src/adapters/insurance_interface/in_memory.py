from src.data_platform.data_access.in_memory import build_sample_store


class InMemoryInsuranceInterfaceAdapter:
    def query_transaction(self, patient_id: str, encounter_id: str):
        return build_sample_store().get_insurance_transaction(patient_id, encounter_id)
