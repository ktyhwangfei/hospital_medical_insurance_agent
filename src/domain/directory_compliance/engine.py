"""合规核验执行引擎（Issue #85，设计 V2.0 §7）。

纯确定性函数：规则 AST + 行上下文 + 值域映射 → 行级裁定。
纪律：
- 占位诊断不算不符合（insufficient_evidence，不是 contradicted）；
- 真实诊断未见相符记录也不构成反证（缺失≠冲突），contradicted 只来自
  价格超限、机构/人群不符等事实冲突；
- 价格核验先规格换算再比价，换算不了判 insufficient_evidence，禁止直接比价；
- 缺映射 fail-closed 判 unverifiable 并指明缺哪条。
"""
from __future__ import annotations

import re

from decimal import Decimal, InvalidOperation
from typing import Iterable

from src.domain.directory_compliance.models import (
    ComplianceRiskTier,
    ComplianceRule,
    ConditionEvidence,
    ConditionVerdict,
    FieldReadStatus,
    LineComplianceResult,
    MappingScope,
    MappingTargetType,
    MatchStatus,
    PriceBasis,
    RestrictionConditionType,
    RuleCondition,
    RuleLookupResult,
    RuleLookupStatus,
    RuleStatus,
    SettlementLineContext,
    ValueDomain,
    ValueDomainMapping,
    VerdictStatus,
)

# 占位值形态：空、纯数字短码（"1"/"01"/"11"）等，非 ICD 编码形态
_PLACEHOLDER_RE = re.compile(r"^\s*$|^\d{1,3}$")
_ICD_CODE_RE = re.compile(r"^[A-Z]\d{2}(?:\.[A-Z0-9]+)?$", re.IGNORECASE)

# 规格解析：如 "10MG/支"、"100ml：0.9g"（取含量/计价单位对）
_SPEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|g|ug|μg|ml)\s*[/／：:]\s*([^\s/／：:]+)?", re.IGNORECASE)
_CAP_UNIT_RE = re.compile(r"(支|瓶|粒|盒|袋|片)$")
# 包装单位全集：多级规格（如 "176ML/瓶 2瓶/盒"）出现多个即视为定价单位歧义，必须走换算映射
_PACK_UNITS_RE = re.compile(r"(支|瓶|粒|盒|袋|片|板|罐)")

_SCOPE_PRIORITY = (MappingScope.HOSPITAL, MappingScope.REGIONAL, MappingScope.DEFAULT)
_READ_STATUS_LABELS = {
    FieldReadStatus.EMPTY: "已查询但字段或记录为空",
    FieldReadStatus.PLACEHOLDER: "字段为占位值",
    FieldReadStatus.INVALID: "字段或关联依据无效",
    FieldReadStatus.NOT_AVAILABLE: "当前未接入该字段来源",
    FieldReadStatus.FETCH_FAILED: "字段查询失败",
    FieldReadStatus.AMBIGUOUS: "存在多条来源，无法唯一关联",
}


def is_placeholder_text(value: str) -> bool:
    """判断源字段是否为占位值（"1"/"01"/空串等）。占位不算不符合。"""
    return bool(_PLACEHOLDER_RE.match(value or ""))


def resolve_mappings(
    mappings: Iterable[ValueDomainMapping],
    domain: ValueDomain,
    concept_code: str,
    hospital_code: str = "",
    region_code: str = "",
) -> tuple[ValueDomainMapping, ...]:
    """按作用域优先级解析概念码映射：hospital > regional > default。

    返回命中作用域的全部绑定行；无映射返回空元组（调用方 fail-closed）。
    """
    candidates = [
        m for m in mappings
        if m.domain == domain and m.concept_code == concept_code
    ]
    for scope in _SCOPE_PRIORITY:
        scoped = [
            m for m in candidates
            if m.scope == scope and (scope == MappingScope.DEFAULT or m.scope_key == (
                hospital_code if scope == MappingScope.HOSPITAL else region_code
            ))
        ]
        if scoped:
            return tuple(scoped)
    return ()


