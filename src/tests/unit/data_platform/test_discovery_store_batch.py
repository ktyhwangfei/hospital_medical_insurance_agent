"""Discovery/Registry Store 批量查询方法测试（mock client，不依赖真实 PG）。

覆盖性能修复引入的批量接口，确保它们正确且只执行一次查询（非 N+1）：
- DiscoveryStore.get_all_field_descriptions        (P0-1: discovery/results N+1)
- DiscoveryStore.get_previously_scanned_fields     (P0-4: 全量历史 JSON → seen 表)
- PostgresRegistryStore.list_value_domains_with_counts (P1-3: 值域 N+1)
"""
from unittest.mock import MagicMock

from src.data_platform.storage.postgresql.discovery_store import DiscoveryStore
from src.data_platform.storage.postgresql.semantic_registry_store import (
    PostgresRegistryStore,
)


def _make_discovery_store(rows) -> DiscoveryStore:
    """构造一个绕过 __init__（不连库）的 DiscoveryStore，execute 返回 rows。"""
    store = DiscoveryStore.__new__(DiscoveryStore)
    store._database_url = None
    store._client = MagicMock()
    store._client.execute.return_value = rows
    return store


def _make_registry_store(rows) -> PostgresRegistryStore:
    store = PostgresRegistryStore.__new__(PostgresRegistryStore)
    store._database_url = None
    store._client = MagicMock()
    store._client.execute.return_value = rows
    return store


# ── P0-1: get_all_field_descriptions ──────────────────────────────

def test_get_all_field_descriptions_returns_dict():
    rows = [
        {"lookup_key": "yb_settlement:set_no", "description": "结算流水号",
         "is_primary_key": True, "remark": None},
        {"lookup_key": "yb_settlement:insu_type", "description": "医保类型",
         "is_primary_key": False, "remark": "编码含义"},
    ]
    store = _make_discovery_store(rows)
    result = store.get_all_field_descriptions()

    assert set(result.keys()) == {"yb_settlement:set_no", "yb_settlement:insu_type"}
    assert result["yb_settlement:set_no"]["is_primary_key"] is True
    assert result["yb_settlement:insu_type"]["description"] == "医保类型"
    assert result["yb_settlement:insu_type"]["remark"] == "编码含义"
    # 关键：只调用一次（批量），不是逐条 N+1
    assert store._client.execute.call_count == 1


def test_get_all_field_descriptions_empty():
    store = _make_discovery_store([])
    assert store.get_all_field_descriptions() == {}


# ── P0-4: get_previously_scanned_fields 从 seen 表查询 ─────────────

def test_get_previously_scanned_fields_uses_seen_table():
    rows = [
        {"field_key": "yb_settlement:set_no"},
        {"field_key": "yb_fee_detail:item_code"},
    ]
    store = _make_discovery_store(rows)
    result = store.get_previously_scanned_fields()

    assert result == {"yb_settlement:set_no", "yb_fee_detail:item_code"}
    # 关键：单表 SELECT，不再加载全部历史 JSON
    assert store._client.execute.call_count == 1


def test_get_previously_scanned_fields_empty():
    store = _make_discovery_store([])
    assert store.get_previously_scanned_fields() == set()


# ── P1-3: list_value_domains_with_counts 批量 JOIN ────────────────

def test_list_value_domains_with_counts_batch_join():
    rows = [
        {"domain_code": "hospital_level", "name": "医院等级", "description": None,
         "standard_values": ["一级", "二级", "三级"], "mapping_count": 3},
        {"domain_code": "person_type", "name": "人员类别", "description": None,
         "standard_values": [], "mapping_count": 0},
    ]
    store = _make_registry_store(rows)
    result = store.list_value_domains_with_counts()

    assert len(result) == 2
    vd0, cnt0 = result[0]
    assert vd0.domain_code == "hospital_level"
    assert cnt0 == 3
    assert vd0.standard_values == ["一级", "二级", "三级"]

    vd1, cnt1 = result[1]
    assert vd1.domain_code == "person_type"
    assert cnt1 == 0
    # 关键：一条 JOIN 查询，非逐值域 N+1
    assert store._client.execute.call_count == 1
