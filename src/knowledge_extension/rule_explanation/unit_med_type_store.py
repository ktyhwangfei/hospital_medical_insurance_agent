"""单元医疗类别人工修正存储：内存 + PostgreSQL 双实现（Issue #19）。

只存人工修正（override）；自动分类由 med_type_classifier 确定性计算，
读取时 manual 覆盖 auto，无需持久化自动值。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field


class UnitMedTypeOverride(BaseModel):
    """一个单元的人工医疗类别修正。"""

    doc_id: str
    unit_id: str
    med_type: str = Field(min_length=1, max_length=64)
    updated_by: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UnitMedTypeStore(Protocol):
    def get(self, doc_id: str, unit_id: str) -> UnitMedTypeOverride | None: ...
    def set(self, override: UnitMedTypeOverride) -> UnitMedTypeOverride: ...
    def delete(self, doc_id: str, unit_id: str) -> bool: ...
    def list_all(self) -> list[UnitMedTypeOverride]: ...


class InMemoryUnitMedTypeStore:
    """测试与本地回退使用。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], UnitMedTypeOverride] = {}

    def get(self, doc_id: str, unit_id: str) -> UnitMedTypeOverride | None:
        item = self._items.get((doc_id, unit_id))
        return item.model_copy(deep=True) if item else None

    def set(self, override: UnitMedTypeOverride) -> UnitMedTypeOverride:
        self._items[(override.doc_id, override.unit_id)] = override.model_copy(deep=True)
        return override.model_copy(deep=True)

    def delete(self, doc_id: str, unit_id: str) -> bool:
        return self._items.pop((doc_id, unit_id), None) is not None

    def list_all(self) -> list[UnitMedTypeOverride]:
        return [item.model_copy(deep=True) for item in self._items.values()]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_unit_med_types (
    doc_id VARCHAR(64) NOT NULL,
    unit_id VARCHAR(64) NOT NULL,
    med_type VARCHAR(64) NOT NULL,
    updated_by VARCHAR(128),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (doc_id, unit_id)
);
"""


class PostgresUnitMedTypeStore:
    """UnitMedTypeStore 的 PostgreSQL adapter，懒建表。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient

            self._client = PostgreSQLClient(self._database_url or DATABASE_URL)
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    self._client.execute(statement)
        return self._client

    def get(self, doc_id: str, unit_id: str) -> UnitMedTypeOverride | None:
        rows = self._get_client().execute(
            """SELECT doc_id, unit_id, med_type, updated_by, updated_at
               FROM policy_unit_med_types WHERE doc_id = %s AND unit_id = %s""",
            (doc_id, unit_id),
        )
        return UnitMedTypeOverride(**rows[0]) if rows else None

    def set(self, override: UnitMedTypeOverride) -> UnitMedTypeOverride:
        self._get_client().execute(
            """INSERT INTO policy_unit_med_types
               (doc_id, unit_id, med_type, updated_by, updated_at)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (doc_id, unit_id) DO UPDATE SET
                 med_type=EXCLUDED.med_type,
                 updated_by=EXCLUDED.updated_by,
                 updated_at=EXCLUDED.updated_at""",
            (
                override.doc_id, override.unit_id, override.med_type,
                override.updated_by, override.updated_at,
            ),
        )
        return override

    def delete(self, doc_id: str, unit_id: str) -> bool:
        client = self._get_client()
        existed = bool(client.execute(
            "SELECT 1 FROM policy_unit_med_types WHERE doc_id = %s AND unit_id = %s",
            (doc_id, unit_id),
        ))
        client.execute(
            "DELETE FROM policy_unit_med_types WHERE doc_id = %s AND unit_id = %s",
            (doc_id, unit_id),
        )
        return existed

    def list_all(self) -> list[UnitMedTypeOverride]:
        rows = self._get_client().execute(
            """SELECT doc_id, unit_id, med_type, updated_by, updated_at
               FROM policy_unit_med_types ORDER BY updated_at DESC"""
        )
        return [UnitMedTypeOverride(**row) for row in rows]
