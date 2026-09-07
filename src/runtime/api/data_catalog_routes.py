"""数据目录 API（Issue #38 Slice 3）。

前缀：/api/v1/medical-insurance-ai-agent/data-catalog

- ``GET /assets``：统一资产搜索（类型过滤 + 关键字 + 分页）
- ``GET /assets/{asset_id}``：资产详情（含溯源字段）
- ``POST /refresh``：触发目录构建器全量刷新（治理支撑操作）
- ``GET /sla``：SLA 看板（门诊同步 P95/质量状态 + 质量门禁 golden_score）

血缘端点（``/assets/{asset_id}/lineage``）属 Slice 4 动态推导，本文件不含。
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.data_platform.storage.data_catalog.data_catalog_ports import (
    DataCatalogStorage,
)
from src.domain.data_catalog.models import CatalogAsset, CatalogAssetType
from src.runtime.data_catalog.lineage import AssetLineage, derive_lineage
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data-catalog"])


def get_data_catalog_store() -> DataCatalogStorage:
    from src.data_platform.storage.data_catalog.data_catalog_factory import (
        get_data_catalog_storage,
    )

    return get_data_catalog_storage()


DataCatalogStoreDependency = Annotated[
    DataCatalogStorage, Depends(get_data_catalog_store)
]


# ── 响应模型 ────────────────────────────────────────────────────


class CatalogAssetListResponse(BaseModel):
    items: list[CatalogAsset]
    limit: int
    offset: int


class CatalogRefreshResponse(BaseModel):
    upserted: int
    pruned: int


class OutpatientSyncSla(BaseModel):
    """门诊同步 SLA（溯源 OutpatientPostgresStore.get_sync_status）。"""

    source_id: str
    last_batch_id: str | None = None
    last_published_at: str | None = None
    p95_latency_seconds: float | None = None
    non_empty_sample_count: int = 0
    quality_status: str = ""


class QualityGateScore(BaseModel):
    """政策管线质量门禁得分（溯源 policy_schema_update_task.golden_score）。"""

    task_id: str
    metric_code: str
    status: str
    golden_score: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class DataCatalogSlaResponse(BaseModel):
    outpatient_sync: OutpatientSyncSla | None = None
    quality_gates: list[QualityGateScore] = Field(default_factory=list)


# ── 资产查询端点 ────────────────────────────────────────────────


@router.get("/data-catalog/assets", response_model=CatalogAssetListResponse)
def list_catalog_assets(
    store: DataCatalogStoreDependency,
    asset_type: CatalogAssetType | None = Query(default=None),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> CatalogAssetListResponse:
    """统一资产搜索：跨源表/语义对象/指标/消费方四类资产。"""
    items = store.list_assets(
        asset_type=asset_type, keyword=keyword, limit=limit, offset=offset
    )
    return CatalogAssetListResponse(items=items, limit=limit, offset=offset)


@router.get("/data-catalog/assets/{asset_id}", response_model=CatalogAsset)
def get_catalog_asset(
    asset_id: str,
    store: DataCatalogStoreDependency,
) -> CatalogAsset:
    """资产详情：含 owner/refresh_freq/semantic_version/last_batch_id/脱敏摘要。"""
    asset = store.get_asset(asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("CATALOG_ASSET_NOT_FOUND", f"资产不存在: {asset_id}"),
        )
    return asset


# ── 血缘端点（Slice 4 动态推导）────────────────────────────────


@router.get("/data-catalog/assets/{asset_id}/lineage", response_model=AssetLineage)
def get_catalog_asset_lineage(
    asset_id: str,
    store: DataCatalogStoreDependency,
) -> AssetLineage:
    """血缘子图：以资产为根双向遍历（源表→指标→语义对象→消费方）。

    零新表：边从目录快照字段动态推导，与资产同刷同新；
    节点携带 semantic_version/last_batch_id 供溯源展示。
    """
    lineage = derive_lineage(store, asset_id)
    if lineage is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("CATALOG_ASSET_NOT_FOUND", f"资产不存在: {asset_id}"),
        )
    return lineage


# ── 目录刷新（治理支撑操作）────────────────────────────────────


@router.post("/data-catalog/refresh", response_model=CatalogRefreshResponse)
def refresh_catalog(store: DataCatalogStoreDependency) -> CatalogRefreshResponse:
    """触发目录构建器全量刷新：registry 发布版本 + 门诊同步状态 + skill 注册表。

    单源故障不阻断（构建器内部记日志跳过），返回 upsert/prune 统计。
    """
    from src.runtime.data_catalog.builder import refresh_data_catalog

    stats = refresh_data_catalog(store)
    return CatalogRefreshResponse(**stats)


# ── SLA 看板 ────────────────────────────────────────────────────


@router.get("/data-catalog/sla", response_model=DataCatalogSlaResponse)
def get_catalog_sla() -> DataCatalogSlaResponse:
    """SLA 看板：门诊同步 P95/质量状态 + 最近质量门禁得分。

    两个数据源各自独立降级：门诊同步不可用时 outpatient_sync=None，
    质量门禁表不可用时 quality_gates 为空列表。
    """
    response = DataCatalogSlaResponse()

    try:
        from src.data_platform.storage.postgresql.outpatient_store import (
            OutpatientPostgresStore,
        )

        sync = OutpatientPostgresStore().get_sync_status("bjybdb")
        response.outpatient_sync = OutpatientSyncSla(
            source_id=sync.source_id,
            last_batch_id=sync.last_batch_id,
            last_published_at=(
                sync.last_published_at.isoformat() if sync.last_published_at else None
            ),
            p95_latency_seconds=sync.p95_latency_seconds,
            non_empty_sample_count=sync.non_empty_sample_count,
            quality_status=sync.quality_status or "",
        )
    except Exception:
        logger.warning("SLA 看板：门诊同步状态不可用", exc_info=True)

    try:
        from src.data_platform.storage.postgresql.policy_meta_store import (
            PolicyMetaStore,
        )

        tasks = PolicyMetaStore().list_tasks(limit=20)
        response.quality_gates = [
            QualityGateScore(
                task_id=t["task_id"],
                metric_code=t["metric_code"],
                status=t.get("status") or "",
                golden_score=t.get("golden_score") or {},
                created_at=(
                    t["created_at"].isoformat() if t.get("created_at") else None
                ),
            )
            for t in tasks
        ]
    except Exception:
        logger.warning("SLA 看板：质量门禁任务不可用", exc_info=True)

    return response
