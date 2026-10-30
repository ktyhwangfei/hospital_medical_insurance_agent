"""按人（身份证号）定位费用分解候选的只读查询适配器（Issue #78 工作台「按身份证号定位」）。

背景：工作台单笔分解只支持门诊交易号/门特登记号；18 位身份证号会被
``[A-Za-z0-9]{15,}`` 规则误判为交易号。本模块提供按人定位：
- 普通门诊候选：o_Trade 身份列（P_IDNo/P_ICNo/P_CardNo）OR 子句全量枚举，
  按交易日期倒序，上限 50 条（超出截断并在 notes 标注）；
- 门特候选：yb_brdjxx（sfz/kh）JOIN yb_mzjyxx（fyfs='0' 项目付费），yllb='12'，
  FUND_TYPE 区分职工/居民，tsb 503/504 标肾移植定额。

铁律（与 ``outpatient_decomposition_queries.py`` 一致）：
- 身份列只进 WHERE，绝不进 SELECT；输出候选不含身份证/姓名原文；
- SQL 仅只读参数化单语句 SELECT；身份证号只进参数，不进 SQL 文本；
- 日志使用 mask_id_no 同款掩码（前 3 后 4），绝不输出身份证原文；
- 全部返回 AdapterCallResult，不抛业务异常。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply.outpatient_special_fixed_kidney_queries import has_kidney_code
from src.adapters.data_supply.outpatient_special_mz_queries import (
    EMPLOYEE_FUND_TYPE,
    FEE_FOR_SERVICE_FYFS,
    RESIDENT_FUND_TYPE_CODES,
    SPECIAL_MZ_YLLB,
    _to_decimal,
)
from src.adapters.data_supply.record_query_mappings import (
    DEFAULT_RECORD_QUERY_MAPPING,
    RecordQueryMapping,
)
from src.adapters.data_supply.settlement_record_queries import (
    _c,
    _fetch_all,
    _identity_clause,
    _k,
    _t,
)

logger = logging.getLogger(__name__)

_SOURCE = "hospital_record_store"
_CAPABILITY = "decomposition_person_resolve"

#: 单链候选上限：全量枚举但有界，超出截断并在 notes 标注
PERSON_CANDIDATE_LIMIT = 50

#: 身份证号格式：15 位纯数字，或 18 位（前 17 位数字 + 末位数字/X/x）
_ID_CARD_PATTERN = re.compile(r"(?:\d{15}|\d{17}[\dXx])")


def is_id_card_format(identifier: str) -> bool:
    """身份证号格式判定。18 位纯字母数字的交易号（含 X 不在末位）不误判。"""
    return _ID_CARD_PATTERN.fullmatch((identifier or "").strip()) is not None


def _mask_id_card(id_card: str) -> str:
    """mask_id_no 同款掩码（前 3 后 4）；非 18 位整体打码，绝不回显原文。"""
    if len(id_card) == 18:
        return f"{id_card[:3]}{'*' * 11}{id_card[-4:]}"
    return "***"


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


def _profile_label(fund_type: str | None) -> str | None:
    """险种码 → 险种标签：3=城镇职工、91/92/93=城乡居民；未知码不猜测（None）。"""
    code = (fund_type or "").strip()
    if code == EMPLOYEE_FUND_TYPE:
        return "城镇职工"
    if code in RESIDENT_FUND_TYPE_CODES:
        return "城乡居民"
    return None


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:10] if text else None


def _fetch_outpatient_candidates(
    conn: Any, id_card: str, mapping: RecordQueryMapping,
) -> tuple[list[dict], bool]:
    """普通门诊候选：o_Trade 身份 OR 子句（复用 _identity_clause 同款构造），
    无日期窗口全量枚举，交易日期倒序，LIMIT+1 探测截断。返回 (候选, 是否截断)。"""
    params: list[Any] = []
    identity = _identity_clause(mapping, id_card, id_card, params)
    sql = (
        f"SELECT TOP ({PERSON_CANDIDATE_LIMIT + 1}) "
        f"r.{_c(mapping, 'op_trade_no')}, r.{_c(mapping, 'op_trade_date')}, "
        f"r.{_c(mapping, 'op_fee_all')}, r.{_c(mapping, 'op_fund_type')} "
        f"FROM {_t(mapping, 'outpatient_trade_table')} r "
        f"WHERE {identity} "
        f"ORDER BY r.{_c(mapping, 'op_trade_date')} DESC"
    )
    rows = _fetch_all(conn, sql, params)
    truncated = len(rows) > PERSON_CANDIDATE_LIMIT
    candidates = [
        {
            "chain": "outpatient",
            "identifier": str(row.get(_k(mapping, "op_trade_no")) or ""),
            "chain_label": "普通门诊",
            "profile_label": _profile_label(
                None if row.get(_k(mapping, "op_fund_type")) is None
                else str(row.get(_k(mapping, "op_fund_type")))),
            "service_date": _date_str(row.get(_k(mapping, "op_trade_date"))),
            "total_amount": (
                None if _to_decimal(row.get(_k(mapping, "op_fee_all"))) is None
                else str(_to_decimal(row.get(_k(mapping, "op_fee_all"))))),
        }
        for row in rows[:PERSON_CANDIDATE_LIMIT]
    ]
    return candidates, truncated


def _fetch_special_candidates(
    conn: Any, id_card: str, mapping: RecordQueryMapping,
) -> tuple[list[dict], bool]:
    """门特候选：yb_brdjxx（sfz/kh 身份过滤）JOIN yb_mzjyxx（fyfs='0' 项目付费），
    yllb='12' 门诊特殊病；tsb 503/504 标肾移植定额。入院日期倒序，LIMIT+1 探测截断。

    SELECT 列刻意不含 sfz/kh（WHERE 可用身份列，输出绝不回显身份原文）。
    """
    sql = (
        f"SELECT TOP ({PERSON_CANDIDATE_LIMIT + 1}) "
        f"b.{_c(mapping, 'reg_djh')}, b.{_c(mapping, 'reg_admit_date')}, "
        f"b.FUND_TYPE, b.{_c(mapping, 'reg_spec1')}, "
        f"b.{_c(mapping, 'reg_spec2')}, b.{_c(mapping, 'reg_spec3')} "
        f"FROM {_t(mapping, 'registration_table')} b "
        f"JOIN {_t(mapping, 'outpatient_settlement_table')} s "
        f"ON b.{_c(mapping, 'reg_djh')} = s.{_c(mapping, 'op_set_djh')} "
        f"WHERE (b.{_c(mapping, 'reg_id_card')} = ? OR b.{_c(mapping, 'reg_card_no')} = ?) "
        f"AND b.{_c(mapping, 'reg_care_type')} = ? AND s.fyfs = ? "
        f"ORDER BY b.{_c(mapping, 'reg_admit_date')} DESC"
    )
    rows = _fetch_all(conn, sql, [id_card, id_card, SPECIAL_MZ_YLLB, FEE_FOR_SERVICE_FYFS])
    truncated = len(rows) > PERSON_CANDIDATE_LIMIT
    candidates = []
    for row in rows[:PERSON_CANDIDATE_LIMIT]:
        # has_kidney_code 以 tsb1/2/3 键读取：按映射键归一化后复用
        kidney_probe = {
            key: row.get(_k(mapping, logical))
            for key, logical in (("tsb1", "reg_spec1"), ("tsb2", "reg_spec2"),
                                 ("tsb3", "reg_spec3"))
        }
        kidney = has_kidney_code(kidney_probe)
        fund_raw = row.get("fund_type")
        candidates.append({
            "chain": "special",
            "identifier": str(row.get(_k(mapping, "reg_djh")) or ""),
            "chain_label": "门诊特殊病·肾移植定额" if kidney else "门诊特殊病",
            "profile_label": _profile_label(None if fund_raw is None else str(fund_raw)),
            "service_date": _date_str(row.get(_k(mapping, "reg_admit_date"))),
            # 登记表无费用口径，总金额留 None
            "total_amount": None,
        })
    return candidates, truncated


def resolve_decomposition_targets_by_person(
    conn: Any,
    id_card: str,
    mapping: RecordQueryMapping = DEFAULT_RECORD_QUERY_MAPPING,
) -> AdapterCallResult:
    """身份证号 → 费用分解候选（普通门诊交易 + 门特登记），多候选供人工澄清，禁止自动选定。

    data：match_status（unique_match/multiple_candidates/no_match）、candidates
    （chain/identifier/chain_label/profile_label/service_date/total_amount，
    绝不含身份原文）、truncated（任一链超 50 条截断）、notes。
    """
    id_card = (id_card or "").strip()
    if not id_card:
        return _failed("按人定位失败：身份证号为空")
    notes: list[str] = []
    try:
        outpatient, op_truncated = _fetch_outpatient_candidates(conn, id_card, mapping)
        special, sp_truncated = _fetch_special_candidates(conn, id_card, mapping)
    except Exception as exc:  # noqa: BLE001 — 适配器不抛异常，统一转 FAILED
        # 异常信息不回显身份证原文（参数化查询，SQL 文本不含参数值）
        logger.warning("[FEE-DECOMP-RESOLVE] 按人定位查询失败 id_card=%s: %s",
                       _mask_id_card(id_card), exc)
        return _failed(f"按人定位候选查询失败: {exc}")
    truncated = op_truncated or sp_truncated
    if op_truncated:
        notes.append(f"普通门诊候选超过 {PERSON_CANDIDATE_LIMIT} 条，已按交易日期倒序截断")
    if sp_truncated:
        notes.append(f"门特候选超过 {PERSON_CANDIDATE_LIMIT} 条，已按入院日期倒序截断")
    candidates = outpatient + special
    if len(candidates) > 1:
        match_status = "multiple_candidates"
        note = f"命中 {len(candidates)} 个分解候选，需人工澄清选择（不确定不执行）"
    elif candidates:
        match_status = "unique_match"
        note = "唯一命中"
    else:
        match_status = "no_match"
        note = "未命中分解候选"
    logger.info("[FEE-DECOMP-RESOLVE] 按人定位 id_card=%s 命中 %d 候选",
                _mask_id_card(id_card), len(candidates))
    return _result(
        {"match_status": match_status, "candidates": candidates,
         "truncated": truncated, "candidate_count": len(candidates),
         "notes": notes},
        quality=DataQualityStatus.COMPLETE if candidates else DataQualityStatus.MISSING,
        message=note,
    )
