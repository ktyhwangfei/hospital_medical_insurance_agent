from dataclasses import dataclass

from src.domain.insurance.models import InsuranceTransaction
from src.domain.patient.models import Patient


@dataclass
class InMemoryDataStore:
    patients: dict[str, Patient]
    transactions: dict[tuple[str, str], InsuranceTransaction]

    def get_patient(self, patient_id: str) -> Patient:
        return self.patients[patient_id]

    def get_insurance_transaction(self, patient_id: str, encounter_id: str) -> InsuranceTransaction:
        return self.transactions[(patient_id, encounter_id)]


def build_sample_store() -> InMemoryDataStore:
    return InMemoryDataStore(
        patients={'P001': Patient(patient_id='P001', name='张三')},
        transactions={
            ('P001', 'E001'): InsuranceTransaction(
                patient_id='P001',
                encounter_id='E001',
                settlement_status='failed',
                upload_status='failed',
                error_code='E-UPLOAD-001',
            )
        },
    )
