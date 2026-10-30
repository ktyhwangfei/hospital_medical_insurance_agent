"""职工门特·按项目付费费用分解事实快照读取适配器（Issue #79，门诊套表）。

Issue #79 明确门特·按项目付费走**门诊套表**（SQL Server bjybdb）：
- ``dbo.yb_brdjxx`` 登记：键 djh；yllb='12'=门诊特殊病（ESP-CODE-001 候选扩展）；
- ``dbo.yb_mzjyxx`` 结算：每 djh 恰好 1 行；fyfs='0'=项目付费（费用方式码表实测）；
- ``dbo.yb_mzfymx`` 明细：djh+xh 行键；
- ``dbo.yb_dyxxtsb`` 门特结算周期：bqqsrq/bqljybnje/bqqfje（交易后口径，医保中心侧数据，
  含跨院累计）；
- ``dbo.yb_dyxxnd`` 年度待遇：bnzqslj/bntczfje/bndezfje（交易后口径）；
- 资格字段：cjjrdj 军残等级、gwydybz 公疗标志（0=享受/1=不享受，与红名单相反，
  Issue #79 手工验证结论）、cblb=61 社会化退休（退休补充类别候选映射）。

读取约定：只接受注入的 PEP 249 连接、只读参数化
单语句 SELECT、不 SELECT 身份证/姓名、全部返回 AdapterCallResult 不抛业务异常
（``build_special_mz_snapshot`` 为纯组装函数，脏数据抛 ValueError 由服务层降级）。

交易后口径推导（本批 9 笔有周期行样本实测，bjyb 库 2024 年）：
- bnmcjylsh == 本笔交易流水号 → dyxxnd 行为本笔交易**结算后**快照；
- 交易前年度统筹累计 = bntczfje − 本笔 tczhf；大额同理（bndezfje − degwyzhf）；
- 交易前周期已交起付 = bqqfje − 本笔 ybnqfje；
- 交易前周期内医保内累计（分段绝对坐标）= bqljybnje − 本笔 tsbybn；
- 适用起付标准：bnzqslj<=1 → 1300（年度第一个住院类结算周期），否则 650。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply.settlement_record_queries import (
    _fetch_all,
    assert_read_only_select,
)
from src.domain.insurance.fee_decomposition import (
    OutpatientSpecialSnapshot,
    RoundingMode,
    SpecialCycleContext,
    SpecialFeeLineItem,
    SpecialInstitutionProfile,
    SpecialObservedAmounts,
    SpecialPersonProfile,
    SecondaryCoverageContext,
)

#: 门特医疗类别码 / 险种码 / 项目付费费用方式码（Issue #79 实测候选口径，待码表确认）
SPECIAL_MZ_YLLB = "12"
EMPLOYEE_FUND_TYPE = "3"
FEE_FOR_SERVICE_FYFS = "0"

#: 住院类起付标准（ESP-DED-001/002）：年度第一个结算周期 1300 / 第二及以后 650
_DEDUCTIBLE_FIRST = Decimal("1300")
_DEDUCTIBLE_SUBSEQUENT = Decimal("650")

_SOURCE = "hospital_record_store"
_CAPABILITY = "outpatient_special_mz_decomposition_snapshot"


def load_special_institution_level(conn: Any, hospital_code: str) -> AdapterCallResult:
    """机构 H_LEVEL 读取（m_institution）。0 条/多条均不取值（h_level=None + note）。"""
    sql = "SELECT H_CODE, H_LEVEL FROM dbo.m_institution WHERE H_CODE = ?"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [hospital_code])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"机构等级读取失败: {exc}")
    if len(rows) != 1:
        note = ("机构表未命中" if not rows else f"机构表命中 {len(rows)} 条（歧义，未取首条）")
        return _result(
            {"h_level": None, "row_count": len(rows), "note": note + "；机构等级按未知处理"},
            quality=DataQualityStatus.MISSING, message=note,
        )
    raw = rows[0].get("h_level")
    return _result({
        "h_level": (None if raw is None else str(raw).strip()),
        "row_count": 1,
    })


def _to_decimal(value: Any) -> Decimal | None:
    """金额构造不经过 float（设计 §9）；None/空串 → None（未知不是零）。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    return Decimal(text) if text else None


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    return date.fromisoformat(text[:10]) if text else None


