"""输入引用的公开投影和依赖验证；未解析、冲突和循环都阻断独立解释。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from src.runtime.policy_qa.fee_decomposition.explanation_evidence import EvidenceStatus, FormulaInput, input_id
from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult, CalculationRecordModel

_ALIASES = {
    "rule.SC-DB-001.deductible": ("calc.secondary.db_deductible",),
    "rule.SC-DB-001.first_rate": ("calc.secondary.db_first_rate",),
    "rule.SC-DB-001.second_rate": ("calc.secondary.db_second_rate",),
    "input.secondary.self_pay_1_after_supplements": ("calc.secondary.personal_base",),
    "input.secondary.proportional_self_pay_2": ("calc.catalog.total_proportional_self_pay",),
    "input.secondary.current_compliant_base": ("calc.secondary.current_base",),
    "input.secondary.first_band_overlap": ("calc.secondary.first_band_base",),
    "input.secondary.second_band_overlap": ("calc.secondary.second_band_base",),
    "input.secondary.remaining_base": ("calc.secondary.remaining_base",),
    "input.secondary.total_out_scope": ("calc.catalog.total_out_scope",),
    "calc.deductible.paid": ("calc.deductible.split", "calc.deductible.observed"),
    "calc.big_pay": ("calc.big_pay.segmented", "calc.big_pay.capped", "calc.big_pay.clamp"),
    "calc.pool.pay": ("calc.pool.segmented",), "calc.pool.self": ("calc.pool.self_pay",),
    "calc.large.pay": ("calc.large.settle",), "calc.large.self": ("calc.large.self_pay",),
}
_NAMES = {"fact.items.fee": "费用明细金额合计", "fact.items.ybnje": "明细医保内账面划分合计",
          "calc.catalog.lines.in_scope": "逐行医保内金额", "calc.catalog.lines.out_scope": "逐行医保外金额",
          "calc.catalog.lines.self_pay_2": "逐行先行自付", "calc.catalog.lines.proportional_self_pay": "逐行比例先行负担",
          "fact.catalog.self_pay_ratio": "目录先行自付比例", "fact.catalog.unit_price_limit": "目录单价限额",
          "fact.line_or_catalog.self_pay_ratio": "本行采用的先行自付比例",
          "fact.line_or_catalog.unit_price_limit": "本行采用的单价限额",
          "fact.line_or_catalog.excess_ratio": "超限价自付比例", "input.employed.factor": "在职自付折算系数"}


def _equal(a: str | None, b: str | None, *, signed_subtraction: bool = False) -> bool:
    if a is None or b is None:
        return False
    try:
        left, right = Decimal(a), Decimal(b)
        return left == right or (signed_subtraction and left < 0 and right >= 0 and left == -right)
    except InvalidOperation:
        return a == b


def project_inputs(result: SettlementDecompositionResult, views: list[dict[str, Any]], calc_index: dict[str, CalculationRecordModel]) -> list[FormulaInput]:
    evidence = result.explanation_evidence
    inputs: dict[str, FormulaInput] = {}
    scoped_values: dict[str, str] = {}
    view_index = {v["calculation_id"]: v for v in views}
    for calc in calc_index.values():
        view = view_index[calc.calculation_id]
        for operand, op in zip(calc.operands, view["operands"]):
            ref = operand.ref
            # 目录参数属于具体行的匹配版本；同名参数在不同行不能合并。
            scoped = f"{ref}@{calc.calculation_id}" if ref.startswith(("fact.catalog.", "fact.line_or_catalog.")) else ref
            ident = input_id(scoped)
            calc_ref = ref if ref in calc_index else None
            if calc_ref is None and ref in _ALIASES:
                matches = [c for c in _ALIASES[ref] if c in calc_index]
                calc_ref = matches[0] if len(matches) == 1 else None
            if calc_ref:
                ident = input_id(calc_ref)
                node = FormulaInput(input_id=ident, name=view_index[calc_ref]["display_name"],
                                    value=calc_index[calc_ref].result, source="上游计算", calculation_ref=calc_ref)
                if not _equal(operand.value, node.value, signed_subtraction=view["layout"] == "sum"):
                    node.status, node.reason = "conflict", "引用的输入值与上游结果不一致"
            elif evidence and ref in evidence.inputs:
                node = evidence.inputs[ref].model_copy()
                ident = node.input_id
                if not _equal(operand.value, node.value, signed_subtraction=view["layout"] == "sum"):
                    node.status, node.reason = "conflict", "采用值与原始输入证据不一致"
            else:
                node = FormulaInput(input_id=ident, name=_NAMES.get(ref, op["display_name"]) or "输入依据", value=operand.value,
                                    source="本次运算记录", reason="未取得该输入的独立来源或完整上游运算")
                if ref == "fact.items.fee" and result.fee_items:
                    node.status, node.source, node.reason = "verified", "本笔费用明细（见逐行表）", None
                elif ref.startswith("calc.catalog.lines.") and result.fee_items:
                    node.status = "verified" if all(i.verification_status == "verified" for i in result.fee_items) else "unverified"
                    node.source, node.reason = "本笔费用明细逐行分解（见逐行表）", None if node.status == "verified" else "费用行的目录适用性或取整口径仍待核实"
                elif ref == "fact.items.ybnje" and result.fee_items:
                    complete = all(i.verification_status == "verified" and _equal(i.observed_in_scope, i.calculated_in_scope) for i in result.fee_items)
                    node.status = "verified" if complete else "unverified"
                    node.source = "本笔明细医保内划分（见费用表及逐行目录依据）"
                    node.reason = None if complete else "账面划分尚未通过完整的逐行目录适用性与算法验证"
                elif ref.startswith(("fact.catalog.", "fact.line_or_catalog.")):
                    line_id = calc.calculation_id.rsplit(".", 1)[-1]
                    row = next((i for i in result.fee_items if i.line_id == line_id), None)
                    node.name = _NAMES.get(ref, "本行目录参数")
                    node.source = f"第{line_id}行匹配目录 · " + ("；".join(row.conditions[:2]) if row else "匹配证据未取得")
                    node.status, node.reason = ("verified", None) if row and row.verification_status == "verified" else ("unverified", "目录版本、适用条件或取整口径未核实")
                elif ref.startswith("input.segment."):
                    node.name = "费用分段下界" if ref.endswith("lower") else "费用分段上界"
                    node.source, node.status, node.reason = "当前门特待遇参数表的费用区间", "verified", None
                elif ref == "input.employed.factor" and operand.value == "1":
                    node.source, node.status, node.reason = "在职档直接采用原自付比例，折算系数为1", "verified", None
                elif ref == "input.rsup.large_not_applicable" and Decimal(operand.value) == 0:
                    node.name, node.source, node.status, node.reason = "大额段退休补助", "本笔无大额自付，未进入大额退休补助", "verified", None
                elif ref in ("rule.issue82.pool_self_pay_reduction", "rule.issue82.large_self_pay_reduction"):
                    node.name = "统筹自付降低值" if "pool" in ref else "大额自付降低值"
                    node.source = "医院定额专用减点条件" if result.algorithm_version == "employee_special_fixed_kidney_v1" else "本单未启用定额减点"
                    node.status = "verified" if operand.value == "0" else "unverified"
                    node.reason = None if node.status == "verified" else "定额减点口径待业务签核"
                elif ref in ("calc.rsup.amount", "calc.dvet.amount", "calc.pmed.amount") and operand.value in ("0", "0.00"):
                    prefix = {"calc.rsup.amount": "rsup", "calc.dvet.amount": "dvet", "calc.pmed.amount": "pmed"}[ref]
                    branches = [b for b in result.branches if b.step_id.startswith(prefix + ".")]
                    if branches and any(b.outcome == "not_applicable" for b in branches) and not any(b.outcome in ("unknown", "blocked") for b in branches):
                        node.status, node.reason, node.source = "verified", None, "本单已判定该补助不适用，支付为0"
            if ident in scoped_values and not _equal(scoped_values[ident], node.value):
                node.status, node.reason = "conflict", "同一输入引用出现不同值"
            if node.value is not None:
                scoped_values[ident] = node.value
            previous = inputs.get(ident)
            if previous and previous.status == "conflict":
                node.status, node.reason = previous.status, previous.reason
            inputs[ident] = node
            op.update(input_ref=ident, calculation_ref=calc_ref, display_name=node.name)
    if evidence:
        # 条件判断也需要原始输入，零支付分支可能在金额计算前就已结束。
        used = {ref for group in evidence.rule_choices for ref in group.input_refs}
        used.update(input_id(ref) for branch in result.branches for ref in branch.input_refs)
        for node in evidence.inputs.values():
            if node.input_id in used and node.input_id not in inputs:
                inputs[node.input_id] = node
    states = {}

    def verify(cid: str, stack: set[str]) -> EvidenceStatus:
        if cid in states:
            return states[cid]
        if cid in stack:
            return "conflict"
        calc, view = calc_index[cid], view_index[cid]
        blocked = []
        stack = stack | {cid}
        for op in view["operands"]:
            node = inputs[op["input_ref"]]
            if node.calculation_ref:
                status = verify(node.calculation_ref, stack)
                if node.status != "conflict":
                    node.status = status
                    node.reason = None if status == "verified" else "上游计算仍有待核实输入"
            if node.status != "verified":
                blocked.append(node)
        status = "conflict" if any(n.status == "conflict" for n in blocked) else "unverified" if blocked or not calc.operands or calc.result is None else "verified"
        # 执行时采用的取整候选口径不能因金额恰好一致变成已核实。
        if status == "verified" and calc.rounding_rule and "待确认" in calc.rounding_rule:
            status = "unverified"
        view["verification_status"] = status
        view["verification_reason"] = "；".join(dict.fromkeys(n.reason or f"{n.name}未核实" for n in blocked)) or ("取整口径待确认" if status != "verified" and calc.rounding_rule and "待确认" in calc.rounding_rule else None)
        states[cid] = status
        return status

    for cid in calc_index:
        verify(cid, set())
    return list(inputs.values())
