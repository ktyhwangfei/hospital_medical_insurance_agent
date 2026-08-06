"""Unit tests for settlement fee calculators."""

from skills.settlement_explain_skill.calculator import FeeDecompositionCalculator
from skills.settlement_explain_skill.tool_interfaces import PatientSettlementData, PolicyRule


def test_retired_segment_calculation_uses_final_ratios_and_pay():
    calculator = FeeDecompositionCalculator()
    sql_data = PatientSettlementData(
        settlement_id="S001",
        treatment={
            "in_scope": 40000.0,
            "deductible": 650.0,
            "pooling_self_pay": 3241.5,
        },
        patient_info={"person_type": "退休人员", "fund_type": "城镇职工"},
    )
    policy_rules = [
        PolicyRule(
            clause="r1",
            evidence_text="650-30000: 15%",
            rule_type="支付比例",
        ),
        PolicyRule(
            clause="r2",
            evidence_text="30000-40000: 10%",
            rule_type="支付比例",
        ),
    ]

    result = calculator.calculate(sql_data, policy_rules)

    segments = [
        segment
        for segment in result["segments"]["segments"]
        if segment["rule_id"] != "deductible_rule"
    ]
    assert len(segments) == 2
    for segment in segments:
        calculation = segment["calculation"]
        assert "待定" not in calculation
        assert f"{segment['amount']:,.2f}" in calculation
        assert f"{segment['base_ratio']:.0%}" in calculation
        assert f"{segment['person_ratio']:.0%}" in calculation
        assert f"{segment['actual_ratio']:.0%}" in calculation
        assert f"{segment['pay']:,.2f}" in calculation
