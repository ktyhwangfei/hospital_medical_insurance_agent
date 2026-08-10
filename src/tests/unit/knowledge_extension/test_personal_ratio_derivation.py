"""问题2 折算展开测试：退休人员个人支付比例 = 职工个人支付比例 × 系数。

复现：退休60% 是相对比例，线上 rule_type='支付比例'、payment_ratio 空、rule_value 是公式
→ 按 rule_type/数值检索无法命中 → 搜退休人员算不出。

修复（用户方案"多存几条"）：入库时把折算规则物化展开成多条退休 personal_payment_ratio
绝对值规则，检索端零运行时计算即可命中。

基数字段现状：基数规则（在职职工分段比例）的 payment_ratio 存的是统筹基金支付比例（85%），
"职工个人支付15%"只在 rule_value 文本里 → 展开需从 rule_value 反解析个人支付比例。
"""
from __future__ import annotations

from src.knowledge_extension.rule_explanation.policy_retrieval.rule_derivation import (
    derive_personal_payment_ratios,
)


def _ft(value):
    """详情字段 FieldTrace 简化（rule_to_entity 产出 {value, extracted_at, ...}）。"""
    return {"value": value, "extracted_at": "", "schema_version": 1, "confidence": 0.7}


def _base_rule(hosp, band, fund_ratio, personal_pct):
    return {
        "rule_id": f"base_{hosp}_{band}",
        "rule_type": "支付比例",
        "insu_type": "城镇职工基本医疗保险",
        "med_type": "住院-普通住院",
        "hosp_lv": hosp,
        "psn_type": "在职职工",
        "setl_type": "",
        "payment_ratio": _ft(fund_ratio),
        "amount_band": _ft(band),
        "rule_value": _ft(f"三级医院，{band}部分，统筹基金支付{fund_ratio}，职工个人支付{personal_pct}%"),
        "fact_id": "fact_base",
        "doc_id": "doc_1",
        "vector": [0.0] * 8,
    }


def _retiree_factor_rule():
    return {
        "rule_id": "retiree_factor",
        "rule_type": "支付比例",
        "insu_type": "城镇职工基本医疗保险",
        "med_type": "住院-普通住院",
        "hosp_lv": "",
        "psn_type": "退休人员",
        "setl_type": "",
        "payment_ratio": _ft(""),
        "amount_band": _ft(""),
        "rule_value": _ft("退休人员个人支付比例 = 同级别医院、同费用段职工支付比例 × 60%"),
        "fact_id": "fact_retiree",
        "doc_id": "doc_1",
        "vector": [1.0] * 8,
    }


def test_retiree_personal_ratio_derived_from_employee_base():
    """退休×0.6：15%→9%、10%→6%，按费用段各生成一条退休 personal_payment_ratio 规则。"""
    inputs = [
        _base_rule("三级", "起付-30000", "85%", "15"),
        _base_rule("三级", "30000-40000", "90%", "10"),
        _retiree_factor_rule(),
    ]
    derived = derive_personal_payment_ratios(inputs)
    assert len(derived) == 2, f"应展开2条，实际 {len(derived)}"

    by_band = {d["amount_band"]["value"]: d for d in derived}
    assert by_band["起付-30000"]["personal_payment_ratio"]["value"] == "9%"
    assert by_band["30000-40000"]["personal_payment_ratio"]["value"] == "6%"
    for d in derived:
        assert d["psn_type"] == "退休人员"
        assert d["hosp_lv"] == "三级"
        assert d["rule_type"] == "支付比例"
        assert d["doc_id"] == "doc_1"
        assert d["rule_id"].startswith("rule_")
        rv = d["rule_value"]["value"]
        assert "60%" in rv and "退休" in rv


def test_no_derivation_when_no_factor_rule():
    """无折算规则时不展开。"""
    inputs = [
        _base_rule("三级", "起付-30000", "85%", "15"),
        _base_rule("二级", "起付-30000", "87%", "13"),
    ]
    assert derive_personal_payment_ratios(inputs) == []


def test_no_derivation_when_no_base_rule():
    """有折算规则但无职工基数（无法反解析个人支付比例）时不展开。"""
    inputs = [_retiree_factor_rule()]
    assert derive_personal_payment_ratios(inputs) == []