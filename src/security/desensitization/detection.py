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
)


def detect_sensitive_patterns(text: str) -> list[str]:
    """返回命中的敏感字段类型，不返回或记录原始敏感值。"""
    return [name for name, pattern in _SENSITIVE_PATTERNS if pattern.search(text)]
