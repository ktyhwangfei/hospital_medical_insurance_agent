"""
Shared fixtures for Skill unit tests.

复用了 skills/settlement_explain_skill/tests/ 的 mock 模式：
- settlement_context: 模拟 1671213 结算
- mock_evidence: 模拟 3 段比例 + 退休 60% 政策证据
- 通过 MODEL_BASE_URL=dummy 避免真实 LLM 调用
"""

import os
import pytest
from types import SimpleNamespace

# 必须在任何模型导入前设置
os.environ.setdefault("MODEL_BASE_URL", "dummy")


@pytest.fixture
def settlement_context() -> SimpleNamespace:
    """模拟 settlement 1671213 的结算上下文。

    退款数据（project 默认 MEMORY 模式常见值）。
    """
    return SimpleNamespace(
        settlement_id="1671213",
        deductible=650.0,
        medical_insurance_inner_amount=50000.0,
        basic_pooling_payment=35000.0,
        basic_pooling_self_pay=4962.67,
        large_amount_payment=10000.0,
        large_amount_self_pay=1500.0,
        personal_total_pay=7112.67,
        insurance_type="城镇职工基本医疗保险",
        person_type="退休人员",
        service_type="普通住院",
        hospital_level="三级医院",
    )


@pytest.fixture
def mock_evidence() -> list[dict]:
    """模拟政策证据：3 段住院支付比例 + 退休人员 60% 折算。

    Segment 1: 起付标准~3万 → 85% / 15%
    Segment 2: 3万~4万     → 90% / 10%
    Segment 3: 4万以上     → 95% /  5%
    Retiree:   个人支付 = 在职的 60%
    """
    return [
        {
            "source_text": (
                "三级医院住院费用分段：起付标准至3万元的部分，"
                "统筹基金支付 85%，职工个人支付 15%"
            ),
            "applied_reason": "本次结算适用三级医院住院首段支付比例。",
            "rule_type": "支付比例",
            "psn_type": "",
        },
        {
            "source_text": (
                "三级医院住院费用分段：超过3万元至4万元的部分，"
                "统筹基金支付 90%，职工个人支付 10%"
            ),
            "applied_reason": "本次结算适用三级医院住院中段支付比例。",
            "rule_type": "支付比例",
            "psn_type": "",
        },
        {
            "source_text": (
                "三级医院住院费用分段：超过4万元的部分，"
                "统筹基金支付 95%，职工个人支付 5%"
            ),
            "applied_reason": "本次结算适用三级医院住院高段支付比例。",
            "rule_type": "支付比例",
            "psn_type": "",
        },
        {
            "source_text": "退休人员个人支付比例为在职职工个人支付比例的60%",
            "applied_reason": "退休人员享受优惠折算。",
            "rule_type": "计算公式",
            "psn_type": "退休人员",
            "rule_value": "retiree_60",
        },
    ]


@pytest.fixture
def ctx_no_out_of_scope() -> SimpleNamespace:
    """不含 out_of_scope 字段的上下文字段（测试优雅降级）。"""
    return SimpleNamespace(
        settlement_id="1671213",
        deductible=650.0,
        basic_pooling_self_pay=4962.67,
        large_amount_self_pay=1500.0,
        personal_total_pay=7112.67,
        insurance_type="城镇职工基本医疗保险",
        person_type="退休人员",
        service_type="普通住院",
        hospital_level="三级医院",
    )
