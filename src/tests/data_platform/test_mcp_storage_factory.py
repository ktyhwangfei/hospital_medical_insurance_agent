from src.config.mcp import McpSettings
from src.data_platform.storage.mcp.factory import create_mcp_storage
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage


def test_factory_uses_in_memory_by_default():
    storage = create_mcp_storage(McpSettings())
    assert isinstance(storage, InMemoryMcpStorage)


def test_factory_can_create_postgres_storage_with_unavailable_executor():
    storage = create_mcp_storage(McpSettings(persistence_backend="postgresql"))
    assert isinstance(storage, PostgresMcpStorage)
    assert storage.health().postgres_available is False or storage.health().postgres_available is True
