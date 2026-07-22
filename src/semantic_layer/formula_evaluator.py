"""
公式求值器 - 安全计算公式求值（Metric Layer 核心）

使用 Python 的 ast 模块实现安全的算术表达式求值，
支持 +, -, *, /, 括号和变量替换。
禁止 eval()/exec()，禁止任意代码执行。

对标 dbt Semantic Layer / MetricFlow 的 formula 设计思路。
"""

import ast
import logging
import operator
from functools import lru_cache
from typing import Any

from src.domain.indicator.models import MetricFormula

logger = logging.getLogger(__name__)


# 支持的操作符映射
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class FormulaEvaluator:
    """
    公式求值器

    将 MetricFormula.expression 解析为 AST，在受控命名空间内求值。
    只允许算术运算符和已注册变量引用。

    Usage:
        evaluator = FormulaEvaluator()
        formula = MetricFormula(
            expression="total_fee - self_fee - first_pay_fee",
            dependencies=["total_fee", "self_fee", "first_pay_fee"],
        )
        result = evaluator.evaluate(formula, {"total_fee": 1000, "self_fee": 200, "first_pay_fee": 50})
        # => 750.0
    """

    # ── 公开 API ──

    def evaluate(
        self,
        formula: MetricFormula,
        values: dict[str, Any],
    ) -> float:
        """求值一个结构化公式

        Args:
            formula: MetricFormula 实例（含 expression, dependencies）
            values: 变量名 → 数值的字典

        Returns:
            计算结果（float）

        Raises:
            ValueError: 缺少依赖、表达式语法错误、包含不支持的语法
        """
        # Step 1: 校验所有依赖项已提供
        self._validate_dependencies(formula.dependencies, values)

        # Step 2: 解析表达式为 AST
        try:
            tree = ast.parse(formula.expression, mode="eval")
        except SyntaxError as e:
            msg = f"公式语法错误 '{formula.expression}': {e}"
            logger.warning(msg)
            raise ValueError(msg) from e

        # Step 3: 在受控环境下求值
        try:
            result = self._eval_node(tree.body, values)
            return float(result)
        except (ValueError, TypeError) as e:
            msg = f"公式求值失败 '{formula.expression}': {e}"
            logger.warning(msg)
            raise ValueError(msg) from e

    def evaluate_raw(
        self,
        expression: str,
        values: dict[str, Any],
    ) -> float:
        """快捷方法：直接对表达式字符串求值（无依赖校验）

        Args:
            expression: 算术表达式字符串
            values: 变量名 → 数值的字典

        Returns:
            计算结果（float）
        """
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as e:
            msg = f"公式语法错误 '{expression}': {e}"
            logger.warning(msg)
            raise ValueError(msg) from e

        try:
            result = self._eval_node(tree.body, values)
            return float(result)
        except (ValueError, TypeError) as e:
            msg = f"公式求值失败 '{expression}': {e}"
            logger.warning(msg)
            raise ValueError(msg) from e

    # ── 内部方法 ──

    @staticmethod
    def _validate_dependencies(
        dependencies: list[str],
        values: dict[str, Any],
    ) -> None:
        """校验所有依赖项在 values 中都有提供"""
        if not dependencies:
            return
        missing = [dep for dep in dependencies if dep not in values]
        if missing:
            raise ValueError(
                f"缺少依赖变量: {missing}。"
                f"公式需要的变量: {dependencies}，"
                f"已提供的变量: {list(values.keys())}"
            )

    @staticmethod
    @lru_cache(maxsize=256)
    def _compile_expression(expression: str) -> ast.Expression:
        """缓存已编译的 AST，避免重复解析

        lru_cache 保证同一表达式只解析一次，线程安全。
        """
        return ast.parse(expression, mode="eval")  # type: ignore[return-value]

    def _eval_node(self, node: ast.AST, values: dict[str, Any]) -> float:
        """递归求值 AST 节点（白名单方式）

        只允许以下节点类型:
        - ast.Constant / ast.Num: 数字字面量
        - ast.Name: 变量引用（从 values 取值）
        - ast.BinOp: 二元算术运算
        - ast.UnaryOp: 一元运算（+/-）
        - ast.Expression: 包装节点
        """
        # ── 叶子节点：常量 ──
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError(f"不支持的常量类型: {type(node.value).__name__} ({node.value})")
            return float(node.value)

        # ── 叶子节点：变量替换 ──
        if isinstance(node, ast.Name):
            var_name = node.id
            if var_name not in values:
                raise ValueError(
                    f"变量 '{var_name}' 未在 values 中提供。"
                    f"已提供的变量: {list(values.keys())}"
                )
            val = values[var_name]
            if val is None:
                raise ValueError(f"变量 '{var_name}' 的值为 None")
            try:
                return float(val)
            except (ValueError, TypeError) as e:
                raise ValueError(
                    f"变量 '{var_name}' 的值 '{val}' 无法转换为数值: {e}"
                ) from e

        # ── 二元运算 ──
        if isinstance(node, ast.BinOp):
            op_func = _BIN_OPS.get(type(node.op))
            if op_func is None:
                raise ValueError(f"不支持的二元运算符: {type(node.op).__name__}")
            left = self._eval_node(node.left, values)
            right = self._eval_node(node.right, values)
            try:
                return float(op_func(left, right))
            except ZeroDivisionError:
                raise ValueError("除零错误: 公式中包含除以零的运算")

        # ── 一元运算 ──
        if isinstance(node, ast.UnaryOp):
            op_func = _UNARY_OPS.get(type(node.op))
            if op_func is None:
                raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
            operand = self._eval_node(node.operand, values)
            return float(op_func(operand))

        # ── 包装节点 ──
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body, values)

        # ── 不支持的类型 ──
        raise ValueError(
            f"不支持的 AST 节点类型: {type(node).__name__}。"
            f"仅支持常量、变量引用、算术运算 (+ - * /)"
        )


# ── 全局单例 ──

_evaluator_instance: FormulaEvaluator | None = None


def get_formula_evaluator() -> FormulaEvaluator:
    """获取全局公式求值器单例"""
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = FormulaEvaluator()
    return _evaluator_instance
