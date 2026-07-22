"""PostgreSQL-backed RegistryStore for Semantic Layer persistence.

Replaces InMemoryRegistryStore so domains, objects, metrics, and
value-domain mappings survive server restarts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.semantic_layer.models import (
    BusinessDomain,
    BusinessObject,
    ObjectRelation,
    Metric,
    ValueDomain,
    ValueDomainMapping,
)

logger = logging.getLogger(__name__)

_SCHEMA = """
-- 业务域
CREATE TABLE IF NOT EXISTS semantic_domains (
    domain_code VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 业务对象
CREATE TABLE IF NOT EXISTS semantic_objects (
    object_code VARCHAR(64) PRIMARY KEY,
    domain_code VARCHAR(64) NOT NULL REFERENCES semantic_domains(domain_code) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    definition TEXT,
    identifier VARCHAR(256),
    source_object VARCHAR(256),
    source_adapter_port VARCHAR(256),
    relations JSONB NOT NULL DEFAULT '[]'::jsonb,
    version VARCHAR(32) NOT NULL DEFAULT '1.0',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_semantic_objects_domain ON semantic_objects(domain_code);

-- 业务指标
CREATE TABLE IF NOT EXISTS semantic_metrics (
    metric_code VARCHAR(256) PRIMARY KEY,
    object_code VARCHAR(64) NOT NULL REFERENCES semantic_objects(object_code) ON DELETE CASCADE,
    name VARCHAR(256) NOT NULL,
    definition TEXT,
    metric_type VARCHAR(32) NOT NULL DEFAULT 'Atomic',
    semantic_type VARCHAR(32),
    unit VARCHAR(64),
    required BOOLEAN NOT NULL DEFAULT FALSE,
    default_value TEXT,
    source_object VARCHAR(256),
    source_field VARCHAR(256),
    source_adapter_port VARCHAR(256),
    transformation JSONB,
    value_domain VARCHAR(128),
    importance VARCHAR(32) NOT NULL DEFAULT 'optional',
    usage_count INTEGER NOT NULL DEFAULT 0,
    quality_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    version VARCHAR(32) NOT NULL DEFAULT '1.0',
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_semantic_metrics_object ON semantic_metrics(object_code);

-- 值域
CREATE TABLE IF NOT EXISTS semantic_value_domains (
    domain_code VARCHAR(128) PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    standard_values JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 值域映射明细
CREATE TABLE IF NOT EXISTS semantic_value_mappings (
    id SERIAL PRIMARY KEY,
    domain_code VARCHAR(128) NOT NULL REFERENCES semantic_value_domains(domain_code) ON DELETE CASCADE,
    source_value VARCHAR(512) NOT NULL,
    standard_value VARCHAR(512) NOT NULL,
    description TEXT,
    UNIQUE(domain_code, source_value)
);
CREATE INDEX IF NOT EXISTS idx_semantic_value_mappings_domain ON semantic_value_mappings(domain_code);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_domain(row: dict) -> BusinessDomain:
    return BusinessDomain(
        domain_code=row["domain_code"],
        name=row["name"],
        description=row.get("description"),
        sort_order=row.get("sort_order", 0),
        created_at=row.get("created_at", _now()),
        updated_at=row.get("updated_at", _now()),
    )


def _row_to_object(row: dict) -> BusinessObject:
    relations_raw = row.get("relations", [])
    if isinstance(relations_raw, str):
        relations_raw = json.loads(relations_raw)
    relations = [ObjectRelation(**r) for r in relations_raw] if relations_raw else []
    return BusinessObject(
        object_code=row["object_code"],
        domain_code=row["domain_code"],
        name=row["name"],
        definition=row.get("definition"),
        identifier=row.get("identifier"),
        source_object=row.get("source_object"),
        source_adapter_port=row.get("source_adapter_port"),
        relations=relations,
        version=row.get("version", "1.0"),
        status=row.get("status", "draft"),
        created_at=row.get("created_at", _now()),
        updated_at=row.get("updated_at", _now()),
    )


def _row_to_metric(row: dict) -> Metric:
    transformation = row.get("transformation")
    if isinstance(transformation, str):
        transformation = json.loads(transformation)
    return Metric(
        metric_code=row["metric_code"],
        object_code=row["object_code"],
        name=row["name"],
        definition=row.get("definition"),
        metric_type=row.get("metric_type", "Atomic"),
        semantic_type=row.get("semantic_type"),
        unit=row.get("unit"),
        required=bool(row.get("required", False)),
        default_value=row.get("default_value"),
        source_object=row.get("source_object"),
        source_field=row.get("source_field"),
        source_adapter_port=row.get("source_adapter_port"),
        transformation=transformation,
        value_domain=row.get("value_domain"),
        importance=row.get("importance", "optional"),
        usage_count=row.get("usage_count", 0),
        quality_score=float(row.get("quality_score", 0.0)),
        version=row.get("version", "1.0"),
        status=row.get("status", "draft"),
        created_at=row.get("created_at", _now()),
        updated_at=row.get("updated_at", _now()),
    )


def _row_to_value_domain(row: dict) -> ValueDomain:
    sv = row.get("standard_values")
    if isinstance(sv, str):
        import json
        sv = json.loads(sv)
    return ValueDomain(
        domain_code=row["domain_code"],
        name=row["name"],
        description=row.get("description"),
        standard_values=list(sv) if sv else [],
        created_at=row.get("created_at", _now()),
    )


def _row_to_value_mapping(row: dict) -> ValueDomainMapping:
    return ValueDomainMapping(
        id=row.get("id"),
        domain_code=row["domain_code"],
        source_value=row["source_value"],
        standard_value=row["standard_value"],
        description=row.get("description"),
    )


class PostgresRegistryStore:
    """PostgreSQL-backed implementation of RegistryStore Protocol."""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            self._ensure_schema()
            self._seed_if_empty()
            logger.info("PostgresRegistryStore: PostgreSQL 初始化完成")
        return self._client

    def _ensure_schema(self) -> None:
        try:
            # 清理残留的 orphan 复合类型（表不存在但类型存在 = WSL 部分创建残留）
            for tbl in ["semantic_value_mappings", "semantic_metrics", "semantic_objects",
                         "semantic_value_domains", "semantic_domains"]:
                try:
                    exists = self._client.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_tables WHERE tablename = %s) as e",
                        (tbl,),
                    )
                    if not exists[0]["e"]:
                        self._client.execute(f"DROP TYPE IF EXISTS {tbl} CASCADE")
                except Exception:
                    pass
            self._client.execute(_SCHEMA)
            # 兼容已存在的数据库：补加 standard_values 列
            self._client.execute(
                "ALTER TABLE semantic_value_domains ADD COLUMN IF NOT EXISTS standard_values JSONB DEFAULT '[]'::jsonb"
            )
            logger.info("PostgresRegistryStore: standard_values 列已确认存在")
            logger.debug("PostgresRegistryStore: 表结构已确认")
        except Exception as e:
            logger.error("PostgresRegistryStore: 建表失败 — %s", e)
            raise

    def _seed_if_empty(self) -> None:
        """如果 domains 表为空，执行种子数据初始化。"""
        rows = self._client.execute("SELECT COUNT(*) as cnt FROM semantic_domains")
        if rows and rows[0]["cnt"] > 0:
            return
        logger.info("PostgresRegistryStore: 首次运行，执行种子数据...")
        from src.semantic_layer.seed import seed_settlement_domain
        seed_settlement_domain(self)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ═══════════════════════════════════════════════════════════════
    # Domain
    # ═══════════════════════════════════════════════════════════════

    def save_domain(self, domain: BusinessDomain) -> None:
        client = self._get_client()
        now = _now()
        domain.updated_at = now
        client.execute(
            """INSERT INTO semantic_domains
               (domain_code, name, description, sort_order, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (domain_code) DO UPDATE SET
                   name = EXCLUDED.name,
                   description = EXCLUDED.description,
                   sort_order = EXCLUDED.sort_order,
                   updated_at = EXCLUDED.updated_at""",
            (domain.domain_code, domain.name, domain.description,
             domain.sort_order, domain.created_at, domain.updated_at),
        )

    def get_domain(self, domain_code: str) -> Optional[BusinessDomain]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM semantic_domains WHERE domain_code = %s", (domain_code,)
        )
        return _row_to_domain(rows[0]) if rows else None

    def list_domains(self) -> list[BusinessDomain]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM semantic_domains ORDER BY sort_order, domain_code"
        )
        return [_row_to_domain(r) for r in rows]

    def delete_domain(self, domain_code: str) -> None:
        client = self._get_client()
        client.execute(
            "DELETE FROM semantic_domains WHERE domain_code = %s", (domain_code,)
        )

    # ═══════════════════════════════════════════════════════════════
    # Object
    # ═══════════════════════════════════════════════════════════════

    def save_object(self, obj: BusinessObject) -> None:
        client = self._get_client()
        now = _now()
        obj.updated_at = now
        relations_json = json.dumps(
            [r.model_dump() for r in obj.relations], ensure_ascii=False
        )
        client.execute(
            """INSERT INTO semantic_objects
               (object_code, domain_code, name, definition, identifier,
                source_object, source_adapter_port, relations, version, status,
                created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (object_code) DO UPDATE SET
                   domain_code = EXCLUDED.domain_code,
                   name = EXCLUDED.name,
                   definition = EXCLUDED.definition,
                   identifier = EXCLUDED.identifier,
                   source_object = EXCLUDED.source_object,
                   source_adapter_port = EXCLUDED.source_adapter_port,
                   relations = EXCLUDED.relations,
                   version = EXCLUDED.version,
                   status = EXCLUDED.status,
                   updated_at = EXCLUDED.updated_at""",
            (obj.object_code, obj.domain_code, obj.name, obj.definition,
             obj.identifier, obj.source_object, obj.source_adapter_port,
             relations_json, obj.version, obj.status,
             obj.created_at, obj.updated_at),
        )

    def get_object(self, object_code: str) -> Optional[BusinessObject]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM semantic_objects WHERE object_code = %s", (object_code,)
        )
        return _row_to_object(rows[0]) if rows else None

    def list_objects(self, domain_code: Optional[str] = None) -> list[BusinessObject]:
        client = self._get_client()
        if domain_code:
            rows = client.execute(
                "SELECT * FROM semantic_objects WHERE domain_code = %s ORDER BY object_code",
                (domain_code,),
            )
        else:
            rows = client.execute(
                "SELECT * FROM semantic_objects ORDER BY object_code"
            )
        return [_row_to_object(r) for r in rows]

    def delete_object(self, object_code: str) -> None:
        client = self._get_client()
        client.execute(
            "DELETE FROM semantic_objects WHERE object_code = %s", (object_code,)
        )

    # ═══════════════════════════════════════════════════════════════
    # Metric
    # ═══════════════════════════════════════════════════════════════

    def save_metric(self, metric: Metric) -> None:
        client = self._get_client()
        now = _now()
        metric.updated_at = now
        transformation_json = (
            json.dumps(metric.transformation, ensure_ascii=False)
            if metric.transformation else None
        )
        client.execute(
            """INSERT INTO semantic_metrics
               (metric_code, object_code, name, definition, metric_type,
                semantic_type, unit, required, default_value,
                source_object, source_field, source_adapter_port,
                transformation, value_domain, importance,
                usage_count, quality_score, version, status,
                created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (metric_code) DO UPDATE SET
                   object_code = EXCLUDED.object_code,
                   name = EXCLUDED.name,
                   definition = EXCLUDED.definition,
                   metric_type = EXCLUDED.metric_type,
                   semantic_type = EXCLUDED.semantic_type,
                   unit = EXCLUDED.unit,
                   required = EXCLUDED.required,
                   default_value = EXCLUDED.default_value,
                   source_object = EXCLUDED.source_object,
                   source_field = EXCLUDED.source_field,
                   source_adapter_port = EXCLUDED.source_adapter_port,
                   transformation = EXCLUDED.transformation,
                   value_domain = EXCLUDED.value_domain,
                   importance = EXCLUDED.importance,
                   usage_count = EXCLUDED.usage_count,
                   quality_score = EXCLUDED.quality_score,
                   version = EXCLUDED.version,
                   status = EXCLUDED.status,
                   updated_at = EXCLUDED.updated_at""",
            (metric.metric_code, metric.object_code, metric.name, metric.definition,
             metric.metric_type, metric.semantic_type, metric.unit, metric.required,
             str(metric.default_value) if metric.default_value is not None else None,
             metric.source_object, metric.source_field, metric.source_adapter_port,
             transformation_json, metric.value_domain, metric.importance,
             metric.usage_count, metric.quality_score, metric.version, metric.status,
             metric.created_at, metric.updated_at),
        )

    def get_metric(self, metric_code: str) -> Optional[Metric]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM semantic_metrics WHERE metric_code = %s", (metric_code,)
        )
        return _row_to_metric(rows[0]) if rows else None

    def list_metrics(self, object_code: Optional[str] = None) -> list[Metric]:
        client = self._get_client()
        if object_code:
            rows = client.execute(
                "SELECT * FROM semantic_metrics WHERE object_code = %s ORDER BY metric_code",
                (object_code,),
            )
        else:
            rows = client.execute(
                "SELECT * FROM semantic_metrics ORDER BY metric_code"
            )
        return [_row_to_metric(r) for r in rows]

    def delete_metric(self, metric_code: str) -> None:
        client = self._get_client()
        client.execute(
            "DELETE FROM semantic_metrics WHERE metric_code = %s", (metric_code,)
        )

    # ═══════════════════════════════════════════════════════════════
    # Value Domain
    # ═══════════════════════════════════════════════════════════════

    def save_value_domain(self, vd: ValueDomain) -> None:
        client = self._get_client()
        import json
        sv_json = json.dumps(vd.standard_values or [], ensure_ascii=False)
        client.execute(
            """INSERT INTO semantic_value_domains
               (domain_code, name, description, standard_values, created_at)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (domain_code) DO UPDATE SET
                   name = EXCLUDED.name,
                   description = EXCLUDED.description,
                   standard_values = EXCLUDED.standard_values""",
            (vd.domain_code, vd.name, vd.description, sv_json, vd.created_at),
        )

    def get_value_domain(self, domain_code: str) -> Optional[ValueDomain]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM semantic_value_domains WHERE domain_code = %s",
            (domain_code,),
        )
        return _row_to_value_domain(rows[0]) if rows else None

    def save_value_mapping(self, vm: ValueDomainMapping) -> None:
        client = self._get_client()
        client.execute(
            """INSERT INTO semantic_value_mappings
               (domain_code, source_value, standard_value, description)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (domain_code, source_value) DO UPDATE SET
                   standard_value = EXCLUDED.standard_value,
                   description = EXCLUDED.description""",
            (vm.domain_code, vm.source_value, vm.standard_value, vm.description),
        )

    def get_value_mappings(self, domain_code: str) -> list[ValueDomainMapping]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM semantic_value_mappings WHERE domain_code = %s ORDER BY id",
            (domain_code,),
        )
        return [_row_to_value_mapping(r) for r in rows]

    def delete_value_mapping(self, domain_code: str, source_value: str) -> None:
        client = self._get_client()
        client.execute(
            "DELETE FROM semantic_value_mappings WHERE domain_code = %s AND source_value = %s",
            (domain_code, source_value),
        )

    def delete_value_domain(self, domain_code: str) -> None:
        client = self._get_client()
        client.execute(
            "DELETE FROM semantic_value_domains WHERE domain_code = %s",
            (domain_code,),
        )
