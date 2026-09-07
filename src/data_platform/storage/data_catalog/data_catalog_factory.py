"""数据目录资产存储工厂。

遵循项目统一存储开关：``USE_MEMORY_STORAGE=1`` 回退内存实现，默认 PostgreSQL。
"""

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_data_catalog_storage():
    """按项目统一存储开关返回进程级数据目录资产存储。"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.data_catalog.data_catalog_in_memory import (
            InMemoryDataCatalogStorage,
        )

        return InMemoryDataCatalogStorage()

    from src.data_platform.storage.data_catalog.data_catalog_postgres import (
        PostgresDataCatalogStorage,
    )

    return PostgresDataCatalogStorage()
