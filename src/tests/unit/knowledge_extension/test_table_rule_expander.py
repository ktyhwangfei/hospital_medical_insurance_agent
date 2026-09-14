"""table_rule_expander：表格/压缩比例句的确定性展开。"""

from __future__ import annotations

from src.knowledge_extension.rule_explanation.table_rule_expander import (
    expand_table_rule,
    parse_level_ratios,
)


def test_parse_explicit_level_pairs() -> None:
    text = "退休职工住院医疗费用1300元至3万元部分，一级医院报销97.0%，二级医院96.1%，三级医院95.5%。"
    assert parse_level_ratios(text) == {"一级": 97.0, "二级": 96.1, "三级": 95.5}


def test_parse_sequence_shorthand() -> None:
    text = "在职职工：1300元至3万元，一/二/三级医院报销比例依次为90%/87%/85%"
    assert parse_level_ratios(text) == {"一级": 90.0, "二级": 87.0, "三级": 85.0}


def test_parse_ignores_fund_personal_sentence() -> None:
    """「统筹基金支付90%，个人支付10%」不是表格写法，不得误展开。"""
    assert parse_level_ratios("统筹基金支付90%，个人支付10%。") == {}


def test_expand_rule_without_hosp_lv() -> None:
    rule = {
        "rule_id": "rule_x",
        "rule_type": "支付比例",
        "psn_type": "在职职工",
        "med_type": "住院",
        "payment_ratio": "90%",
        "source_text": "一级医院报销90.0%，二级医院87.0%，三级医院85.0%。",
    }
    expanded = expand_table_rule(rule)
    assert expanded is not None
    assert len(expanded) == 3
    by_level = {r["hosp_lv"]: r["payment_ratio"] for r in expanded}
    assert by_level == {"一级": "90%", "二级": "87%", "三级": "85%"}
    assert all(r["psn_type"] == "在职职工" for r in expanded)
    assert {r["rule_id"] for r in expanded} == {
        "rule_x_lv_一级", "rule_x_lv_二级", "rule_x_lv_三级",
    }


def test_expand_skips_atomic_rule() -> None:
    """已带医院等级的规则不再展开。"""
    rule = {
        "rule_id": "rule_x",
        "rule_type": "支付比例",
        "hosp_lv": "一级",
        "payment_ratio": "90%",
        "source_text": "一级医院报销90.0%，二级医院87.0%。",
    }
    assert expand_table_rule(rule) is None


def test_expand_skips_non_ratio_rule() -> None:
    rule = {
        "rule_id": "rule_x",
        "rule_type": "起付线",
        "deductible_amount": "1300元",
        "source_text": "一级医院报销90.0%，二级医院87.0%。",
    }
    assert expand_table_rule(rule) is None
