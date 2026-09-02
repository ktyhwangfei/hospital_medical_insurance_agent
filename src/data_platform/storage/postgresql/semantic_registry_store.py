"""PostgreSQL-backed RegistryStore for Semantic Layer persistence.

Replaces InMemoryRegistryStore so domains, objects, metrics, and
value-domain mappings survive server restarts.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from threading import RLock
from typing import Optional

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.semantic_layer.models import (
    BusinessDomain,
    BusinessObject,
    ObjectRelation,
    PreferredRelationPath,
    Metric,
    SemanticDataset,
    DatasetKey,
    SemanticField,
    DatasetRelation,
    DataQualityRule,
    ObjectVersionMetric,
    BusinessObjectVersion,
    ValueDomain,
    ValueDomainMapping,
)

logger = logging.getLogger(__name__)

# ponytail: 全局锁优先保证跨协调器 client swap 正确；吞吐成为瓶颈时再改每 registry 锁。
SEMANTIC_REGISTRY_TRANSACTION_LOCK = RLock()

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
    preferred_relation_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
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
    -- 政策知识管线扩展（语义拉齐）
    metric_kind VARCHAR(32) NOT NULL DEFAULT 'field',
    indexed BOOLEAN NOT NULL DEFAULT FALSE,
    extraction_hint TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    fact_field_code VARCHAR(256),
    aggregation VARCHAR(32),
    expression TEXT,
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    non_additive_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_semantic_metrics_object ON semantic_metrics(object_code);

-- 查询模型元数据（Dataset/Key/Field/Relation/QualityRule 共用受控 JSON 载体）
CREATE TABLE IF NOT EXISTS semantic_query_metadata (
    kind VARCHAR(32) NOT NULL,
    code VARCHAR(256) NOT NULL,
    object_code VARCHAR(64) NOT NULL REFERENCES semantic_objects(object_code) ON DELETE CASCADE,
    payload JSONB NOT NULL,
    PRIMARY KEY (kind, code)
);
CREATE INDEX IF NOT EXISTS idx_semantic_query_metadata_object
    ON semantic_query_metadata(object_code, kind);

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

-- 对象发布版本快照（阶段2）
ALTER TABLE semantic_objects ADD COLUMN IF NOT EXISTS current_version VARCHAR(32);

CREATE TABLE IF NOT EXISTS semantic_object_versions (
    version_id VARCHAR(64) PRIMARY KEY,
    object_code VARCHAR(64) NOT NULL REFERENCES semantic_objects(object_code) ON DELETE CASCADE,
    version VARCHAR(32) NOT NULL,
    snapshot JSONB NOT NULL,
    metrics JSONB NOT NULL DEFAULT '[]'::jsonb,
    query_model JSONB NOT NULL DEFAULT '{}'::jsonb,
    published_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    published_by VARCHAR(128),
    changelog TEXT,
    UNIQUE(object_code, version)
);
CREATE INDEX IF NOT EXISTS idx_semantic_object_versions_object ON semantic_object_versions(object_code);
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
    preferred_raw = row.get("preferred_relation_paths", [])
    if isinstance(preferred_raw, str):
        preferred_raw = json.loads(preferred_raw)
    return BusinessObject(
        object_code=row["object_code"],
        domain_code=row["domain_code"],
        name=row["name"],
        definition=row.get("definition"),
        identifier=row.get("identifier"),
        source_object=row.get("source_object"),
        source_adapter_port=row.get("source_adapter_port"),
        relations=relations,
        preferred_relation_paths=[PreferredRelationPath(**item) for item in (preferred_raw or [])],
        version=row.get("version", "1.0"),
        status=row.get("status", "draft"),
        current_version=row.get("current_version"),
        created_at=row.get("created_at", _now()),
        updated_at=row.get("updated_at", _now()),
    )


def _row_to_metric(row: dict) -> Metric:
    transformation = row.get("transformation")
    if isinstance(transformation, str):
        transformation = json.loads(transformation)
    dependencies = row.get("dependencies") or []
    non_additive = row.get("non_additive_dimensions") or []
    if isinstance(dependencies, str):
        dependencies = json.loads(dependencies)
    if isinstance(non_additive, str):
        non_additive = json.loads(non_additive)
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
        metric_kind=row.get("metric_kind", "field"),
        indexed=bool(row.get("indexed", False)),
        extraction_hint=row.get("extraction_hint"),
        schema_version=int(row.get("schema_version", 1)),
        fact_field_code=row.get("fact_field_code"),
        aggregation=row.get("aggregation"),
        expression=row.get("expression"),
        dependencies=list(dependencies),
        non_additive_dimensions=list(non_additive),
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


def _row_to_object_version(row: dict) -> BusinessObjectVersion:
    snapshot = row.get("snapshot")
    if isinstance(snapshot, str):
        snapshot = json.loads(snapshot)
    metrics_raw = row.get("metrics")
    if isinstance(metrics_raw, str):
        metrics_raw = json.loads(metrics_raw)
    metrics = [ObjectVersionMetric(**m) for m in (metrics_raw or [])]
    query_model = row.get("query_model") or {}
    if isinstance(query_model, str):
        query_model = json.loads(query_model)
    return BusinessObjectVersion(
        version_id=row["version_id"],
        object_code=row["object_code"],
        version=row["version"],
        snapshot=snapshot or {},
        metrics=metrics,
        datasets=[SemanticDataset(**item) for item in query_model.get("datasets", [])],
        keys=[DatasetKey(**item) for item in query_model.get("keys", [])],
        fields=[SemanticField(**item) for item in query_model.get("fields", [])],
        relations=[DatasetRelation(**item) for item in query_model.get("relations", [])],
        quality_rules=[DataQualityRule(**item) for item in query_model.get("quality_rules", [])],
        published_at=row.get("published_at", _now()),
        published_by=row.get("published_by"),
        changelog=row.get("changelog"),
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
            self._ensure_yb_dictionaries()
            logger.info("PostgresRegistryStore: PostgreSQL 初始化完成")
        return self._client

    def _ensure_yb_dictionaries(self) -> None:
        """幂等 ensure：医保字典码→标签映射（FUND_TYPE/YLLB/PERSON_TYPE）。

        upsert 语义，每次进程启动安全重复执行。"""
        try:
            from src.semantic_layer.seed import (
                ensure_outpatient_query_model,
                ensure_yb_dictionary_mappings,
                publish_seed_outpatient_query_object,
            )
            ensure_yb_dictionary_mappings(self)
            from src.semantic_layer.seed import (
                _seed_settlement_query_model,
                ensure_outpatient_query_model,
                publish_seed_outpatient_query_object,
                publish_seed_query_object,
            )
            from src.semantic_layer.registry import SemanticRegistry
            _seed_settlement_query_model(self)
            ensure_outpatient_query_model(self)
            registry = SemanticRegistry(self)
            publish_seed_query_object(registry)
            publish_seed_outpatient_query_object(registry)
        except Exception:
            logger.warning("ensure_yb_dictionary_mappings 失败，跳过", exc_info=True)

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
            # 政策知识管线扩展：为已有 semantic_metrics 表补加 4 列
            self._client.execute(
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS metric_kind VARCHAR(32) NOT NULL DEFAULT 'field'"
            )
            self._client.execute(
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS indexed BOOLEAN NOT NULL DEFAULT FALSE"
            )
            self._client.execute(
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS extraction_hint TEXT"
            )
            self._client.execute(
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1"
            )
            self._client.execute(
                "ALTER TABLE semantic_objects ADD COLUMN IF NOT EXISTS preferred_relation_paths JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
            for statement in [
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS fact_field_code VARCHAR(256)",
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS aggregation VARCHAR(32)",
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS expression TEXT",
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS dependencies JSONB NOT NULL DEFAULT '[]'::jsonb",
                "ALTER TABLE semantic_metrics ADD COLUMN IF NOT EXISTS non_additive_dimensions JSONB NOT NULL DEFAULT '[]'::jsonb",
                "ALTER TABLE semantic_object_versions ADD COLUMN IF NOT EXISTS query_model JSONB NOT NULL DEFAULT '{}'::jsonb",
            ]:
                self._client.execute(statement)
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
        # P8.3：种子后发布 zcgz，解锁提取契约（build_extraction_schema 只收 published）
        from src.semantic_layer.registry import SemanticRegistry
        from src.semantic_layer.seed import (
            publish_seed_outpatient_query_object,
            publish_seed_policy_object,
            publish_seed_query_object,
        )
        registry = SemanticRegistry(self)
        publish_seed_policy_object(registry)
        publish_seed_query_object(registry)
        publish_seed_outpatient_query_object(registry)

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
        preferred_json = json.dumps(
            [item.model_dump() for item in obj.preferred_relation_paths], ensure_ascii=False
        )
        client.execute(
            """INSERT INTO semantic_objects
               (object_code, domain_code, name, definition, identifier,
                source_object, source_adapter_port, relations, preferred_relation_paths,
                version, status,
                current_version, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (object_code) DO UPDATE SET
                   domain_code = EXCLUDED.domain_code,
                   name = EXCLUDED.name,
                   definition = EXCLUDED.definition,
                   identifier = EXCLUDED.identifier,
                   source_object = EXCLUDED.source_object,
                   source_adapter_port = EXCLUDED.source_adapter_port,
                   relations = EXCLUDED.relations,
                   preferred_relation_paths = EXCLUDED.preferred_relation_paths,
                   version = EXCLUDED.version,
                   status = EXCLUDED.status,
                   current_version = EXCLUDED.current_version,
                   updated_at = EXCLUDED.updated_at""",
            (obj.object_code, obj.domain_code, obj.name, obj.definition,
             obj.identifier, obj.source_object, obj.source_adapter_port,
             relations_json, preferred_json, obj.version, obj.status, obj.current_version,
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
        dependencies_json = json.dumps(metric.dependencies, ensure_ascii=False)
        non_additive_json = json.dumps(metric.non_additive_dimensions, ensure_ascii=False)
        client.execute(
            """INSERT INTO semantic_metrics
               (metric_code, object_code, name, definition, metric_type,
                semantic_type, unit, required, default_value,
                source_object, source_field, source_adapter_port,
                transformation, value_domain, importance,
                usage_count, quality_score, version, status,
                metric_kind, indexed, extraction_hint, schema_version,
                fact_field_code, aggregation, expression, dependencies, non_additive_dimensions,
                created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (metric_code) DO UPDATE SET
                   object_code = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.object_code ELSE semantic_metrics.object_code END,
                   name = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.name ELSE semantic_metrics.name END,
                   definition = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.definition ELSE semantic_metrics.definition END,
                   metric_type = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.metric_type ELSE semantic_metrics.metric_type END,
                   semantic_type = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.semantic_type ELSE semantic_metrics.semantic_type END,
                   unit = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.unit ELSE semantic_metrics.unit END,
                   required = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.required ELSE semantic_metrics.required END,
                   default_value = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.default_value ELSE semantic_metrics.default_value END,
                   source_object = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.source_object ELSE semantic_metrics.source_object END,
                   source_field = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.source_field ELSE semantic_metrics.source_field END,
                   source_adapter_port = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.source_adapter_port ELSE semantic_metrics.source_adapter_port END,
                   transformation = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.transformation ELSE semantic_metrics.transformation END,
                   value_domain = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.value_domain ELSE semantic_metrics.value_domain END,
                   importance = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.importance ELSE semantic_metrics.importance END,
                   usage_count = EXCLUDED.usage_count,
                   quality_score = EXCLUDED.quality_score,
                   version = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.version ELSE semantic_metrics.version END,
                   status = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.status ELSE semantic_metrics.status END,
                   metric_kind = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.metric_kind ELSE semantic_metrics.metric_kind END,
                   indexed = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.indexed ELSE semantic_metrics.indexed END,
                   extraction_hint = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.extraction_hint ELSE semantic_metrics.extraction_hint END,
                   fact_field_code = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.fact_field_code ELSE semantic_metrics.fact_field_code END,
                   aggregation = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.aggregation ELSE semantic_metrics.aggregation END,
                   expression = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.expression ELSE semantic_metrics.expression END,
                   dependencies = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.dependencies ELSE semantic_metrics.dependencies END,
                   non_additive_dimensions = CASE WHEN EXCLUDED.schema_version >= semantic_metrics.schema_version THEN EXCLUDED.non_additive_dimensions ELSE semantic_metrics.non_additive_dimensions END,
                   schema_version = GREATEST(semantic_metrics.schema_version, EXCLUDED.schema_version),
                   updated_at = EXCLUDED.updated_at""",
            (metric.metric_code, metric.object_code, metric.name, metric.definition,
             metric.metric_type, metric.semantic_type, metric.unit, metric.required,
             str(metric.default_value) if metric.default_value is not None else None,
             metric.source_object, metric.source_field, metric.source_adapter_port,
             transformation_json, metric.value_domain, metric.importance,
             metric.usage_count, metric.quality_score, metric.version, metric.status,
             metric.metric_kind, metric.indexed, metric.extraction_hint, metric.schema_version,
             metric.fact_field_code, metric.aggregation, metric.expression,
             dependencies_json, non_additive_json,
             metric.created_at, metric.updated_at),
        )

    def increment_metric_usage(self, metric_code: str, delta: int = 1) -> int:
        rows = self._get_client().execute(
            """UPDATE semantic_metrics
               SET usage_count = usage_count + %s, updated_at = CURRENT_TIMESTAMP
               WHERE metric_code = %s
               RETURNING usage_count""",
            (delta, metric_code),
        )
        if not rows:
            raise ValueError(f"指标 '{metric_code}' 不存在")
        return int(rows[0]["usage_count"])

    def update_metric_quality(self, metric_code: str, score: float) -> None:
        self._get_client().execute(
            """UPDATE semantic_metrics
               SET quality_score = %s, updated_at = CURRENT_TIMESTAMP
               WHERE metric_code = %s""",
            (score, metric_code),
        )

    def get_metric(self, metric_code: str) -> Optional[Metric]:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM semantic_metrics WHERE metric_code = %s", (metric_code,)
        )
        return _row_to_metric(rows[0]) if rows else None

    def lock_metric(self, metric_code: str) -> None:
        """在当前事务内锁定指标，防止 schema_version 并发丢失更新。"""
        self._get_client().execute(
            "SELECT metric_code FROM semantic_metrics WHERE metric_code = %s FOR UPDATE",
            (metric_code,),
        )

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
    # Query model metadata
    # ═══════════════════════════════════════════════════════════════

    _QUERY_MODEL_TYPES = {
        "dataset": SemanticDataset,
        "key": DatasetKey,
        "field": SemanticField,
        "relation": DatasetRelation,
        "quality_rule": DataQualityRule,
    }

    def _save_query_item(self, kind: str, code: str, object_code: str, item) -> None:
        self._get_client().execute(
            """INSERT INTO semantic_query_metadata(kind, code, object_code, payload)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT(kind, code) DO UPDATE SET
                   object_code = EXCLUDED.object_code,
                   payload = EXCLUDED.payload""",
            (kind, code, object_code, json.dumps(item.model_dump(mode="json"), ensure_ascii=False)),
        )

    def _get_query_item(self, kind: str, code: str):
        rows = self._get_client().execute(
            "SELECT payload FROM semantic_query_metadata WHERE kind = %s AND code = %s",
            (kind, code),
        )
        if not rows:
            return None
        payload = rows[0]["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return self._QUERY_MODEL_TYPES[kind](**payload)

    def _list_query_items(self, kind: str, object_code: Optional[str] = None):
        if object_code:
            rows = self._get_client().execute(
                "SELECT payload FROM semantic_query_metadata WHERE kind = %s AND object_code = %s ORDER BY code",
                (kind, object_code),
            )
        else:
            rows = self._get_client().execute(
                "SELECT payload FROM semantic_query_metadata WHERE kind = %s ORDER BY code",
                (kind,),
            )
        result = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            result.append(self._QUERY_MODEL_TYPES[kind](**payload))
        return result

    def _delete_query_item(self, kind: str, code: str) -> None:
        self._get_client().execute(
            "DELETE FROM semantic_query_metadata WHERE kind = %s AND code = %s",
            (kind, code),
        )

    def save_dataset(self, dataset: SemanticDataset) -> None:
        self._save_query_item("dataset", dataset.dataset_code, dataset.object_code, dataset)

    def get_dataset(self, dataset_code: str) -> Optional[SemanticDataset]:
        return self._get_query_item("dataset", dataset_code)

    def list_datasets(self, object_code: Optional[str] = None) -> list[SemanticDataset]:
        return self._list_query_items("dataset", object_code)

    def delete_dataset(self, dataset_code: str) -> None:
        self._delete_query_item("dataset", dataset_code)

    def _dataset_object_code(self, dataset_code: str) -> str:
        dataset = self.get_dataset(dataset_code)
        if dataset is None:
            raise ValueError(f"dataset '{dataset_code}' 不存在")
        return dataset.object_code

    def save_dataset_key(self, key: DatasetKey) -> None:
        self._save_query_item("key", key.key_code, self._dataset_object_code(key.dataset_code), key)

    def get_dataset_key(self, key_code: str) -> Optional[DatasetKey]:
        return self._get_query_item("key", key_code)

    def list_dataset_keys(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[DatasetKey]:
        values = self._list_query_items("key", object_code)
        return [item for item in values if item.dataset_code == dataset_code] if dataset_code else values

    def delete_dataset_key(self, key_code: str) -> None:
        self._delete_query_item("key", key_code)

    def save_field(self, field: SemanticField) -> None:
        self._save_query_item("field", field.field_code, self._dataset_object_code(field.dataset_code), field)

    def get_field(self, field_code: str) -> Optional[SemanticField]:
        return self._get_query_item("field", field_code)

    def list_fields(self, dataset_code: Optional[str] = None, object_code: Optional[str] = None) -> list[SemanticField]:
        values = self._list_query_items("field", object_code)
        return [item for item in values if item.dataset_code == dataset_code] if dataset_code else values

    def delete_field(self, field_code: str) -> None:
        self._delete_query_item("field", field_code)

    def save_dataset_relation(self, relation: DatasetRelation) -> None:
        self._save_query_item("relation", relation.relation_code, relation.object_code, relation)

    def get_dataset_relation(self, relation_code: str) -> Optional[DatasetRelation]:
        return self._get_query_item("relation", relation_code)

    def list_dataset_relations(self, object_code: Optional[str] = None) -> list[DatasetRelation]:
        return self._list_query_items("relation", object_code)

    def delete_dataset_relation(self, relation_code: str) -> None:
        self._delete_query_item("relation", relation_code)

    def save_quality_rule(self, rule: DataQualityRule) -> None:
        self._save_query_item("quality_rule", rule.rule_code, rule.object_code, rule)

    def get_quality_rule(self, rule_code: str) -> Optional[DataQualityRule]:
        return self._get_query_item("quality_rule", rule_code)

    def list_quality_rules(self, object_code: Optional[str] = None) -> list[DataQualityRule]:
        return self._list_query_items("quality_rule", object_code)

    def delete_quality_rule(self, rule_code: str) -> None:
        self._delete_query_item("quality_rule", rule_code)

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

    def list_value_domains_with_counts(self) -> list[tuple[ValueDomain, int]]:
        """一条 JOIN 查询返回所有值域及其映射数，替代逐条查询的 N+1。"""
        client = self._get_client()
        rows = client.execute(
            """SELECT vd.*, COALESCE(vm.cnt, 0) AS mapping_count
               FROM semantic_value_domains vd
               LEFT JOIN (
                   SELECT domain_code, COUNT(*) AS cnt
                   FROM semantic_value_mappings GROUP BY domain_code
               ) vm ON vm.domain_code = vd.domain_code
               ORDER BY vd.domain_code"""
        )
        return [(_row_to_value_domain(r), int(r.get("mapping_count", 0))) for r in rows]

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

    # ═══════════════════════════════════════════════════════════════
    # Object Version Snapshot
    # ═══════════════════════════════════════════════════════════════

    def save_object_version(self, version: BusinessObjectVersion) -> None:
        client = self._get_client()
        snapshot_json = json.dumps(version.snapshot, ensure_ascii=False)
        metrics_json = json.dumps(
            [m.model_dump() for m in version.metrics], ensure_ascii=False)
        query_model_json = json.dumps({
            "datasets": [item.model_dump(mode="json") for item in version.datasets],
            "keys": [item.model_dump(mode="json") for item in version.keys],
            "fields": [item.model_dump(mode="json") for item in version.fields],
            "relations": [item.model_dump(mode="json") for item in version.relations],
            "quality_rules": [item.model_dump(mode="json") for item in version.quality_rules],
        }, ensure_ascii=False)
        client.execute(
            """INSERT INTO semantic_object_versions
               (version_id, object_code, version, snapshot, metrics, query_model,
                published_at, published_by, changelog)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (version.version_id, version.object_code, version.version,
             snapshot_json, metrics_json, query_model_json, version.published_at,
             version.published_by, version.changelog),
        )

    def get_object_version(self, object_code: str, version: str) -> Optional[BusinessObjectVersion]:
        client = self._get_client()
        rows = client.execute(
            """SELECT * FROM semantic_object_versions
               WHERE object_code = %s AND version = %s""",
            (object_code, version),
        )
        return _row_to_object_version(rows[0]) if rows else None

    def list_object_versions(self, object_code: str) -> list[BusinessObjectVersion]:
        client = self._get_client()
        rows = client.execute(
            """SELECT * FROM semantic_object_versions
               WHERE object_code = %s ORDER BY (version::int)""",
            (object_code,),
        )
        return [_row_to_object_version(r) for r in rows]
