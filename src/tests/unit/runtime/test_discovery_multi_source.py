"""P7.2 discovery 多源扫描测试 — 从注册表取多源逐个扫描合并。

mock scan_sqlserver 隔离真实 SQL Server。
[依据: docs/steering/政策知识管线设计.md §7.6；开发计划 P7.2]
"""
from src.runtime.discovery import service
from src.runtime.discovery.service import list_enabled_sqlserver_sources, run_discovery


class _FakeMetaStore:
    def __init__(self, ds_list):
        self._ds = ds_list

    def list_datasources(self, enabled_only=False):
        rows = self._ds
        if enabled_only:
            rows = [d for d in rows if d.get("enabled")]
        return rows


def test_list_enabled_sqlserver_sources_filters_type_and_enabled():
    meta = _FakeMetaStore([
        {"id": "ds1", "name": "HIS", "type": "sqlserver", "enabled": True,
         "connection_config": {"host": "h1"}},
        {"id": "ds2", "name": "Milvus", "type": "milvus", "enabled": True,
         "connection_config": {}},
        {"id": "ds3", "name": "禁用", "type": "sqlserver", "enabled": False,
         "connection_config": {"host": "h3"}},
    ])
    sources = list_enabled_sqlserver_sources(meta)
    assert len(sources) == 1
    assert sources[0][0] == "ds1"
    assert sources[0][2]["host"] == "h1"


def test_list_enabled_sqlserver_sources_none_meta():
    assert list_enabled_sqlserver_sources(None) == []


def test_run_discovery_multi_source_merges(monkeypatch):
    """多源：从注册表取 2 个启用源，逐个扫描，合并表/字段。"""
    meta = _FakeMetaStore([
        {"id": "ds1", "type": "sqlserver", "enabled": True,
         "connection_config": {"host": "h1", "database": "d1", "schema": "dbo"}},
        {"id": "ds2", "type": "sqlserver", "enabled": True,
         "connection_config": {"host": "h2", "database": "d2", "schema": "dbo"}},
    ])
    calls: list[str] = []

    def fake_scan(cfg, store=None):
        calls.append(cfg["host"])
        return {
            "tables": [f"t_{cfg['host']}"],
            "fields": [{"field_name": "c", "table_name": f"t_{cfg['host']}",
                        "data_type": "varchar", "non_null_rate": 1.0}],
            "table_statuses": [],
        }

    monkeypatch.setattr(service, "scan_sqlserver", fake_scan)
    result = run_discovery(meta_store=meta)

    assert len(calls) == 2  # 扫了两个源
    assert set(calls) == {"h1", "h2"}
    assert result["total_tables"] == 2
    assert result["total_fields"] == 2
    # 每个字段标记了来源 datasource_id（三段式寻址基础）
    assert all("datasource_id" in f for f in result["fields"])


def test_run_discovery_single_source_config_backward_compatible(monkeypatch):
    """显式传 source_config 时：单源扫描（向后兼容）。"""
    calls: list[str] = []

    def fake_scan(cfg, store=None):
        calls.append(cfg["host"])
        return {"tables": ["t1"], "fields": [], "table_statuses": []}

    monkeypatch.setattr(service, "scan_sqlserver", fake_scan)
    run_discovery(source_config={"sqlserver": {"host": "legacy", "database": "d"}})
    assert calls == ["legacy"]  # 只扫一个


# ── _run_discovery_sync 多源接线（P7.2，semantic_routes）──


def test_run_discovery_sync_passes_meta_store_when_no_sqlserver(monkeypatch):
    """source_config 无 sqlserver 时自动取 meta_store 传给 run_discovery。"""
    from src.runtime.api import semantic_routes
    from src.runtime.discovery import service

    captured: dict = {}

    def fake_run(source_config=None, store=None, meta_store=None):
        captured["meta_store"] = meta_store
        return {"tables": [], "total_tables": 0, "total_fields": 0,
                "mapped_fields": 0, "unmapped_fields": 0,
                "fields": [], "table_statuses": []}

    monkeypatch.setattr(service, "run_discovery", fake_run)
    sentinel = object()
    monkeypatch.setattr(semantic_routes, "_get_meta_store", lambda: sentinel)
    semantic_routes._run_discovery_sync({"sample_limit": 10000}, None)
    assert captured["meta_store"] is sentinel


def test_run_discovery_sync_skips_meta_store_when_sqlserver_config(monkeypatch):
    """source_config 有 sqlserver 时不取 meta_store（单源兼容）。"""
    from src.runtime.api import semantic_routes
    from src.runtime.discovery import service

    captured: dict = {}

    def fake_run(source_config=None, store=None, meta_store=None):
        captured["meta_store"] = meta_store
        return {"tables": [], "total_tables": 0, "total_fields": 0,
                "mapped_fields": 0, "unmapped_fields": 0,
                "fields": [], "table_statuses": []}

    monkeypatch.setattr(service, "run_discovery", fake_run)

    def boom():
        raise AssertionError("source_config 有 sqlserver 时不应取 meta_store")

    monkeypatch.setattr(semantic_routes, "_get_meta_store", boom)
    semantic_routes._run_discovery_sync({"sqlserver": {"host": "h", "database": "d"}}, None)
    assert captured["meta_store"] is None
