"""门特（门诊特殊病）费用分解事实快照读取适配器（Issue #78 第二流程）。

门特结算**不在** o_Trade（门诊表无 T_CureType=16），走住院套表（SQL Server bjybdb）：
- ``dbo.yb_brdjxx`` 登记：键 djh；yllb='16'=门特；FUND_TYPE=3=城镇职工（ESP-CODE-001/002）；
- ``dbo.yb_zyjyxx`` 结算：每 djh 恰好 1 行（已实测验证）；
- ``dbo.yb_zyfymx`` 明细：djh+xh 行键；
- ``dbo.m_institution`` 机构等级（H_CODE → H_LEVEL）。

约定与 ``outpatient_decomposition_queries.py`` 一致：
- 只接受注入的 PEP 249 连接，禁止反向 import src.runtime；
- SQL 仅只读 SELECT 单语句（经 assert_read_only_select 出口断言），参数化占位符防注入；
- 字段语义为 bjyb 实测候选口径，待数据字典确认（ESP-CODE 系列）；
- 不 SELECT 患者身份证/姓名列：同人历史结算通过子查询在库内按 sfz 关联，身份证不出库；
- 全部返回 AdapterCallResult，不抛业务异常（``build_special_snapshot`` 为纯组装函数，
  例外：脏数据抛 ValueError，由服务层统一降级为 unavailable）；
- 物理表/列名为 bjybdb 实测值；其他院区接入时需另行核实，不得默认复用。
"""
from __future__ import annotations

from dataclasses import dataclass
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
)

_SOURCE = "hospital_record_store"
_CAPABILITY = "outpatient_special_decomposition_snapshot"

#: 门特医疗类别码 / 险种码（ESP-CODE-001/002，实测待码表确认）
SPECIAL_YLLB = "16"
EMPLOYEE_FUND_TYPE = "3"

# ── 物理列清单（bjybdb 实测候选口径，待数据字典确认；不含身份证/姓名） ──

_REGISTRATION_COLUMNS = (
    "djh", "ryrq", "cblb", "csrq", "yllb", "FUND_TYPE", "tsbqsrq", "tsbjzrq",
)

_SETTLEMENT_COLUMNS = (
    "djh", "jyrq", "zje", "ybn", "ybw", "ybnqfje", "grziftw",
    "tczhf", "tczif", "degwyzhf", "degwyzif",
    "bczhf", "jczhf", "gfylbchbx", "xjzf", "zhzf",
)

_FEE_ITEM_COLUMNS = (
    "djh", "xh", "xmdm", "xmmc", "sflb", "sfxmdj",
    "dj", "sl", "zje", "ybnje", "ybwje", "grziftw", "fsrq",
)

#: 同人历史结算读取列（供周期上下文重建参考；身份证 sfz 不出库）
_HISTORY_COLUMNS = ("djh", "jyrq", "yllb", "ybn", "ybnqfje", "tczhf", "degwyzhf")


# ── 结果构造 ──────────────────────────────────────────────────


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


# ── 门特登记定位 ──────────────────────────────────────────────


def locate_special_registration(conn: Any, djh: str) -> AdapterCallResult:
    """按登记号定位门特登记（yllb='16' 且 FUND_TYPE=3）。

    data.match_status：unique_match / not_found（djh 无门特职工登记）。
    """
    cols = ", ".join(_REGISTRATION_COLUMNS)
    sql = (
        f"SELECT {cols} FROM dbo.yb_brdjxx "
        "WHERE djh = ? AND yllb = ? AND FUND_TYPE = ?"
    )
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh, SPECIAL_YLLB, EMPLOYEE_FUND_TYPE])
    except Exception as exc:  # noqa: BLE001 — 适配器不抛异常，统一转 FAILED
        return _failed(f"门特登记定位查询失败: {exc}")
    if not rows:
        return _result(
            {"match_status": "not_found", "registration_row": None, "row_count": 0},
            quality=DataQualityStatus.MISSING,
            message=f"登记号 {djh} 未命中门特（yllb=16）职工（FUND_TYPE=3）登记",
        )
    if len(rows) > 1:
        return _result(
            {"match_status": "ambiguous", "registration_row": None, "row_count": len(rows)},
            quality=DataQualityStatus.MISSING,
            message=f"登记号 {djh} 命中 {len(rows)} 条门特登记，属歧义数据异常，未取首条",
        )
    return _result({"match_status": "unique_match", "registration_row": rows[0], "row_count": 1})


# ── 结算与明细读取 ────────────────────────────────────────────


def load_special_settlement(conn: Any, djh: str) -> AdapterCallResult:
    """读取门特结算行（每 djh 应恰好 1 行；0/多行属数据异常，如实返回行数）。"""
    cols = ", ".join(_SETTLEMENT_COLUMNS)
    sql = f"SELECT {cols} FROM dbo.yb_zyjyxx WHERE djh = ?"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门特结算读取失败: {exc}")
    if len(rows) != 1:
        note = "结算表未命中" if not rows else f"结算表命中 {len(rows)} 行（应恰好 1 行，数据异常）"
        return _result(
            {"settlement_row": rows[0] if len(rows) == 1 else None, "row_count": len(rows),
             "note": note},
            quality=DataQualityStatus.MISSING, message=note,
        )
    return _result({"settlement_row": rows[0], "row_count": 1})


