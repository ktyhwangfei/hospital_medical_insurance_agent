import re
from pathlib import Path


SCRIPT = Path(__file__).parents[4] / "scripts" / "enable_outpatient_cdc.sql"


def test_outpatient_cdc_enablement_is_fixed_and_read_only_for_business_data() -> None:
    sql = SCRIPT.read_text(encoding="utf-8")
    upper = sql.upper()

    assert set(re.findall(r"@source_name\s*=\s*N'([^']+)'", sql)) == {
        "o_Trade", "o_FeeItem", "o_Diagnose",
    }
    assert set(re.findall(r"@capture_instance\s*=\s*N'([^']+)'", sql)) == {
        "dbo_o_Trade", "dbo_o_FeeItem", "dbo_o_Diagnose",
    }
    assert sql.count("sys.sp_cdc_enable_table") == 3
    assert sql.count("@supports_net_changes = 0") == 3
    assert "@retention = 4320" in sql
    assert "outpatient_cdc_reader" in sql

    captured = dict(re.findall(
        r"@source_name\s*=\s*N'([^']+)'.*?@captured_column_list\s*=\s*N'([^']+)'",
        sql,
        re.DOTALL,
    ))
    assert set(captured) == {"o_Trade", "o_FeeItem", "o_Diagnose"}
    assert {name: len(columns.split(",")) for name, columns in captured.items()} == {
        "o_Trade": 87, "o_FeeItem": 20, "o_Diagnose": 10,
    }
    for sensitive_column in [
        "P_IDNo", "P_ICNo", "P_Name", "P_Birthday", "P_CardNo", "HisName", "HisCode",
    ]:
        assert all(sensitive_column not in columns for columns in captured.values())
    assert "RecipeNo" not in captured["o_FeeItem"]
    assert "RecipeNo" in captured["o_Diagnose"]

    assert not re.search(r"\b(DROP|INSERT|UPDATE|DELETE)\b", upper)
    assert "TRY_CONVERT" not in upper
    assert "STRING_AGG" not in upper
    assert "sys.databases" in sql
    assert "cdc.change_tables" in sql
    assert "start_lsn" in sql
    assert "msdb.dbo.cdc_jobs" in sql
