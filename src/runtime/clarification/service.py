def missing_context_fields(patient_id: str | None, encounter_id: str | None) -> list[str]:
    missing = []
    if not patient_id:
        missing.append('patient_id')
    if not encounter_id:
        missing.append('encounter_id')
    return missing