def _to_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _result(data: dict, *, quality: DataQualityStatus = DataQualityStatus.COMPLETE,
            message: str | None = None) -> AdapterCallResult:
    return AdapterCallResult(
        status=AdapterCallStatus.SUCCESS, source_system=_SOURCE,
        capability=_CAPABILITY, data=data, data_quality=quality, message=message,
    )


def _failed(message: str) -> AdapterCallResult:
    return AdapterCallResult(
        status=AdapterCallStatus.FAILED, source_system=_SOURCE,
        capability=_CAPABILITY, data_quality=DataQualityStatus.MISSING,
        error_type="DATASOURCE_QUERY_FAILED", message=message,
    )

_REGISTRATION_COLUMNS = (
    "djh", "ryrq", "cblb", "csrq", "yllb", "FUND_TYPE", "tsbqsrq", "tsbjzrq",
    "cjjrdj", "gwydybz", "CIVIL_TYPE", "RETIRE_OFFICER_FLAG", "tsb1", "tsb2", "tsb3", "SPEC_HOSP_FLAG",
)

from src.config.settlement_templates import settlement_template_columns

_SETTLEMENT_COLUMNS = tuple(dict.fromkeys((
    'djh', 'jyrq', 'fyfs', 'jylsh',
    *settlement_template_columns('employee_special', 'outpatient_settlement_table'),
    *settlement_template_columns('resident_special', 'outpatient_settlement_table'),
)))

_FEE_ITEM_COLUMNS = (
    "djh", "xh", "xmdm", "xmmc", "sflb", "sfxmdj", "tsbbs",
    "dj", "sl", "zje", "ybnje", "ybwje", "grziftw", "fsrq",
    # Issue #81 居民门特目录独立分解补充列（职工流程不消费，多读无副作用）：
    # xmlb 项目类别（0=药品/1=诊疗/3=材料，与 o_FeeItem.ItemType 同构）；
    # FEE_MEDIC_L/FEE_SP_SCALE 结算事实比例/限价（同 o_FeeItem.MEDIC_L/SP_SCALE 口径）
    "xmlb", "FEE_MEDIC_L", "FEE_SP_SCALE",
)

_CYCLE_COLUMNS = ("djh", "fynd", "zqxh", "bqqsrq", "bqljybnje", "bqqfje")

_ANNUAL_COLUMNS = ("djh", "fynd", "bnzqslj", "bnybnje", "bntczfje", "bndezfje", "bnmcjylsh",
                   "BIG_ILL_SUM_IN", "BIG_ILL_SUM_PAY", "CIVIL_SUM_IN", "CIVIL_SUM_PAY")


# ── 登记定位 ──────────────────────────────────────────────────


def locate_special_mz_registration(conn: Any, djh: str) -> AdapterCallResult:
    """按登记号定位门特登记（yllb='12' 且 FUND_TYPE=3，Issue #79 口径）。"""
    cols = ", ".join(_REGISTRATION_COLUMNS)
    sql = (
        f"SELECT {cols} FROM dbo.yb_brdjxx "
        "WHERE djh = ? AND yllb = ? AND FUND_TYPE = ? "
        "AND COALESCE(tsb1,'') NOT IN ('503','504') "
        "AND COALESCE(tsb2,'') NOT IN ('503','504') "
        "AND COALESCE(tsb3,'') NOT IN ('503','504')"
    )
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh, SPECIAL_MZ_YLLB, EMPLOYEE_FUND_TYPE])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门特（mz 套表）登记定位查询失败: {exc}")
    if not rows:
        return _result(
            {"match_status": "not_found", "registration_row": None, "row_count": 0},
            quality=DataQualityStatus.MISSING,
            message=f"登记号 {djh} 未命中门特（yllb=12）职工（FUND_TYPE=3）登记",
        )
    if len(rows) > 1:
        return _result(
            {"match_status": "ambiguous", "registration_row": None, "row_count": len(rows)},
            quality=DataQualityStatus.MISSING,
            message=f"登记号 {djh} 命中 {len(rows)} 条门特登记，属歧义数据异常，未取首条",
        )
    return _result({"match_status": "unique_match", "registration_row": rows[0], "row_count": 1})


# ── 结算与明细读取 ────────────────────────────────────────────


