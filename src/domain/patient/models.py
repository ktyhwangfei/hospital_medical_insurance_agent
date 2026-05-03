from dataclasses import dataclass


@dataclass(frozen=True)
class Patient:
    patient_id: str
    name: str
