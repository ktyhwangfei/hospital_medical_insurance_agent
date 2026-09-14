"""extraction_validators：覆盖率 / 维度诚实 / 键唯一性。"""

from __future__ import annotations

from src.knowledge_extension.rule_explanation.extraction_validators import (
    check_dimension_honesty,
    check_key_uniqueness,
    check_value_coverage,
)


def test_coverage_passes_when_all_source_values_covered() -> None:
    rules = [
        {"rule_id": "r1", "payment_ratio": "85%"},
        {"rule_id": "r2", "payment_ratio": "90%"},
        {"rule_id": "r3", "deductible_amount": "1300元"},
    ]
    source = "起付标准为1300元。在医院就医的支付比例为85%，在社区卫生机构就医的支付比例为90%。"
    assert check_value_coverage(source, rules) == []


def test_coverage_flags_uncovered_source_percent() -> None:
    """漏抽检测：原文 90% 没有任何规则覆盖。"""
    rules = [{"rule_id": "r1", "payment_ratio": "85%"}]
    source = "在医院就医的支付比例为85%，在社区卫生机构就医的支付比例为90%。"
    issues = check_value_coverage(source, rules)
    assert any(
        i.code == "SOURCE_VALUE_UNCOVERED" and i.context.get("value") == 90.0
        for i in issues
    )


def test_coverage_flags_hallucinated_rule_value() -> None:
    """幻觉检测：规则值 75% 在原文中不存在。"""
    rules = [{"rule_id": "r1", "payment_ratio": "75%"}]
    source = "在医院就医的支付比例为85%。"
    issues = check_value_coverage(source, rules)
    assert any(
        i.code == "RULE_VALUE_NOT_IN_SOURCE" and i.context.get("rule_id") == "r1"
        for i in issues
    )


def test_coverage_does_not_cross_pollinate_amount_into_percent() -> None:
    """金额字段不能被当成比例（1800元 ≠ 1800%）。"""
    rules = [{"rule_id": "r1", "deductible_amount": "1800元"}]
    source = "在职职工门（急）诊起付标准为1800元。"
    assert check_value_coverage(source, rules) == []


def test_dimension_honesty_flags_hallucinated_hospital_level() -> None:
    """原文只说医院/社区，规则却写二级 → REVIEW。"""
    rules = [{"rule_id": "r1", "hosp_lv": "二级", "psn_type": "在职职工"}]
    source = "在职职工门（急）诊费用2万元以下部分，在医院就医的支付比例为70%。"
    issues = check_dimension_honesty(source, rules)
    assert any(
        i.code == "DIMENSION_NOT_IN_SOURCE"
        and i.context.get("dimension") == "hosp_lv"
        and i.context.get("value") == "二级"
        for i in issues
    )


def test_dimension_honesty_accepts_community_synonyms() -> None:
    rules = [{"rule_id": "r1", "hosp_lv": "社区"}]
    source = "在社区卫生服务机构就医的支付比例为90%。"
    assert check_dimension_honesty(source, rules) == []


def test_key_uniqueness_flags_conflicting_ratios() -> None:
    rules = [
        {
            "rule_id": "r1", "insu_type": "城镇职工基本医疗保险", "psn_type": "在职职工",
            "med_type": "门诊-普通门急诊", "hosp_lv": "一级", "amount_band": "2万元以下",
            "rule_type": "支付比例", "payment_ratio": "0.7",
        },
        {
            "rule_id": "r2", "insu_type": "城镇职工基本医疗保险", "psn_type": "在职职工",
            "med_type": "门诊-普通门急诊", "hosp_lv": "一级", "amount_band": "2万元以下",
            "rule_type": "支付比例", "payment_ratio": "0.9",
        },
    ]
    issues = check_key_uniqueness(rules)
    assert len(issues) == 1
    assert issues[0].level == "ERROR"
    assert issues[0].code == "KEY_CONFLICT"


def test_key_uniqueness_passes_same_value_or_distinct_keys() -> None:
    rules = [
        {
            "rule_id": "r1", "insu_type": "城镇职工基本医疗保险", "psn_type": "在职职工",
            "med_type": "门诊-普通门急诊", "hosp_lv": "一级", "amount_band": "2万元以下",
            "rule_type": "支付比例", "payment_ratio": "70%",
        },
        {
            "rule_id": "r2", "insu_type": "城镇职工基本医疗保险", "psn_type": "在职职工",
            "med_type": "门诊-普通门急诊", "hosp_lv": "社区", "amount_band": "2万元以下",
            "rule_type": "支付比例", "payment_ratio": "90%",
        },
        {
            "rule_id": "r3", "insu_type": "城镇职工基本医疗保险", "psn_type": "在职职工",
            "med_type": "门诊-普通门急诊", "hosp_lv": "一级", "amount_band": "2万元以下",
            "rule_type": "支付比例", "payment_ratio": "0.7",
        },
    ]
    assert check_key_uniqueness(rules) == []
