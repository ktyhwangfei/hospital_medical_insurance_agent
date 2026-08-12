"""面向控制面输入的轻量敏感信息检测。"""

import re


_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "mainland_china_identity_number",
        re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    ),
    (
        "mainland_china_mobile_number",
        re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    ),
    (
        "patient_name",
        re.compile(r"(?P<label>患者姓名|姓名)\s*[:：=]?\s*[一-鿿·]{2,20}"),
    ),
    *(
        (
            name,
            re.compile(rf"(?P<label>{label})\s*[:：=]?\s*[A-Za-z0-9][A-Za-z0-9_-]{{2,63}}"),
        )
        for name, label in (
            ("medical_record_number", "病历号"),
            ("inpatient_number", "住院号"),
            ("outpatient_number", "门诊号"),
            ("medical_insurance_number", "医保号"),
        )
    ),
)


def detect_sensitive_patterns(text: str) -> list[str]:
    """返回命中的敏感字段类型，不返回或记录原始敏感值。"""
    return [name for name, pattern in _SENSITIVE_PATTERNS if pattern.search(text)]


def redact_sensitive_text(text: str) -> str:
    """保留证据结构与字段标签，只替换常见 PHI 原值。"""
    redacted = _SENSITIVE_PATTERNS[0][1].sub("[已脱敏:身份证号]", text)
    redacted = _SENSITIVE_PATTERNS[1][1].sub("[已脱敏:手机号]", redacted)
    for _name, pattern in _SENSITIVE_PATTERNS[2:]:
        redacted = pattern.sub(
            lambda match: f"{match.group('label')}：[已脱敏]", redacted
        )
    return redacted
