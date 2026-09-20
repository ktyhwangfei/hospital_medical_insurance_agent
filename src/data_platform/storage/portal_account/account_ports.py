"""门户账号存储端口（ports/adapter 模式，默认 PostgreSQL，可回退内存）。"""
from __future__ import annotations

from typing import Protocol

from src.domain.portal_account import PortalAccount


class PortalAccountStore(Protocol):
    """门户账号存储端口。"""

    def get_by_username(self, username: str) -> PortalAccount | None:
        """按登录名查账号，不存在返回 None。"""
        ...

    def create_account(self, account: PortalAccount) -> None:
        """新建账号（调用方负责唯一性，重复用户名由存储层约束保证）。"""
        ...
