from dataclasses import dataclass


@dataclass(frozen=True)
class InsuranceTransaction:
    patient_id: str
    encounter_id: str
    settlement_status: str
    upload_status: str
    error_code: str | None
