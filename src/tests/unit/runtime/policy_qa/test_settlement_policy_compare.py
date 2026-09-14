"""结算 vs 政策确定性对比计算单元测试。"""

from src.runtime.policy_qa.settlement_policy_compare import (
    compare_settlement_vs_policy,
    parse_policy_ratio,
)


def test_parse_policy_ratio_accepts_common_formats() -> None:
    assert parse_policy_ratio("0.85") == 0.85
    assert parse_policy_ratio("85%") == 0.85
    assert parse_policy_ratio("85") == 0.85
    assert parse_policy_ratio("") is None
    assert parse_policy_ratio(None) is None
    assert parse_policy_ratio("abc") is None
    assert parse_policy_ratio("0") is None


def _fact(inner=10000.0, pooling=8500.0) -> dict:
    return {
        "settlement_id": "S001",
        "medical_insurance_inner_amount": inner,
        "basic_pooling_payment": pooling,
    }


def _evidence(ratios=("0.85", "0.9")) -> dict:
    return {
        "policy_status": "full_policy_matched",
        "evidence": [
            {"rule_id": f"R{i}", "source_text": f"规则{i}", "payment_ratio": ratio}
            for i, ratio in enumerate(ratios, start=1)
        ],
        "evidence_count": len(ratios),
    }


def test_compare_concludes_match_when_actual_within_policy_ratio() -> None:
    result = compare_settlement_vs_policy(_fact(), _evidence())

    assert result["all_match"] is True
    assert result["comparison_count"] == 1
    assert result["comparisons"][0]["actual"] == 0.85
    assert result["comparisons"][0]["expected"] == [0.85, 0.9]
    assert result["comparisons"][0]["rule_ids"] == ["R1", "R2"]
    assert "一致" in result["conclusion"]


def test_compare_flags_mismatch_when_actual_outside_tolerance() -> None:
    result = compare_settlement_vs_policy(_fact(pooling=6000.0), _evidence())

    assert result["all_match"] is False
    assert result["comparisons"][0]["match"] is False
    assert "差异" in result["conclusion"]


def test_compare_reports_insufficient_evidence_without_ratios() -> None:
    result = compare_settlement_vs_policy(_fact(), _evidence(ratios=(None, "")))

    assert result["all_match"] is False
    assert result["comparisons"][0]["expected"] == []
    assert "无法完成对比" in result["comparisons"][0]["note"]


def test_compare_reports_missing_amount_fields() -> None:
    result = compare_settlement_vs_policy({}, {"evidence": [], "evidence_count": 0})

    assert result["comparisons"] == []
    assert result["all_match"] is False
    assert "缺少金额字段" in result["conclusion"]
