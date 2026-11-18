"""核验质量边界的回归样例，全部为合成输入，不代表真实患者结论。"""
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.directory_compliance.engine import evaluate_rule, verify_condition
from src.domain.directory_compliance.explanation import build_patient_explanation
from src.domain.directory_compliance.models import ComplianceRule, SettlementLineContext
from src.domain.directory_compliance.rules_seed import (
    BASELINE_MAPPINGS, RULE_CARBAZOCHROME, RULE_ILAPRAZOLE,
)


def line(**updates):
    fields = ("item.code", "fee.date", "catalog", "diagnosis.code", "diagnosis.name",
              "price.unit_price", "item.specification", "item.count", "price.payment_base")
    return SettlementLineContext.model_validate({
        "hospital_code": "TEST", "trade_date": "2026-04-16",
        "item_code": RULE_ILAPRAZOLE.item_code, "item_name": "合成测试药品",
        "unit_price": "52.60", "count": "1", "specification": "10mg/支",
        "fee": "52.60", "fee_in": "47.34", "fee_out": "5.26",
        "payment_base": "52.60", "catalog_bz": RULE_ILAPRAZOLE.source_bz,
        "catalog_effective_from": "2024-03-20", "catalog_effective_to": "2050-12-31",
        "same_recipe_diagnoses": [{"code": "K27.400x004", "name": "消化性溃疡伴出血",
                                    "association": "same_prescription"}],
        "field_states": {key: {"status": "present", "source": "synthetic",
                               "association": "same_prescription" if key.startswith("diagnosis") else "same_line"}
                         for key in fields}, **updates,
    })


def mappings():
    return tuple(m.model_copy(update={"reviewed_by": "synthetic-review"}) for m in BASELINE_MAPPINGS)


def price_condition(basis="payment_standard", amount="63", strength="10mg"):
    payload = RULE_ILAPRAZOLE.condition_groups[1].conditions[0].model_dump(mode="json")
    payload["price_cap"].update(basis=basis, amount=amount, strength_text=strength)
    return type(RULE_ILAPRAZOLE.condition_groups[1].conditions[0]).model_validate(payload)


def published_rule():
    payload = RULE_ILAPRAZOLE.model_dump(mode="json")
    payload.update(status="published", reviewed_by="synthetic-review")
    payload["condition_groups"][1]["conditions"][0]["price_cap"]["basis"] = "payment_standard"
    return ComplianceRule.model_validate(payload)


def test_ulcer_without_bleeding_cannot_support_bleeding_condition():
    facts = [{"code": "K27.9", "name": "消化性溃疡", "association": "same_prescription"}]
    result = verify_condition(RULE_ILAPRAZOLE.condition_groups[0].conditions[1],
                              line(same_recipe_diagnoses=facts), mappings())
    assert result.status.value == "insufficient_evidence"


def test_negated_text_is_not_positive_clinical_evidence():
    facts = [{"code": "R00", "name": "其他症状", "medical_record": "无吞咽困难，可正常口服药物",
              "association": "same_prescription"}]
    result = verify_condition(RULE_CARBAZOCHROME.condition_groups[0].conditions[0],
                              line(same_recipe_diagnoses=facts), mappings())
    assert result.status.value != "supported"


@pytest.mark.parametrize("state", ["fetch_failed", "not_available", "placeholder", "ambiguous"])
def test_unusable_field_is_not_an_executed_non_match(state):
    context = line()
    payload = context.model_dump(mode="json")
    payload["field_states"]["diagnosis.code"]["status"] = state
    result = verify_condition(RULE_ILAPRAZOLE.condition_groups[0].conditions[1],
                              SettlementLineContext.model_validate(payload), mappings())
    assert result.status.value != "supported"
    assert result.match_status.value == "not_evaluated"


def test_available_diagnosis_non_match_is_distinct_from_not_fetched():
    facts = [{"code": "K27.9", "name": "其他疾病", "association": "same_prescription"}]
    result = verify_condition(RULE_ILAPRAZOLE.condition_groups[0].conditions[1],
                              line(same_recipe_diagnoses=facts), mappings())
    assert result.match_status.value == "not_matched"
    assert result.status.value == "insufficient_evidence"


def test_same_settlement_diagnosis_is_not_silently_promoted_to_same_prescription():
    facts = [{"code": "K27.400x004", "name": "消化性溃疡伴出血", "association": "same_settlement"}]
    result = verify_condition(RULE_ILAPRAZOLE.condition_groups[0].conditions[1],
                              line(same_recipe_diagnoses=facts), mappings())
    assert result.status.value != "supported"


