from typing import Protocol


class DataAccessPort(Protocol):
    def get_patient(self, patient_id: str):
        raise NotImplementedError

    def get_insurance_transaction(self, patient_id: str, encounter_id: str):
        raise NotImplementedError