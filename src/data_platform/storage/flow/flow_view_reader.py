"""Flow 视图读取适配器 — Phase 3。

PG 适配器经统一 PostgreSQLClient 防腐通道做受控投影查询；
标识符（视图名/列名）先过白名单正则再双引号渲染，杜绝注入面。
USE_MEMORY_STORAGE=1 时回退 fail-closed 读取器（无部署视图可读，
消费请求显式报错而非返回空数据）。
"""
from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _quoted(identifier: str) -> str:
    if not _IDENTIFIER_RE.match(identifier):
        raise ValueError(f"视图读取标识符非法: {identifier!r}")
    return f'"{identifier}"'


class PostgresFlowViewReader:
    """从 PG 落地库按列投影读取已部署视图。"""

    def __init__(self, client=None) -> None:
        self._client = client

    def read(self, view_name: str, columns: list[str]) -> list[dict]:
        if not columns:
            raise ValueError("视图读取至少需要一列")
        if self._client is None:
            from src.data_platform.storage.postgresql.client import PostgreSQLClient

            self._client = PostgreSQLClient()
        sql = (
            f"SELECT {', '.join(_quoted(c) for c in columns)} "
            f"FROM {_quoted(view_name)}"
        )
        return self._client.execute(sql)


class FailClosedFlowViewReader:
    """内存模式读取器：无已部署视图，消费请求直接报错（fail closed）。"""

    def read(self, view_name: str, columns: list[str]) -> list[dict]:
        raise RuntimeError(
            "USE_MEMORY_STORAGE 模式未接视图读取通道：flow 消费需真实 PG 落地库"
        )
