"""职工门特·按项目付费费用分解事实快照读取适配器（Issue #79，门诊套表）。

与 Issue #78 住院套表流程（``outpatient_special_queries.py``，yllb='16'）互补：
Issue #79 明确门特·按项目付费走**门诊套表**（SQL Server bjybdb）：
- ``dbo.yb_brdjxx`` 登记：键 djh；yllb='12'=门诊特殊病（ESP-CODE-001 候选扩展）；
- ``dbo.yb_mzjyxx`` 结算：每 djh 恰好 1 行；fyfs='0'=项目付费（费用方式码表实测）；
- ``dbo.yb_mzfymx`` 明细：djh+xh 行键；
- ``dbo.yb_dyxxtsb`` 门特结算周期：bqqsrq/bqljybnje/bqqfje（交易后口径，医保中心侧数据，
  含跨院累计——解决住院套表流程「周期上下文不可重建」缺口）；
- ``dbo.yb_dyxxnd`` 年度待遇：bnzqslj/bntczfje/bndezfje（交易后口径）；
- 资格字段：cjjrdj 军残等级、gwydybz 公疗标志（0=享受/1=不享受，与红名单相反，
  Issue #79 手工验证结论）、cblb=61 社会化退休（退休补充类别候选映射）。

约定与 ``outpatient_special_queries.py`` 一致：只接受注入的 PEP 249 连接、只读参数化
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

from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply.outpatient_special_queries import (
    _to_date,
    _to_decimal,
    _to_str,
)
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

#: 门特医疗类别码 / 险种码 / 项目付费费用方式码（Issue #79 实测候选口径，待码表确认）
SPECIAL_MZ_YLLB = "12"
EMPLOYEE_FUND_TYPE = "3"
FEE_FOR_SERVICE_FYFS = "0"

#: 住院类起付标准（ESP-DED-001/002）：年度第一个结算周期 1300 / 第二及以后 650
_DEDUCTIBLE_FIRST = Decimal("1300")
_DEDUCTIBLE_SUBSEQUENT = Decimal("650")

_SOURCE = "hospital_record_store"
_CAPABILITY = "outpatient_special_mz_decomposition_snapshot"


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
    "cjjrdj", "gwydybz",
)

_SETTLEMENT_COLUMNS = (
    "djh", "jyrq", "fyfs", "zje", "ptybn", "ptybw", "tsbybn", "tsbybw",
    "ybnqfje", "grziftw", "tczhf", "tczif", "degwyzhf", "degwyzif",
    "bczhf", "jczhf", "gfylbchbx", "xjzf", "zhzf",
)

_FEE_ITEM_COLUMNS = (
    "djh", "xh", "xmdm", "xmmc", "sflb", "sfxmdj", "tsbbs",
    "dj", "sl", "zje", "ybnje", "ybwje", "grziftw", "fsrq",
)

_CYCLE_COLUMNS = ("djh", "fynd", "zqxh", "bqqsrq", "bqljybnje", "bqqfje")

_ANNUAL_COLUMNS = ("djh", "fynd", "bnzqslj", "bnybnje", "bntczfje", "bndezfje", "bnmcjylsh")


# ── 登记定位 ──────────────────────────────────────────────────


def locate_special_mz_registration(conn: Any, djh: str) -> AdapterCallResult:
    """按登记号定位门特登记（yllb='12' 且 FUND_TYPE=3，Issue #79 口径）。"""
    cols = ", ".join(_REGISTRATION_COLUMNS)
    sql = (
        f"SELECT {cols} FROM dbo.yb_brdjxx "
        "WHERE djh = ? AND yllb = ? AND FUND_TYPE = ?"
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

    # 交易后 → 交易前：各累计减去本笔发生额；任一推导为负即矛盾，降 unknown 不硬算
    tsbybn = _to_decimal(settlement_row.get("tsbybn")) or Decimal("0")
    ybnqfje = _to_decimal(settlement_row.get("ybnqfje")) or Decimal("0")
    tczhf = _to_decimal(settlement_row.get("tczhf")) or Decimal("0")
    degwyzhf = _to_decimal(settlement_row.get("degwyzhf")) or Decimal("0")

    cycle_no = _to_decimal(annual_row.get("bnzqslj"))
    deductible_standard = (_DEDUCTIBLE_FIRST if cycle_no is not None and cycle_no <= 1
                           else _DEDUCTIBLE_SUBSEQUENT)
    prior_deductible = (_to_decimal(cycle_row.get("bqqfje")) or Decimal("0")) - ybnqfje
    prior_in_scope = (_to_decimal(cycle_row.get("bqljybnje")) or Decimal("0")) - tsbybn
    prior_pool = (_to_decimal(annual_row.get("bntczfje")) or Decimal("0")) - tczhf
    prior_large = (_to_decimal(annual_row.get("bndezfje")) or Decimal("0")) - degwyzhf

    derived = {
        "prior_cycle_deductible_paid": prior_deductible,
        "prior_cycle_in_scope_total": prior_in_scope,
        "prior_annual_pool_fund_payment": prior_pool,
        "prior_annual_large_fund_payment": prior_large,
    }
    negative = {k: v for k, v in derived.items() if v < 0}
    if negative:
        notes.append(
            "CYCLE_DERIVATION_CONTRADICTION：交易前口径推导出现负值 "
            + ",".join(f"{k}={v}" for k, v in negative.items())
            + "（交易后快照与本笔账面不一致），周期上下文降 unknown")
        return SpecialCycleContext(
            evidence_status="unknown",
            evidence_note="交易前口径推导矛盾（负值），周期证据不完整",
        ), tuple(notes)

    notes.append(
        f"CYCLE_CONTEXT_CONFIRMED：dyxxtsb/dyxxnd 交易后口径−本笔账面 → 交易前口径"
        f"（D={deductible_standard}（bnzqslj={cycle_no}），A={prior_deductible}，"
        f"P={prior_in_scope}，统筹累计={prior_pool}，大额累计={prior_large}）")
    return SpecialCycleContext(
        deductible_standard=deductible_standard,
        prior_cycle_deductible_paid=prior_deductible,
        prior_annual_pool_fund_payment=prior_pool,
        prior_annual_large_fund_payment=prior_large,
        prior_cycle_in_scope_total=prior_in_scope,
        evidence_status="confirmed",
        evidence_note="yb_dyxxtsb/yb_dyxxnd 交易后快照减本笔账面推导（医保中心侧数据，含跨院累计）",
    ), tuple(notes)


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
) -> tuple[OutpatientSpecialSnapshot, tuple[str, ...]]:
    """行 dict → OutpatientSpecialSnapshot（mz 套表）。返回 (快照, 组装留痕 notes)。

    与住院套表组装的差异：
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

    def _total(special: Decimal | None, normal: Decimal | None) -> Decimal | None:
        if special is None and normal is None:
            return None
        return (special or Decimal("0")) + (normal or Decimal("0"))

    observed = SpecialObservedAmounts(
        zje=_to_decimal(settlement_row.get("zje")),
        ybn=_total(_to_decimal(settlement_row.get("tsbybn")), ptybn),
        ybw=_total(_to_decimal(settlement_row.get("tsbybw")), ptybw),
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
    )
    return snapshot, tuple(notes)
