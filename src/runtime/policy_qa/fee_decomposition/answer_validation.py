"""核对回答中的算术关系；只校验表达，不参与结算金额计算。"""
from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP


def _expression_value(text: str) -> Decimal | None:
    text = text.translate(str.maketrans('（），：＋－×÷％−', '(),:+-*/%-'))
    text = re.sub(r'第\s*\d+\s*行|\b\d+\.\s+', '', text)
    text = re.sub(r'\([^()0-9+*/%-]*\)', '', text)
    for note in reversed(list(re.finditer(r'\([^()]*[\u4e00-\u9fff][^()]*\)', text))):
        if not any(operator in note.group() for operator in '+-*/%'):
            text = text[:note.start()] + text[note.end():]
    # 取等号前最近的陈述，保留 min/max 函数括号中的逗号。
    depth = start = 0
    for index, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if char in ',:' and depth == 0:
            start = index + 1
    text = text[start:]
    for name, function in (('较小值', 'min'), ('最小值', 'min'), ('最大值', 'max'), ('取整', 'round')):
        text = text.replace(name, function)
    text = re.sub(r'[\u4e00-\u9fff\s]', '', text)
    text = re.sub(r'(\d+(?:\.\d+)?)%', r'(\1/100)', text)
    if not re.search(r'\d', text):
        if text:
            raise ValueError('unsupported symbolic expression')
        return None  # “字段名＝金额”左侧是名称，不是数值表达式。
    if len(text) > 2000:
        raise ValueError('expression too long')
    tree = ast.parse(text, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 200:
        raise ValueError('expression too complex')

    def value(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            source = ast.get_source_segment(text, node)
            if source is None:
                raise ValueError('missing numeric literal')
            number = Decimal(source)
            if number.is_finite():
                return number
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return value(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            args = [value(arg) for arg in node.args]
            if node.func.id in ('min', 'max') and args:
                return (min if node.func.id == 'min' else max)(args)
            if node.func.id == 'round' and len(args) == 1:
                return args[0].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        raise ValueError('unsupported expression')

    return value(tree.body)


def _equation_segments(text: str) -> list[str]:
    """同一句的多个等式独立核验；函数参数的逗号不能当作分句。"""
    segments: list[str] = []
    part: list[str] = []
    depth = 0
    for index, char in enumerate(text):
        depth += (char in '(（') - (char in ')）')
        if depth == 0 and char in '，,。；;\n':
            if (char == ',' and re.search(r'(?<![\d.])\d{1,3}$', ''.join(part))
                    and re.match(r'\d{3}(?!\d)', text[index + 1:])):
                continue  # 金额千位分隔符，例如 1,837.50。
            segments.append(''.join(part))
            part = []
        else:
            part.append(char)
    segments.append(''.join(part))
    return segments


def equation_issues(text: str, amounts: Mapping[str, Decimal] | None = None) -> list[str]:
    """拒绝不成立或不能安全解析的等式；允许展示金额的半分取整误差。"""
    for segment in _equation_segments(text):
        if not re.search(r'[＝=]', segment):
            continue
        try:
            parts = re.split(r'[＝=]', segment)
            values = [_expression_value(part) for part in parts]
            # “字段名＝表达式”也必须与该字段已知金额一致。
            if values[0] is None and amounts:
                label = re.sub(r'^(?:[-*•\s]+|\d+[.)、]\s*|本[单笔次]|这[笔次])+', '', parts[0]).strip()
                if label in amounts:
                    values[0] = amounts[label]
            numbers = [number for number in values if number is not None]
            if any(abs(number - numbers[0]) > Decimal('0.005') for number in numbers[1:]):
                return ['算式两边金额不一致，请引用资料中的计算关系。']
        except (ValueError, SyntaxError, ArithmeticError, RecursionError):
            return ['算式无法核验，请使用资料中的完整计算关系。']
    return []
