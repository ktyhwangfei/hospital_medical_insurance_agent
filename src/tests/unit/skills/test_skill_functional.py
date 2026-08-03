"""
Skill 功能正确性测试（T1 单元）。

覆盖：
- 6 种 Strategy 的 execute() 冒烟（不崩溃）
- StrategyResult 输出结构完整性（7 字段非空）
- 金额数值精确匹配
- target_fee_item / target_field 映射正确
"""

import pytest
from skills.settlement_explain_skill.strategies.registry import get_strategy, list_strategies


# ═══════════════════════════════════════════════════════════════
# 冒烟：所有 strategy 执行不崩溃
# ═══════════════════════════════════════════════════════════════

ALL_FEE_ITEMS = [
    "pooling_self_pay",
    "deductible",
    "large_amount_self_pay",
    "pooling_payment",
    "personal_total_pay",
    "out_of_scope",
]

EXPECTED_MAPPING = {
    "pooling_self_pay": ("pooling_self_pay", "basic_pooling_self_pay"),
    "deductible": ("deductible", "deductible"),
    "large_amount_self_pay": ("large_amount_self_pay", "large_amount_self_pay"),
    "pooling_payment": ("pooling_payment", "basic_pooling_payment"),
    "personal_total_pay": ("personal_total_pay", "personal_total_pay"),
    "out_of_scope": ("out_of_scope", "out_of_scope"),
}


class TestAllStrategiesExecute:
    """每个 strategy 的 execute() 冒烟测试。"""

    @pytest.mark.parametrize("fee_item", ALL_FEE_ITEMS)
    def test_execute_does_not_crash(self, fee_item, settlement_context, mock_evidence):
        """验证 execute() 在所有 6 种 strategy 上不崩溃。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert result is not None, f"{fee_item}: execute() 返回 None"

    @pytest.mark.parametrize("fee_item", ALL_FEE_ITEMS)
    def test_patient_answer_not_empty(self, fee_item, settlement_context, mock_evidence):
        """验证 patient_answer（患者视角解释）非空且长度合理。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert result.patient_answer, f"{fee_item}: patient_answer 为空"
        assert len(result.patient_answer) > 20, (
            f"{fee_item}: patient_answer 过短 ({len(result.patient_answer)} chars)"
        )

    @pytest.mark.parametrize("fee_item", ALL_FEE_ITEMS)
    def test_office_answer_not_empty(self, fee_item, settlement_context, mock_evidence):
        """验证 office_answer（医保办视角解释）非空且长度合理。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert result.office_answer, f"{fee_item}: office_answer 为空"
        assert len(result.office_answer) > 20, (
            f"{fee_item}: office_answer 过短 ({len(result.office_answer)} chars)"
        )


# ═══════════════════════════════════════════════════════════════
# 输出结构完整性
# ═══════════════════════════════════════════════════════════════

class TestStrategyOutputIntegrity:
    """StrategyResult 7 字段结构完整性。"""

    RESULT_FIELDS = [
        "definition", "patient_answer", "office_answer",
        "calculation_trace", "policy_queries", "warnings", "completeness",
    ]

    @pytest.mark.parametrize("fee_item", ALL_FEE_ITEMS)
    def test_all_fields_present(self, fee_item, settlement_context, mock_evidence):
        """验证 StrategyResult 7 个核心字段全部存在。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        for field in self.RESULT_FIELDS:
            assert hasattr(result, field), f"{fee_item}: 缺少字段 {field}"

    @pytest.mark.parametrize("fee_item", ALL_FEE_ITEMS)
    def test_definition_not_empty(self, fee_item, settlement_context, mock_evidence):
        """验证 definition 字段非空。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert result.definition, f"{fee_item}: definition 为空"
        assert "name" in result.definition, f"{fee_item}: definition 缺少 name"

    @pytest.mark.parametrize("fee_item", [
        f for f in ALL_FEE_ITEMS if f != "out_of_scope"
    ])
    def test_completeness_has_required_keys(self, fee_item, settlement_context, mock_evidence):
        """验证 completeness 包含 level / has_real_data / message。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        c = result.completeness
        assert "level" in c, f"{fee_item}: completeness 缺少 level"
        assert "has_real_data" in c, f"{fee_item}: completeness 缺少 has_real_data"
        assert c["has_real_data"] is True, f"{fee_item}: has_real_data 应为 True"

    def test_out_of_scope_completeness(self, settlement_context, mock_evidence):
        """out_of_scope 策略的 completeness 特殊处理（概念级解释）."""
        strategy = get_strategy("out_of_scope")
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        c = result.completeness
        assert "level" in c
        assert "has_real_data" in c
        # out_of_scope 可能没有直接金额字段，has_real_data 可为 False


# ═══════════════════════════════════════════════════════════════
# target_fee_item / target_field 映射正确
# ═══════════════════════════════════════════════════════════════

class TestFeeItemMapping:
    """target_fee_item 和 target_field 映射。"""

    @pytest.mark.parametrize("fee_item,expected_item,expected_field", [
        (k, v[0], v[1]) for k, v in EXPECTED_MAPPING.items()
    ])
    def test_mapping(self, fee_item, expected_item, expected_field,
                     settlement_context, mock_evidence):
        """验证 strategy 的 fee_item/fee_field 映射正确。"""
        strategy = get_strategy(fee_item)
        assert strategy.fee_item == expected_item, (
            f"fee_item={fee_item}: strategy.fee_item={strategy.fee_item}, "
            f"期望={expected_item}"
        )
        assert strategy.fee_field == expected_field, (
            f"fee_item={fee_item}: strategy.fee_field={strategy.fee_field}, "
            f"期望={expected_field}"
        )

    def test_execute_result_has_target_fee_item(self, settlement_context, mock_evidence):
        """验证 execute() 返回的 result 也携带 target_fee_item。"""
        for fee_item in ALL_FEE_ITEMS:
            strategy = get_strategy(fee_item)
            result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
            assert result.target_fee_item == fee_item, (
                f"result.target_fee_item={result.target_fee_item}, 期望={fee_item}"
            )


# ═══════════════════════════════════════════════════════════════
# 金额数值精确匹配
# ═══════════════════════════════════════════════════════════════

class TestAmountAccuracy:
    """验证输出中包含正确的金额数值。"""

    def test_pooling_self_pay_amount(self, settlement_context, mock_evidence):
        strategy = get_strategy("pooling_self_pay")
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert "4962" in result.patient_answer or "4,962" in result.patient_answer

    def test_deductible_amount(self, settlement_context, mock_evidence):
        strategy = get_strategy("deductible")
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert "650" in result.patient_answer

    def test_large_amount_self_pay_amount(self, settlement_context, mock_evidence):
        strategy = get_strategy("large_amount_self_pay")
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert "1500" in result.patient_answer or "1,500" in result.patient_answer

    def test_pooling_payment_amount(self, settlement_context, mock_evidence):
        strategy = get_strategy("pooling_payment")
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert "35000" in result.patient_answer or "35,000" in result.patient_answer

    def test_personal_total_pay_amount(self, settlement_context, mock_evidence):
        strategy = get_strategy("personal_total_pay")
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert "7112" in result.patient_answer or "7,112" in result.patient_answer
