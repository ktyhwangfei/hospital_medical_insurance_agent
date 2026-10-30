"""四条链路审查反例：稀疏事实、目录范围、年度累计和公开结论。"""
from dataclasses import replace
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_special_mz_queries import (
    derive_mz_cycle_context, derive_mz_resident_cycle_context,
)
from src.domain.insurance.fee_decomposition import DrugCatalogEntry, OriginalPolicyContext
from src.runtime.policy_qa.fee_decomposition import integration
from src.runtime.policy_qa.fee_decomposition.employee_outpatient_special import decompose_employee_outpatient_special
from src.runtime.policy_qa.fee_decomposition.public_view import render_summary
from src.runtime.policy_qa.fee_decomposition.resident_outpatient import decompose_resident_outpatient
from src.runtime.policy_qa.fee_decomposition.resident_special_catalog import adapt_mz_items_to_fee_line_items, split_special_mz_catalog
from src.tests.unit.runtime.policy_qa.fee_decomposition import test_resident_outpatient as ordinary
from src.tests.unit.runtime.policy_qa.fee_decomposition.test_special_mz_golden import _snapshot_djh708, _snapshot_djh814


def test_missing_cash_channel_cannot_be_zero_in_resident_agency_identity():
    from src.tests.unit.runtime.policy_qa.fee_decomposition import test_resident_outpatient_special as special
    from src.runtime.policy_qa.fee_decomposition.resident_outpatient_special import decompose_resident_outpatient_special
    snapshot = special._snapshot()
    snapshot = replace(snapshot, observed=replace(snapshot.observed, xjzf=None, zhzf=Decimal("0")))
    result = decompose_resident_outpatient_special(snapshot, special._split())
    field = special._field(result, "AGENCY_PAY")
    assert field.observed_amount is None
    assert field.check_status == "not_verifiable"


@pytest.mark.parametrize("kind", ["drug", "material"])
def test_price_limit_requires_quantity_instead_of_defaulting_one(kind):
    from src.tests.unit.runtime.policy_qa.fee_decomposition import test_catalog_split as catalog
    item_factory = catalog._drug_item if kind == "drug" else catalog._material_item
    entry_factory = catalog._drug_entry if kind == "drug" else catalog._material_entry
    item = item_factory(fee=Decimal("300"), unit_price=Decimal("100"), count=None, sp_scale=Decimal("9.8"))
    result = catalog._run(item, entry_factory(), kind=kind)
    assert not result.is_complete
    assert "COUNT_MISSING" in {u.code for u in result.uncertainties}


@pytest.mark.parametrize("column", ["bqqfje", "bqljybnje", "bnzqslj", "bntczfje", "bndezfje"])
@pytest.mark.parametrize("missing", [None, "", "invalid"])
def test_missing_cycle_value_cannot_be_confirmed_zero(column, missing):
    cycle = {"bqqfje": "1300", "bqljybnje": "2000"}
    annual = {"bnzqslj": "1", "bntczfje": "500", "bndezfje": "0"}
    settlement = {"tsbybn": "100", "ybnqfje": "0", "tczhf": "91", "degwyzhf": "0"}
    (cycle if column in cycle else annual)[column] = missing
    for derive in (lambda: derive_mz_cycle_context(cycle, annual, settlement, None, None),
                   lambda: derive_mz_resident_cycle_context(cycle, annual, settlement)):
        context, _ = derive()
        assert context.evidence_status != "confirmed"


def test_lagging_annual_value_is_not_confirmed():
    context, _ = derive_mz_resident_cycle_context(
        {"bqqfje": "1300", "bqljybnje": "5000"},
        {"bnzqslj": "1", "bntczfje": "0", "bndezfje": "1587.56"},
        {"tsbybn": "3357.20", "ybnqfje": "0", "tczhf": "0", "degwyzhf": "2517.90"})
    assert context.evidence_status != "confirmed"
    assert context.prior_annual_large_fund_payment is None
    assert "CYCLE_TABLE_LAGGING" in context.evidence_note


def test_mz_actual_lowercase_limit_ratio_survive_adaptation():
    item, = adapt_mz_items_to_fee_line_items(
        [{"xh": "1", "xmdm": "D001", "xmlb": "0", "zje": "100", "fee_medic_l": "0.1", "fee_sp_scale": "9.8"}],
        settle_date=date(2024, 5, 6))
    assert item.medic_l == Decimal("0.1")
    assert item.sp_scale == Decimal("9.8")