def load_special_mz_settlement(conn: Any, djh: str) -> AdapterCallResult:
    """读取门特结算行（yb_mzjyxx，每 djh 应恰好 1 行）。

    费用方式 fyfs 原样带出：'0'=项目付费为本流程支持范围，其他取值由服务层判不支持。
    """
    cols = ", ".join(_SETTLEMENT_COLUMNS)
    sql = f"SELECT {cols} FROM dbo.yb_mzjyxx WHERE djh = ?"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门特（mz 套表）结算读取失败: {exc}")
    if len(rows) != 1:
        note = "结算表未命中" if not rows else f"结算表命中 {len(rows)} 行（应恰好 1 行，数据异常）"
        return _result(
            {"settlement_row": rows[0] if len(rows) == 1 else None, "row_count": len(rows),
             "note": note},
            quality=DataQualityStatus.MISSING, message=note,
        )
    return _result({"settlement_row": rows[0], "row_count": 1})


def load_special_mz_fee_items(conn: Any, djh: str) -> AdapterCallResult:
    """完整读取该登记全部费用明细（yb_mzfymx；禁止分页截断）。"""
    cols = ", ".join(_FEE_ITEM_COLUMNS)
    sql = f"SELECT {cols} FROM dbo.yb_mzfymx WHERE djh = ? ORDER BY xh"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门特（mz 套表）费用明细读取失败: {exc}")
    return _result(
        {"item_rows": rows, "row_count": len(rows)},
        quality=DataQualityStatus.COMPLETE if rows else DataQualityStatus.MISSING,
    )


# ── 周期/年度待遇读取与交易前口径推导 ─────────────────────────


def load_special_mz_cycle(conn: Any, djh: str) -> AdapterCallResult:
    """门特结算周期行（yb_dyxxtsb，交易后口径快照；0 行=院端无周期证据）。"""
    cols = ", ".join(_CYCLE_COLUMNS)
    sql = f"SELECT {cols} FROM dbo.yb_dyxxtsb WHERE djh = ?"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门特结算周期读取失败: {exc}")
    if len(rows) > 1:
        return _result(
            {"cycle_row": None, "row_count": len(rows),
             "note": f"周期表命中 {len(rows)} 行（应恰好 1 行，歧义未取首条）"},
            quality=DataQualityStatus.MISSING,
            message="门特结算周期行歧义",
        )
    return _result(
        {"cycle_row": rows[0] if rows else None, "row_count": len(rows)},
        quality=DataQualityStatus.COMPLETE if rows else DataQualityStatus.MISSING,
    )


def load_special_mz_annual(conn: Any, djh: str) -> AdapterCallResult:
    """年度待遇行（yb_dyxxnd，交易后口径快照；0 行=院端无年度累计证据）。"""
    cols = ", ".join(_ANNUAL_COLUMNS)
    sql = f"SELECT {cols} FROM dbo.yb_dyxxnd WHERE djh = ?"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门特年度待遇读取失败: {exc}")
    if len(rows) > 1:
        return _result(
            {"annual_row": None, "row_count": len(rows),
             "note": f"年度待遇表命中 {len(rows)} 行（应恰好 1 行，歧义未取首条）"},
            quality=DataQualityStatus.MISSING,
            message="门特年度待遇行歧义",
        )
    return _result(
        {"annual_row": rows[0] if rows else None, "row_count": len(rows)},
        quality=DataQualityStatus.COMPLETE if rows else DataQualityStatus.MISSING,
    )