def _field_gap(condition: RuleCondition, line: SettlementLineContext, *keys: str) -> ConditionVerdict | None:
    values = {"price.unit_price": line.unit_price, "item.specification": line.specification,
              "item.count": line.count, "price.payment_base": line.payment_base}
    for key in keys:
        state = line.field_states.get(key)
        if state is None or state.status != FieldReadStatus.PRESENT:
            status = (VerdictStatus.INSUFFICIENT_EVIDENCE if state and state.status in (
                FieldReadStatus.EMPTY, FieldReadStatus.PLACEHOLDER, FieldReadStatus.INVALID,
            ) else VerdictStatus.UNVERIFIABLE)
            reason = (state.reason or _READ_STATUS_LABELS[state.status]) if state else "未提供取得状态"
            return ConditionVerdict(condition=condition, status=status, missing=f"{key}：{reason}")
        if state.association not in ("same_line", "same_prescription"):
            return ConditionVerdict(condition=condition, status=VerdictStatus.INSUFFICIENT_EVIDENCE,
                                    missing=f"{key} 缺少本行/同处方关联依据")
        if key in values and (values[key] is None or values[key] == ""):
            return ConditionVerdict(condition=condition, status=VerdictStatus.INSUFFICIENT_EVIDENCE,
                                    missing=f"{key} 已查询但值为空")
    return None


def locate_rule(line: SettlementLineContext, rules: Iterable[ComplianceRule]) -> RuleLookupResult:
    """字段确实取得后才定位；草稿只作为诊断候选返回，不成为命中。"""
    for key in ("item.code", "fee.date", "catalog"):
        state = line.field_states.get(key)
        if state and state.status == FieldReadStatus.AMBIGUOUS:
            return RuleLookupResult(status=RuleLookupStatus.AMBIGUOUS, reason=f"{key} 来源歧义")
        if state is None or state.status != FieldReadStatus.PRESENT or state.association != "same_line":
            reason = (state.reason or _READ_STATUS_LABELS.get(state.status, "缺少本行关联依据")) if state else "未提供取得状态"
            return RuleLookupResult(status=RuleLookupStatus.NOT_EVALUATED, reason=f"{key}：{reason}，未执行规则匹配")
    if (line.catalog_effective_from is None or line.catalog_effective_to is None
            or not line.catalog_effective_from <= line.trade_date <= line.catalog_effective_to):
        return RuleLookupResult(status=RuleLookupStatus.NOT_EVALUATED, reason="当日目录版本未确认")
    if not line.item_code.strip():
        return RuleLookupResult(status=RuleLookupStatus.NOT_EVALUATED, reason="项目编码为空")
    catalog_bz = (line.catalog_bz or "").strip()
    if not catalog_bz:
        return RuleLookupResult(status=RuleLookupStatus.NOT_FOUND, reason="当日目录未记载本类限制")
    candidates = tuple(r for r in rules if r.item_code == line.item_code
                       and r.catalog_effective_from <= line.trade_date <= r.catalog_effective_to
                       and r.source_bz.strip() == catalog_bz)
    published = tuple(r for r in candidates if r.status == RuleStatus.PUBLISHED)
    if len(published) > 1:
        return RuleLookupResult(status=RuleLookupStatus.AMBIGUOUS, reason="适用的已发布规则区间重叠")
    if published:
        return RuleLookupResult(status=RuleLookupStatus.MATCHED, reason="取得唯一适用的已发布规则", rule=published[0])
    drafts = tuple(r for r in candidates if r.status == RuleStatus.DRAFT)
    return RuleLookupResult(status=RuleLookupStatus.NOT_FOUND,
                            reason="限制原文已取得，规则待审核发布" if drafts else "限制原文已取得，无适用规则",
                            rule=drafts[0] if len(drafts) == 1 else None)