@pytest.mark.parametrize(("base", "expected"), [("80", "supported"), ("100", "contradicted")])
def test_payment_standard_checks_supplied_base_not_sale_price(base, expected):
    result = verify_condition(price_condition(amount="80"),
                              line(unit_price="100", fee="100", fee_in="72", fee_out="28", payment_base=base),
                              mappings())
    assert result.status.value == expected


def test_missing_payment_base_is_not_inferred_from_fee_in_or_ratio():
    result = verify_condition(price_condition(), line(payment_base=None), mappings())
    assert result.status.value == "insufficient_evidence"
    assert result.match_status.value == "not_evaluated"


def test_actual_sale_ceiling_can_directly_check_sale_price():
    result = verify_condition(price_condition(basis="sale_ceiling", amount="40"), line(), mappings())
    assert result.status.value == "contradicted"


@pytest.mark.parametrize(("spec", "expected"), [("10g/支", "insufficient_evidence"),
                                                ("0.01g/支", "supported")])
def test_strength_is_compared_after_unit_normalization(spec, expected):
    result = verify_condition(price_condition(), line(specification=spec), mappings())
    assert result.status.value == expected


def test_no_invented_self_pay_category_or_workflow_promise():
    result = evaluate_rule(published_rule(), line(fee_in="0", fee_out="52.60"), mappings())
    text = build_patient_explanation(result)
    assert "乙类先行自付" not in text
    assert "正在进一步核实" not in text
    assert "规则" in text or "条件" in text


def test_draft_rule_never_claims_formally_verified_payment_eligibility():
    result = evaluate_rule(RULE_ILAPRAZOLE, line(), mappings())
    assert not result.explanation_ready
    assert "符合目录限定的支付范围" not in build_patient_explanation(result)


@pytest.mark.parametrize("change", [{"condition_groups": []}, {"condition_groups": [{"conditions": []}]},
                                  {"catalog_effective_to": "2000-01-01"}])
def test_invalid_rule_is_rejected_before_evaluation(change):
    with pytest.raises(ValidationError):
        ComplianceRule.model_validate(RULE_ILAPRAZOLE.model_dump(mode="json") | change)


def test_rule_lookup_distinguishes_failed_fetch_and_missing_published_rule():
    from src.domain.directory_compliance.engine import locate_rule
    context = line()
    missing = locate_rule(context, ())
    assert missing.status.value == "not_found"
    assert missing.reason
    payload = context.model_dump(mode="json")
    payload["field_states"]["catalog"]["status"] = "fetch_failed"
    failed = locate_rule(SettlementLineContext.model_validate(payload), ())
    assert failed.status.value == "not_evaluated"


def test_rule_lookup_rejects_overlapping_published_rules():
    from src.domain.directory_compliance.engine import locate_rule
    first = published_rule()
    second = first.model_copy(update={"rule_id": "second", "catalog_effective_from": date(2025, 1, 1)})
    assert locate_rule(line(), (first, second)).status.value == "ambiguous"


def test_configuration_document_round_trip():
    from src.domain.directory_compliance.configuration import RuleDocument
    rule = published_rule()
    document = RuleDocument.from_rule(rule)
    assert RuleDocument.model_validate_json(document.model_dump_json()).to_rule() == rule


def test_non_finite_price_is_rejected():
    with pytest.raises(ValidationError):
        line(unit_price=Decimal("NaN"))


def test_missing_field_observations_are_not_assumed_successful():
    result = verify_condition(RULE_ILAPRAZOLE.condition_groups[0].conditions[1],
                              line(field_states={}), mappings())
    assert result.status.value == "unverifiable"
    assert result.match_status.value == "not_evaluated"


def test_unreviewed_mapping_never_becomes_positive_evidence():
    result = verify_condition(RULE_ILAPRAZOLE.condition_groups[0].conditions[1], line(), BASELINE_MAPPINGS)
    assert result.status.value == "unverifiable"


def test_placeholder_code_with_real_name_is_still_not_an_executed_code_match():
    facts = [{"code": "01", "name": "消化性溃疡出血", "association": "same_prescription"}]
    result = verify_condition(RULE_ILAPRAZOLE.condition_groups[0].conditions[1],
                              line(same_recipe_diagnoses=facts), mappings())
    assert result.status.value == "insufficient_evidence"
    assert result.match_status.value == "not_evaluated"


def test_mapping_iterator_is_stable_across_multiple_conditions():
    result = evaluate_rule(published_rule(), line(), iter(mappings()))
    assert result.status.value == "supported"
