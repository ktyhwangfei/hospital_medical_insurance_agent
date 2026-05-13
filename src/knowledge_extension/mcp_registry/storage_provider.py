from src.config.mcp import load_mcp_settings
from src.data_platform.storage.mcp.factory import create_mcp_storage
from src.data_platform.storage.mcp.ports import McpStorage

_storage: McpStorage | None = None


def get_shared_mcp_storage() -> McpStorage:
    global _storage
    if _storage is None:
        _storage = create_mcp_storage(load_mcp_settings())
    return _storage