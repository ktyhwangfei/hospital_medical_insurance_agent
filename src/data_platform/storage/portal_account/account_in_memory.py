"""门户账号内存存储（测试 / USE_MEMORY_STORAGE=1 回退）。"""
from __future__ import annotations

from src.domain.portal_account import PortalAccount


class InMemoryPortalAccountStore:
    def __init__(self) -> None:
        self._accounts: dict[str, PortalAccount] = {}

    def get_by_username(self, username: str) -> PortalAccount | None:
        return self._accounts.get(username)

    def create_account(self, account: PortalAccount) -> None:
        if account.username in self._accounts:
            raise ValueError(f"门户账号已存在: {account.username}")
        self._accounts[account.username] = account