def _verify_disease(
    condition: RuleCondition,
    line: SettlementLineContext,
    mappings: Iterable[ValueDomainMapping],
) -> ConditionVerdict:
    resolved = resolve_mappings(mappings, ValueDomain.DIAGNOSIS, condition.concept_code,
                                line.hospital_code, line.region_code)
    if not resolved:
        return ConditionVerdict(
            condition=condition,
            status=VerdictStatus.UNVERIFIABLE,
            evidence=(ConditionEvidence(
                kind="mapping_missing",
                summary=f"概念码 {condition.concept_code} 无有效 diagnosis 值域映射，fail-closed 不予核验",
                source="value_domain_mappings",
            ),),
            missing=f"缺少 {condition.concept_code} 的诊断值域映射",
        )
    approved = tuple(m for m in resolved if m.reviewed_by.strip())
    if not approved:
        return ConditionVerdict(condition=condition, status=VerdictStatus.UNVERIFIABLE,
                                missing=f"{condition.concept_code} 值域映射待审核")
    gap = _field_gap(condition, line, "diagnosis.code")
    if gap:
        return gap
    icd_mappings = tuple(m for m in approved if m.target_type == MappingTargetType.ICD_PREFIX)

    diagnoses = line.same_recipe_diagnoses
    if not diagnoses:
        return ConditionVerdict(
            condition=condition,
            status=VerdictStatus.INSUFFICIENT_EVIDENCE,
            missing="同处方无诊断记录",
        )
    if all(is_placeholder_text(d.code or "") and is_placeholder_text(d.name or "") for d in diagnoses):
        return ConditionVerdict(
            condition=condition,
            status=VerdictStatus.INSUFFICIENT_EVIDENCE,
            evidence=(ConditionEvidence(
                kind="placeholder_input",
                summary="同处方诊断编码与名称均为占位值，不能据此判定病种条件不符",
                source="o_Diagnose",
            ),),
            missing="同处方诊断为占位值",
        )
    diagnoses = tuple(d for d in diagnoses if d.association == "same_prescription")
    if not diagnoses:
        return ConditionVerdict(condition=condition, status=VerdictStatus.INSUFFICIENT_EVIDENCE,
                                missing="缺少可靠的同处方诊断关联")
    diagnoses = tuple(d for d in diagnoses if d.code and _ICD_CODE_RE.fullmatch(d.code))
    if not diagnoses:
        return ConditionVerdict(condition=condition, status=VerdictStatus.INSUFFICIENT_EVIDENCE,
                                missing="同处方诊断编码为空、占位或无效；名称/病历仅作线索")
    for d in diagnoses:
        hits = tuple(m.mapping_id for m in icd_mappings if d.code and d.code.startswith(m.target_value))
        if hits:
            return ConditionVerdict(
                condition=condition,
                status=VerdictStatus.SUPPORTED,
                match_status=MatchStatus.MATCHED,
                used_mapping_ids=hits,
                evidence=(ConditionEvidence(
                    kind="diagnosis_match",
                    summary=f"同处方诊断编码 {d.code} 命中经审核的条件映射「{condition.source_span}」",
                    source=f"{line.field_states['diagnosis.code'].source}; code={d.code}",
                ),),
            )
    # 真实诊断但未见相符记录：缺失不等于冲突，判资料不足而非反证
    listed = "、".join(d.code or "" for d in diagnoses if not is_placeholder_text(d.code or ""))
    return ConditionVerdict(
        condition=condition,
        status=VerdictStatus.INSUFFICIENT_EVIDENCE,
        match_status=MatchStatus.NOT_MATCHED if icd_mappings else MatchStatus.NOT_EVALUATED,
        evidence=(ConditionEvidence(
            kind="diagnosis_absent",
            summary=f"同处方诊断编码（{listed}）未能支持「{condition.source_span}」；名称或病历关键词仅作线索，未记载不等于条件不成立",
            source=line.field_states["diagnosis.code"].source,
        ),),
        missing=f"同方诊断中未见与「{condition.source_span}」相符的记录",
    )


def _parse_spec(specification: str) -> tuple[Decimal, str, str] | None:
    """解析 HIS 规格为 (含量, 含量单位, 计价单位)。如 '10MG/支' → (10, 'mg', '支')。"""
    match = _SPEC_RE.search(specification or "")
    if not match:
        return None
    strength, strength_unit, unit = match.groups()
    if not unit:
        unit_match = _CAP_UNIT_RE.search((specification or "").strip())
        if not unit_match:
            return None
        unit = unit_match.group(1)
    normalized_unit = strength_unit.lower()
    multiplier = {"g": Decimal("1000"), "ug": Decimal("0.001"), "μg": Decimal("0.001")}.get(normalized_unit, Decimal(1))
    return Decimal(strength) * multiplier, "ml" if normalized_unit == "ml" else "mg", unit


