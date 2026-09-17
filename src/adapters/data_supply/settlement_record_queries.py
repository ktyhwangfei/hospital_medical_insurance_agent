"""结算事实记录查询适配器（映射驱动，一档只读直连）。

承载四类真实查询（见
docs/reviews/2026-09-16-tool69-real-capability-vs-4-questions.md §6）：
退费/冲正记录、费用明细、人员定位结算单、待遇叠加分摊。

产品化约定（多院区）：
- 表名/列名全部来自 RecordQueryMapping（默认 = bjybdb 基线，各院区可注册覆盖），
  本模块不出现任何裸物理标识符；
- 只接受注入的 PEP 249 连接，禁止反向 import src.runtime；
- 全部返回 AdapterCallResult，不抛业务异常；
- SQL 仅只读 SELECT 且单语句（出口断言），参数化占位符防注入；
- 输出不含患者身份原文（身份证/姓名不入结果）。
"""

from __future__ import annotations

from typing import Any

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply.record_query_mappings import (
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
)

_SOURCE = "hospital_record_store"


def assert_read_only_select(sql: str) -> str:
    """出口白名单断言：单语句、仅 SELECT。与语义层查询出口同款硬约束。"""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped or not stripped.lstrip("(").upper().startswith("SELECT"):
        raise ValueError(f"非只读单语句 SELECT，已拒绝执行: {sql[:80]}")
    return stripped


def _result(
    capability: str, data: dict, *, quality: DataQualityStatus = DataQualityStatus.COMPLETE,
    message: str | None = None,
) -> AdapterCallResult:
    return AdapterCallResult(
        status=AdapterCallStatus.SUCCESS,
        source_system=_SOURCE,
        capability=capability,
        data=data,
        data_quality=quality,
        message=message,
    )


def _failed(capability: str, message: str) -> AdapterCallResult:
    return AdapterCallResult(
        status=AdapterCallStatus.FAILED,
        source_system=_SOURCE,
        capability=capability,
        data_quality=DataQualityStatus.MISSING,
        error_type="DATASOURCE_QUERY_FAILED",
        message=message,
    )


