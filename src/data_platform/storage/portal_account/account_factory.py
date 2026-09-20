"""门户账号存储工厂 — 默认 PostgreSQL，USE_MEMORY_STORAGE=1 回退内存。"""
from __future__ import annotations

import os

from src.data_platform.storage.portal_account.account_in_memory import (
    InMemoryPortalAccountStore,
)


def get_portal_account_store():
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        return InMemoryPortalAccountStore()
    from src.data_platform.storage.portal_account.account_postgres import (
        PostgresPortalAccountStore,
    )

    return PostgresPortalAccountStore()