def derive_mz_cycle_context(
    cycle_row: Mapping[str, Any] | None,
    annual_row: Mapping[str, Any] | None,
    settlement_row: Mapping[str, Any],
    special_record_start: date | None,
    settle_date: date | None,
) -> tuple[SpecialCycleContext, tuple[str, ...]]:
    """交易后口径 → 交易前口径推导（纯函数，便于无库单测）。

    周期行与年度行同时存在且推导值全部非负 → confirmed（可独立重算）；
    缺行或推导矛盾（负值）→ unknown（不硬算）；附 tsbqsrq 周期序号推导留痕
    （ESP-CYC-002：360 天周期以第一次特殊病就诊为开始）。
    """
    notes: list[str] = []

    # tsbqsrq 周期序号推导（无论是否有周期行都留痕，供坐标分析参考）
    if special_record_start is not None and settle_date is not None:
        cycle_len = 360  # ESP-CYC-002（2001-10-01 起 360 天为一个结算期）
        days = (settle_date - special_record_start).days
        if days >= 0:
            cycle_index = days // cycle_len + 1
            cycle_start = date.fromordinal(special_record_start.toordinal()
                                           + cycle_len * (cycle_index - 1))
            notes.append(
                f"CYCLE_INDEX_FROM_TBQSRQ：tsbqsrq={special_record_start.isoformat()} + "
                f"360天×{cycle_index - 1} → 第 {cycle_index} 个门特结算周期"
                f"（起点 {cycle_start.isoformat()}，ESP-CYC-002；跨院累计不可得，仅作坐标参考）")

    if cycle_row is None or annual_row is None:
        missing = "yb_dyxxtsb" if cycle_row is None else "yb_dyxxnd"
        return SpecialCycleContext(
            evidence_status="unknown",
            evidence_note=f"{missing} 无本笔行（2025 年起该表未维护/跨院数据缺失），"
                          "周期与年度累计证据不足",
        ), tuple(notes)

    context, derived_notes = _derive_cycle_context(cycle_row, annual_row, settlement_row, employee=True)
    return context, tuple(notes) + derived_notes


def _derive_cycle_context(
    cycle_row: Mapping[str, Any] | None,
    annual_row: Mapping[str, Any] | None,
    settlement_row: Mapping[str, Any],
    *,
    employee: bool,
) -> tuple[SpecialCycleContext, tuple[str, ...]]:
    """分字段推导；未知不当零，负差不反认定滞后原值就是交易前事实。"""
    from decimal import InvalidOperation

    if cycle_row is None or annual_row is None:
        return SpecialCycleContext(evidence_note="缺周期或年度快照"), ()
    notes: list[str] = []
    def number(row, key):
        try:
            value = _to_decimal(row.get(key))
            if value is not None and value.is_finite():
                return value
        except (InvalidOperation, ValueError, TypeError):
            pass
        notes.append(f"CYCLE_INPUT_MISSING：{key} 缺失或非法")
        return None

    cycle_no = number(annual_row, "bnzqslj")
    position = None
    if cycle_no is not None and cycle_no >= 1 and cycle_no == cycle_no.to_integral_value():
        position = "first" if cycle_no <= 1 else "subsequent"
    else:
        notes.append("CYCLE_INPUT_MISSING：周期序号无法确定")
    derived = {}
    pairs = (
        ("prior_cycle_deductible_paid", cycle_row, "bqqfje", "ybnqfje"),
        ("prior_cycle_in_scope_total", cycle_row, "bqljybnje", "tsbybn"),
        ("prior_annual_pool_fund_payment", annual_row, "bntczfje", "tczhf"),
        ("prior_annual_large_fund_payment", annual_row, "bndezfje", "degwyzhf"),
    )
    for field, row, cumulative_key, amount_key in pairs:
        cumulative, amount = number(row, cumulative_key), number(settlement_row, amount_key)
        value = cumulative - amount if cumulative is not None and amount is not None else None
        if value is not None and value < 0:
            code = "CYCLE_DERIVATION_CONTRADICTION" if employee else "CYCLE_TABLE_LAGGING"
            notes.append(f"{code}：{field} 推导为负 {value}，交易前累计未知，不将原值升级为已确认")
            value = None
        derived[field] = value
    # 真实读取投影包含两列流水；不一致时无法证明年度表是本笔交易后快照。
    if "jylsh" in settlement_row or "bnmcjylsh" in annual_row:
        current = _to_str(settlement_row.get("jylsh"))
        last = _to_str(annual_row.get("bnmcjylsh"))
        if not current or current != last:
            notes.append("ANNUAL_SNAPSHOT_ANCHOR_MISMATCH：年度快照流水与本笔不一致，交易前口径未确认")
            derived = {field: None for field in derived}
            position = None
    if "jyrq" in settlement_row or "fynd" in annual_row or "fynd" in cycle_row:
        settlement_date = _to_date(settlement_row.get("jyrq"))
        year = str(settlement_date.year) if settlement_date is not None else None
        if not year or _to_str(annual_row.get("fynd")) != year or _to_str(cycle_row.get("fynd")) != year:
            notes.append("ANNUAL_SNAPSHOT_YEAR_MISMATCH：周期/年度快照不属于本笔结算年度，累计未确认")
            derived = {field: None for field in derived}
            position = None
    standard = (_DEDUCTIBLE_FIRST if position == "first" else _DEDUCTIBLE_SUBSEQUENT) if employee and position else None
    confirmed = tuple(field for field, value in derived.items() if value is not None)
    if position:
        confirmed += ("cycle_position",)
    if standard is not None:
        confirmed += ("deductible_standard",)
    complete = all(value is not None for value in derived.values()) and position is not None
    if complete:
        notes.append("CYCLE_CONTEXT_CONFIRMED：完整交易后快照减本笔账面，交易前口径已确认")
    return SpecialCycleContext(
        deductible_standard=standard, cycle_position=position,
        **derived, confirmed_fields=confirmed,
        evidence_status="confirmed" if complete else "unknown",
        evidence_note=("交易后快照减本笔账面，分字段证据完整" if complete else
            "CYCLE_TABLE_LAGGING：年度快照金额滞后，部分交易前累计无法确认" if any("CYCLE_TABLE_LAGGING" in note for note in notes) else
            "周期或年度累计缺失、矛盾或时点不符，部分累计无法确认"),
    ), tuple(notes)


