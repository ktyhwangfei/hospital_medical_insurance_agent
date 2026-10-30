"""结算展示码表：读取字典视图所对应的分类，不依赖分类表是否登记该 flid。"""
from typing import Any

from src.adapters.base.models import AdapterCallResult, AdapterCallStatus, DataQualityStatus
from src.adapters.data_supply.settlement_record_queries import _fetch_all

# 已核实视图定义：v_xzlx / v_yllb_ss / v_yllb_all / v_ybcbrylb / v_yydj。
DICTIONARY_DOMAINS = ("fund", "yllbss", "300", "290", "310", "k10", "230", "240", "280")


def load_settlement_dictionaries(conn: Any) -> AdapterCallResult:
    """保留历史停用码；重名冲突不任取一条，读取失败仅影响中文展示。"""
    try:
        marks = ",".join("?" for _ in DICTIONARY_DOMAINS)
        rows = _fetch_all(conn, f"SELECT flid,bm,mc FROM dbo.yb_zdxm WHERE flid IN ({marks})", list(DICTIONARY_DOMAINS))
        domains: dict[str, dict[str, str]] = {}
        conflicts: set[tuple[str, str]] = set()
        for row in rows:
            domain, code, name = (str(row[key]).strip() if row.get(key) is not None else "" for key in ("flid", "bm", "mc"))
            if not domain or not code or not name:
                continue
            values = domains.setdefault(domain, {})
            if code in values and values[code] != name:
                conflicts.add((domain, code))
            values[code] = name
        for domain, code in conflicts:
            domains[domain].pop(code, None)
        return AdapterCallResult(status=AdapterCallStatus.SUCCESS, source_system="hospital_record_store",
            capability="settlement_dictionary", data={"domains": domains}, data_quality=DataQualityStatus.COMPLETE)
    except Exception:
        return AdapterCallResult(status=AdapterCallStatus.FAILED, source_system="hospital_record_store",
            capability="settlement_dictionary", data={"domains": {}}, data_quality=DataQualityStatus.MISSING,
            message="本次未取得院内中文码表")
