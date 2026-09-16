"""结算事实记录查询适配器（一档 SQL Server 只读直连）。

承载 2026-09-16 盘点解锁的四类真实查询（见
docs/reviews/2026-09-16-tool69-real-capability-vs-4-questions.md §6）：
退费/冲正记录、费用明细、人员定位结算单、待遇叠加分摊。

约定（对齐 adapters/AGENTS.md）：
- 只接受注入的 PEP 249 连接，禁止反向 import src.runtime；
- 全部返回 AdapterCallResult，不抛业务异常；
- SQL 仅只读 SELECT 且单语句（出口断言），参数化占位符防注入；
- 输出不含患者身份原文（身份证/姓名不入结果）。
"""

from __future__ import annotations

from typing import Any

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus

_SOURCE = "bjybdb_sqlserver"


def assert_read_only_select(sql: str) -> str:
    """出口白名单断言：单语句、仅 SELECT。与语义层查询出口同款硬约束。"""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped or not stripped.lstrip("(").upper().startswith("SELECT"):
        raise ValueError(f"非只读单语句 SELECT，已拒绝执行: {sql[:80]}")
    return stripped


def _result(capability: str, data: dict, *, quality: DataQualityStatus = DataQualityStatus.COMPLETE,
            message: str | None = None) -> AdapterCallResult:
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


# ── 退费/冲正记录 ─────────────────────────────────────────────

_INPATIENT_REFUND_SQL = """
SELECT djh, jylsh, jyrq, zje, tflydjh, STMT_STATE
FROM dbo.yb_zyjyxx
WHERE tflydjh = ? AND tflydjh <> 0
"""

# HIS 收费端退费交易：原交易号链路 / 已退费标志 / 负金额冲正，任一即视为退费相关。
_OUTPATIENT_REFUND_SQL = """
SELECT T_TradeNo, T_TradeDate, T_FeeAll, T_FeeIn, T_FundPay,
       T_HasRefundmented, TR_OraginalTradeNo, TR_RefundmentTradeNo,
       T_PartialReturnFlag, T_OraginalTradeNo
FROM dbo.o_Trade
WHERE (TR_OraginalTradeNo IS NOT NULL AND TR_OraginalTradeNo <> '')
   OR T_HasRefundmented = 1
   OR T_FeeAll < 0
"""


def _identity_clause(id_card: str, insurance_card_no: str, params: list[Any]) -> str:
    """人员唯一标识过滤（三选一里实际提供的），不回显原文。"""
    clauses = []
    if id_card:
        clauses.append("P_IDNo = ?")
        params.append(id_card)
    if insurance_card_no:
        clauses.append("(P_ICNo = ? OR P_CardNo = ?)")
        params.extend([insurance_card_no, insurance_card_no])
    return "(" + " OR ".join(clauses) + ")" if clauses else ""


def query_outpatient_refund_records(
    conn: Any, *, id_card: str = "", insurance_card_no: str = "", visit_date: str = ""
) -> AdapterCallResult:
    """门诊退费记录：HIS 收费端 o_Trade 退费交易链路，按人员标识 + 日期窗口过滤。"""
    try:
        params: list[Any] = []
        identity = _identity_clause(id_card, insurance_card_no, params)
        sql = _OUTPATIENT_REFUND_SQL
        if identity:
            sql += f" AND {identity}"
        if visit_date:
            sql += " AND T_TradeDate >= ? AND T_TradeDate < DATEADD(day, 1, ?)"
            params.extend([visit_date, visit_date])
        rows = _fetch_all(conn, sql, params)
    except Exception as exc:  # noqa: BLE001 — 适配器不抛异常，统一转 FAILED
        return _failed("query_refund_records", f"门诊退费记录查询失败: {exc}")
    records = [
        {
            "trade_no": r.get("t_tradeno"),
            "trade_date": str(r.get("t_tradedate") or ""),
            "fee_all": float(r["t_feeall"]) if r.get("t_feeall") is not None else None,
            "original_trade_no": r.get("tr_oraginaltradeno") or "",
            "partial_return_flag": r.get("t_partialreturnflag") or "",
            "refund_side": "his_outpatient",
        }
        for r in rows
    ]
    return _result(
        "query_refund_records",
        {
            "records": records,
            "refunded_count": len(records),
            "conclusion": f"门诊 HIS 收费端命中 {len(records)} 笔退费相关交易" if records else "未查询到退费相关交易",
        },
    )


