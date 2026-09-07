"""数据目录资产 PostgreSQL 存储。

遵循 ``trusted_question_postgres`` 模式：内联 schema 常量、懒连接、
``client.execute`` 返回 dict rows、JSONB 字段用 ``json.dumps`` 写入。

建表 DDL 双写（仓库硬性约束）：CREATE TABLE 包含全量列，同时逐列配
``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``——旧库已建表时 CREATE IF NOT EXISTS
不补列，缺 ALTER 会在 INSERT 报 UndefinedColumn 500。
"""

from __future__ import annotations

import json
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.data_catalog.models import CatalogAsset, CatalogAssetType

DATA_CATALOG_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_catalog_assets (
    asset_id VARCHAR(96) PRIMARY KEY,
    asset_type VARCHAR(32) NOT NULL,
    asset_key VARCHAR(256) NOT NULL UNIQUE,
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner VARCHAR(64) NOT NULL DEFAULT '',
    refresh_freq VARCHAR(64) NOT NULL DEFAULT '',
    value_ranges JSONB NOT NULL DEFAULT '{}',
    sample_summary JSONB NOT NULL DEFAULT '{}',
    semantic_object_code VARCHAR(128),
    semantic_version VARCHAR(64),
    last_batch_id VARCHAR(64),
    source_ref JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_data_catalog_assets_type
    ON data_catalog_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_data_catalog_assets_name
    ON data_catalog_assets(name);
"""

# CREATE+ALTER 双写：旧库不重建，逐列补列（与 CREATE 列清单一一对应）
DATA_CATALOG_COLUMNS_DDL = """
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS asset_id VARCHAR(96);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS asset_type VARCHAR(32);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS asset_key VARCHAR(256);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS name VARCHAR(256);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS owner VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS refresh_freq VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS value_ranges JSONB NOT NULL DEFAULT '{}';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS sample_summary JSONB NOT NULL DEFAULT '{}';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS semantic_object_code VARCHAR(128);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS semantic_version VARCHAR(64);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS last_batch_id VARCHAR(64);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS source_ref JSONB NOT NULL DEFAULT '{}';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
"""


class PostgresDataCatalogStorage:
    """数据目录资产 PostgreSQL 存储。"""

    def __init__(
        self,
        database_url: str | None = None,
        *,
        client: PostgreSQLClient | None = None,
    ) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client = client
        self._schema_ensured = False

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
        if not self._schema_ensured:
            self._client.execute(DATA_CATALOG_TABLE_SCHEMA)
            self._client.execute(DATA_CATALOG_COLUMNS_DDL)
            self._schema_ensured = True
        return self._client

    # ── 查询 ────────────────────────────────────────────────────

    def get_asset(self, asset_id: str) -> CatalogAsset | None:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM data_catalog_assets WHERE asset_id = %s",
            (asset_id,),
        )
        return None if not rows else self._row_to_asset(rows[0])

    def list_assets(
        self,
        *,
        asset_type: CatalogAssetType | None = None,
        keyword: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CatalogAsset]:
        clauses: list[str] = []
        params: list[Any] = []
        if asset_type is not None:
            clauses.append("asset_type = %s")
            params.append(asset_type.value)
        if keyword:
            clauses.append(
                "(name ILIKE %s OR description ILIKE %s OR asset_key ILIKE %s)"
            )
            like = f"%{keyword}%"
            params.extend([like, like, like])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM data_catalog_assets"
            f"{where} ORDER BY asset_type, name, asset_id"
            " LIMIT %s OFFSET %s",  # noqa: S608
            (*params, limit, offset),
        )
        return [self._row_to_asset(row) for row in rows]

    # ── 写入 ────────────────────────────────────────────────────

    def upsert_asset(self, asset: CatalogAsset) -> CatalogAsset:
        client = self._get_client()
        rows = client.execute(
            """
            INSERT INTO data_catalog_assets (
                asset_id, asset_type, asset_key, name, description, owner,
                refresh_freq, value_ranges, sample_summary,
                semantic_object_code, semantic_version, last_batch_id,
                source_ref, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (asset_key) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                owner = EXCLUDED.owner,
                refresh_freq = EXCLUDED.refresh_freq,
                value_ranges = EXCLUDED.value_ranges,
                sample_summary = EXCLUDED.sample_summary,
                semantic_object_code = EXCLUDED.semantic_object_code,
                semantic_version = EXCLUDED.semantic_version,
                last_batch_id = EXCLUDED.last_batch_id,
                source_ref = EXCLUDED.source_ref,
                updated_at = EXCLUDED.updated_at
            RETURNING *
            """,
            (
                asset.asset_id,
                asset.asset_type.value,
                asset.asset_key,
                asset.name,
                asset.description,
                asset.owner,
                asset.refresh_freq,
                json.dumps(asset.value_ranges, ensure_ascii=False),
                json.dumps(asset.sample_summary, ensure_ascii=False),
                asset.semantic_object_code,
                asset.semantic_version,
                asset.last_batch_id,
                json.dumps(asset.source_ref, ensure_ascii=False),
                asset.created_at,
                asset.updated_at,
            ),
        )
        return self._row_to_asset(rows[0])

    def delete_assets_except(self, keep_keys: list[str]) -> int:
        client = self._get_client()
        if not keep_keys:
            rows = client.execute("DELETE FROM data_catalog_assets RETURNING asset_id")
            return len(rows)
        rows = client.execute(
            "DELETE FROM data_catalog_assets WHERE asset_key <> ALL(%s) RETURNING asset_id",
            (keep_keys,),
        )
        return len(rows)

    # ── 行映射 ──────────────────────────────────────────────────

    @staticmethod
    def _json_value(value: Any, default: Any) -> Any:
        """JSONB 列读取兼容：psycopg 驱动可能返回已解析对象或 JSON 字符串。"""
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    @classmethod
    def _row_to_asset(cls, row: dict[str, Any]) -> CatalogAsset:
        return CatalogAsset(
            asset_id=row["asset_id"],
            asset_type=CatalogAssetType(row["asset_type"]),
            asset_key=row["asset_key"],
            name=row["name"],
            description=row.get("description") or "",
            owner=row.get("owner") or "",
            refresh_freq=row.get("refresh_freq") or "",
            value_ranges=cls._json_value(row.get("value_ranges"), {}),
            sample_summary=cls._json_value(row.get("sample_summary"), {}),
            semantic_object_code=row.get("semantic_object_code"),
            semantic_version=row.get("semantic_version"),
            last_batch_id=row.get("last_batch_id"),
            source_ref=cls._json_value(row.get("source_ref"), {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
