"""费用分解结果的公开视图映射与确定性模板渲染（Issue #78 设计 §11/§12，步骤 5）。

边界：
- 本模块为纯函数，不查数据库、不调用模型；
- 金额为十进制字符串原样透传，不做 float 转换；
- 模板渲染是模型不可用时的确定性基线（设计 §12：模型关闭仍能提供金额和条件解释）；
- 差异只原样呈现（实际值/计算值/差额），不判定医保系统对错；
- 物理表/列、快照引用不进入公开视图（留在受权限控制的审计轨迹）。

解释投影 1.1（2026-10-15 费用解释改造切片 1）：
- 公开 schema_version 独立标识 1.1，内部 SettlementDecompositionResult 保持 1.0；
- 增补字段引用关联（计算/来源/缺口）、计算记录、安全来源与采用条件的公开视图；
- 来源默认拒绝自由文本：issue_note / source_catalog 不公开，快照物理路径不透传，
  链接仅接受 https 协议；
- 缺失/冲突引用只降级受影响字段的解释，金额照常展示。

解释投影 1.2（2026-10-16 交付细化"先看原单，再顺着算到个人应付"）：
- 新增 path_steps：正向结算路径（费用明细→目录划分→起付→统筹/大额→补助→
  大病/救助→个人支付总金额→支付方式），按本单实际执行模块归并；
- 新增 settlement_facts：结算事实侧车（由快照服务从原始交易/登记行构造，
  经 to_public_contract_dict 入参进入公开契约）。

解释投影 1.9（Issue #84 数据结构优化）：
- 字段增补 conclusion（账面列示/勾稽相符/按当前口径重算相符/依据已确认/暂不能解释）、
  amount_semantics（谁的钱、本笔还是周期、能否与重算值直接比较）与 basis（计算/输入/
  规则组/规则/来源标题，安全编号级依据链）；
- 不确定性增补 scope，并在 affected_fields 为空时按缺口类型回填受影响金额；
- 新增 stages：按业务环节列出已验证条件、采用前提与缺失缺口；
- 新增 trace：算法版本、规则版本、分支数与安全证据号，完整轨迹不进公开载荷。

解释投影 1.6（2026-10-19 交易信息+逐行解释）：
- fee_items 增补逐行目录事实（集采标识/门诊限价/住院限价/超限价自付比例/
  药品分类/自制剂标准价格/明细结算时限价）与 explanation；
  原值透传，缺失不补；前端只在条件实际影响该行比例或限价时展示对应列。

解释投影 1.10（阶段 B 字段固定说明）：
- 字段级 explanation：四要素固定说明（含义/构成/本单依据/解释边界），服务端
  确定性合成（field_explanations.py），缺项在 boundary 显式声明；
- template_explanations：按模板 key 索引的展示字段固定说明，覆盖内核未产出
  分解记录的展示字段（如 beyond_cap）；面板模板视图与聊天同源使用；
- 零金额三态：_field_line 按 reason_code 区分"不符合待遇条件 / 符合但为零 /
  资格资料不足"，不再一律"本单不适用"。
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.runtime.policy_qa.fee_decomposition.field_explanations import (
    build_field_explanation,
    chain_family,
    resolve_field_key,
    zero_amount_sentence,
)

from src.runtime.policy_qa.fee_decomposition.formula_display import formula_display, rounding_display
from src.runtime.policy_qa.fee_decomposition.formula_text import (
    calculation_formula, trim_trailing_zeros)
from src.runtime.policy_qa.fee_decomposition.rule_choices import CONFIRMED_RULE_STATUSES
from src.runtime.policy_qa.fee_decomposition.result import (
    CalculationRecordModel,
    SettlementDecompositionResult,
)
from src.runtime.policy_qa.fee_decomposition.settlement_facts import SettlementFactsView

#: 执行状态 → 用户可读状态词（may_claim_full_explanation=False 时不得出现"完整解释"，
#: 由 answer_constraints 保证 execution_status=complete 且核对一致才可宣称）
_EXECUTION_WORDS = {
    "complete": "完整解释",
    "partial": "部分解释",
    "unavailable": "暂不可用",
}

#: 核对状态 → 用户可读状态词
_RECONCILIATION_WORDS = {
    "matched": "核对一致",
    "mismatched": "存在差异",
    "not_verifiable": "暂不能核对",
}

#: 核对类型 → 计算来源措辞
_CHECK_TYPE_WORDS = {
    "independent_recalculation": "按规则重算",
    "detail_aggregation": "明细合计",
    "identity_check": "账面勾稽",
}


def _field_line(field) -> str:
    """单字段一句话（设计 §12：一致/差异/缺项各有固定措辞）。

    零金额三态（阶段 B）：不适用（本单不符合该待遇条件）/ 符合但为零 /
    资格资料不足（不能仅凭零金额判断没有资格），按 reason_code 区分。
    """
    if (field.check_status == "not_verifiable"
            and field.reason_code == "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED"
            and field.calculated_amount is not None):
        # grzif1 列存在但已核样本未维护：不写"无此列"，也不虚称"结算记录 X 元"
        return (f"{field.label}：该列在已核样本中未维护，当前金额由本单分量计算"
                f"（{field.calculated_amount} 元），不作账面核对。")
    state = zero_amount_sentence(
        field.check_status, field.reason_code,
        field.observed_amount, field.calculated_amount, field.field_code)
    source = _CHECK_TYPE_WORDS.get(field.check_type, "计算")
    observed = (
        f"结算记录 {field.observed_amount} 元"
        if field.observed_amount is not None
        else "结算记录缺失"
    )
    if field.check_status == "matched":
        if state:
            return (f"{field.label}：{state[:-1]}"
                    f"（{observed}，{source} {field.calculated_amount} 元，一致）。")
        return f"{field.label}：{observed}，{source} {field.calculated_amount} 元，一致。"
    if field.check_status == "mismatched":
        return (
            f"{field.label}：{observed}，{source} {field.calculated_amount} 元，"
            f"差额 {field.difference} 元（仅呈现差异，不判定对错）。"
        )
    if field.check_status == "not_applicable":
        if state:
            return f"{field.label}：{state}"
        return f"{field.label}：本单不适用。"
    # not_verifiable：区分"资格资料不足""已算出但无法核对"与"无法独立计算"
    if state:
        return f"{field.label}：{observed}，{state}"
    if field.calculated_amount is not None:
        return f"{field.label}：{observed}，{source} {field.calculated_amount} 元，暂不能与账面核对。"
    return f"{field.label}：{observed}，暂不能独立计算。"


#: 这句话只约束退休补充是否已纳入，计算仍 fail-closed，但不对患者展示。
_ENROLL_DATE_GAP_MARKERS = ("不默认已纳入", "缺少退休补充保险纳入起始日期")
_ENROLL_DATE_GAP_LABELS = frozenset({"尚待核实", "未决事项", "待核实"})


def _patient_uncertainties(uncertainties):
    """退休补充纳入日期缺失只约束计算，不进入患者可见说明。"""
    return [item for item in uncertainties
            if not any(marker in (item.message or "") for marker in _ENROLL_DATE_GAP_MARKERS)]


def omit_enroll_date_gap(text: str) -> str:
    """从患者可见正文里去掉退休补充纳入日期缺证。

    只删含该缺证的分句；同一回答里已核对的金额说明保留。
    金额里的千分位逗号不切分。没有这句缺证时原文不动。
    """
    if not text or not any(marker in text for marker in _ENROLL_DATE_GAP_MARKERS):
        return text

    def keep(clause: str) -> bool:
        if any(marker in clause for marker in _ENROLL_DATE_GAP_MARKERS):
            return False
        bare = clause.strip().strip("：:。；; ")
        return bare not in _ENROLL_DATE_GAP_LABELS

    lines: list[str] = []
    for line in text.split("\n"):
        sentences: list[str] = []
        for sentence in re.split(r"(?<=[。；;])", line):
            if not sentence:
                continue
            ending = sentence[-1] if sentence[-1] in "。；;" else ""
            body = sentence[:-1] if ending else sentence
            kept = [part.strip() for part in body.split("，") if part.strip() and keep(part.strip())]
            if not kept:
                continue
            sentences.append("，".join(kept) + ending)
        rebuilt = "".join(sentences).strip()
        if rebuilt:
            lines.append(rebuilt)
    return "\n".join(lines)


def render_summary(result: SettlementDecompositionResult) -> str:
    """确定性模板渲染：总览状态行 + 逐字段行 + 未决事项。

    只使用结果中已有的事实与金额，不补全任何缺失规则或比例。
    """
    status_word = _EXECUTION_WORDS.get(result.execution_status, result.execution_status)
    if result.execution_status == "complete" and not result.answer_constraints.may_claim_full_explanation:
        status_word = "部分解释"
    recon_word = _RECONCILIATION_WORDS.get(
        result.reconciliation_status, result.reconciliation_status)

    if result.execution_status == "unavailable" or not result.fields:
        lines = [f"费用分解{status_word}（算法版本 {result.algorithm_version}）。"]
    else:
        lines = [
            f"费用分解（算法版本 {result.algorithm_version}）：{status_word}，账面核对{recon_word}。",
            *(f"- {_field_line(field)}" for field in result.fields),
        ]
    shown_uncertainties = _patient_uncertainties(result.uncertainties)
    if shown_uncertainties:
        # 同一未决文案可能被多个来源重复命中（仅 id 不同）：按文案保序去重
        lines.append("未决事项：" + "；".join(
            dict.fromkeys(u.message for u in shown_uncertainties)))
    return "\n".join(lines)


#: 基金支付合计（fund_total）是账面勾稽字段：其构成说明指向有独立计算的非零渠道字段。
_FUND_TOTAL_CHANNEL_CODES = (
    "TCZHF", "T_BigPay", "DEGWYZHF", "T_BCPay", "T_JCPay", "T_OfficalPay",
    "RETIRE_OFFICER_PAY", "T_BigillPay", "BIG_ILL_PAY", "NT_CivilPay",
)


def _point_fund_total_to_computed_channels(fields: list[dict], key_by_code: dict[str, str]) -> None:
    """基金支付合计只核对分量勾稽时，把构成说明指向有独立计算的非零渠道字段（阶段 F）。

    只改固定说明措辞：保留“账面勾稽、未独立重算”的诚实口径，追加渠道指引；
    无已计算非零渠道时维持原措辞，不编造指引。
    """
    for field in fields:
        if key_by_code.get(field["field_code"]) != "fund_total":
            continue
        explanation = field.get("explanation")
        if not explanation or not str(explanation.get("composition") or "").startswith("账面勾稽"):
            continue
        channels = [
            sibling for sibling in fields
            if sibling["field_code"] in _FUND_TOTAL_CHANNEL_CODES
            and sibling["check_type"] == "independent_recalculation"
            and sibling["check_status"] == "matched"
            and not _is_zero_amount(sibling.get("observed_amount"))
            and sibling.get("observed_amount") is not None
        ]
        if not channels:
            continue
        pointers = "、".join(f"「{item['label']}」{item['observed_amount']} 元" for item in channels)
        suffix = ("本笔基金支付全部来自" if len(channels) == 1 else "本笔基金支付的有独立计算记录的分量为")
        explanation["composition"] = (
            f"账面勾稽：仅核对各分量关系，未独立重算；{suffix}{pointers}，其计算构成见对应字段说明。")


_RETIRE_OFFICER_KEY = "retire_officer_pay"


def _retire_officer_condition_note(
    settlement_facts: SettlementFactsView | None, observed_amount: str | None,
) -> str:
    """退役医疗费 0 元的唯一说明：本笔结算记录里的退役医疗费标志。

    只陈述可核对事实（标志与原单支付金额），不再罗列未记录条件或“按原单记录列示”等填充语。
    """
    amount = observed_amount if observed_amount is not None else "0.00"
    flag = (settlement_facts.retire_officer_flag if settlement_facts is not None else None)
    flag_text = (flag or "").strip()
    if not flag_text:
        return "本笔结算记录未提供退役医疗费标志。"
    if flag_text in ("0", "0.0", "False", "false", "否"):
        return "本笔结算记录退役医疗费标志为 0（否）。"
    return f"本笔结算记录退役医疗费标志为 {flag_text}，退役医疗费支付 {amount} 元。"


def build_public_view_dict(
    result: SettlementDecompositionResult,
    *,
    summary_text: str,
    summary_source: str,
    settlement_facts: SettlementFactsView | None = None,
) -> dict:
    """结果 → 公开视图 dict（纯映射；文本消毒与契约校验由路由层统一把关）。

    不含分支轨迹、计算记录、快照引用等审计级细节（设计 §12：用户端呈现业务名称，
    物理表/列和 SQL 留在受权限控制的审计视图）。

    解释投影 1.1：字段携带精确引用关联（calculation_refs/source_refs/gap_refs）
    与确定性构成简述 brief；计算、安全来源、采用条件作为顶层数组下发，由前端
    按引用就地展开。缺失/冲突引用只降级对应字段，金额不消失。

    解释投影 1.2：新增 path_steps（正向结算路径，按本单实际执行模块归并）与
    settlement_facts（结算事实侧车，由调用方从原始行构造后传入）。
    """
    calc_index, _calc_conflicts = _index_with_conflicts(
        result.calculations, lambda c: c.calculation_id)
    cit_index, _cit_conflicts = _index_with_conflicts(
        result.citations, lambda c: c.id)
    shown_uncertainties = _patient_uncertainties(result.uncertainties)
    unc_index, _unc_conflicts = _index_with_conflicts(
        shown_uncertainties, lambda u: u.id)
    field_labels = {f.field_code: f.label for f in result.fields}
    calc_names = {
        cid: formula_display(c.formula_id).display_name for cid, c in calc_index.items()
    }

    calculations = [
        _calculation_view(c, field_labels, calc_names) for c in calc_index.values()
    ]
    # 合计展示逐行贡献，复用本次已执行的行结果及合计；不在投影层重新加总。
    summary_columns = {"catalog_total_fee_v1": "total_fee", "catalog_total_in_scope_v1": "calculated_in_scope",
                       "catalog_total_out_scope_v1": "calculated_out_scope", "catalog_total_self_pay_2_v1": "calculated_self_pay_2",
                       "special_detail_sum_v1": "observed_in_scope",
                       # 门特明细逐行合计：总费用/医保外/个人自付二也逐行列示来源行
                       "special_detail_fee_sum_v1": "total_fee",
                       "special_detail_out_sum_v1": "observed_out_scope",
                       "special_detail_advance_sum_v1": "observed_self_pay_2"}
    summary_applied: set[str] = set()
    for view in calculations:
        column = summary_columns.get(view["formula_id"])
        if column and result.fee_items and view["result"] is not None:
            values = [getattr(item, column) for item in result.fee_items]
            if all(value is not None for value in values):
                terms = [f"{item.item_name or item.item_code or '费用行'}（第{index + 1}行） {value} 元" for index, (item, value) in enumerate(zip(result.fee_items, values))]
                view["formula"] = trim_trailing_zeros(
                    f"{view['display_name']}＝" + " ＋ ".join(terms) + f"＝{view['result']} 元")
                summary_applied.add(view["calculation_id"])
    from src.runtime.policy_qa.fee_decomposition.formula_inputs import project_inputs
    formula_inputs = [node.model_dump() for node in project_inputs(result, calculations, calc_index)]
    for view in calculations:
        if view["calculation_id"] not in summary_applied:
            view["formula"] = trim_trailing_zeros(
                calculation_formula(calc_index[view["calculation_id"]], view["operands"]))
    calc_view_by_id = {c["calculation_id"]: c for c in calculations}
    required_refs = {ref for field in result.fields if field.check_type != "identity_check" for ref in field.calculation_refs}
    pending_evidence = any(c["verification_status"] != "verified" for c in calculations if not required_refs or c["calculation_id"] in required_refs)
    pending_evidence = pending_evidence or any(ref not in calc_view_by_id for ref in required_refs)
    if pending_evidence:
        summary_text = summary_text.replace("完整解释", "部分解释")
    sources = [
        view for view in (_source_view(c) for c in cit_index.values()) if view is not None
    ]
    public_source_ids = {s["ref_id"] for s in sources}
    policy_source_ids = {s["ref_id"] for s in sources if s["category"] == "policy_basis"}
    catalog_rule_refs = {
        rule_ref if rule_ref.startswith("rule.") else f"rule.{rule_ref}"
        for branch in result.branches if branch.step_id.startswith("catalog.")
        for rule_ref in branch.rule_refs
    } & policy_source_ids
    conditions = _condition_views(result)

    display_labels = ({field.field_code: field.label
        for field in settlement_facts.display_template.fields if field.field_code}
        if settlement_facts is not None and settlement_facts.display_template is not None else {})
    fields = []
    for f in result.fields:
        # 冲突 ID 已从索引剔除，此处自然过滤；未解析引用不进入公开视图
        calc_refs = _calculation_dependencies(f.calculation_refs, calc_index)
        source_refs = [r for r in f.citation_refs if r in public_source_ids]
        uses_catalog_lines = any(
            operand.ref.startswith("calc.catalog.lines.")
            for calc_id in calc_refs for operand in calc_index[calc_id].operands
        )
        if uses_catalog_lines:
            source_refs.extend(ref for ref in sorted(catalog_rule_refs) if ref not in source_refs)
        gap_refs = [r for r in f.uncertainty_refs if r in unc_index]
        fields.append({
            "field_code": f.field_code,
            "label": display_labels.get(f.field_code, f.label),
            "check_type": f.check_type,
            "check_status": f.check_status,
            "observed_amount": f.observed_amount,
            "calculated_amount": f.calculated_amount,
            "difference": f.difference,
            "explanation_level": f.explanation_level,
            "reason_code": f.reason_code,
            "calculation_refs": calc_refs,
            "source_refs": source_refs,
            "gap_refs": gap_refs,
            "brief": _field_brief(f, calc_refs, calc_view_by_id),
        })

    from src.runtime.policy_qa.fee_decomposition.fee_items import project_item_explanation
    from src.runtime.policy_qa.fee_decomposition.explanation_scope import mark_explanation_scope
    fee_items = [project_item_explanation(item) for item in result.fee_items]
    mark_explanation_scope(result, fields, calculations, formula_inputs, fee_items)
    incomplete_explanation = any(not f["explainable"] for f in fields
        if f["check_type"] == "independent_recalculation" and f["check_status"] != "not_applicable")
    if incomplete_explanation:
        summary_text = summary_text.replace("完整解释", "部分解释")

    # Issue #84：结论分级、金额口径、依据链；缺口回填受影响金额；环节完整性。
    rule_groups = result.explanation_evidence.rule_choices if result.explanation_evidence else []
    for field in fields:
        field_calcs = set(field["calculation_refs"])
        groups = [group for group in rule_groups if field_calcs.intersection(group.calculation_refs)]
        conclusion, conclusion_text = _conclusion_of(field, calc_view_by_id, groups)
        field["conclusion"] = conclusion
        field["conclusion_text"] = conclusion_text
        field["amount_semantics"] = _amount_semantics_views(field)
        field["basis"] = _basis_of(field, calc_view_by_id, groups)

    # 阶段 B：字段四要素固定说明（确定性合成，面板与聊天同源同文）
    family = chain_family(result.algorithm_version)
    template_fields = (
        [tf for tf in settlement_facts.display_template.fields if tf.section != "basic"]
        if settlement_facts is not None and settlement_facts.display_template is not None
        else [])
    key_by_code = {tf.field_code: tf.key for tf in template_fields if tf.field_code}
    siblings_by_code = {field["field_code"]: field for field in fields}
    for field in fields:
        code = field["field_code"]
        if family is None or ("." in code and code not in key_by_code):
            field["explanation"] = None
            continue
        field_calcs = set(field["calculation_refs"])
        field_groups = [group for group in rule_groups
                        if field_calcs.intersection(group.calculation_refs)
                        or code in group.field_refs]
        template_key = key_by_code.get(code)
        composition_notes: list[str] = []
        field_key = resolve_field_key(family, template_key, code)
        composition_override = (
            _retire_officer_condition_note(settlement_facts, field["observed_amount"])
            if field_key == _RETIRE_OFFICER_KEY else None)
        if field_key == "self_pay_2":
            # 自付二只含本单实际计入的比例先行/超限价部分；全自费项目已计医保外，不计入自付二
            full_out = [item for item in result.fee_items
                        if item.division_method == "full_out"
                        and item.total_fee is not None and not _is_zero_amount(item.total_fee)]
            if full_out:
                composition_notes.append(
                    "、".join(
                        f"{item.item_name or item.item_code or '费用行'} "
                        f"{Decimal(item.total_fee).quantize(Decimal('0.01'))} 元"
                        for item in full_out)
                    + "属于全自费，已计入医保范围外金额，不计入自付二。")
        field["explanation"] = build_field_explanation(
            family=family, template_key=template_key, field_code=code,
            label=field["label"], field=field,
            gap_messages=[unc_index[ref].message for ref in field["gap_refs"] if ref in unc_index],
            rule_excerpts=_rule_excerpts(field_groups),
            siblings=siblings_by_code, composition_notes=composition_notes,
            composition_override=composition_override).model_dump()
    _point_fund_total_to_computed_channels(fields, key_by_code)
    field_by_code = {field["field_code"]: field for field in fields}
    template_explanations: dict[str, dict] = {}
    for tf in template_fields:
        linked = field_by_code.get(tf.field_code) if tf.field_code else None
        if linked is not None and linked.get("explanation"):
            template_explanations[tf.key] = linked["explanation"]
        else:
            extra_gaps: list[str] = []
            if tf.key == "beyond_cap":
                # 缺口由实际输入状态决定：已有封顶标准与交易前累计输入时，
                # 不能仍写"缺封顶规则与累计"（评审问题 8）。
                has_cap = any("封顶" in group.title and any(
                    row.status == "selected" for row in group.candidates) for group in rule_groups)
                has_prior = any("累计" in str(node.get("name") or "") for node in formula_inputs)
                if has_cap and has_prior:
                    extra_gaps.append(
                        "本单已有大额封顶标准与交易前累计输入；"
                        "超封顶金额的费用归属未经确认，仅按原单列示。")
            override = (_retire_officer_condition_note(settlement_facts, tf.value)
                        if tf.key == _RETIRE_OFFICER_KEY else None)
            template_explanations[tf.key] = build_field_explanation(
                family=family, template_key=tf.key, field_code=tf.field_code,
                label=tf.label, field=None, gap_messages=extra_gaps,
                composition_override=override).model_dump()
    uncertainty_views = []
    for uncertainty in shown_uncertainties:
        affected = list(uncertainty.affected_fields)
        if not affected:
            affected = _infer_affected_fields(uncertainty.code, fields, calc_view_by_id)
        uncertainty_views.append({
            "code": uncertainty.code,
            "message": uncertainty.message,
            "id": uncertainty.id,
            "affected_fields": affected,
            "scope": "field" if affected else "global",
        })
    stage_views = _stage_views(result, _path_step_views(result), conditions, fields, uncertainty_views)
    trace_view = _trace_view(result, fields, calculations, rule_groups)

    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "algorithm_version": result.algorithm_version,
        "execution_status": result.execution_status,
        "reconciliation_status": result.reconciliation_status,
        "summary_text": summary_text,
        "summary_source": summary_source,
        "may_claim_full_explanation": result.answer_constraints.may_claim_full_explanation and not pending_evidence and not incomplete_explanation,
        "fields": fields,
        "uncertainties": uncertainty_views,
        "coverage": {
            "target_field_count": result.coverage.target_field_count,
            "independently_explained_count": result.coverage.independently_explained_count,
            "amount_reconciled_count": result.coverage.amount_reconciled_count,
            "observed_only_count": result.coverage.observed_only_count,
        },
        "calculations": calculations,
        "formula_inputs": formula_inputs,
        "rule_choices": [group.model_dump() for group in result.explanation_evidence.rule_choices] if result.explanation_evidence else [],
        "sources": sources,
        "conditions": conditions,
        "path_steps": _path_step_views(result),
        "stages": stage_views,
        "trace": trace_view,
        "fee_items": [item.model_dump() for item in fee_items],
        "settlement_facts": (
            settlement_facts.model_dump() if settlement_facts is not None else None),
        "template_explanations": template_explanations,
    }


# ── 解释投影 1.1：索引、安全来源与确定性简述 ─────────────────────────

#: 公开投影独立版本（内部 SettlementDecompositionResult 保持 1.0）
PUBLIC_SCHEMA_VERSION = "1.10"

#: 分支模块 → 业务模块名（未知模块回落"其他计算步骤"，不回显实现名）
_MODULE_LABELS = {
    "person_classification": "人员与机构分类",
    "catalog_split": "目录划分",
    "deductible": "起付线",
    "resident_deductible": "起付线",
    "resident_special_deductible": "起付线",
    "big_pay": "大额支付",
    "resident_big_pay": "大额支付",
    "resident_special_big_pay": "大额支付",
    "pool_fund": "统筹基金",
    "large_fund": "大额基金",
    "retire_supplement": "退休补助",
    "military_supplement": "军残补助",
    "public_medical": "公疗补助",
    "secondary_coverage": "二次保障",
    "detail_aggregation": "明细汇总",
    "resident_bigill_pay": "大病保险",
    "resident_msf_pay": "医事服务费",
    "resident_special_pool": "居民门特统筹",
    "fixed_quota": "定额管理（肾）",
    "employee_outpatient": "职工门诊流程",
    "resident_outpatient": "居民门诊流程",
    "employee_outpatient_special": "职工门特流程",
    "resident_outpatient_special": "居民门特流程",
}
_UNKNOWN_MODULE_LABEL = "其他计算步骤"

#: 明细级逐行分支不进主干条件列表（明细展开属各字段计算记录范畴）
_CONDITION_EXCLUDED_MODULES = {"catalog_split", "detail_aggregation"}

#: 允许公开的来源类别（默认拒绝：issue_note / source_catalog 等不进入公开视图，
#: 样本说明与读取元数据不得冒充正式政策依据）
_SOURCE_CATEGORY = {
    "settlement_fact": "settlement_record",
    "fee_facts": "settlement_record",
    "policy_document": "policy_basis",
}

_SETTLEMENT_FACT_TITLE = "结算记录"



# ── 解释投影 1.9（Issue #84）：结论分级、金额口径、依据链、环节完整性 ────────

_HOSPITAL_FIELDS = {"QUOTA_AMOUNT", "AGENCY_PAY", "QUOTA.balance"}

_CONCLUSION_TEXT = {
    "book_only": "账面列示：本单无独立计算依据，仅列示结算记录金额",
    "reconciled": "勾稽相符：仅核对账面金额关系，未独立重算",
    "recalculated": "按当前口径重算相符：与账面一致，采用依据仍有待确认项",
    "basis_confirmed": "依据已确认：按当前口径重算与账面一致，采用依据已确认",
    "unexplained": "暂不能解释：缺少可用的计算依据或数据",
}

#: 业务环节 → 正向结算路径步骤
_STAGE_DEFS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("catalog", "明细归类", ("path.fee_items", "path.catalog_split")),
    ("deductible", "起付", ("path.deductible",)),
    ("fund", "统筹与大额", ("path.fund",)),
    ("supplements", "补助", ("path.supplements",)),
    ("secondary", "二次保障", ("path.secondary",)),
    ("personal", "个人负担", ("path.personal_total",)),
    ("payment", "现金与账户分配", ("path.payment_method",)),
)


def _amount_semantics_views(field: dict) -> dict:
    """谁的钱、什么范围、能否与重算值直接比较（不同口径的金额不得相减）。"""
    code = field["field_code"]
    if code in _HOSPITAL_FIELDS or code.startswith("QUOTA."):
        owner, owner_text = "hospital_settlement", "医院定额清算"
    elif not field["calculation_refs"] and field["check_type"] == "identity_check":
        owner, owner_text = "book_record", "账面记录"
    else:
        owner, owner_text = "patient_benefit", "患者待遇"
    comparable = owner == "patient_benefit" and field["check_type"] in ("independent_recalculation", "detail_aggregation")
    return {
        "owner": owner,
        "owner_text": owner_text,
        "scope": "trade",
        "scope_text": "本笔",
        "comparable": comparable,
        "text": f"{owner_text}·本笔·{'可与重算值直接比较' if comparable else '仅为账面关系，不与重算值直接比较'}",
    }


def _conclusion_of(field: dict, calc_view_by_id: dict[str, dict], groups: list) -> tuple[str, str]:
    """区分「金额相符 / 可以解释 / 依据已确认」，不让 explainable 承担全部含义。"""
    status = field["check_status"]
    if status == "not_applicable":
        return "book_only", "本单不适用：仅列示账面记录"
    if field.get("reason_code") == "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED":
        return ("book_only",
                "该列在已核样本中未维护：当前金额为本单分量计算值，不作账面核对")
    if not field["explainable"]:
        if (status == "matched" and field["check_type"] != "identity_check"
                and any(ref in calc_view_by_id for ref in field["calculation_refs"])):
            # 金额确由本单算法重算且与账面一致，只是采用依据未全部核实：
            # 不能再说"仅核对账面关系，未独立重算"（计算记录存在即可证）。
            return "recalculated", _CONCLUSION_TEXT["recalculated"]
        return ("reconciled", _CONCLUSION_TEXT["reconciled"]) if status == "matched"             else ("book_only", _CONCLUSION_TEXT["book_only"])
    calcs = [calc_view_by_id[ref] for ref in field["calculation_refs"] if ref in calc_view_by_id]
    verified = bool(calcs) and all(calc["verification_status"] == "verified" for calc in calcs)
    candidates = [row for group in groups for row in group.candidates if row.status == "selected"]
    confirmed = bool(candidates) and all(
        (row.confirmation_status or "").strip() in CONFIRMED_RULE_STATUSES for row in candidates
    )
    if verified and confirmed:
        return "basis_confirmed", _CONCLUSION_TEXT["basis_confirmed"]
    return "recalculated", _CONCLUSION_TEXT["recalculated"]


def _rule_excerpts(groups: list) -> list[str]:
    """本单实际采用档的确定性措辞（供字段固定说明"本单依据"复用）。"""
    excerpts: list[str] = []
    for group in groups:
        title = re.sub(r"\s*·\s*(不适用|已采用|未采用|待核实|未确认)\s*$", "", group.title)
        for row in group.candidates:
            if row.status != "selected":
                continue
            value = "" if row.value is None else f" {row.value}{row.unit}"
            excerpt = f"本次采用：{title} · {row.name}{value}".rstrip(" ·")
            if excerpt not in excerpts:
                excerpts.append(excerpt)
    return excerpts


def _basis_of(field: dict, calc_view_by_id: dict[str, dict], groups: list) -> dict:
    """沿计算 → 输入 → 规则组 → 规则 → 来源标题，给出安全编号级的依据链。"""
    calc_ids = [ref for ref in field["calculation_refs"] if ref in calc_view_by_id]
    input_ids: list[str] = []
    for ref in calc_ids:
        for operand in calc_view_by_id[ref].get("operands", []):
            input_ref = operand.get("input_ref")
            if input_ref and input_ref not in input_ids:
                input_ids.append(input_ref)
    rule_ids: list[str] = []
    source_titles: list[str] = []
    for group in groups:
        for row in group.candidates:
            if row.status != "selected":
                continue
            if row.rule_id and row.rule_id not in rule_ids:
                rule_ids.append(row.rule_id)
            if row.source and row.source not in source_titles:
                source_titles.append(row.source)
    return {
        "calculation_ids": calc_ids,
        "input_ids": input_ids,
        "rule_group_ids": [group.group_id for group in groups],
        "rule_ids": rule_ids,
        "source_titles": source_titles,
    }


def _infer_affected_fields(code: str, fields: list[dict], calc_view_by_id: dict[str, dict]) -> list[str]:
    """全局缺口关联到受影响金额；定位不到时返回空并标记 global。"""
    upper = code.upper()
    if "ROUND" in upper:
        return [field["field_code"] for field in fields if any(
            "待确认" in (calc_view_by_id.get(ref, {}).get("rounding_rule") or "") for ref in field["calculation_refs"])]
    if "CYCLE" in upper or "ACCUM" in upper:
        return [field["field_code"] for field in fields if any(
            ref.startswith(("calc.pool", "calc.large", "calc.deductible")) for ref in field["calculation_refs"])]
    if "CATALOG" in upper:
        return [field["field_code"] for field in fields
                if field["field_code"] in ("T_FeeIn", "T_FeeOut", "T_SelfPay2", "YBN", "YBW", "GRZIFTW", "ZJE", "T_FeeAll")]
    if "QUOTA" in upper or "FIXED" in upper:
        return [field["field_code"] for field in fields
                if field["field_code"] in _HOSPITAL_FIELDS or field["field_code"].startswith("QUOTA.")]
    return []


def _trace_view(result, fields: list[dict], calculations: list[dict], rule_groups: list) -> dict:
    """安全编号级追溯：公开结果只带版本与证据号，完整分支轨迹留在受权限控制的审计侧。"""
    rule_versions = sorted({row.version for group in rule_groups for row in group.candidates
                            if row.status == "selected" and row.version})
    digest = hashlib.sha256("|".join([
        result.settlement_ref or "",
        result.algorithm_version,
        ",".join(sorted(calc["calculation_id"] for calc in calculations)),
        ",".join(rule_versions),
    ]).encode("utf-8")).hexdigest()[:16]
    return {
        "algorithm_version": result.algorithm_version,
        "settlement_ref": result.settlement_ref or "",
        "evidence_id": f"fee-evidence:{digest}",
        "rule_versions": rule_versions,
        "branch_count": len(result.branches),
        "full_trace_in_public": False,
    }


def _stage_views(result, step_views: list[dict], condition_views: list[dict], fields: list[dict],
                 uncertainty_views: list[dict]) -> list[dict]:
    """按业务环节评价完整性：已验证什么、采用什么前提、还缺什么。"""
    by_step = {step["step_id"]: step for step in step_views}
    by_field = {field["field_code"]: field for field in fields}
    stages: list[dict] = []
    for stage_id, label, path_ids in _STAGE_DEFS:
        steps = [by_step[path_id] for path_id in path_ids if path_id in by_step]
        if not steps:
            continue
        step_fields = {ref for step in steps for ref in step["field_refs"] if ref in by_field}
        condition_refs = {ref for step in steps for ref in (step.get("condition_refs") or [])}
        stage_conditions = [row for row in condition_views if row["step_id"] in condition_refs]
        verified = [f"{row['description']}（{row['actual_display']}）" for row in stage_conditions if row["outcome"] == "true"]
        premise = [f"{row['description']}（{row['actual_display']}）" for row in stage_conditions
                   if row["outcome"] in ("unknown", "blocked", "not_evaluated")]
        missing = [row["code"] for row in uncertainty_views if step_fields.intersection(row["affected_fields"])]
        statuses = {step["status"] for step in steps}
        if statuses == {"not_applicable"}:
            status = "not_applicable"
        elif premise:
            status = "partial"
        elif statuses <= {"unknown"}:
            status = "unavailable"
        else:
            status = "verified"
        stages.append({"stage_id": stage_id, "label": label, "status": status,
                       "verified": verified, "premise": premise, "missing": missing})
    hospital = [field for code, field in by_field.items() if code in _HOSPITAL_FIELDS or code.startswith("QUOTA.")]
    if hospital:
        verified = [field["label"] for field in hospital if field["check_status"] == "matched"]
        premise = [field["label"] for field in hospital if field["check_status"] != "matched"]
        missing = [row["code"] for row in uncertainty_views
                   if set(field["field_code"] for field in hospital).intersection(row["affected_fields"])]
        stages.append({"stage_id": "hospital", "label": "医院定额清算",
                       "status": "verified" if verified and not premise else ("partial" if verified else "unavailable"),
                       "verified": verified, "premise": premise, "missing": missing})
    return stages


def _index_with_conflicts(items, key):
    """按 ID 建索引；重复 ID 内容不同视为关联歧义，整体剔除（不任取一条）。"""
    index: dict[str, Any] = {}
    conflicts: set[str] = set()
    for item in items:
        ident = key(item)
        if ident in index:
            if index[ident] != item:
                conflicts.add(ident)
            continue
        index[ident] = item
    for ident in conflicts:
        index.pop(ident, None)
    return index, conflicts


def _calculation_dependencies(refs, index) -> list[str]:
    """仅沿真实操作数引用展开上游记录，按输入先于结果排列，重复/环引用不重复展开。"""
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(ref):
        if ref in seen or ref not in index:
            return
        seen.add(ref)
        for operand in index[ref].operands:
            visit(operand.ref)
        ordered.append(ref)

    for ref in refs:
        visit(ref)
    return ordered


#: 已知 input.* 上游输入引用的业务名（计算中间量；未知名回落"本单输入数据项"）
_INPUT_REF_LABELS = {
    "input.secondary.self_pay_1_after_supplements": "补助后合规自付一",
    "input.secondary.proportional_self_pay_2": "比例先行自付",
    "input.secondary.current_compliant_base": "本笔合规个人负担基数",
    "input.secondary.first_band_overlap": "第一段重叠金额",
    "input.secondary.second_band_overlap": "第二段重叠金额",
    "input.secondary.zero_base": "零基数",
    "input.secondary.total_out_scope": "医保外费用",
    "input.secondary.remaining_base": "大病后剩余基数",
}


def _operand_view(
    operand,
    field_labels: dict[str, str],
    calc_names: dict[str, str],
) -> dict:
    """操作数 → 公开视图：统一中文展示名；中间量显式标识，不冒充账面字段。"""
    ref, value = operand.ref, operand.value
    if ref in field_labels:
        return {"display_name": field_labels[ref], "value": value, "is_intermediate": False}
    if ref.startswith("calc."):
        # 只链接显式记录的计算；未记录的 calc.* 作为已知输入的业务值展示（方案 §渐进解释 5）
        name = calc_names.get(ref)
        return {
            "display_name": name or "计算中间量",
            "value": value,
            "is_intermediate": True,
        }
    if ref.startswith("rule."):
        return {
            "display_name": f"规则参数（{ref[len('rule.'):]}）",
            "value": value,
            "is_intermediate": True,
        }
    if ref.startswith("input."):
        return {
            "display_name": _INPUT_REF_LABELS.get(ref, "本单输入数据项"),
            "value": trim_trailing_zeros(value),
            "is_intermediate": True,
        }
    if ref.startswith("fact."):
        # 结算/明细事实的安全业务引用：物理路径不透传，仅给通用业务名与值
        return {"display_name": "结算记录数据项", "value": trim_trailing_zeros(value),
                "is_intermediate": False}
    return {"display_name": "本单数据项", "value": trim_trailing_zeros(value),
            "is_intermediate": False}


def _calculation_view(
    calc: CalculationRecordModel,
    field_labels: dict[str, str],
    calc_names: dict[str, str],
) -> dict:
    display = formula_display(calc.formula_id)
    operands = [_operand_view(o, field_labels, calc_names) for o in calc.operands]
    return {
        "calculation_id": calc.calculation_id,
        "display_name": display.display_name,
        "formula_id": calc.formula_id,
        "formula_version": calc.formula_version,
        "layout": display.layout,
        "operands": operands,
        "formula": calculation_formula(calc, operands),
        "unrounded_result": None if calc.rounding_rule == "settlement_record" else calc.unrounded_result,
        "rounding_rule": rounding_display(calc.rounding_rule),
        "result": calc.result,
    }


def _source_view(citation) -> dict | None:
    """来源 → 公开安全视图；不允许的类别返回 None（默认拒绝自由文本）。"""
    category = _SOURCE_CATEGORY.get(citation.kind)
    if category is None:
        return None
    # 链接只接受 https 协议与已核实的公开目标；其余（本地路径/内部文档）不下发
    ref = citation.ref or ""
    link = ref if ref.startswith("https://") else None
    if category == "settlement_record":
        return {
            "ref_id": citation.id,
            "title": _SETTLEMENT_FACT_TITLE,
            "category": category,
            "confirmation_status": None,
            "value": citation.value,
            "values": list(citation.values),
            "link": None,
        }
    return {
        "ref_id": citation.id,
        "title": ref if ref and not link else citation.value or "政策依据",
        "category": category,
        "confirmation_status": citation.approval_status,
        "value": None,
        "values": list(citation.values),
        "link": link,
    }


def _condition_views(result: SettlementDecompositionResult) -> list[dict]:
    """采用条件投影：业务描述 + 实际/期望展示值 + 判断结果；condition 为空合法。"""
    views = []
    for branch in result.branches:
        condition = branch.condition
        if condition is None or branch.module_id in _CONDITION_EXCLUDED_MODULES:
            continue
        views.append({
            "step_id": branch.step_id,
            "module_label": _MODULE_LABELS.get(branch.module_id, _UNKNOWN_MODULE_LABEL),
            "description": condition.description,
            "actual_display": condition.actual_value,
            "expected_display": condition.expected_ref,
            "outcome": branch.outcome,
            "calculation_refs": list(branch.calculation_refs),
        })
    return views


def _operand_phrase(calc_view: dict) -> str:
    """操作数中文短语：sum 布局按符号加减相连；product 为基数×比例；generic 逐项列出。"""
    operands = calc_view["operands"]
    if not operands:
        return ""
    layout = calc_view.get("layout", "generic")
    if layout == "product" and len(operands) >= 2:
        head = f"{operands[0]['display_name']} {operands[0]['value']} 元"
        factors = " × ".join(
            f"{o['display_name']} {o['value']}" for o in operands[1:]
        )
        return f"{head} × {factors}"
    if layout == "subtract_rest":
        # 首项减其余各项：操作数按无符号存储值展示，减号由布局给出
        head = f"{operands[0]['display_name']} {operands[0]['value']} 元"
        rest = " ".join(f"－ {o['display_name']} {o['value']} 元" for o in operands[1:])
        return f"{head} {rest}".strip()
    if layout == "sum":
        parts = []
        for op in operands:
            value = op["value"]
            if value.startswith("-"):
                parts.append(f"－ {op['display_name']} {value[1:]} 元")
            elif parts:
                parts.append(f"＋ {op['display_name']} {value} 元")
            else:
                parts.append(f"{op['display_name']} {value} 元")
        return " ".join(parts)
    return "、".join(f"{o['display_name']} {o['value']}" for o in operands)


def _field_brief(field, calc_refs: list[str], calc_view_by_id: dict[str, dict]) -> str | None:
    """字段级 1—2 句确定性构成简述（方案 §中文公式 4：先解释本次构成）。

    只使用已有字段/计算数据，不补比例、不猜公式；identity_check 保留账面勾稽限定；
    无计算记录时给出准确的缺口说明，不把账面值包装成已解释。
    """
    if (field.reason_code == "SELF_PAY_1_BOOK_COLUMN_UNMAINTAINED"
            and field.calculated_amount is not None):
        return (f"{field.label}：该列在已核样本中未维护，当前金额 {field.calculated_amount} 元"
                "由本单分量计算，不作账面核对。")
    if field.calculation_refs and not calc_refs:
        return "本项计算步骤未完整记录，暂不能展开来源与算式。"
    if not calc_refs:
        if field.check_status == "not_applicable":
            return "本单不适用。"
        if field.observed_amount is not None and field.calculated_amount is None:
            return f"结算记录 {field.observed_amount} 元，暂不能独立计算。"
        if field.check_type == "identity_check" and field.calculated_amount is not None:
            return (
                f"账面勾稽：计算值 {field.calculated_amount} 元；"
                "各分量关系未逐步记录，仅核对账面关系。"
            )
        return None
    resolved = [calc_view_by_id[r] for r in calc_refs]
    if field.check_type == "identity_check":
        calc_view = resolved[-1]
        if calc_view.get("formula"):
            return (f"{field.label}：本字段计算值 {field.calculated_amount or '未知'} 元；"
                    f"关联记录：{calc_view['formula']}（账面勾稽，仅核对各分量关系，不单独证明各字段原因）。")
        phrase = _operand_phrase(calc_view)
        result_text = calc_view["result"] or field.calculated_amount or "未知"
        return (
            f"{field.label} {result_text} 元 ＝ {phrase}"
            "（账面勾稽，仅核对各分量关系，不单独证明各字段原因）。"
        )
    if len(resolved) == 1:
        calc_view = resolved[0]
        if calc_view.get("formula"):
            return calc_view["formula"]
        phrase = _operand_phrase(calc_view)
        display = calc_view["display_name"]
        # 内部 label 已以"本次"开头（如"本次起付承担"）时不再叠加前缀
        prefix = "" if field.label.startswith("本次") else "本次"
        if phrase:
            return f"{prefix}{field.label}按{display}计算：{phrase}，得 {calc_view['result']} 元。"
        return f"{prefix}{field.label}按{display}计算，得 {calc_view['result']} 元。"
    # 多步骤字段：渲染终端公式及理解公式所需的上游基数（沿 calculation_ref 实际依赖
    # 选取、去重；终端 = 字段直接关联的计算），不再使用"经 N 步得出，可展开查看"占位说明。
    prefix = "" if field.label.startswith("本次") else "本次"
    terminal_ids = [ref for ref in field.calculation_refs if ref in calc_view_by_id]
    terminals = [calc_view_by_id[ref] for ref in terminal_ids] or [resolved[-1]]
    parts: list[str] = []
    for view in terminals:
        if view.get("formula"):
            parts.append(view["formula"])
            continue
        phrase = _operand_phrase(view)
        display = view["display_name"]
        result_text = view["result"] or "未知"
        if phrase:
            parts.append(f"按{display}计算：{phrase}，得 {result_text} 元。")
        else:
            parts.append(f"按{display}计算，得 {result_text} 元。")
    upstream: list[str] = []
    seen = {view["calculation_id"] for view in terminals}
    for view in terminals:
        for operand in view["operands"]:
            ref = operand.get("calculation_ref")
            if not ref or ref in seen or ref not in calc_view_by_id:
                continue
            seen.add(ref)
            upstream_view = calc_view_by_id[ref]
            if upstream_view.get("formula"):
                upstream.append(upstream_view["formula"])
            elif upstream_view.get("result") is not None:
                upstream.append(f"{upstream_view['display_name']} {upstream_view['result']} 元")
    text = f"{prefix}{field.label}：" + "；".join(parts)
    if upstream:
        text += "；上游基数：" + "；".join(upstream)
    return text


# ── 正向结算路径投影（解释投影 1.2，方案 §55：从费用明细到个人应付）────────
#
# 步骤由本单 branches 实际执行的模块归并（不由前端正排）；未执行的模块不出现该步。
# 状态语义：applied=已结算出金额；zero_amount=已结算但金额为零（零金额≠不适用）；
# not_applicable=该步全部分支 outcome=not_applicable；unknown=无法确定（保留）；
# observed_only=无结算 calc 但字段有账面观测值（不升级为已解释）。
# 金额规则：单金额步取该步结算 calc.result；一步多个金额（如补助=退休+军残+公疗）
# amount 取 None，各金额由 field_refs 展开——后端不加总出新数（不补算）。


@dataclass(frozen=True)
class _PathStepSpec:
    """路径步骤白名单：触发模块 + headline 金额候选 calc + 关联公开字段。"""

    step_id: str
    name: str
    modules: tuple[str, ...]  # 空 = 恒出现步（个人支付/支付方式，按字段存在性门控）
    amount_calc_ids: tuple[str, ...]
    field_codes: tuple[str, ...]


_PATH_STEP_SPECS: tuple[_PathStepSpec, ...] = (
    _PathStepSpec(
        "path.fee_items", "费用明细",
        ("catalog_split", "detail_aggregation"),
        ("calc.catalog.total_fee",),
        ("T_FeeAll", "ZJE")),
    _PathStepSpec(
        "path.catalog_split", "目录划分",
        ("catalog_split", "detail_aggregation"),
        ("calc.catalog.total_in_scope", "calc.catalog.total_out_scope", "calc.detail.total_in_scope"),
        ("T_FeeIn", "T_FeeOut", "T_SelfPay2", "YBN", "YBW", "TSBYBN", "TSBYBW", "GRZIFTW")),
    _PathStepSpec(
        "path.deductible", "起付",
        ("deductible", "resident_deductible", "resident_special_deductible"),
        ("calc.deductible.split",),
        ("T_FirstPay", "YBNQFJE")),
    _PathStepSpec(
        "path.fund", "统筹/大额支付",
        ("big_pay", "resident_big_pay", "resident_msf_pay", "pool_fund", "large_fund", "fixed_quota",
         "resident_special_pool", "resident_special_big_pay"),
        ("calc.big_pay.capped", "calc.big_pay.segmented",
         "calc.pool.segmented", "calc.large.settle", "calc.msf_pay.full", "calc.fixed.hospital_fund"),
        ("T_BigPay", "T_BigSelfPay", "TCZHF", "TCZIF", "DEGWYZHF", "DEGWYZIF")),
    _PathStepSpec(
        "path.supplements", "补助",
        ("retire_supplement", "military_supplement", "public_medical"),
        ("calc.rsup.amount", "calc.rsup.pool", "calc.rsup.large",
         "calc.dvet.amount", "calc.pmed.amount"),
        ("T_BCPay", "T_JCPay", "T_OfficalPay", "BCZHF", "JCZHF", "GFYLBCHBX")),
    _PathStepSpec(
        "path.secondary", "大病/救助",
        ("secondary_coverage", "resident_bigill_pay"),
        ("calc.bigill_pay.pay", "calc.secondary.big_ill_pay", "calc.secondary.civil_in"),
        ("T_BigillPay", "NT_CivilPay", "BIG_ILL_PAY", "CIVIL_IN",
         "FEEIN_DB_PAY", "FEEOUT_DB_PAY", "FEEIN_MAF_PAY", "FEEOUT_MAF_PAY")),
    _PathStepSpec(
        "path.personal_total", "个人支付总金额",
        (),
        ("calc.identity.self_pay_all", "calc.bigill_pay.self_pay_all", "calc.secondary.person_payable"),
        ("T_SelfPayAll", "PERSON_PAYABLE")),
    _PathStepSpec(
        "path.payment_method", "支付方式",
        (),
        ("calc.identity.self_pay_all_channel", "calc.identity.xjzf_channel"),
        ("T_PersonCountPay", "T_CashPay", "XJZF", "ZHZF")),
)

#: 分支 outcome → 一句采用理由中的判断结果措辞
_OUTCOME_WORDS = {
    "true": "命中",
    "false": "未命中",
    "unknown": "无法确定",
    "not_evaluated": "未评估",
    "blocked": "被阻断",
    "not_applicable": "不适用",
}


def _is_zero_amount(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return Decimal(value) == 0
    except InvalidOperation:
        return False


def _step_reason(branches: list, resolved_calc_ids: list[str]) -> str | None:
    """一句采用理由：优先取结算 calc 所在分支的 condition；无 condition 则 None。

    明细级逐行分支（catalog_split/detail_aggregation）与主干条件列表同款排除：
    明细展开属各字段计算记录范畴，不作为路径步骤的采用理由。
    """
    branches = [b for b in branches if b.module_id not in _CONDITION_EXCLUDED_MODULES]
    primary = None
    if resolved_calc_ids:
        target = resolved_calc_ids[0]
        primary = next(
            (b for b in branches if target in b.calculation_refs and b.condition is not None),
            None)
    if primary is None:
        conditioned = [b for b in branches if b.condition is not None]
        primary = conditioned[-1] if conditioned else None
    if primary is None or primary.condition is None:
        return None
    condition = primary.condition
    parts = [condition.description]
    detail = []
    if condition.actual_value is not None:
        detail.append(f"实际 {condition.actual_value}")
    if condition.expected_ref is not None:
        detail.append(f"期望 {condition.expected_ref}")
    if detail:
        parts.append("（" + "，".join(detail) + "）")
    parts.append(f"→ {_OUTCOME_WORDS.get(primary.outcome, primary.outcome)}")
    return "".join(parts)


def _path_step_views(result: SettlementDecompositionResult) -> list[dict]:
    """结果 → 正向结算路径公开视图（纯函数、不查库；缺引用降级到可解析集合）。"""
    calc_index, _conflicts = _index_with_conflicts(
        result.calculations, lambda c: c.calculation_id)
    field_by_code = {f.field_code: f for f in result.fields}
    no_benefit = [b for b in result.branches
                  if b.step_id == "flow.no_benefit_check" and b.outcome == "true"]

    steps: list[dict] = []
    for spec in _PATH_STEP_SPECS:
        branches = [b for b in result.branches if b.module_id in spec.modules]
        if not branches and spec.step_id in ("path.fee_items", "path.personal_total"):
            branches = no_benefit
        fields = [field_by_code[c] for c in spec.field_codes if c in field_by_code]
        if spec.modules:
            if not branches:
                continue  # 模块未执行则不出现该步
        elif not fields:
            continue  # 个人支付/支付方式：恒出现但仅以字段存在为前提

        # 金额候选解析：仅保留能在 calculations 索引里解析且有结果的
        amount_ids = spec.amount_calc_ids
        fixed_fund = spec.step_id == "path.fund" and any(b.module_id == "fixed_quota" for b in branches)
        if fixed_fund:
            amount_ids = ("calc.fixed.hospital_fund",)
            branches = [b for b in branches if b.module_id == "fixed_quota"]
        resolved = [cid for cid in amount_ids
                    if cid in calc_index and calc_index[cid].result is not None]
        calc_refs = list(resolved)
        other_step_calcs = {cid for other in _PATH_STEP_SPECS if other is not spec
                            for cid in other.amount_calc_ids}
        for branch in branches:
            for ref in branch.calculation_refs:
                if ref in calc_index and ref not in calc_refs and ref not in other_step_calcs:
                    calc_refs.append(ref)

        amount: str | None = None
        if spec.modules and all(b.outcome == "not_applicable" for b in branches):
            status = "not_applicable"
        elif spec.modules and any(b.outcome in ("unknown", "blocked", "not_evaluated") for b in branches):
            status = "unknown"
        elif len(resolved) == 1:
            amount = calc_index[resolved[0]].result
            status = "zero_amount" if _is_zero_amount(amount) else "applied"
        elif len(resolved) > 1:
            status = ("zero_amount" if all(_is_zero_amount(calc_index[cid].result)
                                          for cid in resolved) else "applied")
        else:
            observed = [f.observed_amount for f in fields if f.observed_amount is not None]
            if observed:
                status = "observed_only"
                amount = observed[0] if len(observed) == 1 else None
            else:
                status = "unknown"
        name = spec.name
        if fixed_fund:
            name = "医院定额基金（条件口径）"
        elif spec.step_id == "path.catalog_split" and not any(b.module_id == "catalog_split" for b in branches):
            name = "明细已有划分汇总"
        steps.append({
            "step_id": spec.step_id,
            "name": name,
            "status": status,
            "amount": amount,
            "calculation_refs": _calculation_dependencies(calc_refs, calc_index),
            "field_refs": [f.field_code for f in fields],
            "reason": _step_reason(branches, resolved),
            "condition_refs": [b.step_id for b in branches if b.condition is not None and b.module_id not in _CONDITION_EXCLUDED_MODULES],
        })
    return steps


def to_public_contract_dict(
    result: SettlementDecompositionResult,
    *,
    summary_text: str,
    summary_source: str,
    sanitize: Callable[[Any], str],
    settlement_facts: SettlementFactsView | None = None,
) -> dict:
    """公开投影 + 全量文本消毒（两路由共用的唯一入口）。

    sanitize 为路由层的公开文本消毒函数（如 policy_qa_routes._public_text）；
    覆盖所有公开字符串叶，含 sources.value/values、link 之外的文本数组；
    1.2 起覆盖 settlement_facts 全部字符串叶与 path_steps 的 name/reason。
    """
    view = build_public_view_dict(
        result, summary_text=summary_text, summary_source=summary_source,
        settlement_facts=settlement_facts)
    view["summary_text"] = sanitize(view["summary_text"])
    for field in view["fields"]:
        field["label"] = sanitize(field["label"])
        if field["brief"]:
            field["brief"] = sanitize(field["brief"])
    for uncertainty in view["uncertainties"]:
        uncertainty["message"] = sanitize(uncertainty["message"])
    for calc in view["calculations"]:
        if calc["formula"]:
            calc["formula"] = sanitize(calc["formula"])
        calc["display_name"] = sanitize(calc["display_name"])
        if calc["rounding_rule"]:
            calc["rounding_rule"] = sanitize(calc["rounding_rule"])
        for operand in calc["operands"]:
            operand["display_name"] = sanitize(operand["display_name"])
    for source in view["sources"]:
        source["title"] = sanitize(source["title"])
        if source["value"]:
            source["value"] = sanitize(source["value"])
        source["values"] = [sanitize(v) for v in source["values"]]
        if source["confirmation_status"]:
            source["confirmation_status"] = sanitize(source["confirmation_status"])
    for condition in view["conditions"]:
        condition["module_label"] = sanitize(condition["module_label"])
        condition["description"] = sanitize(condition["description"])
        if condition["actual_display"]:
            condition["actual_display"] = sanitize(condition["actual_display"])
        if condition["expected_display"]:
            condition["expected_display"] = sanitize(condition["expected_display"])
    for step in view["path_steps"]:
        step["name"] = sanitize(step["name"])
        if step["reason"]:
            step["reason"] = sanitize(step["reason"])
    facts = view["settlement_facts"]
    if facts is not None:
        if "metadata_names" in facts:
            facts["metadata_names"] = {key: sanitize(value) for key, value in facts["metadata_names"].items()}
        for key in ("identifier", "trade_date", "medical_category",
                    "insurance_type", "person_type", "hospital_level", "retire_officer_flag"):
            if facts[key]:
                facts[key] = sanitize(facts[key])
        for item in (*facts["items"], *facts["payment_items"]):
            item["label"] = sanitize(item["label"])
            if item["value"] is not None:
                item["value"] = sanitize(item["value"])
    # 新证据块覆盖所有文本叶，防止参数来源、理由或条件值绕过消毒。
    def clean(value):
        if isinstance(value, str):
            return sanitize(value)
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value
    view["formula_inputs"] = clean(view["formula_inputs"])
    view["rule_choices"] = clean(view["rule_choices"])
    view["fee_items"] = clean(view["fee_items"])
    if facts is not None and facts.get('display_template'):
        facts['display_template'] = clean(facts['display_template'])
    for field in view["fields"]:
        if field.get("explanation_reason"):
            field["explanation_reason"] = sanitize(field["explanation_reason"])
        if field.get("explanation"):
            field["explanation"] = clean(field["explanation"])
    view["template_explanations"] = clean(view["template_explanations"])
    for calc in view["calculations"]:
        if calc.get("verification_reason"):
            calc["verification_reason"] = sanitize(calc["verification_reason"])
    return view