def _verify_price_cap(
    condition: RuleCondition,
    line: SettlementLineContext,
    mappings: Iterable[ValueDomainMapping],
) -> ConditionVerdict:
    cap = condition.price_cap
    if cap is None:
        return ConditionVerdict(condition=condition, status=VerdictStatus.UNVERIFIABLE,
                                missing="价格条件缺少支付标准参数")
    if cap.basis == PriceBasis.UNKNOWN:
        return ConditionVerdict(condition=condition, status=VerdictStatus.UNVERIFIABLE,
                                missing="价格政策适用口径尚未确认")
    gap = _field_gap(condition, line, "price.unit_price", "item.specification")
    if gap:
        return gap
    assert line.unit_price is not None
    parsed = _parse_spec(line.specification or "")
    if parsed is None:
        return ConditionVerdict(
            condition=condition,
            status=VerdictStatus.INSUFFICIENT_EVIDENCE,
            missing=f"HIS 规格「{line.specification}」无法解析，禁止未换算直接比价",
        )
    strength, strength_unit, unit = parsed
    cap_strength = _parse_spec(f"{cap.strength_text}/{cap.unit}")
    if cap_strength is None or (strength, strength_unit) != cap_strength[:2]:
        return ConditionVerdict(
            condition=condition,
            status=VerdictStatus.INSUFFICIENT_EVIDENCE,
            missing=f"本行规格 {strength}{strength_unit} 与支付标准规格 {cap.strength_text} 不一致，需对应规格的支付标准",
        )
    distinct_units = set(_PACK_UNITS_RE.findall(line.specification or ""))
    multiplier = Decimal(1)
    used_mapping_ids: tuple[str, ...] = ()
    if distinct_units == {cap.unit}:
        effective_price = line.unit_price
        conversion_note = "规格单位一致，直接可比"
    else:
        conversion = resolve_mappings(
            mappings, ValueDomain.PRICE_UNIT, f"pack.{line.item_code}", line.hospital_code, line.region_code
        )
        conversion = tuple(m for m in conversion if m.target_type == MappingTargetType.SPEC_CONVERSION and m.reviewed_by.strip())
        if not conversion:
            if len(distinct_units) > 1:
                hint = f"规格「{line.specification}」含多级包装（{'/'.join(sorted(distinct_units))}），定价单位有歧义"
            else:
                hint = f"计价单位「{unit}」与支付标准单位「{cap.unit}」不一致"
            return ConditionVerdict(
                condition=condition,
                status=VerdictStatus.INSUFFICIENT_EVIDENCE,
                missing=f"{hint}，缺少 pack.{line.item_code} 包装换算映射",
            )
        if len(conversion) != 1:
            return ConditionVerdict(condition=condition, status=VerdictStatus.UNVERIFIABLE,
                                    missing="包装换算存在多条映射，不能任取第一条")
        try:
            multiplier = Decimal(conversion[0].target_value)
        except InvalidOperation:
            multiplier = Decimal("NaN")
        if not multiplier.is_finite() or multiplier <= 0:
            return ConditionVerdict(condition=condition, status=VerdictStatus.UNVERIFIABLE,
                                    missing=f"包装换算映射值非法：{conversion[0].target_value}")
        effective_price = line.unit_price / multiplier
        used_mapping_ids = (conversion[0].mapping_id,)
        conversion_note = f"按映射 {conversion[0].mapping_id} 换算：{line.unit_price}/{multiplier}={effective_price:.4f} 元/{cap.unit}"

    if cap.basis == PriceBasis.PAYMENT_STANDARD:
        gap = _field_gap(condition, line, "item.count", "price.payment_base")
        if gap:
            return gap
        if line.count is None or line.count <= 0:
            return ConditionVerdict(condition=condition, status=VerdictStatus.INSUFFICIENT_EVIDENCE,
                                    missing="缺少正数量，无法核验支付基数上限")
        assert line.payment_base is not None
        limit = min(effective_price, cap.amount) * line.count * multiplier
        checked, threshold = line.payment_base, limit
        comparison = f"已取得支付基数 {checked} 元，按规格/数量核验的支付基数上限 {threshold} 元"
    else:
        checked, threshold = effective_price, cap.amount
        comparison = f"换算后单价 {effective_price:.4f} 元/{cap.unit}，收费上限 {cap.amount} 元/{cap.unit}"
    if checked > threshold:
        return ConditionVerdict(
            condition=condition,
            status=VerdictStatus.CONTRADICTED,
            match_status=MatchStatus.NOT_MATCHED,
            used_mapping_ids=used_mapping_ids,
            evidence=(ConditionEvidence(
                kind="price_check",
                summary=f"{comparison}，超出适用上限（{conversion_note}）",
                source="; ".join(line.field_states[k].source for k in (
                    ("price.unit_price", "item.specification", "item.count", "price.payment_base")
                    if cap.basis == PriceBasis.PAYMENT_STANDARD else ("price.unit_price", "item.specification")
                )),
            ),),
        )
    return ConditionVerdict(
        condition=condition,
        status=VerdictStatus.SUPPORTED,
        match_status=MatchStatus.MATCHED,
        used_mapping_ids=used_mapping_ids,
        evidence=(ConditionEvidence(
            kind="price_check",
            summary=f"{comparison}，未超适用上限（{conversion_note}）",
            source="; ".join(line.field_states[k].source for k in (
                ("price.unit_price", "item.specification", "item.count", "price.payment_base")
                if cap.basis == PriceBasis.PAYMENT_STANDARD else ("price.unit_price", "item.specification")
            )),
        ),),
    )


