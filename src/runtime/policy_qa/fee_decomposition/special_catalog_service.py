"""两条门特mz链路共用的目录读取胶水层；金额与适用性判断保持纯函数。"""
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from src.adapters.base.models import AdapterCallStatus
from src.adapters.data_supply.outpatient_decomposition_queries import (
    _drug_entry, _to_date, _to_decimal, _to_str, load_drug_catalog,
    load_service_catalog, load_material_catalog, load_institution_level,
)
from src.adapters.data_supply.record_query_mappings import DEFAULT_RECORD_QUERY_MAPPING
from src.adapters.data_supply.settlement_record_queries import _k
from src.domain.insurance.fee_decomposition import MaterialCatalogEntry, RoundingMode, ServiceCatalogEntry
from src.runtime.policy_qa.fee_decomposition.catalog_split import CatalogSplitResult
from src.runtime.policy_qa.fee_decomposition.resident_special_catalog import adapt_mz_items_to_fee_line_items, split_special_mz_catalog


@dataclass(frozen=True)
class SpecialCatalogRead:
    split: CatalogSplitResult | None
    h_level: str | None = None
    row_counts: tuple[tuple[str, int], ...] = ()
    notes: tuple[str, ...] = ()
    error: str | None = None
    source_rows: tuple[Mapping[str, Any], ...] = ()


def read_special_catalog(
    conn: Any, item_rows: list[Mapping[str, Any]], settle_date: date,
    hospital_code: str, rounding_mode: RoundingMode,
) -> SpecialCatalogRead:
    """目录完整读取失败则保留错误；不以空目录假冒成功。"""
    mapping = DEFAULT_RECORD_QUERY_MAPPING
    items = adapt_mz_items_to_fee_line_items(item_rows, settle_date=settle_date)
    drug_codes = tuple(it.item_code for it in items if it.item_type == "0")
    other_codes = tuple(it.item_code for it in items if it.item_type != "0")
    results = (
        ("drug_catalog", load_drug_catalog(conn, drug_codes, mapping)),
        ("service_catalog", load_service_catalog(conn, other_codes, mapping)),
        ("material_catalog", load_material_catalog(conn, other_codes, mapping)),
        ("institution", load_institution_level(conn, hospital_code, mapping)),
    )
    for _, result in results:
        if result.status != AdapterCallStatus.SUCCESS:
            return SpecialCatalogRead(None, error=result.message or "目录/机构读取失败")
    drug_res, svc_res, mat_res, inst_res = (result for _, result in results)
    notes: list[str] = []
    if inst_res.data.get("note"):
        notes.append(inst_res.data["note"])
    drug_catalog = tuple(_drug_entry(i, row, mapping, notes) for i, row in enumerate(drug_res.data["catalog_rows"]))
    def common(row, prefix, i):
        return {
            "entry_id": f"{prefix}:{i}:{_to_str(row.get(_k(mapping, 'cat_svc_code')))}",
            "item_code": _to_str(row.get(_k(mapping, "cat_svc_code"))) or "",
            "effective_date": _to_date(row.get(_k(mapping, "cat_svc_effective"))),
            "expiry_date": _to_date(row.get(_k(mapping, "cat_svc_expiry"))),
            "special_disease_marker": _to_str(row.get(_k(mapping, "cat_svc_special_marker"))),
        }
    services = tuple(ServiceCatalogEntry(
        **common(row, "svc", i), sfxmdj=_to_str(row.get(_k(mapping, "cat_svc_sfxmdj"))),
        self_pay_ratio=_to_decimal(row.get(_k(mapping, "cat_svc_self_pay_ratio"))),
        unit_price_limit=_to_decimal(row.get(_k(mapping, "cat_svc_unit_price_limit"))),
    ) for i, row in enumerate(svc_res.data["catalog_rows"]))
    materials = tuple(MaterialCatalogEntry(
        **common(row, "mat", i), sfxmdj=_to_str(row.get(_k(mapping, "cat_svc_sfxmdj"))),
    ) for i, row in enumerate(mat_res.data["catalog_rows"]))
    split = split_special_mz_catalog(items, drug_catalog, services, materials, hospital_code, rounding_mode)
    counts = tuple((name, result.data["row_count"]) for name, result in results)
    rows = tuple(row for result in (drug_res, svc_res, mat_res) for row in result.data["catalog_rows"])
    return SpecialCatalogRead(split, inst_res.data["h_level"], counts, tuple(notes), source_rows=rows)