def test_model_cannot_replace_partial_result_with_full_claim(monkeypatch):
    class Gateway:
        def generate(self, **kwargs):
            return SimpleNamespace(content="全部费用完整解释，全部一致。")
    monkeypatch.setattr("src.model_service.gateway.ModelGateway", Gateway)
    text = "部分解释：100 元；缺少累计，暂不能核对。"
    assert integration.polish_summary(text) == (text, "template")


def test_template_obeys_full_explanation_constraint():
    result = decompose_employee_outpatient_special(_snapshot_djh708())
    result = result.model_copy(update={
        "execution_status": "complete", "reconciliation_status": "mismatched",
        "answer_constraints": result.answer_constraints.model_copy(update={"may_claim_full_explanation": False})})
    assert "完整解释" not in render_summary(result).splitlines()[0]


def test_fully_excluded_item_stays_personal_in_resident_bigill_channel():
    snapshot = ordinary._snapshot(
        items=(ordinary._drug_item("100"), ordinary._drug_item("100", key="L2", item_code="SELF")),
        prior_in_scope="600", prior_fund="4500")
    excluded = DrugCatalogEntry(entry_id="SELF", item_code="SELF", sflb="0103", self_pay_ratio=Decimal("1"),
        effective_date=date(2024, 1, 1), expiry_date=date(2024, 12, 31))
    result = decompose_resident_outpatient(replace(snapshot, drug_catalog=(*snapshot.drug_catalog, excluded)))
    assert Decimal(ordinary._field(result, "T_BigillPay").calculated_amount) == Decimal("75")
    assert Decimal(ordinary._field(result, "T_FeeOut").calculated_amount) == Decimal("100")
    assert Decimal(ordinary._field(result, "T_SelfPayAll").calculated_amount) == Decimal("125")
    assert Decimal(ordinary._field(result, "T_SelfPay2").calculated_amount) == 0


@pytest.mark.parametrize("sign", [1, -1])
def test_resident_bigill_price_excess_is_excluded_and_rounded_buckets_conserve_total(sign):
    item = ordinary._drug_item(str(sign * 100), unit_price=Decimal("100"), count=Decimal(sign),
        sp_scale=Decimal("9.8"), fee_type="0102")
    snap = ordinary._snapshot(items=(item,), prior_in_scope="600", prior_fund="4500",
        original_trade_no="original" if sign < 0 else None)
    snap = replace(snap, drug_catalog=(replace(snap.drug_catalog[0], sflb="0102", self_pay_ratio=Decimal("0.1")),))
    result = decompose_resident_outpatient(snap)
    amount = lambda code: Decimal(ordinary._field(result, code).calculated_amount)
    assert amount("T_BigillPay") == Decimal("7.35") * sign
    assert amount("T_SelfPay2") == Decimal("0.25") * sign
    assert amount("T_FeeOut") == Decimal("90.45") * sign
    assert amount("T_SelfPayAll") == Decimal("92.65") * sign
    assert amount("T_SelfPay1") + amount("T_FeeOut") == amount("T_SelfPayAll")


@pytest.mark.parametrize("factory,column", [
    (_snapshot_djh708, "prior_annual_pool_fund_payment"),
    (_snapshot_djh814, "prior_annual_large_fund_payment")])
def test_missing_fund_cumulative_blocks_cap_inference(factory, column):
    snapshot = factory()
    result = decompose_employee_outpatient_special(replace(snapshot, cycle=replace(snapshot.cycle, **{column: None})))
    code = "TCZHF" if "pool" in column else "DEGWYZHF"
    field = next(f for f in result.fields if f.field_code == code)
    assert field.calculated_amount is None
    assert field.check_status == "not_verifiable"


def test_special_catalog_requires_independent_special_marker():
    split = split_special_mz_catalog(
        (ordinary._drug_item("100"),), ordinary._drug_catalog(), (), (), "01110003", ordinary.MODE)
    assert not split.is_complete
    assert split.total_in_scope is None
    assert any("SPECIAL" in u.code for u in split.uncertainties)


