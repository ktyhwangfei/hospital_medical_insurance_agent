"""三大目录逐项分解（设计 §7.2）。

药品（ItemType=0）/ 诊疗与服务设施 / 医用材料分别按确认规则分解；
目录匹配按**费用发生日期**；0 命中 missing_catalog、多命中 ambiguous_catalog，不取首条；
空结束日期不默认永久有效（设计 §5.3）。

门控边界说明：
- 结构性划分语义（EOP-CAT-001/002/003/006/007、自制剂价格限制）按设计 §7.2 直接编码，
  规则引用保留在轨迹中；
- 带数值阈值且生效日期未明确的参数（EOP-CAT-008 检查费 200 元/8%）经参数选择函数门控，
  当前返回 unknown，不静默生效；
- 集采超限价分支的 a_xbbl 语义（增量/最终比例、作用基数）未确认，不编码公式，输出 unknown；
- EOP-NCP-002（未通过一致性评价先划超限价部分入自付二）生效日期未明确，输出 unknown。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.domain.insurance.fee_decomposition import (
    BranchCondition,
    BranchOutcome,
    BranchTrace,
    CalculationOperand,
    CalculationRecord,
    CatalogKind,
    DecompositionUncertainty,
    DrugCatalogEntry,
    FeeLineItem,
    MaterialCatalogEntry,
    PackagingType,
    RoundingMode,
    ServiceCatalogEntry,
    apply_rounding,
    decimal_to_str,
)
from src.runtime.policy_qa.fee_decomposition.params_employee_outpatient import (
    get_param,
    select_check_fee_param,
    select_material_rule,
)

MODULE_ID = "catalog_split"

#: S1 候选目录收费类别（无自付/有自付/全自付 与 甲/乙/丙 两套写法）
_NO_SELF_PAY = ("无自付", "甲")
_PARTIAL_SELF_PAY = ("有自付", "乙")
_FULL_SELF_PAY = ("全自付", "丙")
#: 收费类别码（字典 flid=230）→ 自付档（决策记录 D2）。
#: 实证：命中编码 zfbl 与分组完全对齐（甲类 zfbl=0、乙类 0.1、其它类 1.0）。
_NO_SELF_PAY_CODES = frozenset({"0101", "0201", "0301", "0302"})  # 甲类西药/中成药、复方/单方可报草药
_PARTIAL_SELF_PAY_CODES = frozenset({"0102", "0202"})  # 乙类（比例取目录 zfbl）
_FULL_SELF_PAY_CODES = frozenset({"0103", "0203", "0303"})  # 其它类（zfbl=1.0 佐证全自付）
#: 自制剂候选 ypfl 代码（设计 §7.2，含义及与集采重叠优先次序待确认）
_HOSPITAL_PREPARATION_YPFL = ("16", "6")


def _fee_category_group(value: str | None) -> str | None:
    """收费类别取值 → 自付档（none/partial/full）；未覆盖取值返回 None 不猜测。"""
    if value is None:
        return None
    v = value.strip()
    if v in _NO_SELF_PAY or v in _NO_SELF_PAY_CODES:
        return "none"
    if v in _PARTIAL_SELF_PAY or v in _PARTIAL_SELF_PAY_CODES:
        return "partial"
    if v in _FULL_SELF_PAY or v in _FULL_SELF_PAY_CODES:
        return "full"
    return None


@dataclass(frozen=True)
class LineDecomposition:
    """单行分解结果：互斥金额桶（医保内/医保外）只分配一次，自付二为可追踪子项。"""

    line_key: str
    fee: Decimal
    status: BranchOutcome  # TRUE=已分解；UNKNOWN/BLOCKED=未得出
    in_scope: Decimal | None = None
    out_scope: Decimal | None = None
    self_pay_2: Decimal | None = None  # 可追踪子项，不预先认定为第三项（设计 §7.2）
    labels: tuple[str, ...] = ()  # 非互斥解释标签（乙类/集采/超限价等）


@dataclass(frozen=True)
class CatalogSplitResult:
    lines: tuple[LineDecomposition, ...]
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()
    fatal_issue: str | None = None  # 数据异常（如重复行键）时置位，合计不可用
    # 合计仅在全部行分解成功时视为完整（设计 §10：完整性不足的合计不得作为完整合计）
    total_fee: Decimal | None = None
    total_in_scope: Decimal | None = None
    total_out_scope: Decimal | None = None
    total_self_pay_2: Decimal | None = None
    is_complete: bool = False


@dataclass(frozen=True)
class _LineOut:
    line: LineDecomposition
    branches: tuple[BranchTrace, ...] = ()
    calculations: tuple[CalculationRecord, ...] = ()
    uncertainties: tuple[DecompositionUncertainty, ...] = ()


def _branch(
    step_id: str,
    outcome: BranchOutcome,
    scope_ref: str,
    condition: BranchCondition | None = None,
    reason_code: str | None = None,
    parent_step_id: str | None = None,
    rule_refs: tuple[str, ...] = (),
    input_refs: tuple[str, ...] = (),
    calculation_refs: tuple[str, ...] = (),
) -> BranchTrace:
    return BranchTrace(
        step_id=step_id,
        parent_step_id=parent_step_id,
        module_id=MODULE_ID,
        scope_ref=scope_ref,
        condition=condition,
        outcome=outcome,
        reason_code=reason_code,
        input_refs=input_refs,
        rule_refs=rule_refs,
        calculation_refs=calculation_refs,
    )


def _calc(
    calc_id: str,
    formula_id: str,
    operands: tuple[CalculationOperand, ...],
    unrounded: Decimal | None,
    result: Decimal | None,
    rounding_mode: RoundingMode,
) -> CalculationRecord:
    return CalculationRecord(
        calculation_id=calc_id,
        formula_id=formula_id,
        formula_version="v1",
        operands=operands,
        unrounded_result=decimal_to_str(unrounded) if unrounded is not None else None,
        rounding_rule=f"explicit:{rounding_mode.value}(EOP-RND-001 待确认)",
        result=decimal_to_str(result) if result is not None else None,
    )


def split_catalog(
    items: tuple[FeeLineItem, ...],
    drug_catalog: tuple[DrugCatalogEntry, ...],
    service_catalog: tuple[ServiceCatalogEntry, ...],
    material_catalog: tuple[MaterialCatalogEntry, ...],
    hospital_code: str,
    rounding_mode: RoundingMode,
) -> CatalogSplitResult:
    """三大目录逐项分解入口。重复行键属数据异常，不静默去重（设计 §5.3）。"""
    keys = [it.line_key for it in items]
    if len(set(keys)) != len(keys):
        return CatalogSplitResult(
            lines=(),
            fatal_issue="DUPLICATE_LINE_KEY",
            uncertainties=(
                DecompositionUncertainty(
                    id="u.catalog.duplicate_line_key",
                    code="DUPLICATE_LINE_KEY",
                    message="费用明细存在重复行键，属数据异常，未静默去重，目录分解未执行。",
                    affected_fields=("T_FeeAll", "T_FeeIn", "T_FeeOut", "T_SelfPay2"),
                ),
            ),
        )

    lines: list[LineDecomposition] = []
    branches: list[BranchTrace] = []
    calcs: list[CalculationRecord] = []
    uncertainties: list[DecompositionUncertainty] = []
    for item in items:
        out = _split_line(
            item, drug_catalog, service_catalog, material_catalog, hospital_code, rounding_mode
        )
        lines.append(out.line)
        branches.extend(out.branches)
        calcs.extend(out.calculations)
        uncertainties.extend(out.uncertainties)

    complete = all(ln.status == BranchOutcome.TRUE for ln in lines)
    return CatalogSplitResult(
        lines=tuple(lines),
        branches=tuple(branches),
        calculations=tuple(calcs),
        uncertainties=tuple(uncertainties),
        total_fee=sum((ln.fee for ln in lines), Decimal("0")),
        total_in_scope=sum((ln.in_scope for ln in lines), Decimal("0")) if complete else None,
        total_out_scope=sum((ln.out_scope for ln in lines), Decimal("0")) if complete else None,
        total_self_pay_2=sum((ln.self_pay_2 or Decimal("0") for ln in lines), Decimal("0")) if complete else None,
        is_complete=complete,
    )


def _split_line(
    item: FeeLineItem,
    drug_catalog: tuple[DrugCatalogEntry, ...],
    service_catalog: tuple[ServiceCatalogEntry, ...],
    material_catalog: tuple[MaterialCatalogEntry, ...],
    hospital_code: str,
    rounding_mode: RoundingMode,
) -> _LineOut:
    scope = f"item:{item.line_key}"
    fee_check = _fee_quantity_check(item, scope)
    if item.catalog_kind == CatalogKind.DRUG or item.item_type == "0":
        out = _split_drug(item, drug_catalog, hospital_code, rounding_mode, scope)
    elif item.catalog_kind == CatalogKind.SERVICE:
        out = _split_service(item, service_catalog, rounding_mode, scope)
    elif item.catalog_kind == CatalogKind.MATERIAL:
        out = _split_material(item, material_catalog, rounding_mode, scope)
    else:
        out = _LineOut(
            line=LineDecomposition(item.line_key, item.fee, BranchOutcome.UNKNOWN),
            branches=(
                _branch(
                    f"catalog.classify.{item.line_key}",
                    BranchOutcome.UNKNOWN,
                    scope,
                    BranchCondition("catalog_kind", "明细目录类别", "in", item.catalog_kind.value, "drug/service/material"),
                    "CATALOG_KIND_UNKNOWN",
                ),
            ),
        )
    if fee_check is not None:
        out = _LineOut(out.line, out.branches + (fee_check,), out.calculations, out.uncertainties)
    return out


def _fee_quantity_check(item: FeeLineItem, scope: str) -> BranchTrace | None:
    """Fee 与 UnitPrice×Count 分开校验（设计 §7.2：源端可能有折扣/换算/取整，不互相替代）。"""
    if item.unit_price is None or item.count is None:
        return None
    product = item.unit_price * item.count
    consistent = product == item.fee
    return _branch(
        f"catalog.fee_quantity_check.{item.line_key}",
        BranchOutcome.TRUE if consistent else BranchOutcome.FALSE,
        scope,
        BranchCondition(
            "fee_equals_unit_price_times_count",
            "账面费用与单价×数量一致性",
            "eq",
            decimal_to_str(item.fee),
            decimal_to_str(product),
        ),
        None if consistent else "FEE_QUANTITY_MISMATCH",
        input_refs=(f"fact.item.{item.line_key}.fee", f"fact.item.{item.line_key}.unit_price_count"),
    )


def _match_catalog(entries, item_code: str, on_date):
    """按编码+费用发生日期匹配目录。空结束日期不默认永久有效（设计 §5.3）。

    返回 (matches, validity_unknown_exists)。
    """
    code_hits = [e for e in entries if e.item_code == item_code]
    matches = []
    validity_unknown = False
    for e in code_hits:
        if e.effective_date is not None and e.effective_date > on_date:
            continue  # 尚未生效
        if e.expiry_date is None:
            # 空结束日期：不默认永久有效 → 效力未知
            validity_unknown = True
            continue
        if on_date > e.expiry_date:
            continue  # 已失效
        matches.append(e)
    return matches, validity_unknown


def _match_branch(step_suffix: str, scope: str, n: int, validity_unknown: bool, kind_label: str) -> BranchTrace:
    if n == 1 and not validity_unknown:
        return _branch(f"catalog.match.{step_suffix}", BranchOutcome.TRUE, scope,
                       BranchCondition("catalog_match", f"{kind_label}目录匹配", "count_eq", "1", "有效目录条目"))
    if validity_unknown:
        # 空截止日期不默认永久有效（设计 §5.3）：即使另有确定命中，空截止条目也可能同样适用，
        # 潜在多命中不得按唯一命中放行
        return _branch(f"catalog.match.{step_suffix}", BranchOutcome.UNKNOWN, scope,
                       BranchCondition("catalog_match", f"{kind_label}目录匹配", "count_eq", str(n), "有效目录条目"),
                       "CATALOG_VALIDITY_UNKNOWN")
    if n == 0:
        return _branch(f"catalog.match.{step_suffix}", BranchOutcome.FALSE, scope,
                       BranchCondition("catalog_match", f"{kind_label}目录匹配", "count_eq", "0", "有效目录条目"),
                       "MISSING_CATALOG")
    return _branch(f"catalog.match.{step_suffix}", BranchOutcome.UNKNOWN, scope,
                   BranchCondition("catalog_match", f"{kind_label}目录匹配", "count_eq", str(n), "有效目录条目"),
                   "AMBIGUOUS_CATALOG")


def _classify_ratio(
    item: FeeLineItem, entry_sflb: str | None, entry_ratio, scope: str, parent: str
) -> tuple[str | None, Decimal | None, tuple[BranchTrace, ...]]:
    """解析收费类别与自付比例。sflb 与账面 FeeType 分组冲突时停在未知（设计 §7.2）。

    冲突判定在自付档分组层面（决策记录 D2）：sflb 与 FeeType 均为字典 230 收费类别码，
    同组不同码（如目录未维护明细码）不视为冲突；分组不同才停未知。
    返回 (分类 one of none/partial/full, 自付比例, 分支轨迹)。
    """
    branches: list[BranchTrace] = []
    sflb_group = _fee_category_group(entry_sflb)
    fee_type_group = _fee_category_group(item.fee_type)
    if (
        entry_sflb is not None and item.fee_type is not None
        and sflb_group is not None and fee_type_group is not None
        and sflb_group != fee_type_group
    ):
        branches.append(_branch(
            f"{parent}.class_conflict", BranchOutcome.UNKNOWN, scope,
            BranchCondition("sflb_vs_fee_type", "目录类别与账面收费类别一致性（自付档分组）", "eq",
                            f"{entry_sflb}({sflb_group})", f"{item.fee_type}({fee_type_group})"),
            "CLASSIFICATION_CONFLICT",
            input_refs=(f"fact.item.{item.line_key}.fee_type",),
        ))
        return None, None, tuple(branches)
    cls = sflb_group if sflb_group is not None else fee_type_group
    if cls is not None and cls != "unknown":
        if cls == "partial":
            if entry_ratio is None:
                branches.append(_branch(
                    f"{parent}.self_pay_ratio", BranchOutcome.UNKNOWN, scope,
                    BranchCondition("self_pay_ratio", "先行自付比例存在性", "not_null", None, "目录自付比例"),
                    "SELF_PAY_RATIO_MISSING",
                ))
                return None, None, tuple(branches)
            return "partial", entry_ratio, tuple(branches)
        return cls, None, tuple(branches)
    raw = entry_sflb if entry_sflb is not None else item.fee_type
    branches.append(_branch(
        f"{parent}.class", BranchOutcome.UNKNOWN, scope,
        BranchCondition("sflb", "目录收费类别取值", "in", raw, "无自付/有自付/全自付 或字典230甲/乙/其它类码"),
        "CLASSIFICATION_UNKNOWN" if raw is not None else "CLASSIFICATION_EMPTY",
    ))
    return None, None, tuple(branches)


def _apply_division(
    item: FeeLineItem, cls: str, ratio: Decimal | None, rounding_mode: RoundingMode, scope: str
) -> tuple[LineDecomposition, tuple[CalculationRecord, ...]]:
    """按类别分解金额：无自付全额医保内；全自付全额自费；
    有自付按比例先行自付——账面口径实证（决策记录 D14）：先行自付不进报销基数
    （FeeIn=Fee-先行自付），且先行自付计入医保外（FeeOut 含先行自付），
    自付二为医保外内的可追踪子项。
    """
    if cls == "none":
        return LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                 in_scope=item.fee, out_scope=Decimal("0")), ()
    if cls == "full":
        return LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                 in_scope=Decimal("0"), out_scope=item.fee), ()
    assert cls == "partial" and ratio is not None
    unrounded = item.fee * ratio
    sp2 = apply_rounding(unrounded, rounding_mode)
    calc = _calc(
        f"calc.catalog.self_pay_2.{item.line_key}", "catalog_self_pay_2_v1",
        (CalculationOperand(f"fact.item.{item.line_key}.fee", decimal_to_str(item.fee)),
         CalculationOperand("fact.catalog.self_pay_ratio", decimal_to_str(ratio))),
        unrounded, sp2, rounding_mode,
    )
    return LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                             in_scope=item.fee - sp2, out_scope=sp2,
                             self_pay_2=sp2, labels=("partial_self_pay",)), (calc,)


def _applied_ratio(item: FeeLineItem, catalog_ratio: Decimal | None) -> Decimal | None:
    """实际先行自付比例：明细行 MEDIC_L>0 时为结算事实优先（决策记录 D18，55/55 行吻合），
    否则回落目录 zfbl。两者皆无返回 None。"""
    if item.medic_l is not None and item.medic_l > 0:
        return item.medic_l
    return catalog_ratio


def _split_drug(
    item: FeeLineItem,
    catalog: tuple[DrugCatalogEntry, ...],
    hospital_code: str,
    rounding_mode: RoundingMode,
    scope: str,
) -> _LineOut:
    branches: list[BranchTrace] = []
    matches, validity_unknown = _match_catalog(catalog, item.item_code, item.fee_occurrence_date)
    branches.append(_match_branch(item.line_key, scope, len(matches), validity_unknown, "药品"))
    if len(matches) != 1 or validity_unknown:
        reason = ("CATALOG_VALIDITY_UNKNOWN" if validity_unknown
                  else "MISSING_CATALOG" if not matches else "AMBIGUOUS_CATALOG")
        return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.UNKNOWN),
                        tuple(branches),
                        uncertainties=(DecompositionUncertainty(
                            id=f"u.catalog.drug.{item.line_key}", code=reason,
                            message=f"药品目录匹配结果不可唯一确定（{reason}），不取首条、不重复展开费用。",
                            affected_fields=("T_FeeIn", "T_FeeOut", "T_SelfPay2")),))
    entry = matches[0]

    # 先定自付档（决策记录 D20）：全自付行整行个人承担，自制剂/集采分支不影响结果，不再评估
    ratio = _applied_ratio(item, entry.self_pay_ratio)
    cls, resolved_ratio, cls_branches = _classify_ratio(
        item, entry.sflb, ratio, scope, f"catalog.drug_class.{item.line_key}")
    branches.extend(cls_branches)
    if cls is None:
        reason = cls_branches[-1].reason_code or "CLASSIFICATION_UNKNOWN"
        return _unknown_line(item, branches, reason, "药品目录收费类别不能确定，停未知。")
    if cls == "full":
        branches.append(_branch(
            f"catalog.drug_full_self_pay.{item.line_key}", BranchOutcome.TRUE, scope,
            BranchCondition("full_self_pay", "全自付行自制剂/集采分支不评估", "eq", "full", "out=fee"),
            rule_refs=("EOP-CAT-001",)))
        line, calcs = _apply_division(item, cls, None, rounding_mode, scope)
        return _LineOut(line, tuple(branches), calcs, rule_uncertainties(entry))

    # 自制剂候选规则（ypfl∈{16,6}）：本院使用 + 单价≤标准价格方可纳入（EOP-CAT-002/003）
    is_preparation = entry.ypfl in _HOSPITAL_PREPARATION_YPFL
    if is_preparation and entry.a_ypbs:
        branches.append(_branch(
            f"catalog.preparation_ncp_overlap.{item.line_key}", BranchOutcome.UNKNOWN, scope,
            BranchCondition("ypfl_and_a_ypbs", "自制剂与集采规则重叠", "and", f"ypfl={entry.ypfl},a_ypbs=1", "互斥"),
            "PREPARATION_NCP_OVERLAP_UNCONFIRMED",
            rule_refs=("EOP-CAT-002", "EOP-NCP-001"),
        ))
        return _unknown_line(item, branches, "PREPARATION_NCP_OVERLAP_UNCONFIRMED",
                             "自制剂与集采规则重叠的优先次序未确认，停未知。")
    if is_preparation:
        if entry.preparation_hospital_code is None:
            branches.append(_branch(
                f"catalog.preparation_hospital.{item.line_key}", BranchOutcome.UNKNOWN, scope,
                BranchCondition("preparation_hospital", "自制剂所属机构对应关系", "eq", None, hospital_code),
                "PREPARATION_HOSPITAL_UNKNOWN", rule_refs=("EOP-CAT-002",)))
            return _unknown_line(item, branches, "PREPARATION_HOSPITAL_UNKNOWN",
                                 "缺少自制剂所属机构对应关系，不能判定本院使用。")
        if entry.preparation_hospital_code != hospital_code:
            branches.append(_branch(
                f"catalog.preparation_hospital.{item.line_key}", BranchOutcome.FALSE, scope,
                BranchCondition("preparation_hospital", "自制剂所属机构对应关系", "eq",
                                entry.preparation_hospital_code, hospital_code),
                None, rule_refs=("EOP-CAT-002",)))
            return _LineOut(
                LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                  in_scope=Decimal("0"), out_scope=item.fee,
                                  labels=("hospital_preparation_out_of_scope",)),
                tuple(branches))
        branches.append(_branch(
            f"catalog.preparation_hospital.{item.line_key}", BranchOutcome.TRUE, scope,
            BranchCondition("preparation_hospital", "自制剂所属机构对应关系", "eq",
                            entry.preparation_hospital_code, hospital_code),
            rule_refs=("EOP-CAT-002",)))
        # 价格限制：单价 ≤bzjg 方可纳入；>bzjg 整项自费（EOP-CAT-003）
        if entry.bzjg is None or item.unit_price is None:
            branches.append(_branch(
                f"catalog.preparation_price.{item.line_key}", BranchOutcome.UNKNOWN, scope,
                BranchCondition("unit_price_le_bzjg", "自制剂单价≤标准价格", "le",
                                decimal_to_str(item.unit_price) if item.unit_price is not None else None,
                                decimal_to_str(entry.bzjg) if entry.bzjg is not None else None),
                "PREPARATION_PRICE_UNKNOWN", rule_refs=("EOP-CAT-003",)))
            return _unknown_line(item, branches, "PREPARATION_PRICE_UNKNOWN",
                                 "自制剂单价或标准价格缺失，不能判定价格限制分支。")
        if item.unit_price > entry.bzjg:
            branches.append(_branch(
                f"catalog.preparation_price.{item.line_key}", BranchOutcome.FALSE, scope,
                BranchCondition("unit_price_le_bzjg", "自制剂单价≤标准价格", "le",
                                decimal_to_str(item.unit_price), decimal_to_str(entry.bzjg)),
                None, rule_refs=("EOP-CAT-003",)))
            return _LineOut(
                LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                  in_scope=Decimal("0"), out_scope=item.fee,
                                  labels=("preparation_over_price",)),
                tuple(branches))
        branches.append(_branch(
            f"catalog.preparation_price.{item.line_key}", BranchOutcome.TRUE, scope,
            BranchCondition("unit_price_le_bzjg", "自制剂单价≤标准价格", "le",
                            decimal_to_str(item.unit_price), decimal_to_str(entry.bzjg)),
            rule_refs=("EOP-CAT-003",)))

    # 集采（a_ypbs=1）：限价内按自付档；超限价按超限价自付比例 a_xbbl 最终比例语义
    # （决策记录 D19：实证 2 行 sp2=fee×a_xbbl，与 docx「原自付+上浮 10%」最终比例一致）
    if entry.a_ypbs:
        ncp = _ncp_price_check(item, entry, scope)
        branches.extend(ncp[1])
        if ncp[0] != "within_limit":
            if ncp[0] == "NCP_LIMIT_MISSING":
                return _unknown_line(item, branches, ncp[0], ncp[2])
            if item.consistency_evaluation_passed is False:
                return _unknown_line(item, branches, ncp[0], ncp[2])
            # 超限价：实际比例 = 明细行 MEDIC_L>0 优先，否则目录 a_xbbl
            excess_ratio = _applied_ratio(item, entry.a_xbbl)
            if excess_ratio is None:
                return _unknown_line(item, branches, "NCP_EXCESS_RATIO_SEMANTICS_UNCONFIRMED", ncp[2])
            unrounded = item.fee * excess_ratio
            sp2 = apply_rounding(unrounded, rounding_mode)
            calc = _calc(
                f"calc.catalog.ncp_excess.{item.line_key}", "ncp_excess_final_ratio_v1",
                (CalculationOperand(f"fact.item.{item.line_key}.fee", decimal_to_str(item.fee)),
                 CalculationOperand("fact.line_or_catalog.excess_ratio", decimal_to_str(excess_ratio))),
                unrounded, sp2, rounding_mode)
            branches.append(_branch(
                f"catalog.ncp_excess.{item.line_key}", BranchOutcome.TRUE, scope,
                BranchCondition("ncp_excess_final_ratio", "集采超限价按最终自付比例", "formula",
                                decimal_to_str(sp2), None),
                rule_refs=("EOP-NCP-001", "EOP-NCP-002"),
                calculation_refs=(calc.calculation_id,)))
            ncp_uncertainty = DecompositionUncertainty(
                id=f"u.catalog.ncp_excess_candidate.{item.line_key}",
                code="NCP_EXCESS_RULE_CANDIDATE",
                message="集采超限价按最终自付比例（a_xbbl/MEDIC_L）划分属实证候选口径（n=2，决策记录 D19），待签核。",
                affected_fields=("T_FeeIn", "T_FeeOut", "T_SelfPay2"))
            return _LineOut(
                LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                  in_scope=item.fee - sp2, out_scope=sp2,
                                  self_pay_2=sp2,
                                  labels=("centralized_procurement", "ncp_over_limit")),
                tuple(branches), (calc,), (ncp_uncertainty,))

    # 非集采门诊限价（决策记录 D17）：行 SP_SCALE>0 优先（结算事实），否则目录 A_mzxj>0；
    # 单价超限价：超限价部分全额个人承担，限内部分按自付档划分
    if not entry.a_ypbs:
        limit = item.sp_scale if (item.sp_scale is not None and item.sp_scale > 0) else entry.a_mzxj
        if (
            limit is not None and limit > 0
            and item.unit_price is not None and item.unit_price > limit
        ):
            if cls == "partial" and resolved_ratio is None:
                return _unknown_line(item, branches, "SELF_PAY_RATIO_MISSING",
                                     "限价内部分自付比例缺失，停未知。")
            within = limit * (item.count if item.count is not None else Decimal("1"))
            if cls == "partial":
                assert resolved_ratio is not None
                in_scope = apply_rounding(within * (1 - resolved_ratio), rounding_mode)
            else:  # none：限内全额纳入
                in_scope = within
            sp2 = item.fee - in_scope
            calc = _calc(
                f"calc.catalog.price_limit.{item.line_key}", "drug_unit_price_limit_v1",
                (CalculationOperand(f"fact.item.{item.line_key}.fee", decimal_to_str(item.fee)),
                 CalculationOperand("fact.line_or_catalog.unit_price_limit", decimal_to_str(limit)),
                 CalculationOperand("fact.line_or_catalog.self_pay_ratio",
                                    decimal_to_str(resolved_ratio) if resolved_ratio is not None else "0")),
                in_scope, in_scope, rounding_mode)
            branches.append(_branch(
                f"catalog.price_limit.{item.line_key}", BranchOutcome.TRUE, scope,
                BranchCondition("unit_price_over_limit", "单价超门诊限价：限内按比例、超限全自担", "formula",
                                decimal_to_str(in_scope),
                                f"limit={decimal_to_str(limit)}"),
                calculation_refs=(calc.calculation_id,)))
            limit_uncertainty = DecompositionUncertainty(
                id=f"u.catalog.price_limit_candidate.{item.line_key}",
                code="DRUG_PRICE_LIMIT_RULE_CANDIDATE",
                message="非集采门诊限价分解（限内按比例、超限全自担）属实证候选口径（n=1，决策记录 D17），待签核。",
                affected_fields=("T_FeeIn", "T_FeeOut", "T_SelfPay2"))
            return _LineOut(
                LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                  in_scope=in_scope, out_scope=sp2, self_pay_2=sp2,
                                  labels=("unit_price_limit",)),
                tuple(branches), (calc,), (limit_uncertainty,))

    line, calcs = _apply_division(item, cls, resolved_ratio, rounding_mode, scope)
    if entry.a_ypbs:
        line = LineDecomposition(line.line_key, line.fee, line.status, line.in_scope,
                                 line.out_scope, line.self_pay_2, line.labels + ("centralized_procurement",))
    return _LineOut(line, tuple(branches), calcs,
                    rule_uncertainties(entry))


def _ncp_price_check(item: FeeLineItem, entry: DrugCatalogEntry, scope: str):
    """集采限价比较：整包→包装单位限价，拆包→制剂单位限价，未给包装类型默认整包。

    返回 (status, branches, message)。status: within_limit / 各 unknown 原因码。
    """
    branches: list[BranchTrace] = []
    packaging = item.packaging_type or PackagingType.WHOLE_PACK
    limit = entry.a_mzxj if packaging == PackagingType.WHOLE_PACK else entry.ncp_unit_limit
    if limit is None or item.unit_price is None:
        branches.append(_branch(
            f"catalog.ncp_price.{item.line_key}", BranchOutcome.UNKNOWN, scope,
            BranchCondition("ncp_price_le_limit", "集采单价≤门诊限价", "le", None, None),
            "NCP_LIMIT_MISSING", rule_refs=("EOP-NCP-001", "EOP-NCP-002")))
        return ("NCP_LIMIT_MISSING", tuple(branches), "集采限价或单价缺失，无法比价。")
    within = item.unit_price <= limit
    branches.append(_branch(
        f"catalog.ncp_price.{item.line_key}",
        BranchOutcome.TRUE if within else BranchOutcome.FALSE, scope,
        BranchCondition("ncp_price_le_limit", "集采单价≤门诊限价", "le",
                        decimal_to_str(item.unit_price), decimal_to_str(limit)),
        rule_refs=("EOP-NCP-001", "EOP-NCP-002"),
        input_refs=(f"fact.item.{item.line_key}.unit_price", f"fact.catalog.{entry.entry_id}.ncp_limit"),
    ))
    if within:
        return ("within_limit", tuple(branches), "")
    # 超限价：未通过一致性评价分支（EOP-NCP-002）生效日期未明确 → unknown；
    # 其他药品超限价自付比例 a_xbbl 语义（增量/最终、作用基数）未确认 → 不编码公式
    if item.consistency_evaluation_passed is False:
        return ("NCP_UNAPPRAISED_RULE_UNCONFIRMED", tuple(branches),
                "未通过一致性评价集采药品的超限价分解规则（EOP-NCP-002）生效日期未明确，输出 unknown。")
    return ("NCP_EXCESS_RATIO_SEMANTICS_UNCONFIRMED", tuple(branches),
            "超限价自付比例 a_xbbl 语义（增量/最终比例、作用基数）未确认，不编码公式，输出 unknown。")


def _split_service(
    item: FeeLineItem,
    catalog: tuple[ServiceCatalogEntry, ...],
    rounding_mode: RoundingMode,
    scope: str,
) -> _LineOut:
    branches: list[BranchTrace] = []
    matches, validity_unknown = _match_catalog(catalog, item.item_code, item.fee_occurrence_date)
    branches.append(_match_branch(item.line_key, scope, len(matches), validity_unknown, "诊疗/服务设施"))
    if len(matches) != 1 or validity_unknown:
        reason = ("CATALOG_VALIDITY_UNKNOWN" if validity_unknown
                  else "MISSING_CATALOG" if not matches else "AMBIGUOUS_CATALOG")
        return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.UNKNOWN),
                        tuple(branches),
                        uncertainties=(DecompositionUncertainty(
                            id=f"u.catalog.service.{item.line_key}", code=reason,
                            message=f"诊疗/服务设施目录匹配结果不可唯一确定（{reason}）。",
                            affected_fields=("T_FeeIn", "T_FeeOut", "T_SelfPay2")),))
    entry = matches[0]

    # 门诊检查费单价限额（EOP-CAT-008）：生效日期未明确且待官方核证 → unknown，不静默生效
    if item.is_check_fee:
        sel = select_check_fee_param(item.fee_occurrence_date)
        branches.append(_branch(
            f"catalog.check_fee_param.{item.line_key}", sel.outcome, scope,
            BranchCondition("check_fee_rule", "门诊检查费单价限额规则适用性", "select", None, "EOP-CAT-008"),
            sel.reason_code, rule_refs=("EOP-CAT-008",)))
        if sel.outcome != BranchOutcome.TRUE:
            return _unknown_line(item, branches, sel.reason_code or "PARAM_NOT_CONFIRMED",
                                 "门诊检查费单价限额规则（EOP-CAT-008）确认状态不足，不静默生效。")

    sfx = entry.sfxmdj
    if sfx is None:
        # S1 的「空无自付（猜测）」不得进入正式算法
        branches.append(_branch(
            f"catalog.service_class.{item.line_key}", BranchOutcome.UNKNOWN, scope,
            BranchCondition("sfxmdj", "收费项目等级", "in", None, "1/2/3"),
            "SFXMDJ_EMPTY", rule_refs=("EOP-CAT-007",)))
        return _unknown_line(item, branches, "SFXMDJ_EMPTY", "sfxmdj 为空必须返回未知，禁止猜测为无自付。")
    if sfx == "1":
        return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                          in_scope=item.fee, out_scope=Decimal("0")),
                        tuple(branches) + (_branch(
                            f"catalog.service_class.{item.line_key}", BranchOutcome.TRUE, scope,
                            BranchCondition("sfxmdj", "收费项目等级", "eq", "1", "1 无自付"),
                            rule_refs=("EOP-CAT-007",)),))
    if sfx == "3":
        return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                          in_scope=Decimal("0"), out_scope=item.fee),
                        tuple(branches) + (_branch(
                            f"catalog.service_class.{item.line_key}", BranchOutcome.TRUE, scope,
                            BranchCondition("sfxmdj", "收费项目等级", "eq", "3", "3 全自付"),
                            rule_refs=("EOP-CAT-007",)),))
    if sfx == "2":
        branches.append(_branch(
            f"catalog.service_class.{item.line_key}", BranchOutcome.TRUE, scope,
            BranchCondition("sfxmdj", "收费项目等级", "eq", "2", "2 有自付"),
            rule_refs=("EOP-CAT-007",)))
        if entry.self_pay_ratio is not None:
            svc_ratio = _applied_ratio(item, entry.self_pay_ratio)
            unrounded = item.fee * svc_ratio
            sp2 = apply_rounding(unrounded, rounding_mode)
            calc = _calc(
                f"calc.catalog.self_pay_2.{item.line_key}", "catalog_self_pay_2_v1",
                (CalculationOperand(f"fact.item.{item.line_key}.fee", decimal_to_str(item.fee)),
                 CalculationOperand("fact.line_or_catalog.self_pay_ratio", decimal_to_str(svc_ratio))),
                unrounded, sp2, rounding_mode)
            # 账面口径实证（决策记录 D14）：先行自付不进报销基数且计入医保外
            return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                              in_scope=item.fee - sp2, out_scope=sp2,
                                              self_pay_2=sp2, labels=("partial_self_pay",)),
                            tuple(branches), (calc,))
        if entry.unit_price_limit is not None and item.unit_price is not None and item.count is not None:
            # 按单价限额：超出限额部分划入个人自付二（不进报销基数，计入医保外，决策记录 D14）
            excess = max(item.unit_price - entry.unit_price_limit, Decimal("0")) * item.count
            sp2 = apply_rounding(excess, rounding_mode)
            calc = _calc(
                f"calc.catalog.price_limit.{item.line_key}", "catalog_unit_price_limit_v1",
                (CalculationOperand(f"fact.item.{item.line_key}.unit_price", decimal_to_str(item.unit_price)),
                 CalculationOperand("fact.catalog.unit_price_limit", decimal_to_str(entry.unit_price_limit)),
                 CalculationOperand(f"fact.item.{item.line_key}.count", decimal_to_str(item.count))),
                excess, sp2, rounding_mode)
            return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                              in_scope=item.fee - sp2, out_scope=sp2,
                                              self_pay_2=sp2, labels=("unit_price_limit",)),
                            tuple(branches), (calc,))
        branches.append(_branch(
            f"catalog.service_ratio.{item.line_key}", BranchOutcome.UNKNOWN, scope,
            BranchCondition("self_pay_ratio_or_limit", "自付比例或单价限额存在性", "not_null", None, "自付比例/单价限额"),
            "SELF_PAY_RULE_PARAM_MISSING"))
        return _unknown_line(item, branches, "SELF_PAY_RULE_PARAM_MISSING",
                             "有自付项目缺少实际自付比例或单价限额，停未知。")
    branches.append(_branch(
        f"catalog.service_class.{item.line_key}", BranchOutcome.UNKNOWN, scope,
        BranchCondition("sfxmdj", "收费项目等级", "in", sfx, "1/2/3"),
        "SFXMDJ_UNKNOWN_VALUE"))
    return _unknown_line(item, branches, "SFXMDJ_UNKNOWN_VALUE", f"sfxmdj={sfx} 为未确认取值，停未知。")


def _split_material(
    item: FeeLineItem,
    catalog: tuple[MaterialCatalogEntry, ...],
    rounding_mode: RoundingMode,
    scope: str,
) -> _LineOut:
    branches: list[BranchTrace] = []
    matches, validity_unknown = _match_catalog(catalog, item.item_code, item.fee_occurrence_date)
    branches.append(_match_branch(item.line_key, scope, len(matches), validity_unknown, "医用材料"))
    if len(matches) != 1 or validity_unknown:
        reason = ("CATALOG_VALIDITY_UNKNOWN" if validity_unknown
                  else "MISSING_CATALOG" if not matches else "AMBIGUOUS_CATALOG")
        return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.UNKNOWN),
                        tuple(branches),
                        uncertainties=(DecompositionUncertainty(
                            id=f"u.catalog.material.{item.line_key}", code=reason,
                            message=f"医用材料目录匹配结果不可唯一确定（{reason}）。",
                            affected_fields=("T_FeeIn", "T_FeeOut", "T_SelfPay2")),))
    entry = matches[0]

    # 人工器官/集采中选例外：政策参数未在参数表覆盖 → unknown（EOP-MAT-005）
    if entry.is_artificial_organ or entry.is_centralized_selected:
        branches.append(_branch(
            f"catalog.material_exception.{item.line_key}", BranchOutcome.UNKNOWN, scope,
            BranchCondition("material_exception", "人工器官/集采中选例外", "or",
                            f"artificial={entry.is_artificial_organ},ncp_selected={entry.is_centralized_selected}",
                            "普通材料"),
            "MATERIAL_EXCEPTION_POLICY_NOT_COVERED", rule_refs=("EOP-MAT-005",)))
        return _unknown_line(item, branches, "MATERIAL_EXCEPTION_POLICY_NOT_COVERED",
                             "人工器官/集采中选材料例外政策参数未覆盖，输出 unknown。")

    if item.unit_price is None:
        branches.append(_branch(
            f"catalog.material_price.{item.line_key}", BranchOutcome.UNKNOWN, scope,
            BranchCondition("unit_price", "材料单价存在性", "not_null", None, "单价"),
            "UNIT_PRICE_MISSING"))
        return _unknown_line(item, branches, "UNIT_PRICE_MISSING", "材料单价缺失，无法适用单价门槛规则。")

    sel = select_material_rule(item.fee_occurrence_date)
    branches.append(_branch(
        f"catalog.material_rule.{item.line_key}", sel.outcome, scope,
        BranchCondition("material_rule_version", "材料门槛规则版本选择", "select",
                        str(item.fee_occurrence_date), "EOP-MAT-001/002/003/004"),
        sel.reason_code,
        rule_refs=(("EOP-MAT-003", "EOP-MAT-004") if item.fee_occurrence_date >= date(2023, 1, 1)
                   else (sel.param.rule_id,) if sel.param else ())))
    if sel.outcome != BranchOutcome.TRUE:
        return _unknown_line(item, branches, sel.reason_code or "PARAM_VERSION_NOT_FOUND",
                             "材料门槛规则版本不可确定，输出 unknown。")

    fee_date = item.fee_occurrence_date
    if fee_date >= date(2023, 1, 1):
        threshold = get_param("EOP-MAT-003").value  # 1000
        included_ratio = get_param("EOP-MAT-004").ratio  # 0.80
    elif fee_date >= date(2008, 7, 1):
        threshold = Decimal("500")
        included_ratio = Decimal("0.70")  # EOP-MAT-002
    else:
        threshold = Decimal("500")
        included_ratio = Decimal("0.50")  # EOP-MAT-001
    assert threshold is not None and included_ratio is not None

    if item.unit_price < threshold:
        return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                          in_scope=item.fee, out_scope=Decimal("0")),
                        tuple(branches) + (_branch(
                            f"catalog.material_threshold.{item.line_key}", BranchOutcome.TRUE, scope,
                            BranchCondition("unit_price_lt_threshold", "材料单价低于纳入门槛", "lt",
                                            decimal_to_str(item.unit_price), decimal_to_str(threshold))),))
    # ≥门槛：按纳入比例纳入医保支付范围，其余为先行自付——账面口径实证（决策记录 D14）：
    # 未纳入部分不进报销基数（FeeIn=Fee×纳入比例）且计入医保外（FeeOut 含先行自付）
    unrounded_in = item.fee * included_ratio
    in_scope = apply_rounding(unrounded_in, rounding_mode)
    sp2 = item.fee - in_scope
    calc = _calc(
        f"calc.catalog.material_included.{item.line_key}", "material_included_ratio_v1",
        (CalculationOperand(f"fact.item.{item.line_key}.fee", decimal_to_str(item.fee)),
         CalculationOperand("rule.material.included_ratio", decimal_to_str(included_ratio))),
        unrounded_in, in_scope, rounding_mode)
    branches.append(_branch(
        f"catalog.material_threshold.{item.line_key}", BranchOutcome.FALSE, scope,
        BranchCondition("unit_price_lt_threshold", "材料单价低于纳入门槛", "lt",
                        decimal_to_str(item.unit_price), decimal_to_str(threshold)),
        calculation_refs=(calc.calculation_id,)))
    return _LineOut(LineDecomposition(item.line_key, item.fee, BranchOutcome.TRUE,
                                      in_scope=in_scope, out_scope=sp2,
                                      self_pay_2=sp2, labels=("material_threshold",)),
                    tuple(branches), (calc,))


def _unknown_line(item: FeeLineItem, branches: list[BranchTrace], reason: str, message: str) -> _LineOut:
    return _LineOut(
        LineDecomposition(item.line_key, item.fee, BranchOutcome.UNKNOWN),
        tuple(branches),
        uncertainties=(DecompositionUncertainty(
            id=f"u.catalog.{item.line_key}", code=reason, message=message,
            affected_fields=("T_FeeIn", "T_FeeOut", "T_SelfPay2")),))


def rule_uncertainties(entry: DrugCatalogEntry) -> tuple[DecompositionUncertainty, ...]:
    """结构性划分语义引用自待官方核证的目录规则，显式声明（不使用即补全）。"""
    return (DecompositionUncertainty(
        id=f"u.catalog.rule_confirmation.{entry.entry_id}",
        code="CATALOG_RULE_PENDING_OFFICIAL_CONFIRMATION",
        message="目录划分语义引用 EOP-CAT 系列规则（文档明确-待官方核证），计算结果不升级为已确认政策解释。",
        affected_fields=("T_FeeIn", "T_FeeOut")),)
