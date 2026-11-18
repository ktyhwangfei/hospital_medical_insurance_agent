"""探针装配边界：不连接实库，以合成行验证不静默丢数据。"""
from datetime import datetime
from decimal import Decimal

from src.domain.directory_compliance.rules_seed import RULE_ILAPRAZOLE


def report(*, catalogs=None, diagnoses=None, duplicate=False, blank_recipe=False, **kwargs):
    from scripts.run_restriction_compliance_probe import build_probe_report
    header = {"T_TradeNo": "synthetic-secret", "T_TradeDate": datetime(2026, 4, 16),
              "T_State": 4, "T_HasRefundmented": 0, "P_FundType": 93, "T_CureType": 19,
              "T_FeeAll": Decimal("52.6"), "T_FeeIn": Decimal("47.34"),
              "T_FeeOut": Decimal("5.26"), "T_FundPay": Decimal("0")}
    lines = [{"ItemId": 1, "ItemCode": RULE_ILAPRAZOLE.item_code, "ItemName": "合成药品",
              "UnitPrice": Decimal("52.6"), "Count": Decimal(1), "Specification": "10mg/支",
              "Fee": Decimal("52.6"), "FeeIn": Decimal("47.34"), "FeeOut": Decimal("5.26"),
              "RecipeNo": "prescription-secret"},
             {"ItemId": 2, "ItemCode": "NO_RULE", "ItemName": "未配置项目",
              "UnitPrice": Decimal(1), "Count": Decimal(1), "Specification": "1mg/支",
              "Fee": Decimal(1), "FeeIn": Decimal(1), "FeeOut": Decimal(0), "RecipeNo": "prescription-secret"}]
    if duplicate:
        lines.append(dict(lines[0]))
    if blank_recipe:
        lines[0]["RecipeNo"] = None
    if catalogs is None:
        catalogs = [{"ypbm": RULE_ILAPRAZOLE.item_code, "bz": RULE_ILAPRAZOLE.source_bz,
                     "sxrq": datetime(2024, 3, 20), "jzrq": datetime(2050, 12, 31)}]
    if diagnoses is None:
        diagnoses = [{"RecipeNo": "prescription-secret", "DiagnoseCode": "K27.400x004",
                      "DiagnoseName": "消化性溃疡伴出血"}]
    return build_probe_report(header, lines, diagnoses, catalogs, **kwargs)


def test_every_line_has_result_even_when_no_rule_exists():
    result = report()
    assert result.bill_line_count == 2
    assert len(result.line_results) == 2
    assert result.line_results[1].lookup.status.value != "matched"
    assert result.line_results[1].lookup.reason


def test_multiple_current_catalog_rows_are_not_last_write_wins():
    catalog = {"ypbm": RULE_ILAPRAZOLE.item_code, "bz": RULE_ILAPRAZOLE.source_bz,
               "sxrq": datetime(2024, 3, 20), "jzrq": datetime(2050, 12, 31)}
    result = report(catalogs=[catalog, dict(catalog)])
    assert result.line_results[0].lookup.status.value == "ambiguous"
    assert result.line_results[0].result is None


def test_catalog_query_failure_is_not_no_rule():
    result = report(catalogs=[], catalog_failed=True)
    assert result.line_results[0].lookup.status.value == "not_evaluated"
    assert result.line_results[0].context.field_states["catalog"].status.value == "fetch_failed"


def test_snapshot_is_replayable_without_patient_or_prescription_identifiers():
    result = report()
    text = result.model_dump_json()
    assert "synthetic-secret" not in text
    assert "prescription-secret" not in text
    assert result.rules_snapshot and result.mappings_snapshot
    assert result.line_results[0].context.same_recipe_diagnoses


def test_diagnosis_query_failure_remains_explicit():
    result = report(diagnoses=[], diagnosis_failed=True)
    assert result.line_results[0].context.field_states["diagnosis.code"].status.value == "fetch_failed"


def test_duplicate_fee_keys_are_reported_not_re_evaluated():
    result = report(duplicate=True)
    assert len(result.line_results) == 3
    assert result.line_results[0].lookup.status.value == "ambiguous"
    assert result.line_results[0].result is None


def test_empty_prescription_is_not_joined_to_other_empty_prescriptions():
    result = report(blank_recipe=True, diagnoses=[{"RecipeNo": None, "DiagnoseCode": "K27.400x004"}])
    assert not result.line_results[0].context.same_recipe_diagnoses
    assert result.line_results[0].context.field_states["diagnosis.code"].status.value == "invalid"
