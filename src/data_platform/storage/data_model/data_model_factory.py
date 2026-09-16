"""数据模型存储工厂 — 按统一存储开关返回进程级存储。"""
import os
from functools import lru_cache

from src.data_platform.storage.data_model.data_model_ports import DataModelStorage


@lru_cache(maxsize=1)
def get_data_model_storage() -> DataModelStorage:
    """按项目统一存储开关返回数据模型存储（USE_MEMORY_STORAGE=1 回退内存）。"""

    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.data_model.data_model_in_memory import (
            InMemoryDataModelStorage,
        )

        return InMemoryDataModelStorage()

    from src.data_platform.storage.data_model.data_model_postgres import (
        PostgresDataModelStorage,
    )

    return PostgresDataModelStorage()
