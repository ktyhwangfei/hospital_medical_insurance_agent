"""健康运营问题库存储工厂 — 按统一存储开关返回进程级存储。"""
import os
from functools import lru_cache

from src.data_platform.storage.ops.ops_ports import OpsFindingStorage


@lru_cache(maxsize=1)
def get_ops_finding_storage() -> OpsFindingStorage:
    """按项目统一存储开关返回问题库存储（USE_MEMORY_STORAGE=1 回退内存）。"""

    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.ops.ops_in_memory import InMemoryOpsFindingStorage

        return InMemoryOpsFindingStorage()

    from src.data_platform.storage.ops.ops_postgres import PostgresOpsFindingStorage

    return PostgresOpsFindingStorage()