def query_inpatient_refund_records(conn: Any, settlement_id: str) -> AdapterCallResult:
    """住院退费记录：医保端 yb_zyjyxx.tflydjh（退费来源登记号）直连 djh。"""
    try:
        rows = _fetch_all(conn, _INPATIENT_REFUND_SQL, [settlement_id])
    except Exception as exc:  # noqa: BLE001
        return _failed("query_refund_records", f"住院退费记录查询失败: {exc}")
    records = [
        {
            "trade_no": r.get("jylsh"),
            "trade_date": str(r.get("jyrq") or ""),
            "fee_all": float(r["zje"]) if r.get("zje") is not None else None,
            "original_trade_no": str(r.get("tflydjh") or ""),
            "partial_return_flag": "",
            "refund_side": "yb_inpatient",
        }
        for r in rows
    ]
    return _result(
        "query_refund_records",
        {
            "records": records,
            "refunded_count": len(records),
            "conclusion": f"住院医保端命中 {len(records)} 笔退费交易（tflydjh={len(records)}）" if records else "未查询到指向该结算单的住院退费交易",
        },
    )


# ── 费用明细 ──────────────────────────────────────────────────

_INPATIENT_FEE_SQL = """
SELECT xh, xmdm, xmmc, NATION_CODE, sflb, sl, dj, zje, ybnje, ybwje, txfy, grziftw, fsrq
FROM dbo.yb_zyfymx WHERE djh = ? ORDER BY xh
"""

_OUTPATIENT_FEE_SQL = """
SELECT xh, xmdm, xmmc, NATION_CODE, sflb, sl, dj, zje, ybnje, ybwje, grziftw, fsrq
FROM dbo.yb_mzfymx WHERE djh = ? ORDER BY xh
"""


def _fee_row(r: dict, service_type: str) -> dict:
    def _num(key: str) -> float | None:
        return float(r[key]) if r.get(key) is not None else None

    return {
        "item_code": r.get("xmdm") or "",
        "nation_code": r.get("nation_code") or "",
        "item_name": r.get("xmmc") or "",
        "fee_category": r.get("sflb") or "",
        "quantity": _num("sl"),
        "unit_price": _num("dj"),
        "total_amount": _num("zje"),
        "insurance_inner_amount": _num("ybnje"),
        "insurance_outer_amount": _num("ybwje"),
        "pre_self_pay_amount": _num("txfy"),
        "individual_first_self_pay": _num("grziftw"),
        "fee_date": str(r.get("fsrq") or ""),
        "service_type": service_type,
    }


def query_fee_detail(conn: Any, settlement_id: str) -> AdapterCallResult:
    """费用明细：按 djh 先查住院（yb_zyfymx），未命中再查门诊（yb_mzfymx）。"""
    try:
        rows = _fetch_all(conn, _INPATIENT_FEE_SQL, [settlement_id])
        service_type = "普通住院"
        if not rows:
            rows = _fetch_all(conn, _OUTPATIENT_FEE_SQL, [settlement_id])
            service_type = "门诊"
    except Exception as exc:  # noqa: BLE001
        return _failed("query_fee_detail", f"费用明细查询失败: {exc}")
    items = [_fee_row(r, service_type) for r in rows]
    return _result(
        "query_fee_detail",
        {
            "settlement_id": settlement_id,
            "service_type": service_type,
            "items": items,
            "item_count": len(items),
            "conclusion": f"{service_type}费用明细 {len(items)} 条" if items else "该结算单下未查询到费用明细",
        },
        quality=DataQualityStatus.COMPLETE if items else DataQualityStatus.MISSING,
    )


# ── 人员定位结算单 ────────────────────────────────────────────

_OUTPATIENT_RESOLVE_SQL = """
SELECT T_TradeNo, T_TradeDate, T_FeeAll, T_FundPay
FROM dbo.o_Trade
WHERE T_TradeDate >= ? AND T_TradeDate < DATEADD(day, 1, ?)
"""

_INPATIENT_RESOLVE_SQL = """
SELECT b.djh, b.ryrq, b.cyrq, b.yllb, z.zje
FROM dbo.yb_brdjxx b
LEFT JOIN dbo.yb_zyjyxx z ON z.djh = b.djh
WHERE b.ryrq <= ? AND (b.cyrq IS NULL OR b.cyrq >= ?)
"""


def _resolve_candidates(
    rows: list[dict], side: str, id_field: str
) -> list[dict]:
    """行 → 候选投影：只含结算标识/日期/金额/类别，不含身份原文。"""
    return [
        {
            "settlement_id": str(r.get("t_tradeno") if side == "his_outpatient" else r.get("djh") or ""),
            "settlement_date": str(r.get("t_tradedate") if side == "his_outpatient" else r.get("ryrq") or ""),
            "total_amount": float(r[key]) if (key := ("t_feeall" if side == "his_outpatient" else "zje")) and r.get(key) is not None else None,
            "service_type": "门诊" if side == "his_outpatient" else "普通住院",
            "resolve_side": side,
            "matched_field": id_field,
        }
        for r in rows
    ]


