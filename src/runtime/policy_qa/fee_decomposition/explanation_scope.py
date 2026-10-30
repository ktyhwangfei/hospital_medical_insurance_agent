"""解释资格只依据本次金额核对及实际依赖，不替代规则来源的治理状态。"""
from decimal import Decimal, InvalidOperation
from typing import Any

from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation
from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult


def _same_amount(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    try:
        a, b = Decimal(left), Decimal(right)
        return a.is_finite() and b.is_finite() and a == b
    except (InvalidOperation, TypeError):
        return False


def mark_explanation_scope(result: SettlementDecompositionResult, fields: list[dict[str, Any]],
                           calculations: list[dict[str, Any]], inputs: list[dict[str, Any]], items: list[FeeItemExplanation]) -> None:
    index = {c['calculation_id']: c for c in calculations}
    input_index = {node['input_id']: node for node in inputs}
    raw = {c.calculation_id: c for c in result.calculations if c.calculation_id in index}
    rows_matched = bool(items) and all(item.explainable for item in items)
    roots = {}
    blocked = set()
    for field in result.fields:
        refs = [ref for ref in field.calculation_refs if ref in index]
        # 同模块可记录多个中间量，先定位与目标金额一致的输出，再沿实际操作数追溯。
        matches = [ref for ref in refs if _same_amount(index[ref]['result'], field.calculated_amount)]
        roots[field.field_code] = matches or refs
        if field.check_status != 'matched' or not _same_amount(field.calculated_amount, field.observed_amount):
            blocked.update(matches or refs)

    def visit(cid: str, stack: set[str]) -> set[str] | None:
        if cid not in index or cid in stack or cid in blocked:
            return None
        calc = index[cid]
        if not _same_amount(calc['result'], calc['result']) or calc['verification_status'] == 'conflict':
            return None
        if calc['formula_id'] == 'observed_deductible_passthrough_v1' or calc['formula_id'].startswith('identity_'):
            return None  # 账面起付复制不能证明独立重算。
        reached = {cid}
        for operand, projected in zip(raw[cid].operands, calc['operands']):
            node = input_index.get(projected.get('input_ref'), {})
            ref = projected.get('calculation_ref')
            if node.get('status') == 'conflict':
                return None
            if ref:
                upstream = visit(ref, stack | {cid})
                if upstream is None:
                    return None
                reached.update(upstream)
            elif operand.ref.startswith('calc.catalog.lines.') or operand.ref == 'fact.items.ybnje':
                if not rows_matched:
                    return None
            elif operand.ref.startswith('calc.') and node.get('status') != 'verified':
                return None
        return reached

    permitted = set()
    for item in items:
        if item.explainable:
            for ref in item.calculation_refs:
                permitted.update(visit(ref, set()) or ())
    for field, projected in zip(result.fields, fields):
        eligible = field.check_status == 'matched' and _same_amount(field.calculated_amount, field.observed_amount) and field.check_type != 'identity_check'
        refs = roots[field.field_code]
        eligible = eligible and bool(refs) and all(ref in index for ref in field.calculation_refs) and any(
            _same_amount(index[ref]['result'], field.calculated_amount) for ref in refs)
        reached = set()
        if eligible:
            for ref in refs:
                dependency = visit(ref, set())
                if dependency is None:
                    eligible = False
                    break
                reached.update(dependency)
        # 列未维护的分量计算降级（GRZIF1）：保留 _field_brief 的专门措辞，
        # 不套用"算法待补全"占位理由（本单确有独立分量计算，只是无账面核对目标）。
        unmaintained_book = field.reason_code == 'SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED'
        projected['explainable'] = eligible
        projected['explanation_reason'] = None if eligible or unmaintained_book else (
            '账面勾稽，仅展示金额构成' if field.check_type == 'identity_check' else
            '金额不符，算法待补全' if field.check_status == 'mismatched' else
            '本项金额一致，实际依赖尚未独立算平（算法待补全）' if field.check_status == 'matched' else
            '尚未取得独立计算或核对值，算法待补全')
        if eligible:
            permitted.update(reached)
            projected['calculation_refs'] = [cid for cid in index if cid in reached]
        elif not unmaintained_book:
            projected['brief'] = None
    for calc in calculations:
        calc['explainable'] = calc['calculation_id'] in permitted
