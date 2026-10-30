"""字段级核对（设计 §10）。

核对类型固定三类：independent_recalculation / detail_aggregation / identity_check。
- difference 统一为 calculated - observed，一分钱差异保留，不自动抹平；
- 未知目标值不是零：observed 为 None 时不按 0 参与核对；
- 计算值为 None（unknown/blocked）→ not_verifiable，绝不用观测值回填（禁止反推）；
- 模块 not_applicable 但账面非零 → 保留 not_applicable 并标记资格与账面冲突；
- 总体状态：任一 mismatched → mismatched；全部 matched/not_applicable → matched；
  其余 → not_verifiable。
"""
from __future__ import annotations

from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchOutcome,
    CalculationOperand,
    CalculationRecord,
    CheckStatus,
    CheckType,
    ExplanationLevel,
    FieldReconciliation,
    decimal_to_str,
)

#: 资格不适用但账面已有非零支付时的冲突诊断 reason_code
ELIGIBILITY_CONFLICT_REASON = "ELIGIBILITY_CONFLICT_WITH_BOOK"


def reconcile_field(
    field_code: str,
    label: str,
    check_type: CheckType,
    calculated: Decimal | None,
    observed: Decimal | None,
    module_outcome: BranchOutcome = BranchOutcome.TRUE,
    reason_code: str | None = None,
    calculation_refs: tuple[str, ...] = (),
    citation_refs: tuple[str, ...] = (),
    uncertainty_refs: tuple[str, ...] = (),
) -> FieldReconciliation:
    """单字段核对。calculated 只接受模块独立计算值；observed 仅为核对目标。"""
    observed_s = decimal_to_str(observed) if observed is not None else None
    calculated_s = decimal_to_str(calculated) if calculated is not None else None

    if module_outcome == BranchOutcome.NOT_APPLICABLE:
        # 资格确定不满足；账面已有非零支付另报资格与账面冲突
        conflict = observed is not None and observed != 0
        return FieldReconciliation(
            field_code=field_code, label=label, check_type=check_type,
            check_status=CheckStatus.NOT_APPLICABLE,
            observed_amount=observed_s, calculated_amount=calculated_s,
            difference=decimal_to_str(calculated - observed)
            if calculated is not None and observed is not None else None,
            explanation_level=ExplanationLevel.OBSERVED_ONLY if observed is not None
            else ExplanationLevel.UNEXPLAINED,
            reason_code=ELIGIBILITY_CONFLICT_REASON if conflict else (reason_code or "NOT_APPLICABLE"),
            calculation_refs=calculation_refs, citation_refs=citation_refs,
            uncertainty_refs=uncertainty_refs)

    if calculated is None or observed is None or module_outcome != BranchOutcome.TRUE:
        # 不可核对：未知目标值不是零，计算缺失不回填
        return FieldReconciliation(
            field_code=field_code, label=label, check_type=check_type,
            check_status=CheckStatus.NOT_VERIFIABLE,
            observed_amount=observed_s, calculated_amount=calculated_s,
            difference=None,
            explanation_level=ExplanationLevel.OBSERVED_ONLY if observed is not None
            else ExplanationLevel.UNEXPLAINED,
            reason_code=reason_code
            or ("OBSERVED_AMOUNT_UNKNOWN" if observed is None else "CALCULATION_UNAVAILABLE"),
            calculation_refs=calculation_refs, citation_refs=citation_refs,
            uncertainty_refs=uncertainty_refs)

    diff = calculated - observed  # 一分钱差异保留
    matched = diff == 0
    return FieldReconciliation(
        field_code=field_code, label=label, check_type=check_type,
        check_status=CheckStatus.MATCHED if matched else CheckStatus.MISMATCHED,
        observed_amount=observed_s, calculated_amount=calculated_s,
        difference=decimal_to_str(diff),
        explanation_level=ExplanationLevel.AMOUNT_RECONCILED if matched
        else ExplanationLevel.OBSERVED_ONLY,
        reason_code=reason_code,
        calculation_refs=calculation_refs, citation_refs=citation_refs,
        uncertainty_refs=uncertainty_refs)


