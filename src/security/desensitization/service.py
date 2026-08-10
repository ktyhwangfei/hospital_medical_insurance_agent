"""脱敏服务：控制面输入与回归案例快照脱敏。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.security.desensitization.detection import detect_sensitive_patterns

# 回归案例快照专用占位符脱敏规则（关键词锚定的业务标识）
_KEYWORD_ANCHORED_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("住院号", re.compile(r"住院号\s*([A-Za-z0-9]{3,20})", re.IGNORECASE), "[住院号]"),
    ("结算号", re.compile(r"结算(?:单)?号\s*([A-Za-z0-9]{3,20})", re.IGNORECASE), "[结算号]"),
    ("病案号", re.compile(r"病案号\s*([A-Za-z0-9]{3,20})", re.IGNORECASE), "[病案号]"),
    ("就诊号", re.compile(r"就诊号\s*([A-Za-z0-9]{3,20})", re.IGNORECASE), "[就诊号]"),
)

_ID_NUMBER_PATTERN = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_MOBILE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def mask_name(name: str) -> str:
    return name[0] + "**" if name else ""


@dataclass(frozen=True)
class SanitizedSnapshot:
    """脱敏后的回归案例快照。"""

    question: str
    answer: str
    comment: str
    masked_patterns: list[str]


def _mask_text(text: str, masked: list[str]) -> str:
    """对单段文本应用占位符脱敏，记录命中的规则名。"""
    if not text:
        return text
    result = text
    for name, pattern, placeholder in _KEYWORD_ANCHORED_PATTERNS:
        if pattern.search(result):
            result = pattern.sub(placeholder, result)
            masked.append(name)
    if _ID_NUMBER_PATTERN.search(result):
        result = _ID_NUMBER_PATTERN.sub("[身份证号]", result)
        masked.append("mainland_china_identity_number")
    if _MOBILE_PATTERN.search(result):
        result = _MOBILE_PATTERN.sub("[手机号]", result)
        masked.append("mainland_china_mobile_number")
    return result


def sanitize_regression_snapshot(
    *,
    question: str,
    answer: str,
    comment: str | None,
) -> SanitizedSnapshot:
    """对回归案例的问题/回答/评论脱敏，返回占位符快照。

    不返回或记录原始敏感值；命中的规则名供审计与指标使用。
    """
    masked: list[str] = []
    sanitized_question = _mask_text(question or "", masked)
    sanitized_answer = _mask_text(answer or "", masked)
    sanitized_comment = _mask_text(comment or "", masked)
    # 去重保序
    seen: set[str] = set()
    unique_masked = [m for m in masked if not (m in seen or seen.add(m))]
    return SanitizedSnapshot(
        question=sanitized_question,
        answer=sanitized_answer,
        comment=sanitized_comment,
        masked_patterns=unique_masked,
    )


def residual_sensitive_patterns(text: str) -> list[str]:
    """对脱敏后的快照再做一次敏感扫描，命中即视为残留需阻断。"""
    return detect_sensitive_patterns(text)