def load_special_fee_items(conn: Any, djh: str) -> AdapterCallResult:
    """完整读取该登记全部费用明细（禁止分页截断；重复行键原样带出，内核判数据异常）。"""
    cols = ", ".join(_FEE_ITEM_COLUMNS)
    sql = f"SELECT {cols} FROM dbo.yb_zyfymx WHERE djh = ? ORDER BY xh"
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [djh])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门特费用明细读取失败: {exc}")
    return _result(
        {"item_rows": rows, "row_count": len(rows)},
        quality=DataQualityStatus.COMPLETE if rows else DataQualityStatus.MISSING,
    )


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


def load_same_person_settlements(conn: Any, djh: str) -> AdapterCallResult:
    """同人历史住院类结算（按身份证在库内关联，sfz 不出库）。

    供周期上下文重建参考：院端抽取不含跨院数据，重建证据天然不完整，
    服务层默认 evidence_status="unknown"，不强行推断。
    """
    cols = ", ".join(f"s.{c}" for c in _HISTORY_COLUMNS)
    sql = (
        f"SELECT {cols} FROM dbo.yb_zyjyxx s "
        "JOIN dbo.yb_brdjxx b ON s.djh = b.djh "
        "WHERE b.FUND_TYPE = ? AND b.sfz = (SELECT sfz FROM dbo.yb_brdjxx WHERE djh = ?) "
        "ORDER BY s.jyrq"
    )
    assert_read_only_select(sql)
    try:
        rows = _fetch_all(conn, sql, [EMPLOYEE_FUND_TYPE, djh])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"同人历史结算读取失败: {exc}")
    return _result({"history_rows": rows, "row_count": len(rows)})


# ── 纯组装：行 dict → OutpatientSpecialSnapshot（与 SQL 分离，便于无库单测） ──


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


def build_special_snapshot(
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
    allow_observed_deductible: bool = False,
) -> tuple[OutpatientSpecialSnapshot, tuple[str, ...]]:
    """行 dict → OutpatientSpecialSnapshot。返回 (快照, 组装留痕 notes)。

    规则：
    - 观测值 None≠0：账面缺失列保持 None，不按零处理；
    - 资格字段（退休类别/军残/公疗）无确认来源，一律 None（禁止金额反推资格）；
    - 险种/医疗类别由调用方显式给出，默认 unknown 不猜测（ESP-CODE-001/002 实测待码表确认）；
    - 周期上下文由调用方注入（默认 unknown，院端抽取不可完整重建）；
    - 脏数据（缺结算日期/明细账面费用、日期不可解析）抛 ValueError，由服务层降级。
    """
    notes: list[str] = []

    settle_date = _to_date(settlement_row.get("jyrq"))
    if settle_date is None:
        raise ValueError("结算行缺少结算日期 jyrq，无法锚定快照时点")
    djh = _to_str(settlement_row.get("djh")) or _to_str(registration_row.get("djh")) or ""

    person = SpecialPersonProfile(
        cblb=_to_str(registration_row.get("cblb")),
        birth_date=_to_date(registration_row.get("csrq")),
        special_record_start=_to_date(registration_row.get("tsbqsrq")),
        special_record_end=_to_date(registration_row.get("tsbjzrq")),
        # 退休类别（普通/社会化）字段未映射，一律 None（不默认 50%）
        retirement_category=None,
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

    observed = SpecialObservedAmounts(
        zje=_to_decimal(settlement_row.get("zje")),
        ybn=_to_decimal(settlement_row.get("ybn")),
        ybw=_to_decimal(settlement_row.get("ybw")),
        ybnqfje=_to_decimal(settlement_row.get("ybnqfje")),
        tczhf=_to_decimal(settlement_row.get("tczhf")),
        tczif=_to_decimal(settlement_row.get("tczif")),
        degwyzhf=_to_decimal(settlement_row.get("degwyzhf")),
        degwyzif=_to_decimal(settlement_row.get("degwyzif")),
        bczhf=_to_decimal(settlement_row.get("bczhf")),
        jczhf=_to_decimal(settlement_row.get("jczhf")),
        gfylbchbx=_to_decimal(settlement_row.get("gfylbchbx")),
        xjzf=_to_decimal(settlement_row.get("xjzf")),
        zhzf=_to_decimal(settlement_row.get("zhzf")),
        grziftw=_to_decimal(settlement_row.get("grziftw")),
    )

    snapshot = OutpatientSpecialSnapshot(
        settlement_ref=f"special_settlement:{djh}",
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
    )
    return snapshot, tuple(notes)


@dataclass(frozen=True)
class SpecialSnapshotReadMeta:
    """快照读取元数据（读取时间、来源、行数、内容哈希）。"""

    read_at: str
    source_system: str
    row_counts: dict[str, int]
    content_hash: str
    notes: tuple[str, ...] = ()
