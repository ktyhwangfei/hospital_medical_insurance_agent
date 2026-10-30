"""定额门特：登记分流→完整源投影→累计转换→内核→公开表述。"""
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from src.adapters.data_supply import outpatient_special_fixed_kidney_queries as fixed_queries
from src.adapters.data_supply import outpatient_special_mz_queries as mz_queries
from src.runtime.policy_qa.fee_decomposition.integration import maybe_decompose_special_outpatient


@pytest.mark.parametrize("special_slot,code", [("tsb1", "503"), ("tsb2", "504"), ("tsb3", "503")])
def test_fixed_chain_source_to_public(special_slot, code, monkeypatch):
    settled = date(2024, 9, 19)
    registration = {"djh": "609", "yllb": "12", "fund_type": "3", "cblb": "21",
        "csrq": date(1952, 4, 1), "cjjrdj": "5", "gwydybz": "0", "civil_type": "0",
        "tsbqsrq": settled, "tsbjzrq": date(2025, 9, 13), "spec_hosp_flag": "1", special_slot: code}
    settlement = {"djh": "609", "fyfs": "0", "jyrq": settled, "jylsh": "source-609",
        "zje": D("1520"), "ptybn": D("0"), "ptybw": D("0"), "tsbybn": D("1520"), "tsbybw": D("0"),
        "ybnqfje": D("1300"), "grziftw": D("0"), "tczhf": D("200.2"), "tczif": D("19.8"),
        "degwyzhf": D("0"), "degwyzif": D("0"), "bczhf": D("9.9"), "jczhf": D("654.95"),
        "gfylbchbx": D("585"), "xjzf": D("68.85"), "zhzf": D("0"),
        "tsbybn1": D("1526"), "tsbybn2": D("0"), "tczhf1": D("210.6"), "tczif1": D("15.4"),
        "dezhf1": D("0"), "dezif1": D("0"), "bczhf1": D("7.7"), "jczhf1": D("653.85"),
        "gfylbchbxde": D("585"), "grzif1": D("1315.4"), "agency_pay_amount": D("1457.15"),
        "deqsrq": settled, "dejzrq": date(2024, 9, 25),
        **{key: D("0") for key in ("big_ill_pay", "civil_in", "feein_db_pay", "feeout_db_pay", "feein_maf_pay", "feeout_maf_pay", "retire_officer_pay")}}
    cycle = {"djh": "609", "fynd": "2024", "zqxh": "1", "bqqsrq": settled, "bqljybnje": D("1526"), "bqqfje": D("1300")}
    annual = {"djh": "609", "fynd": "2024", "bnzqslj": D("1"), "bntczfje": D("210.6"),
        "bndezfje": D("0"), "bnmcjylsh": "source-609", "big_ill_sum_in": D("68.85"), "civil_sum_pay": D("0")}
    item = {"djh": "609", "xh": "1", "xmdm": "XL04ADT002E001020304641", "zje": D("1520"),
        "ybnje": D("1520"), "ybwje": D("0"), "grziftw": D("0"), "dj": D("1520"), "sl": D("1"), "fsrq": settled}
    queries = []
    def fetch(connection, sql, params):
        assert sql.lstrip().upper().startswith("SELECT")
        queries.append((sql, params))
        if "FROM dbo.yb_brdjxx" in sql:
            if "NOT IN ('503','504')" in sql or "FUND_TYPE IN ('91','92','93')" in sql:
                return []
            return [registration]
        for table, row in (("yb_mzjyxx", settlement), ("yb_mzfymx", item), ("yb_dyxxtsb", cycle), ("yb_dyxxnd", annual)):
            if f"FROM dbo.{table}" in sql:
                return [row]
        if "m_institution" in sql:
            return [{"h_code": "01110003", "h_level": "02"}]
        raise AssertionError(sql)
    monkeypatch.setattr(mz_queries, "_fetch_all", fetch)
    monkeypatch.setattr(fixed_queries, "_fetch_all", fetch)
    monkeypatch.setenv("FEE_DECOMPOSITION_ROUNDING_MODE", "round_half_up")
    monkeypatch.setenv("FEE_DECOMPOSITION_HOSPITAL_CODE", "01110003")
    closed = []
    connection = SimpleNamespace(close=lambda: closed.append(True))
    provider = SimpleNamespace(_connect=lambda _: connection)
    presentation = maybe_decompose_special_outpatient(provider, "609", SimpleNamespace())
    assert presentation is not None
    fields = {field.field_code: field for field in presentation.result.fields}
    assert D(fields["TCZHF"].calculated_amount) == D("210.6")
    assert D(fields["GRZIF1"].calculated_amount) == D("1315.4")
    assert D(fields["PERSON_PAYABLE"].calculated_amount) == D("68.85")
    assert fields["PERSON_PAYABLE"].check_status == "matched"
    assert presentation.result.algorithm_version == "employee_special_fixed_kidney_v1"
    from src.runtime.policy_qa.fee_decomposition.public_view import to_public_contract_dict
    from src.runtime.api.policy_qa_routes import _public_text
    public = to_public_contract_dict(presentation.result, summary_text=presentation.summary_text,
        summary_source=presentation.summary_source, settlement_facts=presentation.settlement_facts, sanitize=_public_text)
    template = public['settlement_facts']['display_template']
    displayed = {field['key']: field for field in template['fields']}
    assert template['template_id'] == 'employee_special_fixed_kidney'
    assert displayed['pool_pay']['value'] == '200.2'
    assert displayed['pool_pay']['field_code'] is None
    assert displayed['hospital_pool_pay']['value'] == fields['TCZHF'].observed_amount
    assert displayed['hospital_pool_pay']['scope'] == 'hospital_quota'
    assert displayed['hospital_pool_pay']['field_code'] == 'TCZHF'
    assert not presentation.result.answer_constraints.may_claim_full_explanation
    assert presentation.summary_source == "template"
    assert closed == [True]
    assert any("tsbybn1" in sql and "AGENCY_PAY_AMOUNT" in sql for sql, _ in queries)
