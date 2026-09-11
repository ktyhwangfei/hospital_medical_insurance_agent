"""数据供给适配器测试 — issue #27（一档直连收敛 + 端口合同 + provider 组合根）。"""
from __future__ import annotations

import pytest

from src.adapters.data_supply import SqlServerDirectSupplyAdapter
from src.adapters.ports import DataSupplyConnectionPort
from src.runtime.discovery import semantic_source as semantic_source_module


class _FakeDiscoverySource:
    """SemanticDataSource 桩：记录 open_connection 调用并返回哨兵连接。"""

    def __init__(self):
        self.calls: list[str | None] = []

    def open_connection(self, datasource_id):
        self.calls.append(datasource_id)
        return f"conn:{datasource_id}"


def test_sqlserver_direct_adapter_satisfies_port_and_delegates():
    """一档适配器满足 DataSupplyConnectionPort 合同，connect 透传 datasource_id。"""
    fake = _FakeDiscoverySource()
    adapter = SqlServerDirectSupplyAdapter(connect_fn=fake.open_connection)
    assert isinstance(adapter, DataSupplyConnectionPort)
    assert adapter.connect("bjybdb") == "conn:bjybdb"
    assert fake.calls == ["bjybdb"]


@pytest.mark.asyncio
async def test_provider_default_wiring_routes_through_supply_port(monkeypatch):
    """SemanticSettlementDataProvider 默认装配经供给端口：查询连接走 open_connection（#27）。

    语义：provider 不再触达 discovery 私有方法；换档医院只需替换 supply 实现。
    """
    from src.runtime.policy_qa.settlement_data_provider import SemanticSettlementDataProvider
    from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
    from src.semantic_layer.seed import publish_seed_query_object, seed_semantic_layer

    fake = _FakeDiscoverySource()
    monkeypatch.setattr(
        semantic_source_module, "get_semantic_data_source", lambda: fake
    )

    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    publish_seed_query_object(registry)

    provider = SemanticSettlementDataProvider(registry=registry)
    # 惰性：构造期不开连接；执行期连接经供给端口按注册 datasource_id 取
    assert fake.calls == []
    assert provider._service._connect("bjybdb") == "conn:bjybdb"
    assert fake.calls == ["bjybdb"]