#: 居民门特险种码集合（Issue #81：FUND_TYPE∈91/92/93 判定城乡居民）
RESIDENT_FUND_TYPE_CODES = ("91", "92", "93")


def locate_special_mz_resident_registration(conn: Any, djh: str) -> AdapterCallResult:
    """按登记号定位居民门特登记（yllb='12' 且 FUND_TYPE∈91/92/93，Issue #81 口径）。

    与职工版（FUND_TYPE=3）的唯一差异是险种集合；其余定位/歧义语义一致。
    """
    cols = ", ".join(_REGISTRATION_COLUMNS)
    sql = (
        f"SELECT {cols} FROM dbo.yb_brdjxx "
        "WHERE djh = ? AND yllb = ? AND FUND_TYPE IN ('91','92','93')"
    )
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh, SPECIAL_MZ_YLLB])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"居民门特（mz 套表）登记定位查询失败: {exc}")
    if not rows:
        return _result(
            {"match_status": "not_found", "registration_row": None, "row_count": 0},
            quality=DataQualityStatus.MISSING,
            message=f"登记号 {djh} 未命中门特（yllb=12）居民（FUND_TYPE∈91/92/93）登记",
        )
    if len(rows) > 1:
        return _result(
            {"match_status": "ambiguous", "registration_row": None, "row_count": len(rows)},
            quality=DataQualityStatus.MISSING,
            message=f"登记号 {djh} 命中 {len(rows)} 条居民门特登记，属歧义数据异常，未取首条",
        )
    return _result({"match_status": "unique_match", "registration_row": rows[0], "row_count": 1})


def derive_mz_resident_cycle_context(
    cycle_row: Mapping[str, Any] | None,
    annual_row: Mapping[str, Any] | None,
    settlement_row: Mapping[str, Any],
) -> tuple[SpecialCycleContext, tuple[str, ...]]:
    """居民门特周期上下文推导（Issue #81）。

    与职工版（derive_mz_cycle_context）的差异：不内嵌起付标准（居民起付标准由
    内核经 RSP-DED 参数表按人员类别×机构档×周期位置选择）；仅推导交易前口径
    累计值（周期内已交起付/周期内医保内累计/年度统筹/大额累计）与周期序号位置。
    deductible_standard 置 None 由内核填充；cycle_position（first/subsequent）经
    周期位置通过 cycle_position 和 confirmed_fields 显式传递，缺失值保持未知。
    """
    return _derive_cycle_context(cycle_row, annual_row, settlement_row, employee=False)


# ── 资格字段映射（Issue #79 手工验证候选口径） ─────────────────


def map_military_grade(cjjrdj: Any) -> tuple[str | None, str | None, str | None]:
    """cjjrdj → (等级组, 原值, note)。1-4→"1-4"；5-6→"5-6"；空/'0'→无资格；其他→未知。"""
    raw = _to_str(cjjrdj)
    if raw in (None, "", "0"):
        return None, raw, None
    if raw in ("1", "2", "3", "4"):
        return "1-4", raw, None
    if raw in ("5", "6"):
        return "5-6", raw, None
    return None, raw, f"MILITARY_GRADE_VALUE_UNKNOWN：cjjrdj={raw} 未在 0-6 候选值域内，按未知处理"


