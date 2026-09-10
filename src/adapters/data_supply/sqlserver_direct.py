"""一档供给实现：SQL Server 只读视图直连 — issue #27。

把开发期 real_db 直连收敛为正式供给适配器：连接策略经构造注入
（组合根在 runtime 侧装配，保持 adapters 不反向依赖 runtime），
本类只承载供给合同——按语义层注册的 datasource_id 提供只读连接。
二档医院落地时实现 DataSupplyConnectionPort 替换本类，语义层与 Skill 零改动。
"""
from __future__ import annotations

from typing import Any, Callable


class SqlServerDirectSupplyAdapter:
    """一档（有数据中心/CDR）：只读账号 + 视图直连，协和谈判基线形态。"""

    def __init__(self, connect_fn: Callable[[str], Any]):
        self._connect_fn = connect_fn

    def connect(self, datasource_id: str) -> Any:
        return self._connect_fn(datasource_id)
