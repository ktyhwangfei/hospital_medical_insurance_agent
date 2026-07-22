"""
费用字段识别器 — 将用户问题映射到 target_fee_item / target_field / explanation_type

解决核心 Bug：不同费用类型问题返回相同答案的问题
"""

from __future__ import annotations


class FeeItemDetector:
    """费用字段识别器 — 将用户问题映射到 target_fee_item / target_field / explanation_type"""

    RULES: list[dict] = [
        {
            "keywords": ["统筹自付", "统筹自费", "统筹段自付", "统筹个人自付", "基本统筹自付"],
            "target_fee_item": "统筹自付",
            "target_field": "pooling_self_pay",
            "explanation_type": "why_or_how",
        },
        {
            "keywords": ["起付线", "起付标准", "起付金额", "起付线多少", "起付线为什么", "门槛费"],
            "target_fee_item": "起付线",
            "target_field": "deductible",
            "explanation_type": "amount_or_reason",
        },
        {
            "keywords": ["大额自付", "大额个人负担", "大额段自付", "大额互助"],
            "target_fee_item": "大额自付",
            "target_field": "large_amount_self_pay",
            "explanation_type": "why_or_how",
        },
        {
            "keywords": ["个人总支付", "个人应负", "总共自己付", "个人负担", "自己要付"],
            "target_fee_item": "个人总支付",
            "target_field": "personal_total_pay",
            "explanation_type": "amount_breakdown",
        },
        {
            "keywords": ["统筹支付", "统筹报销", "医保报销"],
            "target_fee_item": "统筹支付",
            "target_field": "basic_pooling_payment",
            "explanation_type": "amount_or_reason",
        },
        {
            "keywords": ["大额支付", "大额报销"],
            "target_fee_item": "大额支付",
            "target_field": "large_amount_payment",
            "explanation_type": "amount_or_reason",
        },
        {
            "keywords": ["医保外", "自费", "目录外", "丙类"],
            "target_fee_item": "医保外费用",
            "target_field": "out_of_scope",
            "explanation_type": "amount_breakdown",
        },
    ]

    @classmethod
    def detect(cls, question: str) -> dict[str, str]:
        """返回 { target_fee_item, target_field, explanation_type } 或空 dict"""
        for rule in cls.RULES:
            if any(kw in question for kw in rule["keywords"]):
                return {
                    "target_fee_item": rule["target_fee_item"],
                    "target_field": rule["target_field"],
                    "explanation_type": rule["explanation_type"],
                }
        return {}