def map_civil_medical_eligible(gwydybz: Any) -> tuple[bool | None, str | None]:
    """gwydybz → (是否享受公疗, note)。0=享受，1=不享受（与红名单相反，Issue #79）。"""
    raw = _to_str(gwydybz)
    if raw == "0":
        return True, None
    if raw == "1":
        return False, None
    return None, f"CIVIL_MEDICAL_FLAG_UNKNOWN：gwydybz={raw} 未在 0/1 候选值域内，按未知处理"


# ── 纯组装：行 dict → OutpatientSpecialSnapshot（与 SQL 分离，便于无库单测） ──


def derive_secondary_coverage_context(
    annual_row: Mapping[str, Any] | None,
    settlement_row: Mapping[str, Any],
) -> SecondaryCoverageContext:
    """只有同年度、本筆流水吻合的年度快照可作为交易后累计。"""
    from decimal import InvalidOperation

    if annual_row is None:
        return SecondaryCoverageContext(evidence_note="缺二次保障年度累计")
    settle_date = _to_date(settlement_row.get("jyrq"))
    last, current = _to_str(annual_row.get("bnmcjylsh")), _to_str(settlement_row.get("jylsh"))
    same_year = settle_date is not None and _to_str(annual_row.get("fynd")) == str(settle_date.year)
    confirmed = bool(same_year and current and current == last)
    def amount(key):
        try:
            value = _to_decimal(annual_row.get(key))
            return value if value is not None and value.is_finite() and value >= 0 else None
        except (InvalidOperation, ValueError, TypeError):
            return None
    return SecondaryCoverageContext(
        big_ill_scope_total=amount("big_ill_sum_in"),
        civil_fund_payment_total=amount("civil_sum_pay"),
        is_post_trade=True if confirmed else None,
        evidence_status="confirmed" if confirmed else "unknown",
        evidence_note="年度与本笔流水吻合，交易后快照" if confirmed else "年度/流水锚点不一致，累计时点未确认",
    )