def verify_condition(
    condition: RuleCondition,
    line: SettlementLineContext,
    mappings: Iterable[ValueDomainMapping],
) -> ConditionVerdict:
    """按条件类型分发核验器；无核验器的类型 fail-closed 判 unverifiable。"""
    if condition.condition_type == RestrictionConditionType.DISEASE:
        return _verify_disease(condition, line, mappings)
    if condition.condition_type == RestrictionConditionType.PRICE_CAP:
        return _verify_price_cap(condition, line, mappings)
    return ConditionVerdict(
        condition=condition,
        status=VerdictStatus.UNVERIFIABLE,
        missing=f"条件类型 {condition.condition_type.value} 的核验器或数据源未就绪",
    )


def evaluate_rule(
    rule: ComplianceRule,
    line: SettlementLineContext,
    mappings: Iterable[ValueDomainMapping],
) -> LineComplianceResult:
    """对一条明细行执行一条规则：组内 any_of，组间 all_of，聚合风险层。"""
    if not rule.condition_groups or any(not group.conditions for group in rule.condition_groups):
        raise ValueError("空规则或空条件组不可执行")
    mappings = tuple(mappings)
    applicable = rule.item_code == line.item_code and rule.catalog_effective_from <= line.trade_date <= rule.catalog_effective_to
    verdicts = tuple(
        verify_condition(condition, line, mappings)
        if applicable else ConditionVerdict(condition=condition, status=VerdictStatus.UNVERIFIABLE,
                                           missing="规则不适用本行项目或费用日期")
        for group in rule.condition_groups
        for condition in group.conditions
    )
    group_statuses: list[VerdictStatus] = []
    offset = 0
    for group in rule.condition_groups:
        group_verdicts = verdicts[offset:offset + len(group.conditions)]
        offset += len(group.conditions)
        statuses = [v.status for v in group_verdicts]
        # any_of：任一支持即支持；全部反证才反证；其余按资料不足/不可核验保守裁定
        if VerdictStatus.SUPPORTED in statuses:
            group_statuses.append(VerdictStatus.SUPPORTED)
        elif all(status == VerdictStatus.CONTRADICTED for status in statuses):
            group_statuses.append(VerdictStatus.CONTRADICTED)
        elif VerdictStatus.INSUFFICIENT_EVIDENCE in statuses:
            group_statuses.append(VerdictStatus.INSUFFICIENT_EVIDENCE)
        elif VerdictStatus.UNVERIFIABLE in statuses:
            group_statuses.append(VerdictStatus.UNVERIFIABLE)
        else:
            group_statuses.append(VerdictStatus.CONTRADICTED)

    if VerdictStatus.CONTRADICTED in group_statuses:
        tier = ComplianceRiskTier.CONTRA
        status = VerdictStatus.CONTRADICTED
    elif all(status == VerdictStatus.SUPPORTED for status in group_statuses):
        tier = ComplianceRiskTier.CLEAR
        status = VerdictStatus.SUPPORTED
    else:
        tier = ComplianceRiskTier.REVIEW
        status = (VerdictStatus.INSUFFICIENT_EVIDENCE if VerdictStatus.INSUFFICIENT_EVIDENCE in group_statuses
                  else VerdictStatus.UNVERIFIABLE)
    return LineComplianceResult(
        rule_id=rule.rule_id,
        rule_revision=rule.revision,
        item_code=rule.item_code,
        item_name=rule.item_name,
        verdicts=verdicts,
        risk_tier=tier,
        fee=line.fee,
        fee_in=line.fee_in,
        fee_out=line.fee_out,
        status=status,
        rule_status=rule.status,
        explanation_ready=rule.status == RuleStatus.PUBLISHED and status in (
            VerdictStatus.SUPPORTED, VerdictStatus.CONTRADICTED,
        ),
    )
