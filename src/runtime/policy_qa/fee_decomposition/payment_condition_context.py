"""仅供解释的目录条件原文与本单事实；不产生符合性裁定或重算金额。"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from typing import TYPE_CHECKING, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from src.adapters.data_supply.record_query_mappings import RecordQueryMapping
    from src.runtime.policy_qa.fee_decomposition.result import SettlementDecompositionResult


class DiagnosisFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str | None = None
    name: str | None = None
    association: Literal["same_prescription", "same_settlement"]
    is_placeholder: bool = False
    department: str | None = None
    prescriber_level: str | None = None


class PaymentConditionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bz: str | None = None
    catalog_status: Literal["unique", "not_found", "ambiguous", "unavailable"] = "unavailable"
    catalog_source: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    fee_date: str | None = None
    date_basis: str | None = None
    specification: str | None = None
    unit: str | None = None
    usage: str | None = None
    hospital_level: str | None = None
    hospital_level_name: str | None = None
    # 以下为目录原始码，未核对字典前不可翻译成适用性结论。
    catalog_hospital_level: str | None = None
    catalog_hospital_type: str | None = None
    catalog_use_restriction: str | None = None
    diagnoses: list[DiagnosisFact] = Field(default_factory=list)
    diagnosis_status: Literal["recorded", "placeholder", "not_found", "unavailable"] = "unavailable"
    symptoms: str | None = None
    symptoms_status: Literal["not_available_in_current_source"] = "not_available_in_current_source"
    clinical_conditions_verified: Literal[False] = False
    source_hash: str = ""
    read_at: str = ""


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def build_payment_condition_context(
    row: Mapping[str, Any] | None, diagnosis_rows: list[Mapping[str, Any]], *,
    catalog_available: bool, diagnosis_available: bool, ambiguous: bool,
    hospital_level: str | None, hospital_level_name: str | None,
    source_hash: str, read_at: str,
) -> PaymentConditionContext:
    row = row or {}
    context = PaymentConditionContext(
        catalog_status=("unavailable" if not catalog_available else "ambiguous" if ambiguous
                        else "unique" if row.get("catalog_code") else "not_found"),
        hospital_level=hospital_level, hospital_level_name=hospital_level_name,
        source_hash=source_hash, read_at=read_at,
    )
    for key in ("specification", "unit", "usage", "date_basis"):
        setattr(context, key, _text(row.get(key)))
    context.fee_date = (_text(row.get("fee_date")) or "")[:10] or None
    if context.catalog_status == "unique":
        context.bz = _text(row.get("bz"))
        context.catalog_source = _text(row.get("catalog_source"))
        for key in ("catalog_hospital_level", "catalog_hospital_type", "catalog_use_restriction"):
            setattr(context, key, _text(row.get(key)))
        for key in ("effective_from", "effective_to"):
            setattr(context, key, (_text(row.get(key)) or "")[:10] or None)
    if not diagnosis_available:
        return context
    recipe = None if ambiguous else _text(row.get("recipe_ref"))
    selected = [d for d in diagnosis_rows if not recipe or _text(d.get("recipe_ref")) == recipe]
    seen: set[tuple] = set()
    for diagnostic in selected:
        values = tuple(_text(diagnostic.get(k)) for k in
                       ("diagnosis_code", "diagnosis_name", "department", "prescriber_level"))
        if values in seen:
            continue
        seen.add(values)
        code, name, department, prescriber = values
        context.diagnoses.append(DiagnosisFact(
            code=code, name=name, department=department, prescriber_level=prescriber,
            association="same_prescription" if recipe else "same_settlement",
            is_placeholder=code in (None, "0", "1", "01") and name in (None, "0", "1", "未知", "未填"),
        ))
    context.diagnosis_status = ("not_found" if not context.diagnoses else
                                "placeholder" if all(d.is_placeholder for d in context.diagnoses)
                                else "recorded")
    return context


def attach_payment_condition_context(
    result: SettlementDecompositionResult, conn: Any, anchor: str, *, special: bool,
    hospital_level: str | None, hospital_level_name: str | None,
    mapping: RecordQueryMapping | None = None,
) -> SettlementDecompositionResult:
    """三处快照服务共用，覆盖职工/居民门诊、门特及定额变体的早退结果。"""
    if not result.fee_items:
        return result
    from src.adapters.data_supply.payment_condition_queries import load_payment_condition_rows
    from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING

    read = load_payment_condition_rows(conn, anchor, special=special,
                                       mapping=mapping or DEFAULT_RECORD_QUERY_MAPPING)
    data = read.data
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in data["catalog_rows"]:
        grouped[_text(row.get("line_id")) or ""].append(row)
    counts = Counter(item.line_id for item in result.fee_items)
    source_hash = hashlib.sha256(json.dumps(data, sort_keys=True, default=str,
                                           ensure_ascii=False).encode("utf-8")).hexdigest()
    read_at = datetime.now(timezone.utc).isoformat()
    items = []
    for item in result.fee_items:
        rows = grouped.get(item.line_id, [])
        unique = bool(item.line_id) and counts[item.line_id] == 1 and len(rows) == 1
        row = rows[0] if unique and _text(rows[0].get("item_code")) == item.item_code else None
        context = build_payment_condition_context(
            row, data["diagnosis_rows"], catalog_available=data["catalog_available"],
            diagnosis_available=data["diagnosis_available"],
            ambiguous=len(rows) > 1 or counts[item.line_id] > 1 or (unique and row is None),
            hospital_level=hospital_level, hospital_level_name=hospital_level_name,
            source_hash=source_hash, read_at=read_at,
        )
        items.append(item.model_copy(update={"payment_condition_context": context}))
    return result.model_copy(update={"fee_items": items})
