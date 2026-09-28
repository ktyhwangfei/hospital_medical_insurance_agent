"""门诊费用分解事实快照读取适配器（Issue #78，设计 §5 / §15 步骤 1）。

交易号 → 完整事实快照（交易锚点 + 全部明细 + 全版本目录 + 机构等级 + 账面观测值）。

约定与 ``settlement_record_queries.py`` 一致：
- 表名/列名全部来自 RecordQueryMapping（默认值为 Issue #78 候选映射，
  **待黄金样本确认，设计 §16 P0/P1**），本模块不出现裸物理标识符；
- 只接受注入的 PEP 249 连接，禁止反向 import src.runtime；
- SQL 仅只读 SELECT 单语句（出口断言），参数化占位符防注入；
- 不 SELECT 患者身份证/姓名列；出生日期仅进入内部值对象供内核计算年龄档，不外泄；
- 全部返回 AdapterCallResult，不抛业务异常（``build_snapshot`` 为纯组装函数，例外：
  脏数据抛 ValueError，由服务层统一降级为 unavailable）。

设计 §5.3 要点落实：
- 定位交易：0 条 = not_found；>1 条 = ambiguous（数据异常，不取首条）；
- 明细完整读取，禁止分页截断；重复行键原样带出（内核判 DUPLICATE_LINE_KEY）；
- 目录按编码批量读取全部版本（含空截止日期行），有效期筛选留给内核，
  不在 WHERE 里排除（设计 §5.3-4）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply.record_query_mappings import (
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
    mapping_fingerprint,
)
from src.adapters.data_supply.settlement_record_queries import (
    _c,
    _fetch_all,
    _k,
    _t,
)
from src.domain.insurance.fee_decomposition import (
    AnnualAccumulation,
    CatalogKind,
    DecompositionSnapshot,
    DrugCatalogEntry,
    FeeLineItem,
    InstitutionProfile,
    MaterialCatalogEntry,
    ObservedSettlementAmounts,
    PersonProfile,
    RoundingMode,
    ServiceCatalogEntry,
    TradeAnchor,
)

#: ItemType → 目录类别（院内字典 k10：0=药品 1=诊疗项目 2=服务设施 3=耗材；
#: 1/2 查诊疗目录 yb_xzzlfwxm，3 查材料目录（材料是否完整在 yb_xzzlfwxm 仍待确认）。
#: 实证：ItemType=0 编码 100% 命中药品目录，1/3 编码 100% 命中 yb_xzzlfwxm（决策记录 D1）
_ITEM_TYPE_TO_CATALOG_KIND = {
    "0": CatalogKind.DRUG,
    "1": CatalogKind.SERVICE,
    "2": CatalogKind.SERVICE,
    "3": CatalogKind.MATERIAL,
}

#: 军残人员类别码（院内字典 290 名称含「伤残军人」，决策记录 D7）
_DISABLED_VETERAN_PERSON_TYPE_CODES = frozenset({"13", "23", "24", "47", "48", "49"})
#: 在乡残疾军人类别码（字典 290：49=在乡二等乙级伤残军人）
_RURAL_DISABLED_VETERAN_PERSON_TYPE_CODES = frozenset({"49"})
#: 普通退休（非预提）人员类别码（决策记录 D8：21=退休 22=退休异地安置按普通 50%）
_NORMAL_RETIRED_PERSON_TYPE_CODES = frozenset({"21", "22"})

#: 退休补充保险纳入起始日期占位：规则生效日（EOP-RSUP-001/002，2006-04-01）。
#: 个人实际纳入日期无来源列，按规则起始日视为已纳入（决策记录 D8）
_RETIRE_SUPPLEMENT_ENROLL_FALLBACK = date(2006, 4, 1)

_SOURCE = "hospital_record_store"
_CAPABILITY = "outpatient_decomposition_snapshot"

#: 交易定位读取的 o_Trade 列（不含身份证/姓名等身份原文列）
_TRADE_COLUMNS = (
    "op_trade_no", "op_trade_date", "op_hosp_code",
    "op_fund_type", "op_cure_type", "op_person_type", "op_birthday",
    "op_card_ic", "op_year",
    "op_prior_fee_in", "op_prior_big_pay",
    "op_official", "op_official_code", "op_jc_level",
    "op_fee_all", "op_fee_in", "op_fee_out", "op_fund_pay",
    "op_self_pay_2", "op_first_pay", "op_big_pay", "op_big_self_pay",
    "op_bc_pay", "op_jc_pay", "op_official_pay", "op_self_pay_1",
    "op_self_pay_all", "op_person_count_pay", "op_cash_pay",
    "op_has_refundmented", "op_partial_return",
    "op_ref_original_no", "op_reversal_original_no",
    "op_no_right_reason",
)

_FEE_ITEM_COLUMNS = (
    "opf_line_id", "opf_item_type", "opf_item_code", "opf_fee_type",
    "opf_unit_price", "opf_count", "opf_fee", "opf_fee_in", "opf_fee_out",
    "opf_self_pay_2", "opf_medic_l", "opf_sp_scale", "opf_fee_date",
)

_DRUG_COLUMNS = (
    "cat_drug_code", "cat_drug_effective", "cat_drug_expiry", "cat_drug_sflb",
    "cat_drug_self_pay_ratio", "cat_drug_a_ypbs", "cat_drug_a_mzxj",
    "cat_drug_a_xbbl", "cat_drug_ypfl", "cat_drug_bzjg",
    "cat_drug_preparation_hospital",
)

#: 诊疗/材料同表（yb_xzzlfwxm）共用列；材料的人工器官/集采中选标志列未映射（待确认）
_SERVICE_COLUMNS = (
    "cat_svc_code", "cat_svc_effective", "cat_svc_expiry", "cat_svc_sfxmdj",
    "cat_svc_self_pay_ratio", "cat_svc_unit_price_limit",
)


# ── 读取元数据 ────────────────────────────────────────────────


@dataclass(frozen=True)
class SnapshotReadMeta:
    """快照读取元数据（设计 §5.3-7 / §9：读取时间、来源、行数、内容哈希、映射版本）。"""

    read_at: str  # ISO 时间（utc）
    source_system: str
    row_counts: dict[str, int]
    content_hash: str  # 全部读取行的 sha256（default=str 序列化）
    mapping_fingerprint: str  # 映射内容哈希（映射版本标识）
    notes: tuple[str, ...] = ()  # 降级与待确认事项留痕


def hash_rows(*row_groups: Iterable[Mapping[str, Any]]) -> str:
    """读取行内容哈希：同输入必同哈希（回放一致性校验用，不能用于回放本身）。"""
    payload = json.dumps(
        [[dict(r) for r in group] for group in row_groups],
        sort_keys=True, default=str, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assemble_read_meta(
    *,
    row_counts: dict[str, int],
    content_hash: str,
    mapping: RecordQueryMapping,
    notes: tuple[str, ...] = (),
) -> SnapshotReadMeta:
    return SnapshotReadMeta(
        read_at=datetime.now(timezone.utc).isoformat(),
        source_system=_SOURCE,
        row_counts=dict(row_counts),
        content_hash=content_hash,
        mapping_fingerprint=mapping_fingerprint(mapping),
        notes=notes,
    )


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


def _render_columns(mapping: RecordQueryMapping, keys: Iterable[str]) -> str:
    """渲染查询列清单；映射值为空的列（真实库无此列）跳过，读取时按缺失降级。"""
    return ", ".join(_c(mapping, k) for k in keys if mapping.column(k).strip())


# ── 交易定位 ──────────────────────────────────────────────────


def locate_outpatient_trade(
    conn: Any,
    trade_no: str,
    hospital_code: str,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """按交易号+院区唯一定位门诊交易。

    data.match_status：unique_match / not_found / ambiguous。
    ambiguous 属数据异常，不取首条（trade_row 为 None）。
    """
    rendered = ", ".join(_c(mapping, k) for k in _TRADE_COLUMNS)
    sql = (
        f"SELECT {rendered} FROM {_t(mapping, 'outpatient_trade_table')} "
        f"WHERE {_c(mapping, 'op_trade_no')} = ? AND {_c(mapping, 'op_hosp_code')} = ?"
    )
    try:
        rows = _fetch_all(conn, sql, [trade_no, hospital_code])
    except Exception as exc:  # noqa: BLE001 — 适配器不抛异常，统一转 FAILED
        return _failed(f"门诊交易定位查询失败: {exc}")
    if len(rows) > 1:
        return _result(
            {"match_status": "ambiguous", "trade_row": None, "row_count": len(rows)},
            quality=DataQualityStatus.MISSING,
            message=f"交易号 {trade_no} 在该院区命中 {len(rows)} 条，属歧义数据异常，未取首条",
        )
    if not rows:
        return _result(
            {"match_status": "not_found", "trade_row": None, "row_count": 0},
            quality=DataQualityStatus.MISSING,
            message=f"交易号 {trade_no} 在该院区未找到",
        )
    return _result({"match_status": "unique_match", "trade_row": rows[0], "row_count": 1})


# ── 费用明细（完整读取，禁止分页截断） ─────────────────────────


def load_outpatient_fee_items(
    conn: Any,
    trade_no: str,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """完整读取该交易全部明细。重复行键原样带出，不静默去重（内核判数据异常）。"""
    rendered = _render_columns(mapping, _FEE_ITEM_COLUMNS)
    sql = (
        f"SELECT {rendered} FROM {_t(mapping, 'outpatient_trade_fee_table')} "
        f"WHERE {_c(mapping, 'opf_trade_no')} = ? ORDER BY {_c(mapping, 'opf_line_id')}"
    )
    try:
        rows = _fetch_all(conn, sql, [trade_no])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"门诊费用明细读取失败: {exc}")
    return _result(
        {"item_rows": rows, "row_count": len(rows)},
        quality=DataQualityStatus.COMPLETE if rows else DataQualityStatus.MISSING,
    )


def extract_item_codes(
    item_rows: Iterable[Mapping[str, Any]],
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """明细行 → (药品编码, 非药品编码)，用于目录批量读取。

    ItemType=0 为药品；1=诊疗项目/2=服务设施/3=耗材（院内字典 k10）统一查
    yb_xzzlfwxm 系目录；其他取值语义未确认，统一归为非药品不猜测归属。
    """
    type_key, code_key = _k(mapping, "opf_item_type"), _k(mapping, "opf_item_code")
    drug: list[str] = []
    non_drug: list[str] = []
    for row in item_rows:
        code = row.get(code_key)
        if code is None or str(code).strip() == "":
            continue
        code_s = str(code).strip()
        item_type = row.get(type_key)
        (drug if item_type is not None and str(item_type).strip() == "0" else non_drug).append(code_s)
    return tuple(drug), tuple(non_drug)


# ── 目录批量读取（全版本，不在 WHERE 排除日期） ──────────────────


def _load_catalog(
    conn: Any,
    table_attr: str,
    columns: tuple[str, ...],
    code_key: str,
    item_codes: Iterable[str],
    mapping: RecordQueryMapping,
    label: str,
) -> AdapterCallResult:
    codes = sorted({c for c in item_codes if c})
    if not codes:
        return _result({"catalog_rows": [], "row_count": 0})
    placeholders = ", ".join("?" for _ in codes)
    rendered = _render_columns(mapping, columns)
    # 全版本读取（含空截止日期行）：有效期筛选留给内核（设计 §5.3-4）
    sql = (
        f"SELECT {rendered} FROM {_t(mapping, table_attr)} "
        f"WHERE {_c(mapping, code_key)} IN ({placeholders})"
    )
    try:
        rows = _fetch_all(conn, sql, list(codes))
    except Exception as exc:  # noqa: BLE001
        return _failed(f"{label}目录读取失败: {exc}")
    return _result({"catalog_rows": rows, "row_count": len(rows)})


def load_drug_catalog(
    conn: Any,
    item_codes: Iterable[str],
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """药品目录批量读取（yb_ypzdml 全版本）。"""
    return _load_catalog(conn, "drug_catalog_table", _DRUG_COLUMNS, "cat_drug_code",
                         item_codes, mapping, "药品")


def load_service_catalog(
    conn: Any,
    item_codes: Iterable[str],
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """诊疗/服务设施目录批量读取（yb_xzzlfwxm 全版本）。"""
    return _load_catalog(conn, "service_catalog_table", _SERVICE_COLUMNS, "cat_svc_code",
                         item_codes, mapping, "诊疗/服务设施")


def load_material_catalog(
    conn: Any,
    item_codes: Iterable[str],
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """医用材料目录批量读取（候选与诊疗同表 yb_xzzlfwxm，材料是否完整包含待确认）。"""
    return _load_catalog(conn, "material_catalog_table", _SERVICE_COLUMNS, "cat_svc_code",
                         item_codes, mapping, "医用材料")


# ── 机构等级 ──────────────────────────────────────────────────


def load_institution_level(
    conn: Any,
    hospital_code: str,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """机构 H_LEVEL/H_TYPE 读取。0 条/多条均不取值（按未知 + note），连接键待确认。"""
    sql = (
        f"SELECT {_c(mapping, 'ins_code')}, {_c(mapping, 'ins_h_level')}, "
        f"{_c(mapping, 'ins_h_type')} "
        f"FROM {_t(mapping, 'institution_table')} WHERE {_c(mapping, 'ins_code')} = ?"
    )
    try:
        rows = _fetch_all(conn, sql, [hospital_code])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"机构等级读取失败: {exc}")
    if len(rows) != 1:
        note = ("机构表未命中" if not rows else f"机构表命中 {len(rows)} 条（歧义，未取首条）")
        return _result(
            {"h_level": None, "h_type": None, "row_count": len(rows),
             "note": note + "；机构类别按未知处理"},
            quality=DataQualityStatus.MISSING, message=note,
        )
    row = rows[0]
    h_type_raw = row.get(_k(mapping, "ins_h_type"))
    return _result({
        "h_level": (None if row.get(_k(mapping, "ins_h_level")) is None
                    else str(row.get(_k(mapping, "ins_h_level"))).strip()),
        "h_type": None if h_type_raw is None else str(h_type_raw).strip(),
        "row_count": 1,
    })


# ── 年度累计推导（TB 列未维护时，决策记录 D16） ──────────────────


def derive_in_hospital_accumulation(
    conn: Any,
    card_ic: str,
    fund_type: str,
    trade_datetime: Any,
    trade_no: str,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """TB_Year≠交易年（账面累计未维护）时，按同人同年本院历史推导交易前累计下界。

    算法（决策记录 D16）：同人（P_ICNo）同险种的同自然年历史交易按
    (T_TradeDate, T_TradeNo) 排序；遇到 TB 列已维护的锚点交易（TB_Year=交易年）
    时 floor 抬升到锚点口径（max(floor, TB_列)），再逐笔累加 T_FeeIn/T_BigPay。
    结果为**下界**（跨院部分不可得），是否可用由调用方按候选口径决断。
    """
    year = trade_datetime.year if hasattr(trade_datetime, "year") else None
    if year is None:
        return _failed("交易日期无法解析，累计推导不可用")
    sql = (
        f"SELECT {_c(mapping, 'op_trade_no')}, {_c(mapping, 'op_trade_date')}, "
        f"{_c(mapping, 'op_year')}, {_c(mapping, 'op_prior_fee_in')}, "
        f"{_c(mapping, 'op_fee_in')}, {_c(mapping, 'op_prior_big_pay')}, "
        f"{_c(mapping, 'op_big_pay')} "
        f"FROM {_t(mapping, 'outpatient_trade_table')} "
        f"WHERE {_c(mapping, 'op_card_ic')} = ? AND {_c(mapping, 'op_fund_type')} = ? "
        f"AND YEAR({_c(mapping, 'op_trade_date')}) = ? "
        f"ORDER BY {_c(mapping, 'op_trade_date')}, {_c(mapping, 'op_trade_no')}"
    )
    try:
        rows = _fetch_all(conn, sql, [card_ic, fund_type, year])
    except Exception as exc:  # noqa: BLE001
        return _failed(f"同人历史交易读取失败: {exc}")

    k_no, k_dt, k_year = _k(mapping, "op_trade_no"), _k(mapping, "op_trade_date"), _k(mapping, "op_year")
    k_tb_in, k_in = _k(mapping, "op_prior_fee_in"), _k(mapping, "op_fee_in")
    k_tb_big, k_big = _k(mapping, "op_prior_big_pay"), _k(mapping, "op_big_pay")
    self_key = (str(trade_datetime), trade_no)
    floor_in = Decimal("0")
    floor_fund = Decimal("0")
    anchor_count = 0
    prior_count = 0
    for row in rows:
        row_key = (str(row.get(k_dt)), str(row.get(k_no) or ""))
        if row_key >= self_key:
            continue  # 只取严格早于本交易的历史（同日按交易号定序）
        prior_count += 1
        fee_in = _to_decimal(row.get(k_in)) or Decimal("0")
        big = _to_decimal(row.get(k_big)) or Decimal("0")
        if str(row.get(k_year) or "").strip() == str(year):
            # 锚点：账面 TB 列已维护（含跨院），floor 抬升
            anchor_count += 1
            tb_in = _to_decimal(row.get(k_tb_in))
            tb_big = _to_decimal(row.get(k_tb_big))
            if tb_in is not None:
                floor_in = max(floor_in, tb_in)
            if tb_big is not None:
                floor_fund = max(floor_fund, tb_big)
        floor_in += fee_in
        floor_fund += big
    return _result({
        "prior_in_scope_fee": floor_in,
        "prior_fund_payment": floor_fund,
        "anchor_count": anchor_count,
        "prior_trade_count": prior_count,
        "row_count": len(rows),
    })


# ── 纯组装：行 dict → DecompositionSnapshot（与 SQL 分离，便于无库单测） ──


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


def _truthy(value: Any) -> bool:
    return value is not None and str(value).strip() in ("1", "1.0", "true", "True")


def build_snapshot(
    *,
    trade_row: Mapping[str, Any],
    item_rows: Iterable[Mapping[str, Any]],
    drug_catalog_rows: Iterable[Mapping[str, Any]],
    service_catalog_rows: Iterable[Mapping[str, Any]],
    material_catalog_rows: Iterable[Mapping[str, Any]],
    institution_h_level: str | None,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
    rounding_mode: RoundingMode,
    insurance_type: str = "unknown",
    medical_category: str = "unknown",
    institution_h_type: str | None = None,
    # 年度累计口径断言：默认未确认（设计 §16 P0），只有调用方显式确认后才置 True
    prior_in_scope_fee_is_pre_trade: bool = False,
    prior_fund_payment: Decimal | None = None,
    prior_fund_payment_is_pre_trade: bool = False,
    in_scope_basis_aligned: bool = False,
    # 交易前大额累计直接取账面 TB_BigPay 列（实证交易前口径，决策记录 D4）；
    # 仅在累计口径确认时由服务层开启，开启后覆盖 prior_fund_payment 入参
    use_book_prior_big_pay: bool = False,
    # 交易前医保内累计覆盖值（TB_FeeIn 未维护时由服务层按同人同年推导，决策记录 D16）；
    # 非 None 时替代账面 TB_FeeIn
    prior_in_scope_fee_override: Decimal | None = None,
    # 从院内码表列派生待遇资格（公疗/军残/退休补充类别，决策记录 D6/D7/D8）；
    # 派生规则为候选状态，签核前仅评估链路开启
    derive_eligibility_from_codes: bool = False,
) -> tuple[DecompositionSnapshot, tuple[str, ...]]:
    """行 dict → DecompositionSnapshot。返回 (快照, 组装留痕 notes)。

    规则：
    - 观测值 None≠0：账面缺失列保持 None，不按零处理；
    - PersonProfile 资格字段默认 None（禁止金额反推资格）；仅在调用方显式开启
      derive_eligibility_from_codes 时从院内码表列（PN_PersonType/P_Official*/P_JCLevel）
      派生，派生依据全部留痕 notes（决策记录 D6/D7/D8，签核前候选）；
    - 险种/医疗类别由调用方（经确认的 resolver）显式给出，默认 unknown 不猜测（设计 §6.1）；
    - TB_FeeIn/TB_BigPay 交易前口径默认未确认；use_book_prior_big_pay 与
      prior_in_scope_fee_is_pre_trade 仅评估链路显式开启（实证依据见决策记录 D3/D4）；
    - 费用发生日期列缺失时降级用交易日期并在 notes 标注（o_FeeItem 无发生日期列，实测）；
    - 脏数据（缺交易日期/账面费用、日期不可解析）抛 ValueError，由服务层降级。
    """
    m = mapping
    notes: list[str] = []

    trade_date = _to_date(trade_row.get(_k(m, "op_trade_date")))
    if trade_date is None:
        raise ValueError("交易行缺少交易日期 T_TradeDate，无法锚定快照时点")
    trade_no = _to_str(trade_row.get(_k(m, "op_trade_no"))) or ""
    hospital_code = _to_str(trade_row.get(_k(m, "op_hosp_code"))) or ""

    # 冲正/退款识别：被退费标记、部分退费标记、退费/冲正关联原交易号
    original_trade_no = _to_str(trade_row.get(_k(m, "op_ref_original_no"))) or _to_str(
        trade_row.get(_k(m, "op_reversal_original_no")))
    is_reversal = (
        _truthy(trade_row.get(_k(m, "op_has_refundmented")))
        or _truthy(trade_row.get(_k(m, "op_partial_return")))
    )
    trade = TradeAnchor(
        trade_no=trade_no, trade_date=trade_date, hospital_code=hospital_code,
        is_reversal=is_reversal, original_trade_no=original_trade_no,
        no_right_reason=_to_str(trade_row.get(_k(m, "op_no_right_reason"))),
    )

    # 人员：默认仅映射人员类别与出生日期；资格字段仅在显式开启时从码表列派生
    person_type_code = _to_str(trade_row.get(_k(m, "op_person_type")))
    person_kwargs: dict[str, Any] = {}
    if derive_eligibility_from_codes:
        # 军残资格：PN_PersonType 属字典 290 伤残军人类别码（决策记录 D7）；
        # 等级取 P_JCLevel（1-4→'1-4'，5-6→'5-6'，其他/0→None）
        is_dvet = person_type_code in _DISABLED_VETERAN_PERSON_TYPE_CODES
        jc_level = _to_str(trade_row.get(_k(m, "op_jc_level")))
        grade: str | None = None
        if is_dvet and jc_level is not None:
            try:
                lv = int(jc_level)
                grade = "1-4" if 1 <= lv <= 4 else ("5-6" if 5 <= lv <= 6 else None)
            except ValueError:
                grade = None
        # 公疗资格：P_Official=0（字典 flid=150 享受）且 P_OfficialCode='3'（决策记录 D6）；
        # 资格人员默认本院即本人定点（单院区部署，待确认）
        official = _to_str(trade_row.get(_k(m, "op_official")))
        official_code = _to_str(trade_row.get(_k(m, "op_official_code")))
        pmed_eligible = official == "0" and official_code == "3"
        # 退休补充类别：21/22 → 普通（50%，决策记录 D8，实证两笔精确对账）；
        # 其余退休代码（社会化/企业改组等）类别未确认，保持 None fail-closed
        retire_category = (
            "normal" if person_type_code in _NORMAL_RETIRED_PERSON_TYPE_CODES else None
        )
        person_kwargs = {
            "is_disabled_veteran": is_dvet,
            "is_rural_disabled_veteran": (
                True if person_type_code in _RURAL_DISABLED_VETERAN_PERSON_TYPE_CODES
                else (False if is_dvet or person_type_code is not None else None)
            ),
            "military_disability_grade": grade,
            "public_medical_eligible": pmed_eligible,
            "public_medical_designated": True if pmed_eligible else None,
            "retirement_category": retire_category,
            "retire_supplement_enroll_date": (
                _RETIRE_SUPPLEMENT_ENROLL_FALLBACK if retire_category is not None else None
            ),
        }
        notes.append(
            "ELIGIBILITY_DERIVED_FROM_CODES：待遇资格由院内码表列派生（候选口径，"
            "决策记录 D6/D7/D8，签核前仅评估链路使用）")
    person = PersonProfile(
        person_type_code=person_type_code,
        birth_date=_to_date(trade_row.get(_k(m, "op_birthday"))),
        **person_kwargs,
    )

    institution = InstitutionProfile(
        hospital_code=hospital_code,
        h_level=institution_h_level,
        h_type=institution_h_type,
    )

    if use_book_prior_big_pay:
        prior_fund_payment = _to_decimal(trade_row.get(_k(m, "op_prior_big_pay")))
        prior_fund_payment_is_pre_trade = True

    prior_in_scope_fee = (
        prior_in_scope_fee_override
        if prior_in_scope_fee_override is not None
        else _to_decimal(trade_row.get(_k(m, "op_prior_fee_in")))
    )
    accumulation = AnnualAccumulation(
        prior_in_scope_fee=prior_in_scope_fee,
        prior_in_scope_fee_is_pre_trade=prior_in_scope_fee_is_pre_trade,
        prior_fund_payment=prior_fund_payment,
        prior_fund_payment_is_pre_trade=prior_fund_payment_is_pre_trade,
        in_scope_basis_aligned=in_scope_basis_aligned,
    )

    items: list[FeeLineItem] = []
    fee_date_fallback = False
    for row in item_rows:
        fee = _to_decimal(row.get(_k(m, "opf_fee")))
        if fee is None:
            raise ValueError(f"明细行 {row.get(_k(m, 'opf_line_id'))} 缺少账面费用 Fee，属数据异常")
        occ = _to_date(row.get(_k(m, "opf_fee_date")))
        if occ is None:
            # 费用发生日期列缺失：降级用交易日期并留痕（设计 §5.2 日期与分段 P0 待确认）
            occ = trade_date
            fee_date_fallback = True
        item_type = _to_str(row.get(_k(m, "opf_item_type")))
        items.append(FeeLineItem(
            line_key=_to_str(row.get(_k(m, "opf_line_id"))) or "",
            item_code=_to_str(row.get(_k(m, "opf_item_code"))) or "",
            # ItemType→目录类别：院内字典 k10（0=药品 1=诊疗 2=服务设施 3=耗材）；
            # 未覆盖取值按 UNKNOWN 不猜测（决策记录 D1）
            catalog_kind=_ITEM_TYPE_TO_CATALOG_KIND.get(item_type or "", CatalogKind.UNKNOWN),
            fee=fee,
            fee_occurrence_date=occ,
            item_type=item_type,
            fee_type=_to_str(row.get(_k(m, "opf_fee_type"))),
            unit_price=_to_decimal(row.get(_k(m, "opf_unit_price"))),
            count=_to_decimal(row.get(_k(m, "opf_count"))),
            fee_in=_to_decimal(row.get(_k(m, "opf_fee_in"))),
            fee_out=_to_decimal(row.get(_k(m, "opf_fee_out"))),
            self_pay_2=_to_decimal(row.get(_k(m, "opf_self_pay_2"))),
            medic_l=_to_decimal(row.get(_k(m, "opf_medic_l"))),
            sp_scale=_to_decimal(row.get(_k(m, "opf_sp_scale"))),
        ))
    if fee_date_fallback:
        notes.append(
            "FEE_OCCURRENCE_DATE_FALLBACK：部分明细费用发生日期缺失，已降级使用交易日期"
            "（o_FeeItem 发生日期列口径 P0 待确认）")

    drug_catalog = tuple(_drug_entry(i, row, m, notes) for i, row in enumerate(drug_catalog_rows))
    service_catalog = tuple(
        ServiceCatalogEntry(
            entry_id=f"svc:{i}:{_to_str(row.get(_k(m, 'cat_svc_code')))}",
            item_code=_to_str(row.get(_k(m, "cat_svc_code"))) or "",
            effective_date=_to_date(row.get(_k(m, "cat_svc_effective"))),
            expiry_date=_to_date(row.get(_k(m, "cat_svc_expiry"))),
            sfxmdj=_to_str(row.get(_k(m, "cat_svc_sfxmdj"))),
            self_pay_ratio=_to_decimal(row.get(_k(m, "cat_svc_self_pay_ratio"))),
            unit_price_limit=_to_decimal(row.get(_k(m, "cat_svc_unit_price_limit"))),
        )
        for i, row in enumerate(service_catalog_rows)
    )
    if material_catalog_rows:
        # 材料的人工器官/集采中选标志列未映射：默认 False 为占位，待黄金样本确认（设计 §16 P1）
        notes.append(
            "MATERIAL_EXCEPTION_FLAGS_UNMAPPED：材料人工器官/集采中选标志列未映射，"
            "按普通材料占位（待黄金样本确认）")
    material_catalog = tuple(
        MaterialCatalogEntry(
            entry_id=f"mat:{i}:{_to_str(row.get(_k(m, 'cat_svc_code')))}",
            item_code=_to_str(row.get(_k(m, "cat_svc_code"))) or "",
            effective_date=_to_date(row.get(_k(m, "cat_svc_effective"))),
            expiry_date=_to_date(row.get(_k(m, "cat_svc_expiry"))),
        )
        for i, row in enumerate(material_catalog_rows)
    )

    observed = ObservedSettlementAmounts(
        fee_all=_to_decimal(trade_row.get(_k(m, "op_fee_all"))),
        fee_in=_to_decimal(trade_row.get(_k(m, "op_fee_in"))),
        fee_out=_to_decimal(trade_row.get(_k(m, "op_fee_out"))),
        self_pay_2=_to_decimal(trade_row.get(_k(m, "op_self_pay_2"))),
        first_pay=_to_decimal(trade_row.get(_k(m, "op_first_pay"))),
        big_pay=_to_decimal(trade_row.get(_k(m, "op_big_pay"))),
        big_self_pay=_to_decimal(trade_row.get(_k(m, "op_big_self_pay"))),
        bc_pay=_to_decimal(trade_row.get(_k(m, "op_bc_pay"))),
        jc_pay=_to_decimal(trade_row.get(_k(m, "op_jc_pay"))),
        official_pay=_to_decimal(trade_row.get(_k(m, "op_official_pay"))),
        self_pay_1=_to_decimal(trade_row.get(_k(m, "op_self_pay_1"))),
        fund_pay=_to_decimal(trade_row.get(_k(m, "op_fund_pay"))),
        self_pay_all=_to_decimal(trade_row.get(_k(m, "op_self_pay_all"))),
        person_count_pay=_to_decimal(trade_row.get(_k(m, "op_person_count_pay"))),
        cash_pay=_to_decimal(trade_row.get(_k(m, "op_cash_pay"))),
    )

    snapshot = DecompositionSnapshot(
        settlement_ref=f"settlement:{trade_no}",
        insurance_type=insurance_type,
        medical_category=medical_category,
        trade=trade,
        person=person,
        institution=institution,
        accumulation=accumulation,
        items=tuple(items),
        observed=observed,
        rounding_mode=rounding_mode,
        drug_catalog=drug_catalog,
        service_catalog=service_catalog,
        material_catalog=material_catalog,
        # 本单是否另有非零基金渠道无来源列：未知（不默认已穷尽）
        has_other_fund_channels=None,
    )
    return snapshot, tuple(notes)


def _drug_entry(
    index: int, row: Mapping[str, Any], m: RecordQueryMapping, notes: list[str],
) -> DrugCatalogEntry:
    a_ypbs_raw = row.get(_k(m, "cat_drug_a_ypbs"))
    if a_ypbs_raw is None or str(a_ypbs_raw).strip() == "":
        notes.append(
            "DRUG_A_YPBS_EMPTY：药品目录集采标识存在空值，按非集采占位（待黄金样本确认）")
    return DrugCatalogEntry(
        entry_id=f"drug:{index}:{_to_str(row.get(_k(m, 'cat_drug_code')))}",
        item_code=_to_str(row.get(_k(m, "cat_drug_code"))) or "",
        effective_date=_to_date(row.get(_k(m, "cat_drug_effective"))),
        expiry_date=_to_date(row.get(_k(m, "cat_drug_expiry"))),
        sflb=_to_str(row.get(_k(m, "cat_drug_sflb"))),
        self_pay_ratio=_to_decimal(row.get(_k(m, "cat_drug_self_pay_ratio"))),
        a_ypbs=_truthy(a_ypbs_raw),
        a_mzxj=_to_decimal(row.get(_k(m, "cat_drug_a_mzxj"))),
        a_xbbl=_to_decimal(row.get(_k(m, "cat_drug_a_xbbl"))),
        ypfl=_to_str(row.get(_k(m, "cat_drug_ypfl"))),
        bzjg=_to_decimal(row.get(_k(m, "cat_drug_bzjg"))),
        preparation_hospital_code=_to_str(row.get(_k(m, "cat_drug_preparation_hospital"))),
    )
