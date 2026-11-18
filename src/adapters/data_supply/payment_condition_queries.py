"""读取本单的目录备注和诊断；补充查询失败不改变既有费用计算。"""
from __future__ import annotations

from typing import Any

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING, RecordQueryMapping
from src.adapters.data_supply.settlement_record_queries import _c, _fetch_all, _t


def _column(mapping: RecordQueryMapping, alias: str, key: str) -> str:
    return f"{alias}.{_c(mapping, key)}" if mapping.column(key).strip() else "NULL"


def load_payment_condition_rows(
    conn: Any, anchor: str, *, special: bool,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """目录按本次费用时点关联；诊断独立读取，避免一对多放大金额。

    门特诊断按结算流水关联，绝不以相同处方号跨结算单补诊断。
    不读取自由病历、患者/医师姓名及身份证；现有来源无独立症状字段。
    """
    m = mapping
    def f(key: str) -> str:
        return _column(m, "f", key)
    def t(key: str) -> str:
        return _column(m, "t", key)
    if special:
        keys = ("fee_seq", "fee_item_code", "fee_item_type", "fee_recipe_no",
                "fee_specification", "fee_unit", "fee_usage")
        fee_date = f("fee_date")
        date_expr = f"COALESCE({fee_date}, {t('op_set_date')})"
        from_sql = (f"FROM {_t(m, 'outpatient_fee_table')} f "
                    f"JOIN {_t(m, 'outpatient_settlement_table')} t "
                    f"ON {f('fee_djh')} = {t('op_set_djh')}")
        where = f"{f('fee_djh')} = ?"
        diagnostic_sql = (
            f"SELECT d.{_c(m, 'special_diag_recipe_no')} AS recipe_ref, "
            f"d.{_c(m, 'special_diag_code')} AS diagnosis_code, "
            f"d.{_c(m, 'special_diag_name')} AS diagnosis_name, "
            "NULL AS department, NULL AS prescriber_level "
            f"FROM {_t(m, 'special_outpatient_diagnosis_table')} d "
            f"JOIN {_t(m, 'outpatient_settlement_table')} t "
            f"ON d.{_c(m, 'special_diag_trade_no')} = {t('op_set_jylsh')} "
            f"WHERE {t('op_set_djh')} = ?")
    else:
        keys = ("opf_line_id", "opf_item_code", "opf_item_type", "opf_recipe_no",
                "opf_specification", "opf_unit", "opf_usage")
        fee_date = f("opf_fee_date")
        date_expr = f"COALESCE({fee_date}, {t('op_trade_date')})"
        from_sql = (f"FROM {_t(m, 'outpatient_trade_fee_table')} f "
                    f"JOIN {_t(m, 'outpatient_trade_table')} t "
                    f"ON {f('opf_trade_no')} = {t('op_trade_no')}")
        where = f"{f('opf_trade_no')} = ?"
        diagnostic_sql = (
            f"SELECT {_column(m, 'd', 'diag_recipe_no')} AS recipe_ref, "
            f"{_column(m, 'd', 'diag_code')} AS diagnosis_code, {_column(m, 'd', 'diag_name')} AS diagnosis_name, "
            f"{_column(m, 'd', 'diag_department')} AS department, "
            f"{_column(m, 'd', 'diag_prescriber_level')} AS prescriber_level "
            f"FROM {_t(m, 'outpatient_diagnosis_table')} d "
            f"WHERE d.{_c(m, 'diag_trade_no')} = ?")
    line, code, kind, recipe, spec, unit, usage = (f(key) for key in keys)
    date_expr = f"CAST({date_expr} AS date)"
    is_drug = f"{kind} = '0'"
    is_service = f"{kind} IN ('1', '2')"
    is_material = f"{kind} = '3'"
    source_expr = (f"CASE WHEN {is_drug} THEN '药品目录' "
                   f"WHEN {is_service} THEN '诊疗目录' WHEN {is_material} THEN '材料目录' END")
    select = [f"{expr} AS {name}" for expr, name in (
        (line, "line_id"), (code, "item_code"), (recipe, "recipe_ref"),
        (spec, "specification"), (unit, "unit"), (usage, "usage"),
        (date_expr, "fee_date"))]
    select.append(f"{source_expr} AS catalog_source")
    select.append(f"CASE WHEN {fee_date} IS NULL THEN 'settlement_date_fallback' ELSE 'fee_date' END AS date_basis")
    for name, drug_key, service_key in (
        ("catalog_code", "cat_drug_code", "cat_svc_code"),
        ("bz", "cat_drug_note", "cat_svc_note"),
        ("effective_from", "cat_drug_effective", "cat_svc_effective"),
        ("effective_to", "cat_drug_expiry", "cat_svc_expiry"),
    ):
        select.append(f"CASE WHEN {is_drug} THEN {_column(m, 'd', drug_key)} "
                      f"WHEN {is_service} THEN {_column(m, 's', service_key)} "
                      f"WHEN {is_material} THEN {_column(m, 'a', service_key)} END AS {name}")
    for key, name in (("cat_drug_hospital_level", "catalog_hospital_level"),
                      ("cat_drug_hospital_type", "catalog_hospital_type"),
                      ("cat_drug_use_restriction", "catalog_use_restriction")):
        select.append(f"CASE WHEN {is_drug} THEN {_column(m, 'd', key)} END AS {name}")
    joins = []
    for alias, table, prefix, condition in (
        ("d", "drug_catalog_table", "cat_drug", is_drug),
        ("s", "service_catalog_table", "cat_svc", is_service),
        ("a", "material_catalog_table", "cat_svc", is_material),
    ):
        joins.append(f"LEFT JOIN {_t(m, table)} {alias} ON {condition} "
                     f"AND {code} = {_column(m, alias, prefix + '_code')} "
                     f"AND {date_expr} BETWEEN CAST({_column(m, alias, prefix + '_effective')} AS date) "
                     f"AND CAST({_column(m, alias, prefix + '_expiry')} AS date)")
    catalog_sql = f"SELECT {', '.join(select)} {from_sql} {' '.join(joins)} WHERE {where}"
    data: dict[str, Any] = {}
    # 两次补充读取独立降级；一侧缺失不能抹掉另一侧已取得的事实。
    for key, sql in (("catalog", catalog_sql), ("diagnosis", diagnostic_sql)):
        try:
            data[key + "_rows"] = _fetch_all(conn, sql, [anchor])
            data[key + "_available"] = True
        except Exception:  # noqa: BLE001 — 仅标记补充资料不可用，不外泄异常及连接信息
            data[key + "_rows"] = []
            data[key + "_available"] = False
    return AdapterCallResult(
        status=AdapterCallStatus.SUCCESS, source_system="hospital_record_store",
        capability="payment_condition_context", data=data,
        data_quality=DataQualityStatus.COMPLETE if all(data[k] for k in
            ("catalog_available", "diagnosis_available")) else DataQualityStatus.DEGRADED,
    )
