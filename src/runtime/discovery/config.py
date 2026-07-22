"""Discovery 可配置数据源定义。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SqlServerConnectionConfig(BaseModel):
    """SQL Server 连接配置，全部从页面/请求传入，不依赖环境变量。"""

    host: str = Field(default="127.0.0.1", description="SQL Server 主机")
    port: int = Field(default=1433, description="SQL Server 端口")
    database: str = Field(default="", description="数据库名")
    user: str = Field(default="", description="用户名")
    password: str = Field(default="", description="密码")
    driver: str = Field(default="ODBC Driver 18 for SQL Server", description="ODBC 驱动")
    schema: str = Field(default="dbo", description="默认 schema")
    tables: list[str] = Field(default_factory=list, description="要扫描的表名列表，空=全部")
    exclude_prefixes: list[str] = Field(default_factory=lambda: ["sys_", "dt_", "MSreplication_"], description="排除前缀")


class DiscoverySourceConfig(BaseModel):
    """Discovery 扫描的数据源配置。"""

    sqlserver: SqlServerConnectionConfig | None = Field(default=None, description="SQL Server 连接")
