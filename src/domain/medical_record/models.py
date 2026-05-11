from dataclasses import dataclass


@dataclass(frozen=True)
class MedicalRecordHomepage:
    """病案首页：患者本次住院的完整病案首页信息。"""

    record_id: str
    patient_id: str
    primary_diagnosis: "Diagnosis"
    secondary_diagnoses: tuple["Diagnosis", ...]
    surgeries: tuple["Surgery", ...]
    codings: tuple["Coding", ...]
    discharge_status: str
    total_cost: float


@dataclass(frozen=True)
class Diagnosis:
    """诊断记录：疾病诊断的编码与名称信息。"""

    code: str
    name: str
    type: str  # "primary", "secondary"
    sequence: int


@dataclass(frozen=True)
class Surgery:
    """手术记录：手术操作的相关信息。"""

    code: str
    name: str
    date: str
    surgeon: str


@dataclass(frozen=True)
class Coding:
    """编码信息：诊断或手术的编码系统记录。"""

    code_system: str
    code: str
    description: str