def build_special_mz_snapshot(
    *,
    registration_row: Mapping[str, Any],
    settlement_row: Mapping[str, Any],
    item_rows: Iterable[Mapping[str, Any]],
    institution_h_level: str | None,
    hospital_code: str,
    rounding_mode: RoundingMode,
    cycle_context: SpecialCycleContext,
    insurance_type: str = "unknown",
    medical_category: str = "unknown",
    retirement_category: str | None = None,
    allow_observed_deductible: bool = False,
    segment_coordinate_guard: bool = False,
    secondary_coverage: SecondaryCoverageContext | None = None,
) -> tuple[OutpatientSpecialSnapshot, tuple[str, ...]]:
    """行 dict → OutpatientSpecialSnapshot（mz 套表）。返回 (快照, 组装留痕 notes)。

    组装约定：
    - 医保内/外观测值 = 特殊病 + 普通（tsbybn+ptybn / tsbybw+ptybw），
      与明细 Σybnje/Σybwje 核对；非特殊病费用（ptybn/ptybw）非零属不支持范围
      （ESP-CAT-002 普通门诊处理未实现），抛 ValueError 由服务层降级；
    - 资格字段按 Issue #79 候选口径映射（cjjrdj/gwydybz/cblb=61），留痕候选状态；
    - 险种/医疗类别仍由调用方显式给出，不猜测。
    """
    notes: list[str] = []

    settle_date = _to_date(settlement_row.get("jyrq"))
    if settle_date is None:
        raise ValueError("结算行缺少结算日期 jyrq，无法锚定快照时点")
    djh = _to_str(settlement_row.get("djh")) or _to_str(registration_row.get("djh")) or ""

    # 非特殊病费用（普通门诊口径）当前不支持分解（ESP-CAT-002）
    ptybn = _to_decimal(settlement_row.get("ptybn"))
    ptybw = _to_decimal(settlement_row.get("ptybw"))
    if (ptybn is not None and ptybn != 0) or (ptybw is not None and ptybw != 0):
        raise ValueError(
            f"存在非特殊病费用（ptybn={ptybn}, ptybw={ptybw}），"
            "按普通门诊处理规则未实现（ESP-CAT-002），本流程不支持分解")

    cblb = _to_str(registration_row.get("cblb"))
    grade, grade_raw, grade_note = map_military_grade(registration_row.get("cjjrdj"))
    if grade_note:
        notes.append(grade_note)
    civil_eligible, civil_note = map_civil_medical_eligible(registration_row.get("gwydybz"))
    if civil_note:
        notes.append(civil_note)
    notes.append(
        "ELIGIBILITY_CANDIDATE_MAPPING：资格字段按 Issue #79 候选口径映射"
        f"（cjjrdj={grade_raw}→grade={grade}；gwydybz={registration_row.get('gwydybz')}"
        f"→civil={civil_eligible}；cblb={cblb}→retirement_category={retirement_category}），"
        "签核前不升级为已确认字段语义")

    person = SpecialPersonProfile(
        cblb=cblb,
        birth_date=_to_date(registration_row.get("csrq")),
        special_record_start=_to_date(registration_row.get("tsbqsrq")),
        special_record_end=_to_date(registration_row.get("tsbjzrq")),
        retirement_category=retirement_category,
        military_grade=grade,
        military_grade_raw=grade_raw,
        civil_medical_eligible=civil_eligible,
        civil_type=_to_str(registration_row.get("civil_type")),
    )
    institution = SpecialInstitutionProfile(hospital_code=hospital_code,
                                            h_level=institution_h_level)

    items: list[SpecialFeeLineItem] = []
    fee_date_missing = False
    for row in item_rows:
        fee = _to_decimal(row.get("zje"))
        if fee is None:
            raise ValueError(f"明细行 xh={row.get('xh')} 缺少账面费用 zje，属数据异常")
        if _to_date(row.get("fsrq")) is None:
            fee_date_missing = True
        items.append(SpecialFeeLineItem(
            line_key=_to_str(row.get("xh")) or "",
            item_code=_to_str(row.get("xmdm")) or "",
            fee=fee,
            item_name=_to_str(row.get("xmmc")),
            sflb=_to_str(row.get("sflb")),
            self_pay_level=_to_str(row.get("sfxmdj")),
            in_scope_fee=_to_decimal(row.get("ybnje")),
            out_scope_fee=_to_decimal(row.get("ybwje")),
            full_self_pay_advance=_to_decimal(row.get("grziftw")),
            unit_price=_to_decimal(row.get("dj")),
            quantity=_to_decimal(row.get("sl")),
            fee_date=_to_date(row.get("fsrq")),
        ))
    if fee_date_missing:
        notes.append(
            "FEE_DATE_MISSING：部分明细缺费用发生日期（fsrq），退休补助资格时点判定将受阻")

    from src.config.settlement_templates import get_settlement_template
    from src.adapters.data_supply.settlement_template_bindings import observed_template_amounts
    template = get_settlement_template('resident_special' if insurance_type == 'resident' else 'employee_special')
    observed = SpecialObservedAmounts(**observed_template_amounts(template, {'outpatient_settlement_table': settlement_row}))
    # grzif1：模板按“项目付费单该列为 0”未绑定为核对目标，但 690/718 实测有值且
    # 恰为大病可报基数（972.40×65%＝632.06 与账面一致），这里保留原单事实供内核判用。
    raw_grzif1 = settlement_row.get('grzif1')
    if raw_grzif1 is not None:
        from dataclasses import replace as _dc_replace
        observed = _dc_replace(observed, grzif1=_to_decimal(raw_grzif1))

    snapshot = OutpatientSpecialSnapshot(
        settlement_ref=f"special_mz_settlement:{djh}",
        insurance_type=insurance_type,
        medical_category=medical_category,
        djh=djh,
        settle_date=settle_date,
        admit_date=_to_date(registration_row.get("ryrq")),
        yllb=_to_str(registration_row.get("yllb")),
        fund_type=_to_str(registration_row.get("fund_type")),
        person=person,
        institution=institution,
        cycle=cycle_context,
        items=tuple(items),
        observed=observed,
        rounding_mode=rounding_mode,
        allow_observed_deductible=allow_observed_deductible,
        segment_coordinate_guard=segment_coordinate_guard,
        secondary_coverage=secondary_coverage or SecondaryCoverageContext(),
    )
    return snapshot, tuple(notes)
