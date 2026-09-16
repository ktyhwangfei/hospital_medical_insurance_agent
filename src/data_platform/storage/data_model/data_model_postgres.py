"""数据模型 PostgreSQL 存储 — 架构设计 V3.0 §4.2。

data_models：模型文档主表（JSONB 整体存储，乐观锁 revision）。
data_model_mappings：多源映射行级表（确认流按行粒度操作）。
"""
from __future__ import annotations

import json

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.domain.data_model.models import (
    DataModel,
    DataModelConflictError,
    DataModelMapping,
    DataModelNotFoundError,
)

DATA_MODEL_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS data_models (
    model_code VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    layer VARCHAR(8) NOT NULL,
    grain VARCHAR(128) NOT NULL,
    entity_code VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    owner VARCHAR(128) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL DEFAULT 1,
    content_hash VARCHAR(64) NOT NULL DEFAULT '',
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS data_model_mappings (
    model_code VARCHAR(64) NOT NULL REFERENCES data_models(model_code) ON DELETE CASCADE,
    field_code VARCHAR(64) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    physical_table VARCHAR(128) NOT NULL,
    physical_column VARCHAR(128) NOT NULL,
    transform_rule TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (model_code, field_code, source_id)
);
"""


class PostgresDataModelStorage:
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
            self._client.execute(DATA_MODEL_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    # ── 模型主表 ────────────────────────────────────────────────────

    def create_model(self, model: DataModel) -> DataModel:
        client = self._get_client()
        exists = client.execute(
            "SELECT 1 FROM data_models WHERE model_code = %s", (model.model_code,)
        )
        if exists:
            raise DataModelConflictError(f"数据模型 {model.model_code} 已存在")
        client.execute(
            """
            INSERT INTO data_models
                (model_code, name, layer, grain, entity_code, status, owner,
                 version, revision, content_hash, definition)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                model.model_code, model.name, model.layer.value, model.grain,
                model.entity_code, model.status.value, model.owner,
                model.version, model.revision, model.content_hash,
                json.dumps(model.model_dump(mode="json"), ensure_ascii=False),
            ),
        )
        return model.model_copy(deep=True)

    def get_model(self, model_code: str) -> DataModel | None:
        rows = self._get_client().execute(
            "SELECT definition FROM data_models WHERE model_code = %s", (model_code,)
        )
        if not rows:
            return None
        return DataModel.model_validate(rows[0]["definition"])

    def list_models(self) -> list[DataModel]:
        rows = self._get_client().execute(
            "SELECT definition FROM data_models ORDER BY model_code"
        )
        return [DataModel.model_validate(row["definition"]) for row in rows]

    def update_model(self, model: DataModel, expected_revision: int) -> DataModel:
        client = self._get_client()
        rows = client.execute(
            """
            UPDATE data_models
            SET name = %s, layer = %s, grain = %s, entity_code = %s, status = %s,
                owner = %s, version = %s, revision = %s, content_hash = %s,
                definition = %s, updated_at = CURRENT_TIMESTAMP
            WHERE model_code = %s AND revision = %s
            RETURNING model_code
            """,
            (
                model.name, model.layer.value, model.grain, model.entity_code,
                model.status.value, model.owner, model.version, model.revision,
                model.content_hash,
                json.dumps(model.model_dump(mode="json"), ensure_ascii=False),
                model.model_code, expected_revision,
            ),
        )
        if not rows:
            if self.get_model(model.model_code) is None:
                raise DataModelNotFoundError(model.model_code)
            raise DataModelConflictError(f"数据模型版本冲突: 期望 {expected_revision}")
        return model.model_copy(deep=True)

    def delete_model(self, model_code: str, expected_revision: int) -> None:
        client = self._get_client()
        rows = client.execute(
            "DELETE FROM data_models WHERE model_code = %s AND revision = %s RETURNING model_code",
            (model_code, expected_revision),
        )
        if not rows:
            if self.get_model(model_code) is None:
                raise DataModelNotFoundError(model_code)
            raise DataModelConflictError(f"数据模型版本冲突: 期望 {expected_revision}")

    # ── 多源映射 ────────────────────────────────────────────────────

    def upsert_mapping(
        self, mapping: DataModelMapping, expected_revision: int | None
    ) -> DataModelMapping:
        client = self._get_client()
        if expected_revision is not None:
            rows = client.execute(
                """
                UPDATE data_model_mappings
                SET physical_table = %s, physical_column = %s, transform_rule = %s,
                    status = %s, revision = %s, updated_at = CURRENT_TIMESTAMP
                WHERE model_code = %s AND field_code = %s AND source_id = %s AND revision = %s
                RETURNING model_code
                """,
                (
                    mapping.physical_table, mapping.physical_column, mapping.transform_rule,
                    mapping.status.value, mapping.revision,
                    mapping.model_code, mapping.field_code, mapping.source_id,
                    expected_revision,
                ),
            )
            if not rows:
                if self.get_mapping(mapping.model_code, mapping.field_code, mapping.source_id) is None:
                    raise DataModelNotFoundError(
                        f"{mapping.model_code}.{mapping.field_code}@{mapping.source_id}"
                    )
                raise DataModelConflictError(f"映射版本冲突: 期望 {expected_revision}")
        else:
            client.execute(
                """
                INSERT INTO data_model_mappings
                    (model_code, field_code, source_id, physical_table, physical_column,
                     transform_rule, status, revision)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (model_code, field_code, source_id) DO UPDATE
                SET physical_table = EXCLUDED.physical_table,
                    physical_column = EXCLUDED.physical_column,
                    transform_rule = EXCLUDED.transform_rule,
                    status = EXCLUDED.status,
                    revision = EXCLUDED.revision,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    mapping.model_code, mapping.field_code, mapping.source_id,
                    mapping.physical_table, mapping.physical_column,
                    mapping.transform_rule, mapping.status.value, mapping.revision,
                ),
            )
        return mapping.model_copy(deep=True)

    def list_mappings(self, model_code: str) -> list[DataModelMapping]:
        rows = self._get_client().execute(
            """
            SELECT model_code, field_code, source_id, physical_table, physical_column,
                   transform_rule, status, revision
            FROM data_model_mappings WHERE model_code = %s
            ORDER BY field_code, source_id
            """,
            (model_code,),
        )
        return [self._row_to_mapping(row) for row in rows]

    def get_mapping(
        self, model_code: str, field_code: str, source_id: str
    ) -> DataModelMapping | None:
        rows = self._get_client().execute(
            """
            SELECT model_code, field_code, source_id, physical_table, physical_column,
                   transform_rule, status, revision
            FROM data_model_mappings
            WHERE model_code = %s AND field_code = %s AND source_id = %s
            """,
            (model_code, field_code, source_id),
        )
        if not rows:
            return None
        return self._row_to_mapping(rows[0])

    def delete_mapping(
        self, model_code: str, field_code: str, source_id: str, expected_revision: int
    ) -> None:
        rows = self._get_client().execute(
            """
            DELETE FROM data_model_mappings
            WHERE model_code = %s AND field_code = %s AND source_id = %s AND revision = %s
            RETURNING model_code
            """,
            (model_code, field_code, source_id, expected_revision),
        )
        if not rows:
            if self.get_mapping(model_code, field_code, source_id) is None:
                raise DataModelNotFoundError(f"{model_code}.{field_code}@{source_id}")
            raise DataModelConflictError(f"映射版本冲突: 期望 {expected_revision}")

    @staticmethod
    def _row_to_mapping(row: dict) -> DataModelMapping:
        return DataModelMapping(
            model_code=row["model_code"],
            field_code=row["field_code"],
            source_id=row["source_id"],
            physical_table=row["physical_table"],
            physical_column=row["physical_column"],
            transform_rule=row["transform_rule"],
            status=row["status"],
            revision=row["revision"],
            updated_at=row["updated_at"].isoformat() if row.get("updated_at") else None,
        )