def test_refund_without_original_policy_facts_is_not_recalculated():
    snapshot = ordinary._snapshot(items=(ordinary._drug_item("-168", occ=date(2017, 8, 1)),),
        original_trade_no="2017-original", prior_in_scope="600", prior_fund="100")
    snapshot = replace(snapshot, original_policy_context=None, drug_catalog=(replace(snapshot.drug_catalog[0],
        effective_date=date(2016, 1, 1), expiry_date=date(2018, 12, 31)),))
    result = decompose_resident_outpatient(snapshot)
    assert ordinary._field(result, "T_FirstPay").calculated_amount is None
    assert any("ORIGINAL" in u.code for u in result.uncertainties)


def test_historical_refund_uses_original_policy_and_original_year_accumulation():
    snapshot = ordinary._snapshot(items=(ordinary._drug_item("-168", occ=date(2017, 8, 1)),),
        original_trade_no="2017-original", prior_in_scope="600", prior_fund="100")
    original = OriginalPolicyContext(date(2017, 8, 1), snapshot.person, snapshot.institution,
        "resident", "outpatient", 2017, "19")
    snapshot = replace(snapshot, original_policy_context=original,
        drug_catalog=(replace(snapshot.drug_catalog[0], effective_date=date(2016, 1, 1), expiry_date=date(2018, 12, 31)),))
    result = decompose_resident_outpatient(snapshot)
    assert Decimal(ordinary._field(result, "T_FirstPay").calculated_amount) == Decimal("-168")
    assert Decimal(ordinary._field(result, "T_BigPay").calculated_amount) == 0
    assert next(c for c in result.citations if c.id == "fact.trade.trade_date").value == "2024-09-13"


def test_refund_accumulation_year_must_match_original_policy_year():
    snapshot = ordinary._snapshot(items=(ordinary._drug_item("-100"),), original_trade_no="2017-original")
    original = OriginalPolicyContext(date(2017, 8, 1), snapshot.person, snapshot.institution,
        "resident", "outpatient", 2024, "19")
    result = decompose_resident_outpatient(replace(snapshot, original_policy_context=original))
    assert ordinary._field(result, "T_FirstPay").calculated_amount is None


def test_basic_annual_snapshot_requires_same_year_as_settlement():
    cycle = {"fynd": "2024", "bqqfje": "1300", "bqljybnje": "2000"}
    annual = {"fynd": "2023", "bnmcjylsh": "same", "bnzqslj": "1", "bntczfje": "500", "bndezfje": "0"}
    settlement = {"jyrq": "2024-05-06", "jylsh": "same", "tsbybn": "100", "ybnqfje": "0", "tczhf": "91", "degwyzhf": "0"}
    context, _ = derive_mz_cycle_context(cycle, annual, settlement, None, date(2024, 5, 6))
    assert context.evidence_status != "confirmed"
    assert context.prior_annual_pool_fund_payment is None


def test_unique_source_registration_supplies_profile_without_question_context(monkeypatch):
    monkeypatch.setattr(integration, "locate_special_fixed_kidney_registration", lambda *a: SimpleNamespace(
        status=AdapterCallStatus.SUCCESS, data={"match_status": "not_found", "registration_row": None}))
    monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
    monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "01110003")
    monkeypatch.setattr(integration, "locate_special_mz_registration", lambda *a: SimpleNamespace(
        status=AdapterCallStatus.SUCCESS, data={"match_status": "unique_match", "registration_row": {"fund_type": "3", "yllb": "12"}}))
    monkeypatch.setattr(integration, "locate_special_mz_resident_registration", lambda *a: SimpleNamespace(
        status=AdapterCallStatus.SUCCESS, data={"match_status": "not_found", "registration_row": None}))
    captured = {}
    def decompose(*args, **kwargs):
        captured.update(kwargs)
        from src.runtime.policy_qa.fee_decomposition.settlement_facts import DecompositionOutcome
        return DecompositionOutcome(decompose_employee_outpatient_special(_snapshot_djh708()))
    monkeypatch.setattr(integration, "decompose_special_mz_settlement", decompose)
    monkeypatch.setattr(integration, "polish_summary", lambda text: (text, "template"))
    provider = SimpleNamespace(_connect=lambda db: SimpleNamespace(close=lambda: None))
    integration.maybe_decompose_special_outpatient(provider, "708", SimpleNamespace())
    assert captured["profile"] == ("employee", "outpatient_special")
