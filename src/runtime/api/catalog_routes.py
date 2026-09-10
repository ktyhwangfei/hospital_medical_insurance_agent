"""数据目录 API 路由 — issue #38（只读，无凭据泄露面）。

GET 端点与 semantic 路由同口径不设鉴权（聚合的是已公开的语义元数据与
批次统计，不含连接串/凭据）；无写端点。
服务通过 Depends(get_catalog_service) 注入——API 测试 override 该依赖。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.runtime.catalog.service import (
    CatalogAssetDetail,
    CatalogAssetNotFoundError,
    CatalogLineage,
    CatalogOverview,
    CatalogSearchResult,
    CatalogService,
    CatalogSlaBoard,
    build_default_catalog_service,
)
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/catalog",
    tags=["data-catalog"],
)

_AssetTypeParam = Literal["dataset", "field", "object", "metric", "consumer"]


@lru_cache(maxsize=1)
def _cached_default_service() -> CatalogService:
    return build_default_catalog_service()


def get_catalog_service() -> CatalogService:
    """默认走生产装配（语义注册表 + PG 只读面）；测试 override 注入内存实现。"""
    return _cached_default_service()


def _not_found(exc: CatalogAssetNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=error_detail("CATALOG_ASSET_NOT_FOUND", str(exc)),
    )


@router.get("/search", response_model=CatalogSearchResult)
def search_assets(
    q: str = Query(..., min_length=1, max_length=128, description="搜索关键词"),
    asset_type: _AssetTypeParam | None = Query(None, description="按资产类型过滤"),
    limit: int = Query(20, ge=1, le=50),
    service: CatalogService = Depends(get_catalog_service),
):
    return service.search(q, asset_type=asset_type, limit=limit)


@router.get("/overview", response_model=CatalogOverview)
def catalog_overview(service: CatalogService = Depends(get_catalog_service)):
    return service.overview()


@router.get("/sla", response_model=CatalogSlaBoard)
def catalog_sla(service: CatalogService = Depends(get_catalog_service)):
    return service.get_sla()


@router.get("/assets/{asset_type}/{asset_id}", response_model=CatalogAssetDetail)
def get_asset(
    asset_type: _AssetTypeParam,
    asset_id: str,
    service: CatalogService = Depends(get_catalog_service),
):
    try:
        return service.get_asset(asset_type, asset_id)
    except CatalogAssetNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/lineage/{asset_type}/{asset_id}", response_model=CatalogLineage)
def get_lineage(
    asset_type: _AssetTypeParam,
    asset_id: str,
    service: CatalogService = Depends(get_catalog_service),
):
    try:
        return service.get_lineage(asset_type, asset_id)
    except CatalogAssetNotFoundError as exc:
        raise _not_found(exc) from exc
