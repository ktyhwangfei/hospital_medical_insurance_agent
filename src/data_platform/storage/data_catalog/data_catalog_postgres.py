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
from src.domain.data_catalog.models import (
    CatalogAsset,
    CatalogAssetType,
    CatalogColumn,
    CatalogLineageEdge,
)

DATA_CATALOG_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_catalog_assets (
    asset_id VARCHAR(96) PRIMARY KEY,
    asset_type VARCHAR(32) NOT NULL,
    asset_key VARCHAR(256) NOT NULL UNIQUE,
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner VARCHAR(64) NOT NULL DEFAULT '',
    refresh_freq VARCHAR(64) NOT NULL DEFAULT '',
    tags JSONB NOT NULL DEFAULT '[]',
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

CREATE TABLE IF NOT EXISTS data_catalog_columns (
    column_id VARCHAR(96) PRIMARY KEY,
    asset_id VARCHAR(96) NOT NULL,
    column_name VARCHAR(256) NOT NULL,
    name VARCHAR(256) NOT NULL DEFAULT '',
    data_type VARCHAR(64) NOT NULL DEFAULT '',
    field_role VARCHAR(32) NOT NULL DEFAULT '',
    nullable BOOLEAN NOT NULL DEFAULT TRUE,
    value_domain VARCHAR(128),
    ordinal INTEGER NOT NULL DEFAULT 0,
    UNIQUE (asset_id, column_name)
);
CREATE INDEX IF NOT EXISTS idx_data_catalog_columns_asset
    ON data_catalog_columns(asset_id);

CREATE TABLE IF NOT EXISTS data_catalog_lineage_edges (
    edge_id VARCHAR(96) PRIMARY KEY,
    upstream_asset_id VARCHAR(96) NOT NULL,
    downstream_asset_id VARCHAR(96) NOT NULL,
    relation VARCHAR(128) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_data_catalog_lineage_upstream
    ON data_catalog_lineage_edges(upstream_asset_id);
CREATE INDEX IF NOT EXISTS idx_data_catalog_lineage_downstream
    ON data_catalog_lineage_edges(downstream_asset_id);
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
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS value_ranges JSONB NOT NULL DEFAULT '{}';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS sample_summary JSONB NOT NULL DEFAULT '{}';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS semantic_object_code VARCHAR(128);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS semantic_version VARCHAR(64);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS last_batch_id VARCHAR(64);
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS source_ref JSONB NOT NULL DEFAULT '{}';
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE data_catalog_assets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS column_id VARCHAR(96);
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS asset_id VARCHAR(96);
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS column_name VARCHAR(256);
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS name VARCHAR(256) NOT NULL DEFAULT '';
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS data_type VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS field_role VARCHAR(32) NOT NULL DEFAULT '';
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS nullable BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS value_domain VARCHAR(128);
ALTER TABLE data_catalog_columns ADD COLUMN IF NOT EXISTS ordinal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE data_catalog_lineage_edges ADD COLUMN IF NOT EXISTS edge_id VARCHAR(96);
ALTER TABLE data_catalog_lineage_edges ADD COLUMN IF NOT EXISTS upstream_asset_id VARCHAR(96);
ALTER TABLE data_catalog_lineage_edges ADD COLUMN IF NOT EXISTS downstream_asset_id VARCHAR(96);
ALTER TABLE data_catalog_lineage_edges ADD COLUMN IF NOT EXISTS relation VARCHAR(128);
"""


def _asset_filters(
    asset_type: CatalogAssetType | None,
    keyword: str | None,
    owner: str | None,
    tag: str | None,
) -> tuple[str, list[Any]]:
    """list/count 共用的 WHERE 子句组装（参数化，禁止字符串拼接值）。"""
    clauses: list[str] = []
    params: list[Any] = []
    if asset_type is not None:
        clauses.append("asset_type = %s")
        params.append(asset_type.value)
    if keyword:
        clauses.append("(name ILIKE %s OR description ILIKE %s OR asset_key ILIKE %s)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if owner:
        clauses.append("owner = %s")
        params.append(owner)
    if tag:
        # JSONB 数组包含匹配
        clauses.append("tags @> %s::jsonb")
        params.append(json.dumps([tag], ensure_ascii=False))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


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
        owner: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CatalogAsset]:
        where, params = _asset_filters(asset_type, keyword, owner, tag)
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM data_catalog_assets"
            f"{where} ORDER BY asset_type, name, asset_id"
            " LIMIT %s OFFSET %s",  # noqa: S608
            (*params, limit, offset),
        )
        return [self._row_to_asset(row) for row in rows]

    def count_assets(
        self,
        *,
        asset_type: CatalogAssetType | None = None,
        keyword: str | None = None,
        owner: str | None = None,
        tag: str | None = None,
    ) -> int:
        where, params = _asset_filters(asset_type, keyword, owner, tag)
        client = self._get_client()
        rows = client.execute(
            f"SELECT COUNT(*) AS c FROM data_catalog_assets{where}",  # noqa: S608
            tuple(params),
        )
        return int(rows[0]["c"])

    # ── 写入 ────────────────────────────────────────────────────

    def upsert_asset(self, asset: CatalogAsset) -> CatalogAsset:
        client = self._get_client()
        rows = client.execute(
            """
            INSERT INTO data_catalog_assets (
                asset_id, asset_type, asset_key, name, description, owner,
                refresh_freq, tags, value_ranges, sample_summary,
                semantic_object_code, semantic_version, last_batch_id,
                source_ref, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (asset_key) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                owner = EXCLUDED.owner,
                refresh_freq = EXCLUDED.refresh_freq,
                tags = EXCLUDED.tags,
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
                json.dumps(asset.tags, ensure_ascii=False),
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

    # ── 列级元数据 ──────────────────────────────────────────────

    def replace_columns(self, columns: list[CatalogColumn]) -> None:
        client = self._get_client()
        client.execute("DELETE FROM data_catalog_columns")
        for col in columns:
            client.execute(
                """
                INSERT INTO data_catalog_columns (
                    column_id, asset_id, column_name, name, data_type,
                    field_role, nullable, value_domain, ordinal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_id, column_name) DO UPDATE SET
                    column_id = EXCLUDED.column_id,
                    name = EXCLUDED.name,
                    data_type = EXCLUDED.data_type,
                    field_role = EXCLUDED.field_role,
                    nullable = EXCLUDED.nullable,
                    value_domain = EXCLUDED.value_domain,
                    ordinal = EXCLUDED.ordinal
                """,
                (
                    col.column_id,
                    col.asset_id,
                    col.column_name,
                    col.name,
                    col.data_type,
                    col.field_role,
                    col.nullable,
                    col.value_domain,
                    col.ordinal,
                ),
            )

    def list_columns(self, asset_id: str) -> list[CatalogColumn]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM data_catalog_columns WHERE asset_id = %s"
            " ORDER BY ordinal, column_name",
            (asset_id,),
        )
        return [
            CatalogColumn(
                column_id=row["column_id"],
                asset_id=row["asset_id"],
                column_name=row["column_name"],
                name=row.get("name") or "",
                data_type=row.get("data_type") or "",
                field_role=row.get("field_role") or "",
                nullable=bool(row.get("nullable", True)),
                value_domain=row.get("value_domain"),
                ordinal=int(row.get("ordinal") or 0),
            )
            for row in rows
        ]

    # ── 血缘边 ──────────────────────────────────────────────────

    def replace_lineage_edges(self, edges: list[CatalogLineageEdge]) -> None:
        client = self._get_client()
        client.execute("DELETE FROM data_catalog_lineage_edges")
        for edge in edges:
            client.execute(
                """
                INSERT INTO data_catalog_lineage_edges (
                    edge_id, upstream_asset_id, downstream_asset_id, relation
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (edge_id) DO UPDATE SET
                    upstream_asset_id = EXCLUDED.upstream_asset_id,
                    downstream_asset_id = EXCLUDED.downstream_asset_id,
                    relation = EXCLUDED.relation
                """,
                (
                    edge.edge_id,
                    edge.upstream_asset_id,
                    edge.downstream_asset_id,
                    edge.relation,
                ),
            )

    def list_lineage_edges(self) -> list[CatalogLineageEdge]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM data_catalog_lineage_edges"
            " ORDER BY upstream_asset_id, downstream_asset_id, relation"
        )
        return [
            CatalogLineageEdge(
                edge_id=row["edge_id"],
                upstream_asset_id=row["upstream_asset_id"],
                downstream_asset_id=row["downstream_asset_id"],
                relation=row["relation"],
            )
            for row in rows
        ]

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
            tags=cls._json_value(row.get("tags"), []),
            value_ranges=cls._json_value(row.get("value_ranges"), {}),
            sample_summary=cls._json_value(row.get("sample_summary"), {}),
            semantic_object_code=row.get("semantic_object_code"),
            semantic_version=row.get("semantic_version"),
            last_batch_id=row.get("last_batch_id"),
            source_ref=cls._json_value(row.get("source_ref"), {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
