"""数据供给连接端口 — issue #27（数据供给规范：语义层标准 + 分档适配接入）。

语义层是需求侧标准（跨院不变），本端口是供给侧合同（每院落地一个实现）：
一档 只读视图直连（SqlServerDirectSupplyAdapter，协和谈判基线）
二档 厂商接口/中间库定时同步（后续按院实现本端口）
三档 医保局代理通道（方向三立项后再议）

合同约定：按语义层注册的 datasource_id 建立只读连接；实现不得提供任何写通道。
"""
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DataSupplyConnectionPort(Protocol):
    """医院数据供给连接端口（供给侧合同）。"""

    def connect(self, datasource_id: str) -> Any:
        """按语义层注册的数据源标识建立只读连接。

        Args:
            datasource_id: 语义层注册的数据源标识（如 "bjybdb"）

        Returns:
            只读数据库连接（PEP 249 连接对象）

        Raises:
            RuntimeError: 数据源未注册/未启用，或供给通道不可用
        """
        ...
