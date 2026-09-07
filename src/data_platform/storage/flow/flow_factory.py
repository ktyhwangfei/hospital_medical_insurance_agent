"""治理 Flow 存储工厂 — 按统一存储开关返回进程级存储。"""
import os
from functools import lru_cache

from src.data_platform.storage.flow.flow_ports import GovernedFlowStorage


@lru_cache(maxsize=1)
def get_governed_flow_storage() -> GovernedFlowStorage:
    """按项目统一存储开关返回治理 Flow 存储（USE_MEMORY_STORAGE=1 回退内存）。"""

    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.flow.flow_in_memory import (
            InMemoryGovernedFlowStorage,
        )

        return InMemoryGovernedFlowStorage()

    from src.data_platform.storage.flow.flow_postgres import (
        PostgresGovernedFlowStorage,
    )

    return PostgresGovernedFlowStorage()