def identity_field(
    field_code: str,
    label: str,
    observed: Decimal | None,
    components: tuple[Decimal | None, ...],
    citation_refs: tuple[str, ...] = (),
    calculation_refs: tuple[str, ...] = (),
) -> FieldReconciliation:
    """恒等式核对：calculated 由**账面观测分量**求和/差得出，显式标注 identity_check。

    只证明账面字段之间满足等式，不证明各字段原因（设计 §10）。
    任一分量未知 → not_verifiable（未知不按零处理）。
    calculation_refs 仅记录本恒等式已执行加减的轨迹元数据，不改变核对语义。
    """
    if observed is None or any(c is None for c in components):
        return FieldReconciliation(
            field_code=field_code, label=label, check_type=CheckType.IDENTITY_CHECK,
            check_status=CheckStatus.NOT_VERIFIABLE,
            observed_amount=decimal_to_str(observed) if observed is not None else None,
            calculated_amount=None, difference=None,
            explanation_level=ExplanationLevel.OBSERVED_ONLY if observed is not None
            else ExplanationLevel.UNEXPLAINED,
            reason_code="IDENTITY_COMPONENTS_INCOMPLETE",
            citation_refs=citation_refs, calculation_refs=calculation_refs)
    total = sum(components, Decimal("0"))  # type: ignore[arg-type]
    diff = total - observed
    matched = diff == 0
    return FieldReconciliation(
        field_code=field_code, label=label, check_type=CheckType.IDENTITY_CHECK,
        check_status=CheckStatus.MATCHED if matched else CheckStatus.MISMATCHED,
        observed_amount=decimal_to_str(observed),
        calculated_amount=decimal_to_str(total),
        difference=decimal_to_str(diff),
        explanation_level=ExplanationLevel.AMOUNT_RECONCILED if matched
        else ExplanationLevel.OBSERVED_ONLY,
        citation_refs=citation_refs, calculation_refs=calculation_refs)


def identity_calculation(
    calculation_id: str,
    formula_id: str,
    operands: tuple[CalculationOperand, ...],
) -> CalculationRecord:
    """账面恒等式已执行加减的轨迹记录：result 为有符号分量合计（解释投影 1.1）。

    只记录内核本来已执行的恒等加减，不引入新运算；分量带符号（减项为负值）。
    """
    total = sum((Decimal(o.value) for o in operands), Decimal("0"))
    return CalculationRecord(
        calculation_id=calculation_id,
        formula_id=formula_id,
        formula_version="v1",
        operands=operands,
        unrounded_result=decimal_to_str(total),
        rounding_rule="not_applicable（账面分量加减，无取整）",
        result=decimal_to_str(total),
    )


def overall_reconciliation_status(entries: tuple[FieldReconciliation, ...]) -> str:
    """总体核对状态轴：matched / mismatched / not_verifiable。"""
    if any(e.check_status == CheckStatus.MISMATCHED for e in entries):
        return "mismatched"
    if entries and all(
        e.check_status in (CheckStatus.MATCHED, CheckStatus.NOT_APPLICABLE) for e in entries
    ):
        return "matched"
    return "not_verifiable"


def coverage_counts(entries: tuple[FieldReconciliation, ...]) -> dict[str, int]:
    """覆盖统计（设计 §11 coverage）。"""
    return {
        "target_field_count": len(entries),
        "independently_explained_count": sum(
            1
            for e in entries
            if e.check_type == CheckType.INDEPENDENT_RECALCULATION
            and e.check_status == CheckStatus.MATCHED
        ),
        "amount_reconciled_count": sum(
            1 for e in entries if e.explanation_level == ExplanationLevel.AMOUNT_RECONCILED
        ),
        "observed_only_count": sum(
            1 for e in entries if e.explanation_level == ExplanationLevel.OBSERVED_ONLY
        ),
    }
