"""费用行展示侧车：保留已执行的分解，金额结果不因展示改变。"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Literal, Mapping
from pydantic import BaseModel, ConfigDict, Field
from src.domain.insurance.fee_decomposition import BranchOutcome, FeeLineItem, decimal_to_str
from src.runtime.policy_qa.fee_decomposition.formula_display import rounding_display

if TYPE_CHECKING:
    from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult


class FeeItemDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    label: str
    operator: str
    actual: str | None = None
    expected: str | None = None
    outcome: str
    rule_refs: list[str] = Field(default_factory=list)
    calculation_refs: list[str] = Field(default_factory=list)


class FeeItemReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    observed: str | None = None
    calculated: str | None = None
    difference: str | None = None
    check_status: Literal["matched", "mismatched", "not_verifiable"]


class FeeItemExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_id: str
    item_code: str = ""
    item_name: str = ""
    item_type: str | None = None
    fee_date: str | None = None
    unit_price: str | None = None
    quantity: str | None = None
    total_fee: str | None = None
    observed_in_scope: str | None = None
    observed_out_scope: str | None = None
    observed_self_pay_2: str | None = None
    calculated_in_scope: str | None = None
    calculated_out_scope: str | None = None
    calculated_self_pay_2: str | None = None
    calculated_proportional_self_pay: str | None = None
    status: Literal["calculated", "observed_only", "unknown"] = "observed_only"
    verification_status: Literal["verified", "unverified"] = "unverified"
    division_method: Literal["ratio", "limit", "full_in", "full_out", "settlement_override", "unknown"] = "unknown"
    self_pay_ratio: str | None = None
    included_ratio: str | None = None
    unit_price_limit: str | None = None
    conditions: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    classification_code: str | None = None
    classification_label: str | None = None
    classification_source: str | None = None
    centralized_procurement: bool | None = None
    catalog_entry_id: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    ratio_source: str | None = None
    ratio_basis: str | None = None
    limit_source: str | None = None
    decision_path: list[FeeItemDecision] = Field(default_factory=list)
    calculation_refs: list[str] = Field(default_factory=list)
    reconciliations: list[FeeItemReconciliation] = Field(default_factory=list)
    explainable: bool = False
    explanation_reason: str | None = None
    # ── 逐行目录事实（仅当对应条件实际影响本行比例/限价时才需要展示） ──
    # 集采标识（A_ypbs）/门诊限价（A_mzxj）/住院限价（A_zyxj，本流程不使用）/
    # 超限价自付比例（A_xbbl）/药品分类（ypfl）/自制剂标准价格（bzjg）/
    # 明细行结算时限价（SP_SCALE）；原值透传，缺失 None。
    a_ypbs: str | None = Field(default=None, exclude_if=lambda value: value is None)
    a_mzxj: str | None = Field(default=None, exclude_if=lambda value: value is None)
    a_zyxj: str | None = Field(default=None, exclude_if=lambda value: value is None)
    a_xbbl: str | None = Field(default=None, exclude_if=lambda value: value is None)
    ypfl: str | None = Field(default=None, exclude_if=lambda value: value is None)
    bzjg: str | None = Field(default=None, exclude_if=lambda value: value is None)
    settlement_price_limit: str | None = Field(default=None, exclude_if=lambda value: value is None)
    # 本行中文解释：逐字取自本行已执行的公式与来源说明，不另造词。
    explanation: str | None = Field(default=None, exclude_if=lambda value: value is None)


def catalog_item_explanation(item: FeeLineItem, line: Any, branches: tuple, calculations: tuple,
                             entry: Any | None) -> FeeItemExplanation:
    """只格式化本行的输入/输出，不从账面目标反推比例。"""
    def money(value):
        return decimal_to_str(value) if value is not None else None
    view = FeeItemExplanation(line_id=item.line_key, item_code=item.item_code,
        calculation_refs=[calc.calculation_id for calc in calculations],
        fee_date=item.fee_occurrence_date.isoformat(), unit_price=money(item.unit_price), quantity=money(item.count),
        total_fee=money(item.fee), observed_in_scope=money(item.fee_in), observed_out_scope=money(item.fee_out),
        observed_self_pay_2=money(item.self_pay_2), calculated_in_scope=money(line.in_scope),
        calculated_out_scope=money(line.out_scope), calculated_self_pay_2=money(line.self_pay_2 if line.self_pay_2 is not None else Decimal(0)) if line.status == BranchOutcome.TRUE else None,
        calculated_proportional_self_pay=money(line.proportional_self_pay) if line.status == BranchOutcome.TRUE else None,
        status="calculated" if line.status == BranchOutcome.TRUE else "unknown")
    if entry is not None:
        view.catalog_entry_id = entry.entry_id
        view.effective_from = entry.effective_date.isoformat() if entry.effective_date else None
        view.effective_to = entry.expiry_date.isoformat() if entry.expiry_date else None
        if hasattr(entry, "a_ypbs") and entry.a_ypbs_known:
            view.centralized_procurement = entry.a_ypbs
            view.a_ypbs = "是" if entry.a_ypbs else "否"
        if hasattr(entry, "a_mzxj"):
            view.a_mzxj = money(entry.a_mzxj)
            view.a_xbbl = money(entry.a_xbbl)
            view.ypfl = entry.ypfl if entry.ypfl else None
            view.bzjg = money(entry.bzjg)
        start = entry.effective_date.isoformat() if entry.effective_date else "未返回"
        end = entry.expiry_date.isoformat() if entry.expiry_date else "未返回"
        view.conditions.append(f"项目编码 {item.item_code} 命中目录条目 {entry.entry_id}；费用日期 {view.fee_date}；目录有效期 {start} 至 {end}。")
    if item.sp_scale is not None:
        view.settlement_price_limit = money(item.sp_scale)
    outcomes = {"true": "满足", "false": "不满足", "unknown": "待核实"}
    for branch in branches:
        condition = branch.condition
        if condition is None:
            continue
        view.decision_path.append(FeeItemDecision(code=condition.code, label=condition.description,
            operator=condition.operator, actual=condition.actual_value, expected=condition.expected_ref,
            outcome="unknown" if condition.code == "centralized_procurement" and entry is not None and not entry.a_ypbs_known else branch.outcome.value,
            rule_refs=list(branch.rule_refs), calculation_refs=list(branch.calculation_refs)))
        if condition.code == "adopted_fee_category":
            view.classification_code = condition.actual_value
            view.classification_source = condition.expected_ref
            view.classification_label = _CATEGORY_LABELS.get((condition.actual_value or "").strip(), condition.actual_value)
        elif condition.code == "sfxmdj":
            view.classification_code = condition.actual_value
            view.classification_label = _SERVICE_LEVELS.get(condition.actual_value or "")
            view.classification_source = "诊疗/设施目录"
        if condition.code in ("ncp_price_le_limit", "drug_price_le_limit", "unit_price_le_bzjg", "service_price_le_limit"):
            view.unit_price_limit = condition.expected_ref
        detail = condition.description
        if condition.actual_value is not None:
            detail += f"；本行 {condition.actual_value}"
        if condition.expected_ref is not None:
            detail += f"；比较条件 {condition.expected_ref}"
        view.conditions.append(f"{detail} → {outcomes.get(str(branch.outcome.value), '未评估')}")
    # 耗材与诊疗共用 yb_xzzlfwxm：目录等级(sfxmdj)统一作为目录属性，含义与药品收费类别一致。
    level = getattr(entry, "sfxmdj", None) if entry is not None else None
    if level and not view.classification_label:
        label = _SERVICE_LEVELS.get(level.strip())
        if label:
            view.classification_code = level.strip()
            view.classification_label = label
            view.classification_source = "诊疗/服务设施目录"
    if entry is not None and hasattr(entry, "sflb"):
        view.conditions.append(f"目录收费类别：{entry.sflb or '未返回'}；账面收费类别：{item.fee_type or '未返回'}。")
    if view.status != "calculated":
        view.notes.append("目录匹配、参数或适用条件不能确定；保留账面金额，不拼造计算值。")
        return view
    quantity_check = next((b for b in branches if b.condition is not None and b.condition.code == "fee_equals_unit_price_times_count"), None)
    if quantity_check is not None:
        view.formulas.append(f"单价 {view.unit_price} 元×数量 {view.quantity}＝{quantity_check.condition.expected_ref} 元；原单费用 {view.total_fee} 元" +
            ("，两者一致。" if quantity_check.outcome == BranchOutcome.TRUE else "，两者不一致，分解仍采用原单费用。"))
    fee, inside, outside = view.total_fee, view.calculated_in_scope, view.calculated_out_scope
    for calc in calculations:
        values = [op.value for op in calc.operands]
        if calc.formula_id in ("catalog_self_pay_2_v1", "ncp_excess_final_ratio_v1"):
            view.division_method = "ratio"
            view.self_pay_ratio = values[-1]
        elif calc.formula_id == "material_included_ratio_v1":
            view.division_method = "ratio"
            view.included_ratio = values[-1]
            view.ratio_source = "本次日期命中的材料纳入规则"
            view.ratio_basis = "本行费用金额"
        elif calc.formula_id in ("drug_unit_price_limit_v1", "catalog_unit_price_limit_v1", "material_price_limit_v1"):
            view.division_method = "limit"
            view.unit_price_limit = next((op.value for op in calc.operands if op.ref.endswith(("sp_scale", "unit_price_limit"))), None)
            view.self_pay_ratio = next((op.value for op in calc.operands if op.ref.endswith("self_pay_ratio")), None)
        if any(op.ref.endswith(("self_pay_ratio", "excess_ratio")) for op in calc.operands):
            if item.medic_l is not None and item.medic_l > 0:
                view.ratio_source = "明细结算时比例（正值优先）"
                view.notes.append(f"比例来源：采用明细结算时比例 {item.medic_l}，按既有规则优先于目录比例。")
            else:
                view.ratio_source = "命中目录的超限最终比例" if calc.formula_id == "ncp_excess_final_ratio_v1" else "命中目录的自付比例"
                view.notes.append("比例来源：本行未维护正值结算时比例，采用本次命中目录的对应比例。")
        if any(op.ref.endswith("sp_scale") for op in calc.operands):
            view.limit_source = "明细结算时限价"
            view.notes.append("限价来源：本行结算时限价。")
        elif any(op.ref.endswith("unit_price_limit") for op in calc.operands):
            view.limit_source = "命中目录的单价限额"
            view.notes.append("限价来源：本次命中目录的单价限额。")
        if calc.formula_id in ("catalog_self_pay_2_v1", "ncp_excess_final_ratio_v1") and len(values) == 2:
            view.formulas.append(f"自付二＝取整（费用金额 {values[0]} 元×采用自付比例 {values[1]}）＝{calc.result} 元")
        elif calc.formula_id == "drug_unit_price_limit_v1":
            refs = {op.ref.rsplit(".", 1)[-1]: op.value for op in calc.operands}
            limit = refs.get("sp_scale") or refs.get("unit_price_limit")
            ratio = refs.get("self_pay_ratio")
            if limit is not None and ratio is not None and view.quantity is not None:
                view.formulas.append(f"医保内金额＝取整（单价限额 {limit} 元×数量 {view.quantity}×（1－自付二比例 {ratio}））＝{inside} 元")
        elif calc.formula_id == "catalog_unit_price_limit_v1" and len(values) == 3:
            view.formulas.append(f"超限价自付二＝取整（最大值（单价 {values[0]}－限额 {values[1]}，0）×数量 {values[2]}）＝{calc.result} 元")
        elif calc.formula_id == "material_price_limit_v1" and len(values) == 3:
            view.formulas.append(f"医保内金额＝结算时限价 {values[1]} 元×数量 {values[2]}＝{inside} 元")
        elif calc.formula_id == "material_included_ratio_v1" and len(values) == 2:
            view.formulas.append(f"医保内金额＝取整（费用金额 {values[0]} 元×纳入比例 {values[1]}）＝{inside} 元")
        if calc.rounding_rule:
            view.notes.append(f"本行取整记录：{rounding_display(calc.rounding_rule)}")
    if not calculations:
        view.conditions.append("本行目录分支直接确定纳入范围，未使用比例或限价计算。")
        if line.in_scope == item.fee and line.out_scope == 0:
            view.division_method = "full_in"
            view.formulas.append(f"本行全部纳入医保内：医保内金额＝本行费用 {fee} 元；医保外金额＝0 元")
        elif line.out_scope == item.fee and line.in_scope == 0:
            view.division_method = "full_out"
            view.formulas.append(f"本行全部由个人承担：医保内金额＝0 元；医保外金额＝本行费用 {fee} 元")
    if entry is not None and not any(c.rounding_rule and "待确认" in c.rounding_rule for c in calculations):
        view.verification_status = "verified"
    view.formulas.extend([f"医保内金额＝费用金额 {fee} 元－医保外金额 {outside} 元＝{inside} 元",
                          f"医保外金额＝费用金额 {fee} 元－医保内金额 {inside} 元＝{outside} 元"])
    if view.calculated_self_pay_2 is not None:
        view.notes.append(f"自付二 {view.calculated_self_pay_2} 元已包含在医保外金额中，不再额外加一次。")
    if view.self_pay_ratio is not None:
        view.ratio_basis = "限价内金额" if view.division_method == "limit" else "本行费用金额"
    if view.unit_price_limit is not None and view.limit_source is None:
        view.limit_source = "本次命中目录限价"
    return view


_SERVICE_LEVELS = {"1": "无自付", "2": "有自付", "3": "全自付"}

_CATEGORY_LABELS = {"甲": "甲类", "乙": "乙类", "丙": "丙类", "无自付": "无自付", "有自付": "有自付", "全自付": "全自付",
    "0101": "甲类西药", "0201": "甲类中成药", "0102": "乙类西药", "0202": "乙类中成药",
    "0103": "其它类西药（全自付档）", "0203": "其它类中成药（全自付档）", "0301": "复方可报草药", "0302": "单方可报草药", "0303": "其它类草药（全自付档）"}


def project_item_explanation(item: FeeItemExplanation) -> FeeItemExplanation:
    """逐金额精确核对；未算平行只保留事实和诊断，不生成原因链。"""
    checks = []
    for suffix, label in (("in_scope", "医保范围内"), ("out_scope", "医保范围外"), ("self_pay_2", "自付二")):
        observed, calculated = getattr(item, f"observed_{suffix}"), getattr(item, f"calculated_{suffix}")
        try:
            diff = Decimal(calculated) - Decimal(observed) if calculated is not None and observed is not None else None
            if diff is not None and not diff.is_finite():
                diff = None
        except InvalidOperation:
            diff = None
        checks.append(FeeItemReconciliation(label=label, observed=observed, calculated=calculated,
            difference=decimal_to_str(diff) if diff is not None else None,
            check_status="not_verifiable" if diff is None else "matched" if diff == 0 else "mismatched"))
    eligible = item.status == "calculated" and all(c.check_status == "matched" for c in checks) and not any(c.outcome in ("unknown", "blocked") for c in item.decision_path)
    reason = "金额已一致，实际判定条件未取得（算法待补全）" if all(c.check_status == "matched" for c in checks) else "本行尚未逐项算平，算法待补全"
    update = dict(reconciliations=checks, explainable=eligible, explanation_reason=None if eligible else reason)
    if not eligible:
        update.update(conditions=[], formulas=[], notes=[], decision_path=[], calculation_refs=[], explanation=reason)
    else:
        update["explanation"] = _item_explanation(item)
    return item.model_copy(update=update)


def _item_explanation(item: FeeItemExplanation) -> str | None:
    """逐行解释：分类 + 比例来源 + 本行主算式（逐字取自已执行记录，不另造词）。"""
    pieces: list[str] = []
    if item.classification_label:
        pieces.append(item.classification_label)
    source = next((note for note in item.notes if note.startswith("比例来源")), None)
    if source:
        pieces.append(source)
    steps = [formula for formula in item.formulas if not formula.startswith("单价 ")]
    pieces.extend(steps[:2])
    return "；".join(pieces) if pieces else None


def attach_item_rows(result: SettlementDecompositionResult, rows: list[Mapping[str, Any]], *,
                     special: bool, mapping: Any = None) -> SettlementDecompositionResult:
    """名称与金额同一读取快照；按唯一行键关联，歧义不借项目名或金额猜测。"""
    from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING
    from src.adapters.data_supply.settlement_record_queries import _k
    m = mapping or DEFAULT_RECORD_QUERY_MAPPING
    keys = {"line_id": "xh", "item_code": "xmdm", "item_name": "xmmc", "item_type": "xmlb",
            "fee_date": "fsrq", "unit_price": "dj", "quantity": "sl", "total_fee": "zje",
            "observed_in_scope": "ybnje", "observed_out_scope": "ybwje", "observed_self_pay_2": "grziftw"} if special else {
        "line_id": _k(m, "opf_line_id"), "item_code": _k(m, "opf_item_code"), "item_name": _k(m, "opf_item_name"),
        "item_type": _k(m, "opf_item_type"), "fee_date": _k(m, "opf_fee_date"), "unit_price": _k(m, "opf_unit_price"),
        "quantity": _k(m, "opf_count"), "total_fee": _k(m, "opf_fee"), "observed_in_scope": _k(m, "opf_fee_in"),
        "observed_out_scope": _k(m, "opf_fee_out"), "observed_self_pay_2": _k(m, "opf_self_pay_2")}
    counts = Counter(str(row[keys["line_id"]]).strip() if row.get(keys["line_id"]) is not None else "" for row in rows)
    index = {item.line_id: item for item in result.fee_items}
    no_benefit = any(b.step_id == "flow.no_benefit_check" and b.outcome == "true" for b in result.branches)
    items = []
    for row in rows:
        values = {key: None if row.get(col) is None else str(row[col]).strip() for key, col in keys.items()}
        line_id = values["line_id"] or ""
        previous = index.get(line_id) if counts[line_id] == 1 and line_id else None
        if previous is None:
            previous = FeeItemExplanation(line_id=line_id, item_code=values["item_code"] or "")
        update: dict[str, Any] = {key: value for key, value in values.items() if value is not None and key not in ("line_id", "item_code", "item_type")}
        update["item_type"] = {"0": "药品", "1": "诊疗项目", "2": "服务设施", "3": "耗材"}.get(values["item_type"] or "", "类别待核实")
        if no_benefit and counts[line_id] == 1 and line_id and values["total_fee"] is not None:
            fee = values["total_fee"]
            update.update(status="calculated", calculated_in_scope="0", calculated_out_scope=fee,
                division_method="settlement_override", self_pay_ratio=None, included_ratio=None, unit_price_limit=None,
                calculated_self_pay_2="0", conditions=["本单命中全额个人承担分支，未执行目录独立重算。"],
                formulas=[f"医保内金额＝0 元；医保外金额＝本行费用金额 {fee} 元"],
                notes=["原因码的业务含义仍待签核，不能据此认定项目本身属于目录外。"])
        if not line_id or counts[line_id] != 1:
            update.update(status="unknown", calculated_in_scope=None, calculated_out_scope=None,
                division_method="unknown", self_pay_ratio=None, included_ratio=None, unit_price_limit=None,
                calculated_self_pay_2=None, formulas=[], notes=["费用行键缺失或重复，无法唯一关联算法记录。"])
        items.append(previous.model_copy(update=update))
    return result.model_copy(update={"fee_items": items})
