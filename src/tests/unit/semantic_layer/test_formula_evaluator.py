"""FormulaEvaluator 单元测试"""

import pytest

from src.domain.indicator.models import MetricFormula
from src.semantic_layer.formula_evaluator import (
    FormulaEvaluator,
    get_formula_evaluator,
)


# ── Fixtures ──


@pytest.fixture
def evaluator():
    return FormulaEvaluator()


@pytest.fixture
def in_scope_total_formula():
    return MetricFormula(
        expression="total_fee - self_fee - first_pay_fee",
        dependencies=["total_fee", "self_fee", "first_pay_fee"],
    )


# ── 基本运算测试 ──


class TestBasicArithmetic:
    def test_addition(self, evaluator):
        f = MetricFormula(expression="a + b", dependencies=["a", "b"])
        assert evaluator.evaluate(f, {"a": 10, "b": 20}) == 30.0

    def test_subtraction(self, evaluator):
        f = MetricFormula(expression="a - b", dependencies=["a", "b"])
        assert evaluator.evaluate(f, {"a": 100, "b": 30}) == 70.0

    def test_multiplication(self, evaluator):
        f = MetricFormula(expression="rate * base", dependencies=["rate", "base"])
        assert evaluator.evaluate(f, {"rate": 0.8, "base": 1000}) == 800.0

    def test_division(self, evaluator):
        f = MetricFormula(expression="total / count", dependencies=["total", "count"])
        assert evaluator.evaluate(f, {"total": 100, "count": 5}) == 20.0

    def test_complex_expression(self, evaluator, in_scope_total_formula):
        # total_fee - self_fee - first_pay_fee = 1000 - 200 - 50 = 750
        result = evaluator.evaluate(
            in_scope_total_formula,
            {"total_fee": 1000, "self_fee": 200, "first_pay_fee": 50},
        )
        assert result == 750.0

    def test_parentheses(self, evaluator):
        f = MetricFormula(expression="(a + b) * c", dependencies=["a", "b", "c"])
        assert evaluator.evaluate(f, {"a": 10, "b": 20, "c": 3}) == 90.0

    def test_float_results(self, evaluator):
        f = MetricFormula(expression="a / b", dependencies=["a", "b"])
        assert evaluator.evaluate(f, {"a": 10, "b": 3}) == pytest.approx(3.3333, rel=1e-4)


# ── 边界与异常测试 ──


class TestErrorHandling:
    def test_missing_dependency(self, evaluator, in_scope_total_formula):
        with pytest.raises(ValueError, match="缺少依赖变量"):
            evaluator.evaluate(in_scope_total_formula, {"total_fee": 1000})

    def test_all_dependencies_missing(self, evaluator):
        f = MetricFormula(expression="a + b", dependencies=["a", "b"])
        with pytest.raises(ValueError, match="缺少依赖变量"):
            evaluator.evaluate(f, {})

    def test_empty_dependencies_ok(self, evaluator):
        f = MetricFormula(expression="3 + 5", dependencies=[])
        assert evaluator.evaluate(f, {}) == 8.0

    def test_variable_not_in_values(self, evaluator):
        """变量在 dependencies 中声明但在 values 中未提供"""
        f = MetricFormula(expression="a + b", dependencies=["a", "b"])
        with pytest.raises(ValueError, match="缺少依赖变量"):
            evaluator.evaluate(f, {"a": 5})

    def test_syntax_error(self, evaluator):
        f = MetricFormula(expression="a +* b", dependencies=["a", "b"])
        with pytest.raises(ValueError, match="公式语法错误"):
            evaluator.evaluate(f, {"a": 1, "b": 2})

    def test_division_by_zero(self, evaluator):
        f = MetricFormula(expression="a / b", dependencies=["a", "b"])
        with pytest.raises(ValueError, match="除零错误"):
            evaluator.evaluate(f, {"a": 10, "b": 0})

    def test_none_value(self, evaluator):
        f = MetricFormula(expression="a + b", dependencies=["a", "b"])
        with pytest.raises(ValueError, match="值为 None"):
            evaluator.evaluate(f, {"a": 10, "b": None})

    def test_non_numeric_variable(self, evaluator):
        f = MetricFormula(expression="a + b", dependencies=["a", "b"])
        with pytest.raises(ValueError, match="无法转换为数值"):
            evaluator.evaluate(f, {"a": 10, "b": "not_a_number"})


