"""门户账号 PostgreSQL 存储。

DDL 遵守项目约定：CREATE + ALTER 双写（活库 CREATE TABLE IF NOT EXISTS 不重建，
加列必须同时配 ALTER TABLE ... ADD COLUMN IF NOT EXISTS）。
"""
from __future__ import annotations

from typing import Any

from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.portal_account import PortalAccount


class PostgresPortalAccountStore:
    def __init__(self, client: PostgreSQLClient | None = None):
        self._client = client or PostgreSQLClient()
        self.ensure_tables()

    def ensure_tables(self) -> None:
        self._client.execute(
            """
            create table if not exists portal_accounts (
                id serial primary key,
                username varchar(64) not null unique,
                password_hash varchar(256) not null,
                role varchar(32) not null,
                status varchar(16) not null default 'active',
                created_at timestamptz not null default current_timestamp,
                updated_at timestamptz not null default current_timestamp
            )
            """
        )
        self._client.execute(
            "alter table portal_accounts add column if not exists status varchar(16) not null default 'active'"
        )

    @staticmethod
    def _row_to_account(row: dict[str, Any]) -> PortalAccount:
        return PortalAccount(
            username=row["username"],
            password_hash=row["password_hash"],
            role=row["role"],
            status=row.get("status") or "active",
        )

    def get_by_username(self, username: str) -> PortalAccount | None:
        rows = self._client.execute(
            "select username, password_hash, role, status from portal_accounts where username = %s",
            (username,),
        )
        if not rows:
            return None
        return self._row_to_account(rows[0])

    def create_account(self, account: PortalAccount) -> None:
        self._client.execute(
            """
            insert into portal_accounts (username, password_hash, role, status)
            values (%s, %s, %s, %s)
            """,
            (account.username, account.password_hash, account.role, account.status),
        )
