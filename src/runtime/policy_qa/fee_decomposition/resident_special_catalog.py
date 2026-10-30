"""居民门特（mz 套表）目录独立分解适配层（Issue #81）。

职工门特（Issue #79）本期未做目录独立重算（直接用账面 ybnje/ybwje 汇总）；
Issue #81 明确要求目录分解（药品甲乙丙/集采/自制剂，ptybn/ptybw/tsbybn/tsbybw 划分）。
本模块把 yb_mzfymx 明细行适配为门诊目录分解输入（``FeeLineItem``），复用
``catalog_split.split_catalog``（与居民门诊 ROP-CAT-000 同一套规则）。

xmlb 项目类别（与 o_FeeItem.ItemType 同构，实证全库分布）：'0'=药品 → DRUG、
'1'=诊疗 → SERVICE、'3'=材料 → MATERIAL；其他取值 → UNKNOWN 不猜测归属。

特殊病费用划分（RSP-CAT-001）：目录分解得出逐行医保内/外后，本层按
``yb_ypzdml.tsbyybz``（特殊病用药标识）判定该行是否特殊病费用——
本批 3 笔明细目录标识均非空（培美曲塞 '2'、他克莫司/阿普米司特 '494'），
与账面 ptybn=0/ptybw=0（全部费用属特殊病通道）一致；非特殊病费用按普通门诊
结算本期不支持（同 ESP-CAT-002，快照服务层前置拦截 ptybn/ptybw≠0）。
"""
from __future__ import annotations

from datetime import date, datetime
from dataclasses import replace
from decimal import Decimal
from typing import Any, Iterable, Mapping

from src.domain.insurance.fee_decomposition import (
    CatalogKind,
    BranchOutcome,
    DecompositionUncertainty,
    FeeLineItem,
)
from src.runtime.policy_qa.fee_decomposition.catalog_split import (
    CatalogRuleLabels,
    CatalogSplitResult,
    _match_catalog,
    split_catalog,
)

#: xmlb → 目录类别（与 o_FeeItem.ItemType 同构，全库分布实证 0/1/3）
_XMLB_TO_CATALOG_KIND = {
    "0": CatalogKind.DRUG,
    "1": CatalogKind.SERVICE,
    "2": CatalogKind.SERVICE,
    "3": CatalogKind.MATERIAL,
}


def _to_decimal(value: Any) -> Decimal | None:
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


def adapt_mz_items_to_fee_line_items(
    item_rows: Iterable[Mapping[str, Any]],
    *,
    settle_date: date,
) -> tuple[FeeLineItem, ...]:
    """yb_mzfymx 行 dict → FeeLineItem（目录分解输入）。

    - fsrq 缺失时降级用结算日期（与门诊快照 FEE_OCCURRENCE_DATE_FALLBACK 同口径）；
    - FEE_MEDIC_L/FEE_SP_SCALE 结算事实列原样映射（None/0=未维护，同门诊 D17/D18）；
    - 账面 ybnje/ybwje/grziftw 进入 fee_in/fee_out/self_pay_2 供账面汇总核对。
    """
    items: list[FeeLineItem] = []
    for row in item_rows:
        fee = _to_decimal(row.get("zje"))
        xmlb = _to_str(row.get("xmlb"))
        occ = _to_date(row.get("fsrq")) or settle_date
        items.append(FeeLineItem(
            line_key=_to_str(row.get("xh")) or "",
            item_code=_to_str(row.get("xmdm")) or "",
            catalog_kind=_XMLB_TO_CATALOG_KIND.get(xmlb or "", CatalogKind.UNKNOWN),
            fee=fee if fee is not None else Decimal("0"),
            fee_occurrence_date=occ,
            item_type=xmlb,
            fee_type=_to_str(row.get("sflb")),
            unit_price=_to_decimal(row.get("dj")),
            count=_to_decimal(row.get("sl")),
            fee_in=_to_decimal(row.get("ybnje")),
            fee_out=_to_decimal(row.get("ybwje")),
            self_pay_2=_to_decimal(row.get("grziftw")),
            medic_l=_to_decimal(row.get("fee_medic_l")),
            sp_scale=_to_decimal(row.get("fee_sp_scale")),
        ))
    return tuple(items)


def split_special_mz_catalog(
    items: tuple[FeeLineItem, ...],
    drug_catalog,
    service_catalog,
    material_catalog,
    hospital_code: str,
    rounding_mode,
) -> CatalogSplitResult:
    """先独立核对有效目录特殊病标志，再复用目录金额划分（规则编号按本链 RSP 口径传入）。"""
    result = split_catalog(
        items, drug_catalog, service_catalog, material_catalog,
        hospital_code, rounding_mode,
        rules=CatalogRuleLabels(rounding_rule_id="RSP-RND-001", catalog_rule_ref="RSP-CAT-001"))
    catalogs = {CatalogKind.DRUG: drug_catalog, CatalogKind.SERVICE: service_catalog,
                CatalogKind.MATERIAL: material_catalog}
    invalid = set()
    uncertainties = []
    for item in items:
        matches, ambiguous_validity = _match_catalog(catalogs.get(item.catalog_kind, ()), item.item_code, item.fee_occurrence_date)
        marker = matches[0].special_disease_marker if len(matches) == 1 and not ambiguous_validity else None
        if not marker or marker.strip() in ("0", "无", "否"):
            invalid.add(item.line_key)
            uncertainties.append(DecompositionUncertainty(
                id=f"u.catalog.special_marker.{item.line_key}", code="SPECIAL_DISEASE_APPLICABILITY_UNCONFIRMED",
                message="费用项目缺少唯一有效的特殊病目录适用标志，不能由账面普通费用为零判为特殊病费用。",
                affected_fields=("TSBYBN", "TSBYBW", "GRZIFTW", "DEGWYZHF", "BIG_ILL_PAY", "CIVIL_IN")))
    if not invalid:
        return result
    return replace(result,
        explanations=tuple(item.model_copy(update={"status": "unknown", "verification_status": "unverified", "calculated_in_scope": None,
            "division_method": "unknown", "self_pay_ratio": None, "included_ratio": None, "unit_price_limit": None,
            "calculated_out_scope": None, "calculated_self_pay_2": None, "calculated_proportional_self_pay": None, "formulas": [],
            "notes": [*item.notes, "特殊病目录适用标志尚未确认，不能把一般目录划分当作门特适用结果。"]})
            if item.line_id in invalid else item for item in result.explanations),
        lines=tuple(replace(line, status=BranchOutcome.UNKNOWN, in_scope=None, out_scope=None,
                            self_pay_2=None) if line.line_key in invalid else line for line in result.lines),
        uncertainties=(*result.uncertainties, *uncertainties), is_complete=False,
        total_in_scope=None, total_out_scope=None, total_self_pay_2=None, total_proportional_self_pay=None)
