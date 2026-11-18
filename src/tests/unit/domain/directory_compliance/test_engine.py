"""目录合规核验引擎单元测试（Issue #85）。

锚定设计 V2.0 纪律：占位≠不符合、缺失≠反证、价格先换算再比价、缺映射 fail-closed。
样例数据来自 bjyb 测试库实存记录（2026-04-16 急诊单，脱敏）。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.domain.directory_compliance.engine import (
    evaluate_rule,
    is_placeholder_text,
    resolve_mappings,
    verify_condition,
)
from src.domain.directory_compliance.explanation import (
    PATIENT_BANNED_WORDS,
    build_ops_explanation,
    build_patient_explanation,
)
from src.domain.directory_compliance.models import (
    ComplianceRiskTier,
    ComplianceRule,
    ConditionGroup,
    DiagnosisFact,
    MappingScope,
    MappingTargetType,
    PriceBasis,
    PriceCapSpec,
    RestrictionConditionType,
    RuleStatus,
    RuleCondition,
    SettlementLineContext,
    ValueDomain,
    ValueDomainMapping,
    VerdictStatus,
)
from src.domain.directory_compliance.rules_seed import (
    BASELINE_MAPPINGS as DRAFT_MAPPINGS,
    RULE_CARBAZOCHROME as DRAFT_CARBAZOCHROME,
    RULE_ILAPRAZOLE as DRAFT_ILAPRAZOLE,
)

# 合成审核配置仅测试算法，不把种子或临床映射视为已完成正式审核。
BASELINE_MAPPINGS = tuple(m.model_copy(update={"reviewed_by": "synthetic-review"}) for m in DRAFT_MAPPINGS)
_payload = DRAFT_ILAPRAZOLE.model_dump(mode="json")
_payload.update(status="published", reviewed_by="synthetic-review")
_payload["condition_groups"][1]["conditions"][0]["price_cap"]["basis"] = "sale_ceiling"
RULE_ILAPRAZOLE = ComplianceRule.model_validate(_payload)
RULE_CARBAZOCHROME = DRAFT_CARBAZOCHROME.model_copy(update={
    "status": RuleStatus.PUBLISHED, "reviewed_by": "synthetic-review",
})

# ── 样例结算单事实（2026-04-16 急诊，同方 E260416018105）─────────

SAMPLE_DIAGNOSES = (
    DiagnosisFact(association="same_prescription", code="D66.x01", name="血友病A型"),
    DiagnosisFact(association="same_prescription", code="K92.209", name="下消化道出血"),
    DiagnosisFact(association="same_prescription", code="D64.903", name="重度贫血"),
    DiagnosisFact(association="same_prescription", code="K27.400x004", name="消化性溃疡伴出血", medical_record="消化性溃疡出血"),
)


def _line(**overrides) -> SettlementLineContext:
    base = {
        "hospital_code": "01110003",
        "trade_date": date(2026, 4, 16),
        "item_code": "XA02BCA084B001010100453",
        "item_name": "注射用艾普拉唑钠",
        "unit_price": Decimal("52.6000"),
        "count": Decimal("1"),
        "specification": "10MG/支",
        "fee": Decimal("52.60"),
        "fee_in": Decimal("47.34"),
        "fee_out": Decimal("5.26"),
        "same_recipe_diagnoses": SAMPLE_DIAGNOSES,
        "same_bill_item_names": (),
        "section_name": "急诊科专业",
        "field_states": {key: {"status": "present", "source": "synthetic",
                               "association": "same_prescription" if key.startswith("diagnosis") else "same_line"}
                         for key in ("diagnosis.code", "price.unit_price", "item.specification", "item.count")},
    }
    return SettlementLineContext(**{**base, **overrides})


# ── 占位纪律 ────────────────────────────────────────────────

def test_placeholder_text_detection():
    assert is_placeholder_text("1")
    assert is_placeholder_text("01")
    assert is_placeholder_text("11")
    assert is_placeholder_text("")
    assert not is_placeholder_text("K27.400x004")
    assert not is_placeholder_text("消化性溃疡伴出血")


def test_placeholder_diagnosis_is_insufficient_not_contradicted():
    """占位诊断（罗沙司他教训）：不能判条件不符。"""
    line = _line(same_recipe_diagnoses=(DiagnosisFact(association="same_prescription", code="01", name="1"),))
    condition = RULE_ILAPRAZOLE.condition_groups[0].conditions[1]
    verdict = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert verdict.status == VerdictStatus.INSUFFICIENT_EVIDENCE
    assert "占位" in verdict.missing


# ── 病种核验 ────────────────────────────────────────────────

def test_disease_supported_by_icd_prefix():
    """艾普拉唑样例：K27.400x004 命中消化性溃疡出血前缀集。"""
    line = _line()
    condition = RULE_ILAPRAZOLE.condition_groups[0].conditions[1]
    verdict = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert verdict.status == VerdictStatus.SUPPORTED
    assert verdict.evidence[0].kind == "diagnosis_match"
    assert "K27.400x004" in verdict.evidence[0].source


def test_disease_absent_is_insufficient_not_contradicted():
    """卡络磺钠样例：真实诊断未见"无法口服"记录，缺失≠反证。"""
    line = _line(item_code="XB02BXK018B001010201504", item_name="注射用卡络磺钠")
    condition = RULE_CARBAZOCHROME.condition_groups[0].conditions[0]
    verdict = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert verdict.status == VerdictStatus.INSUFFICIENT_EVIDENCE
    assert "未见" in verdict.missing


def test_missing_mapping_fails_closed():
    """应激性溃疡预防条件故意无映射：fail-closed 判 unverifiable。"""
    line = _line()
    condition = RULE_ILAPRAZOLE.condition_groups[0].conditions[0]
    verdict = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert verdict.status == VerdictStatus.UNVERIFIABLE
    assert "映射" in verdict.missing


def test_mapping_scope_hospital_overrides_default():
    hospital_mapping = ValueDomainMapping(
        mapping_id="map-hosp-1",
        domain=ValueDomain.DIAGNOSIS,
        concept_code="dg.peptic_ulcer_bleeding",
        scope=MappingScope.HOSPITAL,
        scope_key="01110003",
        target_type=MappingTargetType.ICD_PREFIX,
        target_value="K99.9",
    )
    resolved = resolve_mappings(
        [*BASELINE_MAPPINGS, hospital_mapping],
        ValueDomain.DIAGNOSIS, "dg.peptic_ulcer_bleeding", "01110003",
    )
    assert tuple(m.target_value for m in resolved) == ("K99.9",)
    resolved_other = resolve_mappings(
        [*BASELINE_MAPPINGS, hospital_mapping],
        ValueDomain.DIAGNOSIS, "dg.peptic_ulcer_bleeding", "99999999",
    )
    assert len(resolved_other) > 1  # 其他院区回落 default 基线


# ── 价格核验（规格换算铁律）──────────────────────────────────

def test_price_cap_supported_same_unit():
    line = _line()
    condition = RULE_ILAPRAZOLE.condition_groups[1].conditions[0]
    verdict = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert verdict.status == VerdictStatus.SUPPORTED
    assert "52.6000" in verdict.evidence[0].summary


def test_price_cap_contradicted_when_exceeded():
    line = _line(unit_price=Decimal("70.00"), fee=Decimal("70.00"))
    condition = RULE_ILAPRAZOLE.condition_groups[1].conditions[0]
    verdict = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert verdict.status == VerdictStatus.CONTRADICTED


def test_price_cap_unparseable_spec_blocks_direct_compare():
    line = _line(specification="盒")
    condition = RULE_ILAPRAZOLE.condition_groups[1].conditions[0]
    verdict = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert verdict.status == VerdictStatus.INSUFFICIENT_EVIDENCE
    assert "禁止" in verdict.missing or "无法解析" in verdict.missing


def test_price_cap_packaging_conversion_clears_false_positive():
    """硫酸镁钠钾教训：95.90 元/盒经 2瓶/盒 换算后未超 48 元/瓶。"""
    condition = RuleCondition(
        condition_type=RestrictionConditionType.PRICE_CAP,
        concept_code="unit.bottle_176ml",
        source_span="支付标准不得高于：48.00元(176ml/瓶)",
        price_cap=PriceCapSpec(amount=Decimal("48.00"), unit="瓶", strength_text="176ml", basis=PriceBasis.SALE_CEILING),
    )
    pack_mapping = ValueDomainMapping(
        mapping_id="map-pack-mag",
        domain=ValueDomain.PRICE_UNIT,
        concept_code="pack.XA06ADL397X019010183508",
        scope=MappingScope.DEFAULT,
        target_type=MappingTargetType.SPEC_CONVERSION,
        target_value="2",
        reviewed_by="synthetic-review",
    )
    line = _line(
        item_code="XA06ADL397X019010183508",
        specification="CO 176ML/瓶 2瓶/盒",
        unit_price=Decimal("95.90"),
    )
    verdict = verify_condition(condition, line, [*BASELINE_MAPPINGS, pack_mapping])
    assert verdict.status == VerdictStatus.SUPPORTED
    assert "换算" in verdict.evidence[0].summary
    without_mapping = verify_condition(condition, line, BASELINE_MAPPINGS)
    assert without_mapping.status == VerdictStatus.INSUFFICIENT_EVIDENCE


# ── 规则聚合 ────────────────────────────────────────────────

def test_rule_clear_on_sample_line():
    """样单艾普拉唑行：病种组 any_of（不可核验+支持）+ 限价支持 → clear。"""
    result = evaluate_rule(RULE_ILAPRAZOLE, _line(), BASELINE_MAPPINGS)
    assert result.risk_tier == ComplianceRiskTier.CLEAR
    statuses = {v.status for v in result.verdicts}
    assert VerdictStatus.SUPPORTED in statuses
    assert VerdictStatus.UNVERIFIABLE in statuses  # 重症预防条件缺映射


def test_rule_review_when_evidence_insufficient():
    """样单卡络磺钠行：真实诊断未见相符记录 → review。"""
    line = _line(
        item_code="XB02BXK018B001010201504", item_name="注射用卡络磺钠",
        unit_price=Decimal("3.8200"), specification="20MG 5西林/盒",
        fee=Decimal("15.28"), fee_in=Decimal("13.7520"), fee_out=Decimal("1.5280"),
    )
    result = evaluate_rule(RULE_CARBAZOCHROME, line, BASELINE_MAPPINGS)
    assert result.risk_tier == ComplianceRiskTier.REVIEW


def test_rule_contra_when_price_exceeded():
    line = _line(unit_price=Decimal("70.00"), fee=Decimal("70.00"))
    result = evaluate_rule(RULE_ILAPRAZOLE, line, BASELINE_MAPPINGS)
    assert result.risk_tier == ComplianceRiskTier.CONTRA


def test_partial_contradiction_in_any_of_group_not_upgraded():
    """any_of 组内部分反证+其余不可核验 → 不升级为反证。"""
    rule = ComplianceRule(
        rule_id="rule-test-partial",
        item_code="X", item_name="测试",
        catalog_effective_from=date(2024, 1, 1),
        catalog_effective_to=date(2050, 12, 31),
        condition_groups=(ConditionGroup(conditions=(
            RuleCondition(
                condition_type=RestrictionConditionType.PRICE_CAP,
                concept_code="unit.vial_10mg",
                source_span="限价",
                price_cap=PriceCapSpec(amount=Decimal("10.00"), unit="支", strength_text="10mg", basis=PriceBasis.SALE_CEILING),
            ),
            RuleCondition(
                condition_type=RestrictionConditionType.DISEASE,
                concept_code="dg.no_mapping",
                source_span="无映射病种",
            ),
        )),),
        source_bz="测试",
    )
    line = _line(item_code="X", unit_price=Decimal("70.00"), fee=Decimal("70.00"))
    result = evaluate_rule(rule, line, BASELINE_MAPPINGS)
    assert result.risk_tier == ComplianceRiskTier.REVIEW


# ── 双方向解释 ──────────────────────────────────────────────

def test_patient_explanation_clear_states_fact():
    result = evaluate_rule(RULE_ILAPRAZOLE, _line(), BASELINE_MAPPINGS)
    text = build_patient_explanation(result)
    assert "医保外" in text
    assert "乙类先行自付" not in text
    assert "5.26" in text
    for banned in PATIENT_BANNED_WORDS:
        assert banned not in text


def test_patient_explanation_review_is_non_accusatory():
    line = _line(item_code="XB02BXK018B001010201504", item_name="注射用卡络磺钠",
                 fee=Decimal("15.28"), fee_in=Decimal("13.7520"), fee_out=Decimal("1.5280"))
    result = evaluate_rule(RULE_CARBAZOCHROME, line, BASELINE_MAPPINGS)
    text = build_patient_explanation(result)
    assert "以结算单为准" in text
    assert "不代表存在问题" in text
    assert "医保窗口" in text
    for banned in PATIENT_BANNED_WORDS:
        assert banned not in text


def test_ops_explanation_review_carries_evidence_chain():
    line = _line(item_code="XB02BXK018B001010201504", item_name="注射用卡络磺钠",
                 fee=Decimal("15.28"), fee_in=Decimal("13.7520"), fee_out=Decimal("1.5280"))
    result = evaluate_rule(RULE_CARBAZOCHROME, line, BASELINE_MAPPINGS)
    text = build_ops_explanation(result)
    assert "抽查建议" in text
    assert "13.75" in text
    assert "限无法口服" in text
    assert "不构成违规结论" in text
