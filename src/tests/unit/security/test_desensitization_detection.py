from src.security.desensitization.detection import (
    detect_sensitive_patterns,
    redact_sensitive_text,
)


def test_detects_and_redacts_common_phi_without_removing_labels() -> None:
    text = (
        "患者姓名：张三，身份证 110101199001011234，"
        "手机号 13800138000，病历号：MR-9988，住院号=ZY20260812，"
        "门诊号：MZ-7788，医保号：YB556677"
    )

    detected = set(detect_sensitive_patterns(text))
    redacted = redact_sensitive_text(text)

    assert detected == {
        "mainland_china_identity_number",
        "mainland_china_mobile_number",
        "patient_name",
        "medical_record_number",
        "inpatient_number",
        "outpatient_number",
        "medical_insurance_number",
    }
    for secret in (
        "张三", "110101199001011234", "13800138000", "MR-9988",
        "ZY20260812", "MZ-7788", "YB556677",
    ):
        assert secret not in redacted
    for label in ("患者姓名", "病历号", "住院号", "门诊号", "医保号"):
        assert label in redacted
