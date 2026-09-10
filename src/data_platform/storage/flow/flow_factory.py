"""治理 Flow 存储工厂 — 按统一存储开关返回进程级存储。"""
import os
from functools import lru_cache

from src.data_platform.storage.flow.flow_ports import (
    FlowViewDeployer,
    FlowViewReader,
    GovernedFlowStorage,
)


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


@lru_cache(maxsize=1)
def get_flow_view_deployer() -> FlowViewDeployer:
    """视图部署器与存储同一开关：默认 PG 真部署，内存模式回退 Noop。"""

    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.flow.flow_view_deployer import (
            NoopFlowViewDeployer,
        )

        return NoopFlowViewDeployer()

    from src.data_platform.storage.flow.flow_view_deployer import (
        PostgresFlowViewDeployer,
    )

    return PostgresFlowViewDeployer()


@lru_cache(maxsize=1)
def get_flow_view_reader() -> FlowViewReader:
    """视图读取器与存储同一开关：默认 PG 真读取，内存模式 fail closed。"""

    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.flow.flow_view_reader import (
            FailClosedFlowViewReader,
        )

        return FailClosedFlowViewReader()

    from src.data_platform.storage.flow.flow_view_reader import (
        PostgresFlowViewReader,
    )

    return PostgresFlowViewReader()