def _fetch_all(conn: Any, sql: str, params: list[Any]) -> list[dict]:
    """执行只读查询并返回 dict 行（列名小写键）。"""
    cur = conn.cursor()
    try:
        cur.execute(assert_read_only_select(sql), params)
        cols = [c[0].lower() for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def _c(m: RecordQueryMapping, key: str) -> str:
    """映射逻辑列 → 方言引用的物理列。"""
    return m.quote(m.column(key)) if "." not in m.column(key) else m.column(key)


def _k(m: RecordQueryMapping, key: str) -> str:
    """结果行取键：按映射后的物理列名小写（跨院区列名不同时仍能取到值）。"""
    return m.column(key).lower().split(".")[-1]


def _t(m: RecordQueryMapping, table_attr: str) -> str:
    return m.quote(getattr(m, table_attr))


# ── 结算侧别检测 ──────────────────────────────────────────────


def detect_settlement_side(
    conn: Any, settlement_id: str, mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING
) -> str | None:
    """判定结算单属于住院/门诊医保端（None = 两端均无记录）。"""
    try:
        ip = _fetch_all(
            conn,
            f"SELECT 1 FROM {_t(mapping, 'inpatient_settlement_table')} "
            f"WHERE {_c(mapping, 'ip_djh')} = ?",
            [settlement_id],
        )
        if ip:
            return "inpatient"
        op = _fetch_all(
            conn,
            f"SELECT 1 FROM {_t(mapping, 'outpatient_settlement_table')} "
            f"WHERE {_c(mapping, 'op_set_djh')} = ?",
            [settlement_id],
        )
        if op:
            return "outpatient"
        return None
    except Exception:  # noqa: BLE001 — 侧别检测失败按未知处理，调用方 fail-closed
        return None


# ── 退费/冲正记录 ─────────────────────────────────────────────


def _inpatient_refund_sql(m: RecordQueryMapping) -> str:
    return (
        f"SELECT {_c(m, 'ip_djh')}, {_c(m, 'ip_jylsh')}, {_c(m, 'ip_jyrq')}, "
        f"{_c(m, 'ip_zje')}, {_c(m, 'ip_tflydjh')} "
        f"FROM {_t(m, 'inpatient_settlement_table')} "
        f"WHERE {_c(m, 'ip_tflydjh')} = ? AND {_c(m, 'ip_tflydjh')} <> 0"
    )


def _outpatient_refund_sql(
    m: RecordQueryMapping, identity: str, with_date: bool, with_original: bool = False
) -> str:
    """HIS 门诊退费交易链路（关联原交易取起付线/年度累计，供 Q4 核验）。"""
    o = "o"  # 原交易别名
    r_cols = ", ".join(
        f"r.{_c(m, k)}" for k in (
            "op_trade_no", "op_trade_date", "op_fee_all", "op_fee_in", "op_fund_pay",
            "op_has_refundmented", "op_ref_original_no", "op_ref_trade_no",
            "op_partial_return", "op_reversal_original_no",
        )
    )
    orig = ", ".join(
        f"{o}.{_c(m, k)}" for k in ("op_first_pay", "op_year", "op_year_times")
    )
    sql = (
        f"SELECT {r_cols}, {orig} "
        f"FROM {_t(m, 'outpatient_trade_table')} r "
        f"LEFT JOIN {_t(m, 'outpatient_trade_table')} {o} "
        f"ON {o}.{_c(m, 'op_trade_no')} = r.{_c(m, 'op_ref_original_no')} "
        # 基础退费条件整体括号：后续 AND 过滤（原交易号/身份/日期）不得被 OR 优先级吞掉
        f"WHERE ((r.{_c(m, 'op_ref_original_no')} IS NOT NULL AND r.{_c(m, 'op_ref_original_no')} <> '') "
        f"OR r.{_c(m, 'op_has_refundmented')} = 1 "
        f"OR r.{_c(m, 'op_fee_all')} < 0)"
    )
    if with_original:
        sql += f" AND r.{_c(m, 'op_ref_original_no')} = ?"
    if identity:
        sql += f" AND {identity}"
    if with_date:
        sql += (
            f" AND r.{_c(m, 'op_trade_date')} >= ? AND r.{_c(m, 'op_trade_date')} < "
            f"DATEADD(day, 1, ?)"
        )
    return sql


def _identity_clause(
    m: RecordQueryMapping, id_card: str, insurance_card_no: str, params: list[Any]
) -> str:
    clauses = []
    if id_card:
        clauses.append(f"r.{_c(m, 'op_id_card')} = ?")
        params.append(id_card)
    if insurance_card_no:
        clauses.append(f"(r.{_c(m, 'op_card_ic')} = ? OR r.{_c(m, 'op_card_no')} = ?)")
        params.extend([insurance_card_no, insurance_card_no])
    return "(" + " OR ".join(clauses) + ")" if clauses else ""


def _num(value: Any) -> float | None:
    return float(value) if value is not None else None


def query_outpatient_refund_records(
    conn: Any,
    *,
    id_card: str = "",
    insurance_card_no: str = "",
    visit_date: str = "",
    original_trade_no: str = "",
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """门诊退费记录：HIS 交易表退费链路，按人员标识/原交易号/日期窗口过滤。"""
    try:
        params: list[Any] = []
        identity = _identity_clause(mapping, id_card, insurance_card_no, params)
        if original_trade_no:
            params.insert(0, original_trade_no)
        sql = _outpatient_refund_sql(
            mapping, identity, bool(visit_date), bool(original_trade_no)
        )
        if visit_date:
            params.extend([visit_date, visit_date])
        rows = _fetch_all(conn, sql, params)
    except Exception as exc:  # noqa: BLE001 — 适配器不抛异常，统一转 FAILED
        return _failed("query_refund_records", f"门诊退费记录查询失败: {exc}")
    records = [
        {
            "trade_no": r.get(_k(mapping, "op_trade_no")),
            "trade_date": str(r.get(_k(mapping, "op_trade_date")) or ""),
            "fee_all": _num(r.get(_k(mapping, "op_fee_all"))),
            "original_trade_no": r.get(_k(mapping, "op_ref_original_no")) or "",
            "partial_return_flag": r.get(_k(mapping, "op_partial_return")) or "",
            "refund_side": "his_outpatient",
            # 原交易起付线/年度累计（Q4：退费结算架构核验事实）
            "original_first_pay": _num(r.get(_k(mapping, "op_first_pay"))),
            "original_year": r.get(_k(mapping, "op_year")),
            "original_year_times": r.get(_k(mapping, "op_year_times")),
        }
        for r in rows
    ]
    return _result(
        "query_refund_records",
        {
            "records": records,
            "refunded_count": len(records),
            "conclusion": (
                f"门诊 HIS 收费端命中 {len(records)} 笔退费相关交易"
                if records
                else "未查询到退费相关交易"
            ),
        },
    )


def query_inpatient_refund_records(
    conn: Any, settlement_id: str, mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING
) -> AdapterCallResult:
    """住院退费记录：医保端 tflydjh（退费来源登记号）直连 djh。"""
    try:
        rows = _fetch_all(conn, _inpatient_refund_sql(mapping), [settlement_id])
    except Exception as exc:  # noqa: BLE001
        return _failed("query_refund_records", f"住院退费记录查询失败: {exc}")
    records = [
        {
            "trade_no": r.get(_k(mapping, "ip_jylsh")),
            "trade_date": str(r.get(_k(mapping, "ip_jyrq")) or ""),
            "fee_all": _num(r.get(_k(mapping, "ip_zje"))),
            "original_trade_no": str(r.get(_k(mapping, "ip_tflydjh")) or ""),
            "partial_return_flag": "",
            "refund_side": "yb_inpatient",
            "original_first_pay": None,
            "original_year": None,
            "original_year_times": None,
        }
        for r in rows
    ]
    return _result(
        "query_refund_records",
        {
            "records": records,
            "refunded_count": len(records),
            "conclusion": (
                f"住院医保端命中 {len(records)} 笔退费交易（tflydjh）"
                if records
                else "未查询到指向该结算单的住院退费交易"
            ),
        },
    )


# ── 费用明细 ──────────────────────────────────────────────────


def _fee_sql(m: RecordQueryMapping, table_attr: str, with_pre_self: bool) -> str:
    cols = [
        "fee_seq", "fee_item_code", "fee_item_name", "fee_nation_code", "fee_category",
        "fee_qty", "fee_price", "fee_total", "fee_inner", "fee_outer",
    ]
    if with_pre_self:
        cols.append("fee_pre_self")
    cols.append("fee_indiv_first")
    cols.append("fee_date")
    rendered = ", ".join(_c(m, k) for k in cols)
    return (
        f"SELECT {rendered} FROM {_t(m, table_attr)} "
        f"WHERE {_c(m, 'ip_djh')} = ? ORDER BY {_c(m, 'fee_seq')}"
    )


def _fee_row(m: RecordQueryMapping, r: dict, service_type: str) -> dict:
    return {
        "item_code": r.get(_k(m, "fee_item_code")) or "",
        "nation_code": r.get(_k(m, "fee_nation_code")) or "",
        "item_name": r.get(_k(m, "fee_item_name")) or "",
        "fee_category": r.get(_k(m, "fee_category")) or "",
        "quantity": _num(r.get(_k(m, "fee_qty"))),
        "unit_price": _num(r.get(_k(m, "fee_price"))),
        "total_amount": _num(r.get(_k(m, "fee_total"))),
        "insurance_inner_amount": _num(r.get(_k(m, "fee_inner"))),
        "insurance_outer_amount": _num(r.get(_k(m, "fee_outer"))),
        "pre_self_pay_amount": _num(r.get(_k(m, "fee_pre_self"))),
        "individual_first_self_pay": _num(r.get(_k(m, "fee_indiv_first"))),
        "fee_date": str(r.get(_k(m, "fee_date")) or ""),
        "service_type": service_type,
    }


def query_fee_detail(
    conn: Any,
    settlement_id: str,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """费用明细：按 djh 先查住院表，未命中再查门诊表。"""
    try:
        rows = _fetch_all(conn, _fee_sql(mapping, "inpatient_fee_table", True), [settlement_id])
        service_type = "普通住院"
        if not rows:
            rows = _fetch_all(conn, _fee_sql(mapping, "outpatient_fee_table", False), [settlement_id])
            service_type = "门诊"
    except Exception as exc:  # noqa: BLE001
        return _failed("query_fee_detail", f"费用明细查询失败: {exc}")
    items = [_fee_row(mapping, r, service_type) for r in rows]
    return _result(
        "query_fee_detail",
        {
            "settlement_id": settlement_id,
            "service_type": service_type,
            "items": items,
            "item_count": len(items),
            "conclusion": (
                f"{service_type}费用明细 {len(items)} 条" if items else "该结算单下未查询到费用明细"
            ),
        },
        quality=DataQualityStatus.COMPLETE if items else DataQualityStatus.MISSING,
    )


# ── 人员定位结算单 ────────────────────────────────────────────


def resolve_settlements_by_person(
    conn: Any,
    *,
    id_card: str = "",
    patient_id: str = "",
    insurance_card_no: str = "",
    visit_date: str = "",
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """人员唯一标识（三选一）+ 就诊日期 → 结算单候选。

    门诊走 HIS 交易表（身份列），住院走医保端登记表入院-结算区间命中。
    多笔命中返回全部候选供人工澄清，禁止自动选定。
    """
    try:
        candidates: list[dict] = []
        op_params: list[Any] = [visit_date, visit_date]
        identity = _identity_clause(mapping, id_card, insurance_card_no, op_params)
        if identity:
            sql = (
                f"SELECT r.{_c(mapping, 'op_trade_no')}, r.{_c(mapping, 'op_trade_date')}, "
                f"r.{_c(mapping, 'op_fee_all')}, r.{_c(mapping, 'op_fund_pay')} "
                f"FROM {_t(mapping, 'outpatient_trade_table')} r "
                f"WHERE r.{_c(mapping, 'op_trade_date')} >= ? "
                f"AND r.{_c(mapping, 'op_trade_date')} < DATEADD(day, 1, ?) "
                f"AND {identity}"
            )
            for r in _fetch_all(conn, sql, op_params):
                candidates.append(
                    {
                        "settlement_id": str(r.get(_k(mapping, "op_trade_no")) or ""),
                        "settlement_date": str(r.get(_k(mapping, "op_trade_date")) or ""),
                        "total_amount": _num(r.get(_k(mapping, "op_fee_all"))),
                        "service_type": "门诊",
                        "resolve_side": "his_outpatient",
                        "matched_field": "identity",
                    }
                )
        if id_card or insurance_card_no:
            ip_params: list[Any] = [visit_date, visit_date]
            ip_identity = []
            if id_card:
                ip_identity.append(f"b.{_c(mapping, 'reg_id_card')} = ?")
                ip_params.append(id_card)
            if insurance_card_no:
                ip_identity.append(f"b.{_c(mapping, 'reg_card_no')} = ?")
                ip_params.append(insurance_card_no)
            sql = (
                f"SELECT b.{_c(mapping, 'reg_djh')}, b.{_c(mapping, 'reg_admit_date')}, "
                f"b.{_c(mapping, 'reg_discharge_date')}, z.{_c(mapping, 'ip_zje')} "
                f"FROM {_t(mapping, 'registration_table')} b "
                f"LEFT JOIN {_t(mapping, 'inpatient_settlement_table')} z "
                f"ON z.{_c(mapping, 'ip_djh')} = b.{_c(mapping, 'reg_djh')} "
                f"WHERE b.{_c(mapping, 'reg_admit_date')} <= ? "
                f"AND (b.{_c(mapping, 'reg_discharge_date')} IS NULL "
                f"OR b.{_c(mapping, 'reg_discharge_date')} >= ?) "
                f"AND ({' OR '.join(ip_identity)})"
            )
            for r in _fetch_all(conn, sql, ip_params):
                candidates.append(
                    {
                        "settlement_id": str(r.get(_k(mapping, "reg_djh")) or ""),
                        "settlement_date": str(r.get(_k(mapping, "reg_admit_date")) or ""),
                        "total_amount": _num(r.get(_k(mapping, "ip_zje"))),
                        "service_type": "普通住院",
                        "resolve_side": "yb_inpatient",
                        "matched_field": "identity",
                    }
                )
    except Exception as exc:  # noqa: BLE001
        return _failed("resolve_settlements", f"人员定位结算单查询失败: {exc}")
    if len(candidates) > 1:
        match_status = "multiple_candidates"
        note = f"命中 {len(candidates)} 笔候选结算单，需人工澄清选择（不确定不执行）"
    elif len(candidates) == 1:
        match_status = "unique_match"
        note = "唯一命中"
    else:
        match_status = "no_match"
        note = "未命中结算单"
    return _result(
        "resolve_settlements",
        {"match_status": match_status, "settlement_candidates": candidates, "resolve_note": note},
    )


# ── 待遇叠加分摊 ──────────────────────────────────────────────


def query_benefit_stacking(
    conn: Any,
    settlement_id: str,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """待遇叠加分摊：特病登记（登记表）+ 结算表逐笔分摊列（大病/民政救助）。"""
    try:
        reg_rows = _fetch_all(
            conn,
            f"SELECT {_c(mapping, 'reg_spec1')}, {_c(mapping, 'reg_spec2')}, "
            f"{_c(mapping, 'reg_spec3')}, {_c(mapping, 'reg_low_income')}, "
            f"{_c(mapping, 'reg_civil_type')} "
            f"FROM {_t(mapping, 'registration_table')} "
            f"WHERE {_c(mapping, 'reg_djh')} = ?",
            [settlement_id],
        )
        reg = reg_rows[0] if reg_rows else {}
        ben_cols = [
            "ip_big_ill_pay", "ip_civil_in", "ip_db_pay_true", "ip_maf_pay_true",
        ]
        rendered = ", ".join(_c(mapping, k) for k in ben_cols)
        ben_rows = _fetch_all(
            conn,
            f"SELECT {rendered} FROM {_t(mapping, 'inpatient_settlement_table')} "
            f"WHERE {_c(mapping, 'ip_djh')} = ?",
            [settlement_id],
        )
        side = "yb_inpatient"
        if not ben_rows:
            ben_cols = ["ip_tsbybn", "ip_tsbybw"] + ben_cols
            rendered = ", ".join(_c(mapping, k) for k in ben_cols)
            ben_rows = _fetch_all(
                conn,
                f"SELECT {rendered} FROM {_t(mapping, 'outpatient_settlement_table')} "
                f"WHERE {_c(mapping, 'op_set_djh')} = ?",
                [settlement_id],
            )
            side = "yb_outpatient"
        ben = ben_rows[0] if ben_rows else {}
    except Exception as exc:  # noqa: BLE001
        return _failed("query_benefit_stacking", f"待遇叠加查询失败: {exc}")

    def _z(key: str) -> float:
        physical = _k(mapping, key)
        return float(ben.get(physical)) if ben.get(physical) is not None else 0.0

    special_codes = [
        reg.get(_k(mapping, k))
        for k in ("reg_spec1", "reg_spec2", "reg_spec3")
        if reg.get(_k(mapping, k))
    ]
    data = {
        "settlement_id": settlement_id,
        "special_disease_registered": bool(special_codes),
        "special_disease_codes": special_codes,
        "low_income_flag": reg.get(_k(mapping, "reg_low_income")) or "",
        "civil_type": reg.get(_k(mapping, "reg_civil_type")) or "",
        "special_disease_inner_amount": _z("ip_tsbybn"),
        "special_disease_outer_amount": _z("ip_tsbybw"),
        "big_ill_pay": _z("ip_big_ill_pay"),
        "civil_assistance_amount": _z("ip_civil_in"),
        "db_pay_true": _z("ip_db_pay_true"),
        "maf_pay_true": _z("ip_maf_pay_true"),
        "resolve_side": side,
    }
    stacking_parts = [
        f"大病支付 {data['big_ill_pay']}",
        f"民政救助 {data['civil_assistance_amount']}",
        f"特病医保内 {data['special_disease_inner_amount']}",
    ]
    data["conclusion"] = (
        f"该结算单实际分摊：{'；'.join(stacking_parts)}"
        + (f"；特病登记 {len(special_codes)} 项" if special_codes else "；无特病登记")
    )
    data["uncertainties"] = [
        "低保标识（dbzbs）在当前数据源无数据，低保待遇维度未覆盖，结论不含低保归因"
    ]
    return _result("query_benefit_stacking", data)