def resolve_settlements_by_person(
    conn: Any,
    *,
    id_card: str = "",
    patient_id: str = "",
    insurance_card_no: str = "",
    visit_date: str = "",
) -> AdapterCallResult:
    """人员唯一标识（三选一）+ 就诊日期 → 结算单候选。

    门诊走 HIS o_Trade（P_IDNo/P_ICNo/P_CardNo），住院走医保 yb_brdjxx（sfz/kh）
    入院-结算区间命中。多笔命中返回全部候选供人工澄清，禁止自动选定。
    """
    try:
        candidates: list[dict] = []
        # 门诊（HIS 收费端）
        op_params: list[Any] = [visit_date, visit_date]
        identity = _identity_clause(id_card, insurance_card_no, op_params)
        if identity or patient_id:
            if patient_id:
                # HIS 患者ID当前无映射列，保留占位：测试库未启用，不拼空条件
                pass
            sql = _OUTPATIENT_RESOLVE_SQL + (f" AND {identity}" if identity else "")
            op_rows = _fetch_all(conn, sql, op_params)
            candidates.extend(_resolve_candidates(op_rows, "his_outpatient", "identity"))
        # 住院（医保端登记）
        if id_card or insurance_card_no:
            ip_params: list[Any] = [visit_date, visit_date]
            ip_identity = []
            if id_card:
                ip_identity.append("b.sfz = ?")
                ip_params.append(id_card)
            if insurance_card_no:
                ip_identity.append("b.kh = ?")
                ip_params.append(insurance_card_no)
            sql = _INPATIENT_RESOLVE_SQL + " AND (" + " OR ".join(ip_identity) + ")"
            ip_rows = _fetch_all(conn, sql, ip_params)
            candidates.extend(_resolve_candidates(ip_rows, "yb_inpatient", "identity"))
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
        {
            "match_status": match_status,
            "settlement_candidates": candidates,
            "resolve_note": note,
        },
    )


# ── 待遇叠加分摊 ──────────────────────────────────────────────

_BENEFIT_REGISTRATION_SQL = """
SELECT tsb1, tsb2, tsb3, tsbqsrq, tsbjzrq, dbzbs, CIVIL_TYPE, rylx
FROM dbo.yb_brdjxx WHERE djh = ?
"""

_INPATIENT_BENEFIT_SQL = """
SELECT BIG_ILL_PAY, CIVIL_IN, DB_PAY_TRUE, MAF_PAY_TRUE
FROM dbo.yb_zyjyxx WHERE djh = ?
"""

_OUTPATIENT_BENEFIT_SQL = """
SELECT tsbybn, tsbybw, BIG_ILL_PAY, CIVIL_IN, DB_PAY_TRUE, MAF_PAY_TRUE
FROM dbo.yb_mzjyxx WHERE djh = ?
"""


def _num_or_zero(value: Any) -> float:
    return float(value) if value is not None else 0.0


def query_benefit_stacking(conn: Any, settlement_id: str) -> AdapterCallResult:
    """待遇叠加分摊：特病登记（yb_brdjxx.tsb1-3）+ 结算表逐笔分摊列（大病/民政救助）。"""
    try:
        reg_rows = _fetch_all(conn, _BENEFIT_REGISTRATION_SQL, [settlement_id])
        reg = reg_rows[0] if reg_rows else {}
        ben_rows = _fetch_all(conn, _INPATIENT_BENEFIT_SQL, [settlement_id])
        side = "yb_inpatient"
        if not ben_rows:
            ben_rows = _fetch_all(conn, _OUTPATIENT_BENEFIT_SQL, [settlement_id])
            side = "yb_outpatient"
        ben = ben_rows[0] if ben_rows else {}
    except Exception as exc:  # noqa: BLE001
        return _failed("query_benefit_stacking", f"待遇叠加查询失败: {exc}")
    special_codes = [reg.get(k) for k in ("tsb1", "tsb2", "tsb3") if reg.get(k)]
    data = {
        "settlement_id": settlement_id,
        "special_disease_registered": bool(special_codes),
        "special_disease_codes": special_codes,
        "low_income_flag": reg.get("dbzbs") or "",
        "civil_type": reg.get("civil_type") or "",
        "special_disease_inner_amount": _num_or_zero(ben.get("tsbybn")),
        "special_disease_outer_amount": _num_or_zero(ben.get("tsbybw")),
        "big_ill_pay": _num_or_zero(ben.get("big_ill_pay")),
        "civil_assistance_amount": _num_or_zero(ben.get("civil_in")),
        "db_pay_true": _num_or_zero(ben.get("db_pay_true")),
        "maf_pay_true": _num_or_zero(ben.get("maf_pay_true")),
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
    # 低保不确定性：dbzbs 测试库全空，低保身份渠道（民政/CIVIL_TYPE）未经业务确认。
    data["uncertainties"] = [
        "低保标识（dbzbs）在当前数据源无数据，低保待遇维度未覆盖，结论不含低保归因"
    ]
    return _result("query_benefit_stacking", data)
