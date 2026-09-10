"""数据供给适配器（#27 分档接入）：一档 SQL Server 直连；二档/三档按院实现端口。"""
from src.adapters.data_supply.sqlserver_direct import SqlServerDirectSupplyAdapter

__all__ = ["SqlServerDirectSupplyAdapter"]
