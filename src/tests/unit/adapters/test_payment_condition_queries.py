from src.adapters.data_supply import payment_condition_queries as queries
from src.adapters.data_supply.settlement_record_queries import assert_read_only_select
from src.adapters.data_supply.record_query_mappings import RecordQueryMapping
import pytest


@pytest.mark.parametrize("special", [False, True])
def test_queries_are_bill_scoped_dated_parameterized_and_do_not_read_identity(monkeypatch, special):
    calls = []
    def fetch(conn, sql, params):
        calls.append((assert_read_only_select(sql), params))
        return []
    monkeypatch.setattr(queries, "_fetch_all", fetch)
    anchor = "x' OR 1=1 --"
    result = queries.load_payment_condition_rows(object(), anchor, special=special)
    assert result.data["catalog_available"] and result.data["diagnosis_available"]
    assert len(calls) == 2
    assert all(params == [anchor] and anchor not in sql for sql, params in calls)
    catalog, diagnosis = [sql for sql, _ in calls]
    assert "BETWEEN CAST(" in catalog and "AS catalog_source" in catalog
    assert "[bz]" in catalog and "TOP" not in catalog.upper()
    assert "[yb_xzzlfwxm]" in catalog
    assert not any(field in (catalog + diagnosis).lower() for field in
                   ("drname", "medicalrecord", "p_idno", "person_name", "symptom"))
    if special:
        assert "[yb_mzzd_mz]" in diagnosis
        assert "d.[jylsh] = t.[jylsh]" in diagnosis and "t.[djh] = ?" in diagnosis
    else:
        assert "[o_Diagnose]" in diagnosis and "[T_TradeNo] = ?" in diagnosis


def test_optional_columns_can_be_unmapped_without_inventing_a_source(monkeypatch):
    calls = []
    monkeypatch.setattr(queries, "_fetch_all", lambda conn, sql, params: calls.append(sql) or [])
    queries.load_payment_condition_rows(object(), "bill", special=False,
        mapping=RecordQueryMapping(columns={"opf_usage": "", "diag_prescriber_level": ""}))
    assert "NULL AS usage" in calls[0]
    assert "NULL AS prescriber_level" in calls[1]
    assert "[]" not in " ".join(calls)


def test_diagnosis_failure_does_not_discard_catalog(monkeypatch):
    def fetch(conn, sql, params):
        if "o_Diagnose" in sql:
            raise RuntimeError("connection details must not escape")
        return [{"line_id": "1", "bz": "限定原文"}]
    monkeypatch.setattr(queries, "_fetch_all", fetch)
    result = queries.load_payment_condition_rows(object(), "bill", special=False)
    assert result.data["catalog_rows"][0]["bz"] == "限定原文"
    assert result.data["catalog_available"] is True
    assert result.data["diagnosis_available"] is False
    assert "connection details" not in result.model_dump_json()
