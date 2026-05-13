from enum import StrEnum


class Role(StrEnum):
    CASHIER = "cashier"
    MEDICAL_OFFICE = "medical_office"
    INFORMATION_DEPARTMENT = "information_department"
    MEDICAL_RECORD_STAFF = "medical_record_staff"
    CLINICIAN = "clinician"


OWNER_ROLES: frozenset[Role] = frozenset({
    Role.CASHIER,
    Role.MEDICAL_OFFICE,
    Role.INFORMATION_DEPARTMENT,
    Role.MEDICAL_RECORD_STAFF,
})

ROLE_LABELS: dict[Role, str] = {
    Role.CASHIER: "收费员",
    Role.MEDICAL_OFFICE: "医保办",
    Role.INFORMATION_DEPARTMENT: "信息科",
    Role.MEDICAL_RECORD_STAFF: "病案室",
    Role.CLINICIAN: "临床医生",
}
