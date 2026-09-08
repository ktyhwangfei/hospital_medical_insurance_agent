"""数据目录构建器（Issue #38 Slice 2 / 开源对标增强）。

扫描四个来源生成资产快照：
- semantic registry：已发布语义对象版本（最新可查询版本快照）/ 指标 / 数据集
- outpatient 同步状态：门诊 PG 投影数据集的最近批次与质量状态（SLA 溯源）
- skill 注册表 + portal 页面静态清单：消费方
- Milvus：向量集合（政策知识 RAG 资产，第五类 ``vector_collection``）

资产按 ``asset_key`` 幂等 upsert，全量刷新后 prune 失效资产；
列级元数据（``data_catalog_columns``）与血缘边（``data_catalog_lineage_edges``）
随刷新整体重建。样例分布只采集脱敏摘要（行数/质量状态），不出库行级数据。
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from src.data_platform.storage.data_catalog.data_catalog_ports import DataCatalogStorage
from src.domain.data_catalog.models import (
    CatalogAsset,
    CatalogAssetType,
    CatalogColumn,
)

if TYPE_CHECKING:
    from src.data_platform.storage.postgresql.outpatient_store import OutpatientSyncStatus
    from src.semantic_layer.models import BusinessObject, BusinessObjectVersion
    from src.semantic_layer.registry import SemanticRegistry

logger = logging.getLogger(__name__)

# Portal 消费方静态清单（页面级消费，运行时调用追踪不在本期范围）
# business_object 声明该页面真实消费的语义对象编码（与 skill 挂载口径一致），
# 用于血缘推导 semantic_object → consumer；无语义消费的页面不声明。
PORTAL_PAGE_CONSUMERS: list[dict[str, str]] = [
    {
        "route": "/policy-qa",
        "name": "政策问答",
        "description": "结算费用解释主链路，消费门诊语义模型与政策知识",
        # 与 settlement_explain_skill 的挂载对象一致（门诊交易语义对象）
        "business_object": "mzjyxx",
    },
    {
        "route": "/semantic-layer",
        "name": "语义层工作台",
        "description": "语义对象/指标/映射浏览",
    },
    {
        "route": "/qa-history",
        "name": "问答历史",
        "description": "政策问答任务与轨迹档案",
    },
    {
        "route": "/trusted-questions",
        "name": "可信问题库",
        "description": "可信问题审核与同义表达运营（Issue #37）",
    },
]


def _asset_id(asset_key: str) -> str:
    """确定性 asset_id：同一 asset_key 跨刷新稳定。"""
    digest = hashlib.sha256(asset_key.encode("utf-8")).hexdigest()[:12]
    return f"ca_{digest}"


def _column_id(asset_id: str, column_name: str) -> str:
    """确定性 column_id：同一资产同一列跨刷新稳定。"""
    digest = hashlib.sha256(f"{asset_id}:{column_name}".encode("utf-8")).hexdigest()[:12]
    return f"cc_{digest}"


def _milvus_type_name(raw_type: Any) -> str:
    """pymilvus DataType 枚举归一化为可读名（如 FLOAT_VECTOR）。"""
    return getattr(raw_type, "name", str(raw_type))


def build_catalog_columns(
    *,
    versions_by_object: dict[str, "BusinessObjectVersion"],
    collections: list[dict[str, Any]] | None = None,
) -> list[CatalogColumn]:
    """纯函数：发布版本字段 + Milvus 集合 schema → 列快照（可独立单测）。

    - source_table 列来自 ``SemanticField``（field_role/semantic_type/value_domain 同源）；
    - vector_collection 列来自 ``describe_collection`` 的 fields（dynamic key 不出现在
      固定字段列表，故以 ``enable_dynamic_field`` 标记在资产摘要中，见资产构建）。
    """
    columns: list[CatalogColumn] = []
    for version in versions_by_object.values():
        ordinals: dict[str, int] = {}
        for field in version.fields:
            asset_id = _asset_id(f"source_table:{field.dataset_code}")
            ordinal = ordinals.get(field.dataset_code, 0)
            ordinals[field.dataset_code] = ordinal + 1
            columns.append(
                CatalogColumn(
                    column_id=_column_id(asset_id, field.column_name),
                    asset_id=asset_id,
                    column_name=field.column_name,
                    name=field.name,
                    data_type=field.semantic_type,
                    field_role=field.field_role,
                    nullable=field.nullable,
                    value_domain=field.value_domain,
                    ordinal=ordinal,
                )
            )
    for col_info in collections or []:
        asset_id = _asset_id(f"vector_collection:{col_info['name']}")
        for idx, f in enumerate(col_info.get("fields") or []):
            type_name = _milvus_type_name(f.get("type", ""))
            if "VECTOR" in type_name.upper():
                role = "vector"
            elif f.get("is_primary"):
                role = "primary_key"
            else:
                role = "scalar"
            columns.append(
                CatalogColumn(
                    column_id=_column_id(asset_id, f["name"]),
                    asset_id=asset_id,
                    column_name=f["name"],
                    name=str(f.get("description") or ""),
                    data_type=type_name,
                    field_role=role,
                    nullable=bool(f.get("nullable", True)),
                    ordinal=idx,
                )
            )
    return columns


def build_catalog_assets(
    *,
    objects: list["BusinessObject"],
    versions_by_object: dict[str, "BusinessObjectVersion"],
    outpatient_dataset_codes: set[str] | None = None,
    sync_status: "OutpatientSyncStatus | None" = None,
    table_row_counts: dict[str, int] | None = None,
    skills: list[dict[str, Any]] | None = None,
    value_domains: dict[str, list[str]] | None = None,
    collections: list[dict[str, Any]] | None = None,
) -> list[CatalogAsset]:
    """纯函数：扫描结果 → 资产快照列表（可独立单测）。

    ``versions_by_object`` 只放最新可查询已发布版本（与 planner
    ``_published_version`` 口径一致）；门诊同步状态只作用于
    ``outpatient_dataset_codes`` 中的数据集（避免错贴到其他数据源）；
    ``value_domains`` 为值域编码 → 标准值列表，回填 source_table 的 ``value_ranges``。
    """
    assets: list[CatalogAsset] = []
    outpatient_dataset_codes = outpatient_dataset_codes or set()
    table_row_counts = table_row_counts or {}
    value_domains = value_domains or {}

    for obj in objects:
        version = versions_by_object.get(obj.object_code)

        # ── 语义对象 ──
        key = f"semantic_object:{obj.object_code}"
        assets.append(
            CatalogAsset(
                asset_id=_asset_id(key),
                asset_type=CatalogAssetType.SEMANTIC_OBJECT,
                asset_key=key,
                name=obj.name,
                description=obj.definition or "",
                # owner 真实来源：发布人（对象模型本身无 owner 字段）
                owner=(version.published_by or "") if version else "",
                tags=[obj.domain_code] if obj.domain_code else [],
                semantic_object_code=obj.object_code,
                semantic_version=version.version if version else None,
                source_ref={
                    "object_code": obj.object_code,
                    "domain_code": obj.domain_code,
                    "identifier": obj.identifier,
                },
            )
        )

        if version is None:
            continue

        # ── 指标（发布版本快照自带展示与治理字段）──
        for metric in version.metrics:
            key = f"metric:{metric.metric_code}"
            assets.append(
                CatalogAsset(
                    asset_id=_asset_id(key),
                    asset_type=CatalogAssetType.METRIC,
                    asset_key=key,
                    name=metric.name,
                    description=metric.definition or "",
                    owner=metric.owner or "",
                    refresh_freq=metric.refresh_frequency or "",
                    tags=[t for t in [obj.domain_code, metric.metric_type] if t],
                    semantic_object_code=obj.object_code,
                    semantic_version=version.version,
                    source_ref={
                        "object_code": obj.object_code,
                        "metric_type": metric.metric_type,
                        "semantic_type": metric.semantic_type,
                        "unit": metric.unit,
                        "source_object": metric.source_object,
                        "source_field": metric.source_field,
                        "fact_field_code": metric.fact_field_code,
                    },
                )
            )

        # ── 源表 / 投影表 ──
        for dataset in version.datasets:
            key = f"source_table:{dataset.dataset_code}"
            is_outpatient = dataset.dataset_code in outpatient_dataset_codes
            row_count = table_row_counts.get(dataset.dataset_code)
            # 脱敏摘要：仅计数与质量状态，剔除缺省值
            sample_summary = {
                k: v
                for k, v in {
                    "row_count": row_count,
                    "quality_status": (
                        sync_status.quality_status
                        if is_outpatient and sync_status
                        else None
                    ),
                }.items()
                if v is not None
            }
            # 值域回填：该数据集声明了 value_domain 的字段 → 标准值列表
            value_ranges = {
                field.field_code: value_domains[field.value_domain]
                for field in version.fields
                if field.dataset_code == dataset.dataset_code
                and field.value_domain
                and field.value_domain in value_domains
            }
            tags = [t for t in [obj.domain_code] if t]
            if is_outpatient:
                tags.append("门诊同步")
            assets.append(
                CatalogAsset(
                    asset_id=_asset_id(key),
                    asset_type=CatalogAssetType.SOURCE_TABLE,
                    asset_key=key,
                    name=dataset.name,
                    description=f"{dataset.schema_name}.{dataset.table_name}",
                    refresh_freq="5 分钟定时 SQL 同步" if is_outpatient else "",
                    tags=tags,
                    value_ranges=value_ranges,
                    sample_summary=sample_summary,
                    semantic_object_code=obj.object_code,
                    semantic_version=version.version,
                    last_batch_id=(
                        sync_status.last_batch_id if is_outpatient and sync_status else None
                    ),
                    source_ref={
                        "dataset_code": dataset.dataset_code,
                        "datasource_id": dataset.datasource_id,
                        "schema_name": dataset.schema_name,
                        "table_name": dataset.table_name,
                        "outpatient_pg_projection": is_outpatient,
                    },
                )
            )

    # ── 消费方：skill ──
    for skill in skills or []:
        key = f"consumer:skill:{skill['skill_id']}"
        assets.append(
            CatalogAsset(
                asset_id=_asset_id(key),
                asset_type=CatalogAssetType.CONSUMER,
                asset_key=key,
                name=skill.get("skill_name") or skill["skill_id"],
                description=f"skill：{', '.join(skill.get('include_keywords') or [])}",
                tags=["skill"],
                source_ref={
                    "kind": "skill",
                    "skill_id": skill["skill_id"],
                    "business_action": skill.get("business_action"),
                    "business_object": skill.get("business_object"),
                },
            )
        )

    # ── 消费方：portal 页面（静态清单）──
    for page in PORTAL_PAGE_CONSUMERS:
        key = f"consumer:page:{page['route']}"
        assets.append(
            CatalogAsset(
                asset_id=_asset_id(key),
                asset_type=CatalogAssetType.CONSUMER,
                asset_key=key,
                name=page["name"],
                description=page["description"],
                tags=["portal页面"],
                source_ref={
                    "kind": "portal_page",
                    "route": page["route"],
                    # 页面真实消费的语义对象（无则不产生血缘边）
                    "business_object": page.get("business_object"),
                },
            )
        )

    # ── 向量集合（Milvus，政策知识 RAG 资产）──
    for col_info in collections or []:
        key = f"vector_collection:{col_info['name']}"
        sample_summary = {
            k: v
            for k, v in {
                "row_count": col_info.get("row_count"),
                "enable_dynamic_field": col_info.get("enable_dynamic_field"),
            }.items()
            if v is not None
        }
        assets.append(
            CatalogAsset(
                asset_id=_asset_id(key),
                asset_type=CatalogAssetType.VECTOR_COLLECTION,
                asset_key=key,
                name=col_info["name"],
                description=col_info.get("description") or "Milvus 向量集合",
                tags=["政策知识", "向量检索"],
                sample_summary=sample_summary,
                source_ref={"collection_name": col_info["name"]},
            )
        )

    return assets


def _latest_queryable_version(registry: "SemanticRegistry", object_code: str):
    """与 planner._published_version 同口径：最新版本且 datasets/fields/keys 非空。"""
    versions = registry.list_object_versions(object_code)
    if not versions:
        return None
    latest = versions[-1]
    if not latest.datasets or not latest.fields or not latest.keys:
        return None
    return latest


def _scan_milvus_collections() -> list[dict[str, Any]]:
    """扫描 Milvus 集合（名称/描述/行数/schema 字段）；连接失败抛异常由调用方降级。"""
    from pymilvus import MilvusClient

    from src.config.production import MILVUS_HOST, MILVUS_PORT, MILVUS_TOKEN

    client = MilvusClient(
        uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}",
        token=MILVUS_TOKEN or "",
    )
    collections: list[dict[str, Any]] = []
    for name in client.list_collections() or []:
        desc = client.describe_collection(name)
        stats = client.get_collection_stats(name)
        collections.append(
            {
                "name": name,
                "description": desc.get("description") or "",
                "row_count": int(stats.get("row_count", 0)),
                "enable_dynamic_field": bool(desc.get("enable_dynamic_field", False)),
                "fields": desc.get("fields") or [],
            }
        )
    return collections


def refresh_data_catalog(storage: DataCatalogStorage | None = None) -> dict[str, int]:
    """真实源编排：扫描 registry 发布版本 + 门诊同步状态 + skills + Milvus，刷新目录快照。

    刷新末尾整体重建列快照与血缘边表。单源故障不阻断整体刷新（记日志跳过）。
    返回统计：{"upserted", "pruned", "columns", "edges"}。
    """
    from src.data_platform.storage.data_catalog.data_catalog_factory import (
        get_data_catalog_storage,
    )
    from src.data_platform.storage.postgresql.client import PostgreSQLClient
    from src.data_platform.storage.postgresql.outpatient_store import (
        OutpatientPostgresStore,
    )
    from src.data_platform.storage.postgresql.semantic_registry_store import (
        PostgresRegistryStore,
    )
    from src.semantic_layer.registry import SemanticRegistry
    from src.skill_infra.skill_router import list_skills

    storage = storage or get_data_catalog_storage()

    registry = SemanticRegistry(PostgresRegistryStore())
    objects = registry.list_objects()
    versions_by_object = {
        obj.object_code: v
        for obj in objects
        if (v := _latest_queryable_version(registry, obj.object_code)) is not None
    }

    # 值域码表：发布版本字段引用到的 value_domain → 标准值列表
    value_domains: dict[str, list[str]] = {}
    for version in versions_by_object.values():
        for field in version.fields:
            if not field.value_domain or field.value_domain in value_domains:
                continue
            try:
                domain = registry.get_value_domain(field.value_domain)
            except Exception:
                logger.warning("值域读取跳过: %s", field.value_domain, exc_info=True)
                continue
            if domain is not None:
                value_domains[field.value_domain] = list(domain.standard_values)

    # 门诊同步状态与投影表行数（脱敏摘要：仅计数；只作用于门诊 PG 投影数据集）
    sync_status = None
    outpatient_dataset_codes: set[str] = set()
    table_row_counts: dict[str, int] = {}
    try:
        outpatient_store = OutpatientPostgresStore()
        sync_status = outpatient_store.get_sync_status("bjybdb")
        outpatient_dataset_codes = set(outpatient_store.get_view_columns())
        client = PostgreSQLClient()
        for dataset_code in outpatient_dataset_codes:
            projection_table = f"outpatient_{dataset_code.removeprefix('mz_')}_current"
            try:
                rows = client.execute(
                    f'SELECT COUNT(*) AS c FROM "{projection_table}"'  # noqa: S608
                )
                table_row_counts[dataset_code] = int(rows[0]["c"])
            except Exception:
                logger.warning("行数采集跳过: %s", projection_table)
    except Exception:
        logger.warning("门诊同步状态不可用，跳过批次溯源", exc_info=True)

    skills: list[dict[str, Any]] = []
    try:
        skills = list_skills()
    except Exception:
        logger.warning("skill 注册表不可用，跳过消费方扫描", exc_info=True)

    collections: list[dict[str, Any]] = []
    try:
        collections = _scan_milvus_collections()
    except Exception:
        logger.warning("Milvus 不可用，跳过向量集合扫描", exc_info=True)

    assets = build_catalog_assets(
        objects=objects,
        versions_by_object=versions_by_object,
        outpatient_dataset_codes=outpatient_dataset_codes,
        sync_status=sync_status,
        table_row_counts=table_row_counts,
        skills=skills,
        value_domains=value_domains,
        collections=collections,
    )
    for asset in assets:
        storage.upsert_asset(asset)
    pruned = storage.delete_assets_except([a.asset_key for a in assets])

    # 列快照整体重建（source_table 来自发布版本字段，vector_collection 来自集合 schema）
    columns = build_catalog_columns(
        versions_by_object=versions_by_object, collections=collections
    )
    # 裁剪掉已 prune 资产的列（列按资产快照全量重建，asset_id 必须在册）
    live_ids = {a.asset_id for a in assets}
    columns = [c for c in columns if c.asset_id in live_ids]
    storage.replace_columns(columns)

    # 血缘边推导落表（查询期走索引，不再全量现推）
    from src.runtime.data_catalog.lineage import derive_edges

    edges = derive_edges(assets)
    storage.replace_lineage_edges(edges)

    return {
        "upserted": len(assets),
        "pruned": pruned,
        "columns": len(columns),
        "edges": len(edges),
    }
