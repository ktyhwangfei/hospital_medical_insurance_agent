"""
Skill 边界与异常测试（T1 单元）。

覆盖：
- 零证据降级（no_policy_matched）
- 空证据列表
- 缺失字段降级
- 未知 fee_item fallback
- 极端值（金额=0 / None）
"""

import pytest
from types import SimpleNamespace
from skills.settlement_explain_skill.strategies.registry import get_strategy, list_strategies


# ═══════════════════════════════════════════════════════════════
# 零证据降级
# ═══════════════════════════════════════════════════════════════

class TestNoEvidence:
    """零证据时所有 strategy 正确降级。"""

    @pytest.mark.parametrize("fee_item", [
        "pooling_self_pay", "deductible", "large_amount_self_pay",
        "pooling_payment", "personal_total_pay",
    ])
    def test_execute_does_not_crash_no_evidence(self, fee_item, settlement_context):
        """验证零证据时 execute() 不崩溃。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, [], "no_policy_matched")
        assert result.patient_answer, f"{fee_item}: 零证据时 patient_answer 为空"

    @pytest.mark.parametrize("fee_item", [
        "pooling_self_pay", "deductible", "large_amount_self_pay",
        "pooling_payment", "personal_total_pay",
    ])
    def test_warnings_non_empty_no_evidence(self, fee_item, settlement_context):
        """验证零证据时 warnings 非空。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, [], "no_policy_matched")
        assert result.warnings, f"{fee_item}: 零证据时 warnings 应为非空"

    @pytest.mark.parametrize("fee_item", [
        "pooling_self_pay", "deductible", "large_amount_self_pay",
        "pooling_payment", "personal_total_pay",
    ])
    def test_completeness_downgraded_no_evidence(self, fee_item, settlement_context):
        """验证零证据时 completeness 降级（不是 full_policy_matched）。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, [], "no_policy_matched")
        assert result.completeness
        # 零证据时 level 不应为 full_policy_matched
        assert result.completeness["level"] != "full_policy_matched", (
            f"{fee_item}: 零证据时 completeness.level 不应为 full_policy_matched"
        )


# ═══════════════════════════════════════════════════════════════
# 空证据列表
# ═══════════════════════════════════════════════════════════════

class TestEmptyEvidence:
    """evidence=[] 时的行为。"""

    @pytest.mark.parametrize("fee_item", list_strategies())
    def test_office_answer_still_generated(self, fee_item, settlement_context):
        """验证即使空证据，office_answer 仍然生成（基于真实数据）。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, [], "no_policy_matched")
        assert result.office_answer, (
            f"{fee_item}: 空证据时 office_answer 为空"
        )

    @pytest.mark.parametrize("fee_item", [
        f for f in list_strategies() if f != "out_of_scope"
    ])
    def test_completeness_has_real_data_true(self, fee_item, settlement_context):
        """验证即使空证据，has_real_data 仍为 True（因为有 settlement_context）。"""
        strategy = get_strategy(fee_item)
        result = strategy.execute(settlement_context, [], "no_policy_matched")
        c = result.completeness
        if c.get("has_real_data") is not None:
            assert c["has_real_data"] is True, (
                f"{fee_item}: 有 ctx 时 has_real_data 应为 True"
            )


# ═══════════════════════════════════════════════════════════════
# 未知 fee_item fallback
# ═══════════════════════════════════════════════════════════════

class TestUnknownFeeItem:
    """get_strategy("unknown") → fallback 到 pooling_self_pay。"""

    def test_unknown_falls_back(self, settlement_context, mock_evidence):
        strategy = get_strategy("this_is_not_a_real_fee_item")
        assert strategy.fee_item == "pooling_self_pay"
        assert strategy.fee_label == "统筹自付"
        assert strategy.fee_field == "basic_pooling_self_pay"

    def test_unknown_execute_does_not_crash(self, settlement_context, mock_evidence):
        strategy = get_strategy("not_a_strategy")
        result = strategy.execute(settlement_context, mock_evidence, "policy_matched")
        assert result.patient_answer


# ═══════════════════════════════════════════════════════════════
# 缺失字段降级
# ═══════════════════════════════════════════════════════════════