# ── 单例测试 ──


class TestSingleton:
    def test_get_formula_evaluator_returns_same_instance(self):
        e1 = get_formula_evaluator()
        e2 = get_formula_evaluator()
        assert e1 is e2

    def test_singleton_works(self, evaluator):
        f = MetricFormula(expression="2 + 2", dependencies=[])
        assert evaluator.evaluate(f, {}) == 4.0


# ── evaluate_raw 快捷方法测试 ──


class TestEvaluateRaw:
    def test_raw_expression(self, evaluator):
        assert evaluator.evaluate_raw("2 + 3 * 4", {}) == 14.0

    def test_raw_with_variables(self, evaluator):
        assert evaluator.evaluate_raw("rate * base", {"rate": 0.9, "base": 2000}) == 1800.0

    def test_raw_parentheses(self, evaluator):
        assert evaluator.evaluate_raw("(2 + 3) * 4", {}) == 20.0

    def test_raw_negative(self, evaluator):
        assert evaluator.evaluate_raw("-5 + 3", {}) == -2.0

    def test_raw_division_float(self, evaluator):
        assert evaluator.evaluate_raw("10 / 4", {}) == 2.5


# ── 安全测试 ──


class TestSecurity:
    def test_no_exec_allowed(self, evaluator):
        """验证不能执行任意 Python 代码"""
        f = MetricFormula(expression="__import__('os').system('echo hack')", dependencies=[])
        with pytest.raises((ValueError, SyntaxError)):
            evaluator.evaluate(f, {})

    def test_no_attribute_access(self, evaluator):
        """验证不能访问对象属性"""
        f = MetricFormula(expression="a.__class__", dependencies=["a"])
        with pytest.raises(ValueError, match="不支持的 AST 节点"):
            evaluator.evaluate(f, {"a": 5})

    def test_no_function_calls(self, evaluator):
        """验证不能调用函数"""
        f = MetricFormula(expression="int(a)", dependencies=["a"])
        with pytest.raises((ValueError, SyntaxError)):
            evaluator.evaluate(f, {"a": "5"})

    def test_no_string_constants(self, evaluator):
        """验证字符串常量被拒绝"""
        f = MetricFormula(expression="'hello'", dependencies=[])
        with pytest.raises(ValueError, match="不支持的常量类型"):
            evaluator.evaluate(f, {})


# ── 边界值测试 ──


class TestEdgeCases:
    def test_large_numbers(self, evaluator):
        f = MetricFormula(expression="a * b", dependencies=["a", "b"])
        result = evaluator.evaluate(f, {"a": 1e10, "b": 2e5})
        assert result == 2e15

    def test_negative_values(self, evaluator):
        f = MetricFormula(expression="a - b", dependencies=["a", "b"])
        assert evaluator.evaluate(f, {"a": 10, "b": 20}) == -10.0

    def test_zero_values(self, evaluator):
        f = MetricFormula(expression="a + b", dependencies=["a", "b"])
        assert evaluator.evaluate(f, {"a": 0, "b": 0}) == 0.0

    def test_int_values_return_float(self, evaluator):
        f = MetricFormula(expression="a + b", dependencies=["a", "b"])
        result = evaluator.evaluate(f, {"a": 5, "b": 3})
        assert isinstance(result, float)
        assert result == 8.0

    def test_nested_parentheses(self, evaluator):
        f = MetricFormula(expression="((a + b) * c) - d", dependencies=["a", "b", "c", "d"])
        result = evaluator.evaluate(f, {"a": 1, "b": 2, "c": 3, "d": 4})
        assert result == 5.0
