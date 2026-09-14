"""fund_ratio_guard：统筹基金/个人支付比例误抽纠偏。"""

from __future__ import annotations

from src.knowledge_extension.rule_explanation.fund_ratio_guard import (
    correct_fund_personal_ratio,
    to_percent,
)


def test_corrects_personal_ratio_misextracted_as_fund_ratio() -> None:
    """「统筹基金支付90%，个人支付10%」误抽成 0.1 → 纠正为基金 90%，个人进 personal。"""
    rule = {
        "source_text": "统筹基金支付90%，个人支付10%。",
        "payment_ratio": "0.1",
    }
    assert correct_fund_personal_ratio(rule) is True
    assert rule["payment_ratio"] == "90%"
    assert rule["personal_payment_ratio"] == "10%"


def test_corrects_percentage_style_personal_value() -> None:
    rule = {
        "source_text": "统筹基金支付85%，职工支付15%。",
        "payment_ratio": "15%",
    }
    assert correct_fund_personal_ratio(rule) is True
    assert rule["payment_ratio"] == "85%"
    assert rule["personal_payment_ratio"] == "15%"


def test_fills_missing_fund_ratio_from_source_text() -> None:
    rule = {"source_text": "统筹基金支付80%，个人支付20%。", "payment_ratio": ""}
    assert correct_fund_personal_ratio(rule) is True
    assert rule["payment_ratio"] == "80%"
    assert rule["personal_payment_ratio"] == "20%"


def test_already_correct_rule_is_idempotent() -> None:
    rule = {
        "source_text": "统筹基金支付90%，个人支付10%。",
        "payment_ratio": "90%",
        "personal_payment_ratio": "10%",
    }
    assert correct_fund_personal_ratio(rule) is False
    assert rule["payment_ratio"] == "90%"


def test_no_fund_personal_pattern_untouched() -> None:
    rule = {"source_text": "在医院就医的支付比例为70%。", "payment_ratio": "70%"}
    assert correct_fund_personal_ratio(rule) is False
    assert rule["payment_ratio"] == "70%"


def test_equal_fund_and_personal_untouched() -> None:
    rule = {"source_text": "统筹基金支付50%，个人支付50%。", "payment_ratio": "50%"}
    assert correct_fund_personal_ratio(rule) is False


def test_to_percent_formats() -> None:
    assert to_percent("0.9") == 90
    assert to_percent("90%") == 90
    assert to_percent("85") == 85
    assert to_percent("") is None
    assert to_percent("abc") is None


# ── correct_canonical_ratio（编译结果纠偏）──

from decimal import Decimal

from src.knowledge_extension.rule_explanation.fund_ratio_guard import (
    correct_canonical_ratio,
)


def test_canonical_ratio_complement_error_corrected() -> None:
    """字段 payment_ratio=90 / personal=10 正确，但 result.ratio=0.1（个人补集）→ 修为 0.9。"""
    corrected = correct_canonical_ratio(
        "payment_ratio",
        Decimal("0.1"),
        {"payment_ratio": "90", "personal_payment_ratio": "10"},
    )
    assert corrected == Decimal("0.9")


def test_canonical_ratio_correct_value_untouched() -> None:
    assert correct_canonical_ratio(
        "payment_ratio",
        Decimal("0.9"),
        {"payment_ratio": "90", "personal_payment_ratio": "10"},
    ) is None


def test_canonical_ratio_personal_subject_skipped() -> None:
    """personal_payment_ratio 主体的 ratio 本来就应是个人比例，不动。"""
    assert correct_canonical_ratio(
        "personal_payment_ratio",
        Decimal("0.1"),
        {"payment_ratio": "90", "personal_payment_ratio": "10"},
    ) is None


def test_canonical_ratio_without_personal_field_skipped() -> None:
    assert correct_canonical_ratio(
        "payment_ratio", Decimal("0.6"), {"payment_ratio": "60"}
    ) is None