class TestMissingFields:
    """ctx 缺少字段时不崩溃。"""

    def test_missing_deductible(self, mock_evidence):
        """ctx 缺 deductible 时各 strategy 不崩溃。"""
        ctx = SimpleNamespace(
            settlement_id="1671213",
            basic_pooling_self_pay=4962.67,
            large_amount_self_pay=1500.0,
            personal_total_pay=7112.67,
            insurance_type="城镇职工基本医疗保险",
            person_type="退休人员",
        )
        for fee_item in list_strategies():
            strategy = get_strategy(fee_item)
            try:
                result = strategy.execute(ctx, mock_evidence, "policy_matched")
                assert result.patient_answer, f"{fee_item}: 缺 deductible 输出为空"
            except (AttributeError, KeyError, TypeError) as e:
                pytest.fail(f"{fee_item}: 缺 deductible 时异常 {type(e).__name__}: {e}")

    def test_only_essential_fields(self, mock_evidence):
        """ctx 仅含 settlement_id 时不崩溃。"""
        ctx = SimpleNamespace(settlement_id="1671213")
        for fee_item in list_strategies():
            strategy = get_strategy(fee_item)
            try:
                result = strategy.execute(ctx, mock_evidence, "policy_matched")
                assert result is not None
            except (AttributeError, KeyError, TypeError) as e:
                pytest.fail(f"{fee_item}: 最小 ctx 时异常 {type(e).__name__}: {e}")

    def test_out_of_scope_no_amount_field(self, ctx_no_out_of_scope):
        """OutOfScopeStrategy 在 ctx 无 out_of_scope 字段时优雅降级。"""
        strategy = get_strategy("out_of_scope")
        result = strategy.execute(ctx_no_out_of_scope, [], "no_policy_matched")
        assert "医保外费用" in result.patient_answer
        assert result.completeness["level"] == "incomplete"
        assert result.completeness["has_real_data"] is False
        assert any("未提供独立的医保外费用金额字段" in w for w in result.warnings)


# ═══════════════════════════════════════════════════════════════
# 极端值
# ═══════════════════════════════════════════════════════════════

class TestExtremeValues:
    """极端值处理。"""

    def test_all_amounts_zero(self, mock_evidence):
        """所有金额=0 时不崩溃且输出合理。"""
        ctx = SimpleNamespace(
            settlement_id="1671213",
            deductible=0.0,
            basic_pooling_self_pay=0.0,
            large_amount_self_pay=0.0,
            personal_total_pay=0.0,
            basic_pooling_payment=0.0,
            large_amount_payment=0.0,
            insurance_type="城镇职工基本医疗保险",
            person_type="退休人员",
        )
        for fee_item in ["pooling_self_pay", "deductible", "personal_total_pay"]:
            strategy = get_strategy(fee_item)
            try:
                result = strategy.execute(ctx, mock_evidence, "policy_matched")
                assert result.patient_answer is not None
            except Exception as e:
                pytest.fail(f"{fee_item}: 全部金额=0 时异常 {e}")

    def test_all_amounts_none(self):
        """所有金额=None 时不崩溃。"""
        ctx = SimpleNamespace(
            settlement_id="1671213",
            deductible=None,
            basic_pooling_self_pay=None,
            large_amount_self_pay=None,
            personal_total_pay=None,
            basic_pooling_payment=None,
            insurance_type="城镇职工基本医疗保险",
            person_type="退休人员",
        )
        for fee_item in ["pooling_self_pay", "deductible", "personal_total_pay"]:
            strategy = get_strategy(fee_item)
            try:
                result = strategy.execute(ctx, [], "no_policy_matched")
                assert result.patient_answer is not None
            except Exception as e:
                pytest.fail(f"{fee_item}: 全部金额=None 时异常 {e}")


# ═══════════════════════════════════════════════════════════════
# Strategy 7 抽象方法全覆盖
# ═══════════════════════════════════════════════════════════════

class TestAbstractMethodCoverage:
    """所有 strategy 正确实现了 BaseFeeStrategy 的 7 个抽象方法。"""

    ABSTRACT_METHODS = [
        "build_definition",
        "build_policy_queries",
        "build_patient_answer",
        "build_office_answer",
        "build_calculation_trace",
        "build_warnings",
        "build_completeness",
    ]

    @pytest.mark.parametrize("fee_item", list_strategies())
    def test_all_7_methods_implemented(self, fee_item):
        """每个 strategy 实现了全部 7 个抽象方法。"""
        strategy = get_strategy(fee_item)
        for method in self.ABSTRACT_METHODS:
            assert hasattr(strategy, method), f"{fee_item} 缺少方法 {method}"
            assert callable(getattr(strategy, method)), (
                f"{fee_item}.{method} 不可调用"
            )

    @pytest.mark.parametrize("fee_item", list_strategies())
    def test_build_definition_returns_dict(self, fee_item):
        strategy = get_strategy(fee_item)
        result = strategy.build_definition()
        assert isinstance(result, dict), f"{fee_item}.build_definition() 未返回 dict"
        assert result, f"{fee_item}.build_definition() 返回空字典"

    @pytest.mark.parametrize("fee_item", list_strategies())
    def test_build_policy_queries_returns_list(self, fee_item):
        strategy = get_strategy(fee_item)
        result = strategy.build_policy_queries()
        assert isinstance(result, list), f"{fee_item}.build_policy_queries() 未返回 list"

    @pytest.mark.parametrize("fee_item", list_strategies())
    def test_build_warnings_returns_list(self, fee_item, settlement_context):
        strategy = get_strategy(fee_item)
        result = strategy.build_warnings(settlement_context, "policy_matched")
        assert isinstance(result, list), f"{fee_item}.build_warnings() 未返回 list"
