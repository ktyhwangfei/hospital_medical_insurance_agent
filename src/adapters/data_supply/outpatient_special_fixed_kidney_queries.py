"""肾/肝肾抗排异定额独立定位、事实投影和累计口径，全部只读。"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from src.adapters.base.models import AdapterCallResult, DataQualityStatus
from src.adapters.data_supply.outpatient_special_mz_queries import (
    _REGISTRATION_COLUMNS, _SETTLEMENT_COLUMNS, _failed, _result, _to_date, _to_decimal, _to_str,
)
from src.adapters.data_supply.settlement_record_queries import _fetch_all, assert_read_only_select
from src.domain.insurance.fee_decomposition import KidneyFixedQuotaContext, OutpatientSpecialSnapshot
from src.config.settlement_templates import get_settlement_template, settlement_template_columns
from src.adapters.data_supply.settlement_template_bindings import bind_template_values, observed_template_amounts

KIDNEY_SCOPE_SQL = "(b.tsb1 IN ('503','504') OR b.tsb2 IN ('503','504') OR b.tsb3 IN ('503','504'))"
FIXED_COLUMNS = tuple(column for column in settlement_template_columns('employee_special_fixed_kidney', 'outpatient_settlement_table')
                      if column not in _SETTLEMENT_COLUMNS) + ('tsbybn2', 'deqsrq', 'dejzrq')


def has_kidney_code(row: Mapping[str, Any]) -> bool:
    return any(_to_str(row.get(key)) in ("503", "504") for key in ("tsb1", "tsb2", "tsb3"))


def locate_special_fixed_kidney_registration(conn: Any, djh: str) -> AdapterCallResult:
    columns = ", ".join(f"b.{column}" for column in _REGISTRATION_COLUMNS)
    sql = (f"SELECT {columns} FROM dbo.yb_brdjxx b JOIN dbo.yb_mzjyxx m ON b.djh=m.djh "
           f"WHERE b.djh=? AND b.yllb='12' AND b.FUND_TYPE=3 AND m.fyfs='0' AND {KIDNEY_SCOPE_SQL}")
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:
        return _failed(f"定额门特登记定位失败: {exc}")
    status = "unique_match" if len(rows) == 1 else "not_found" if not rows else "ambiguous"
    return _result({"match_status": status, "registration_row": rows[0] if len(rows) == 1 else None,
                    "row_count": len(rows)}, quality=DataQualityStatus.COMPLETE if len(rows) == 1 else DataQualityStatus.MISSING)


def load_special_fixed_kidney_settlement(conn: Any, djh: str) -> AdapterCallResult:
    sql = f"SELECT {', '.join((*_SETTLEMENT_COLUMNS, *FIXED_COLUMNS))} FROM dbo.yb_mzjyxx WHERE djh=?"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:
        return _failed(f"定额门特结算读取失败: {exc}")
    return _result({"settlement_row": rows[0] if len(rows) == 1 else None, "row_count": len(rows),
                    "note": None if len(rows) == 1 else "结算行缺失或歧义"})


def fixed_accumulation_settlement(row: Mapping[str, Any]) -> dict[str, Any]:
    """交易后快照减本笔医院定额口径，609不能减普通汇总制造6元/10.4元假前值。"""
    bound = bind_template_values(get_settlement_template('employee_special_fixed_kidney'), {'outpatient_settlement_table': row}).values
    return {**row, "tsbybn": bound['quota_amount'], "tczhf": bound['hospital_pool_pay'], "degwyzhf": bound['hospital_big_pay']}


def attach_fixed_quota(snapshot: OutpatientSpecialSnapshot, registration: Mapping[str, Any],
                       settlement: Mapping[str, Any], cycle_row: Mapping[str, Any] | None) -> OutpatientSpecialSnapshot:
    """后缀1的基金/补助是本链路核对目标；定额公疗列不与普通公疗汇总重复相加。"""
    template = get_settlement_template('employee_special_fixed_kidney')
    observed = replace(snapshot.observed, **observed_template_amounts(template, {'outpatient_settlement_table': settlement}))
    bound = bind_template_values(template, {'outpatient_settlement_table': settlement}).values
    context = KidneyFixedQuotaContext(
        special_codes=tuple(value for key in ("tsb1", "tsb2", "tsb3") if (value := _to_str(registration.get(key))) is not None),
        designated_hospital_flag=_to_str(registration.get("spec_hosp_flag")),
        quota_amount=_to_decimal(bound['quota_amount']),
        medication_start=_to_date(settlement.get("deqsrq")), medication_end=_to_date(settlement.get("dejzrq")),
        cycle_start=_to_date(cycle_row.get("bqqsrq")) if cycle_row is not None else None,
        initial_self_pay_observed=_to_decimal(bound['initial_self']),
        agency_pay_observed=_to_decimal(bound['agency_pay']))
    return replace(snapshot, observed=observed, kidney_fixed_quota=context)
