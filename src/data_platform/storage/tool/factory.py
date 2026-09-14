"""Tool 版本存储工厂：默认 PostgreSQL，`USE_MEMORY_STORAGE=1` 时回退内存实现。"""

import os
from functools import lru_cache

from src.data_platform.storage.tool.ports import ToolVersionStorage


def _use_memory_storage() -> bool:
    return os.environ.get("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")


@lru_cache(maxsize=1)
def get_tool_version_storage() -> ToolVersionStorage:
    if _use_memory_storage():
        from src.data_platform.storage.tool.in_memory import InMemoryToolVersionStorage

        return InMemoryToolVersionStorage()

    from src.data_platform.storage.tool.postgres import PostgresToolVersionStorage

    return PostgresToolVersionStorage()
