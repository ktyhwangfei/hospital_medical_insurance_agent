"""语义层 API 路由 — 指标定义与字典查询（只读）"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/semantic-layer",
    tags=["语义层"],
)

# ── 尝试导入语义层模块，失败时降级为空实现 ──────────────────────────────────
try:
    from src.semantic_layer.registry import get_registry as _get_registry_impl

    def _get_registry():
        return _get_registry_impl()

    _HAS_SEMANTIC_LAYER = True
except ImportError:
    logger.warning("语义层模块 (src.semantic_layer) 未安装，使用空降级实现")

    _HAS_SEMANTIC_LAYER = False

    def _get_registry() -> None:  # type: ignore[misc]
        return None


# ── Indicators ────────────────────────────────────────────────────────────────


@router.get("/indicators")
async def list_indicators() -> dict[str, Any]:
    """获取所有指标定义"""
    if not _HAS_SEMANTIC_LAYER:
        return {
            "indicators": [],
            "total": 0,
            "categories": {},
            "status": "semantic_layer_not_initialized",
        }

    registry = _get_registry()
    if registry is None:
        return {
            "indicators": [],
            "total": 0,
            "categories": {},
            "status": "registry_not_loaded",
        }

    try:
        indicators = registry.list_all()
    except Exception:
        logger.exception("读取指标列表失败")
        return {
            "indicators": [],
            "total": 0,
            "categories": {},
            "status": "read_error",
        }

    result: list[dict[str, Any]] = []
    categories_count: dict[str, int] = {}
    for ind in indicators:
        d = ind.model_dump() if hasattr(ind, "model_dump") else {"id": str(ind)}
        result.append(d)
        cat = d.get("category", "unknown")
        categories_count[cat] = categories_count.get(cat, 0) + 1

    return {"indicators": result, "total": len(result), "categories": categories_count}


@router.get("/indicators/{indicator_id}")
async def get_indicator(indicator_id: str) -> dict[str, Any]:
    """获取单个指标定义"""
    if not _HAS_SEMANTIC_LAYER:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "SEMANTIC_LAYER_UNAVAILABLE",
                "语义层模块未初始化",
                {"indicator_id": indicator_id},
            ),
        )

    registry = _get_registry()
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "REGISTRY_NOT_LOADED",
                "语义层注册表未加载",
                {"indicator_id": indicator_id},
            ),
        )

    try:
        indicator = registry.get(indicator_id)
    except Exception:
        logger.exception("查询指标 %s 失败", indicator_id)
        raise HTTPException(
            status_code=500,
            detail=error_detail(
                "INDICATOR_READ_ERROR", "读取指标定义时出错", {"indicator_id": indicator_id}
            ),
        )

    if indicator is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "INDICATOR_NOT_FOUND",
                "指标不存在",
                {"indicator_id": indicator_id},
            ),
        )

    return indicator.model_dump() if hasattr(indicator, "model_dump") else {"id": str(indicator)}


# ── Dictionaries ──────────────────────────────────────────────────────────────


@router.get("/dictionaries")
async def list_dictionaries() -> dict[str, Any]:
    """获取所有字典分类及条目计数"""
    if not _HAS_SEMANTIC_LAYER:
        return {
            "categories": [],
            "total": 0,
            "status": "semantic_layer_not_initialized",
        }

    registry = _get_registry()
    if registry is None:
        return {
            "categories": [],
            "total": 0,
            "status": "registry_not_loaded",
        }

    try:
        categories = registry.list_dictionary_categories()
    except Exception:
        logger.exception("读取字典分类列表失败")
        return {
            "categories": [],
            "total": 0,
            "status": "read_error",
        }

    result = []
    total_entries = 0
    for cat in categories:
        entry_count = cat.get("entry_count", 0) if isinstance(cat, dict) else 0
        total_entries += entry_count
        result.append(
            {
                "category": cat["category"] if isinstance(cat, dict) else str(cat),
                "entry_count": entry_count,
            }
        )

    return {"categories": result, "total": total_entries}


@router.get("/dictionaries/{category}")
async def get_dictionary_category(category: str) -> dict[str, Any]:
    """获取指定字典分类的条目"""
    if not _HAS_SEMANTIC_LAYER:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "SEMANTIC_LAYER_UNAVAILABLE",
                "语义层模块未初始化",
                {"category": category},
            ),
        )

    registry = _get_registry()
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "REGISTRY_NOT_LOADED",
                "语义层注册表未加载",
                {"category": category},
            ),
        )

    try:
        entries = registry.get_dictionary_entries(category)
    except Exception:
        logger.exception("查询字典分类 %s 失败", category)
        raise HTTPException(
            status_code=500,
            detail=error_detail(
                "DICTIONARY_READ_ERROR",
                "读取字典条目时出错",
                {"category": category},
            ),
        )

    if entries is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "DICTIONARY_CATEGORY_NOT_FOUND",
                "字典分类不存在",
                {"category": category},
            ),
        )

    return {
        "category": category,
        "entries": [e.model_dump() if hasattr(e, "model_dump") else e for e in entries],
        "total": len(entries),
    }


# ── Summary ───────────────────────────────────────────────────────────────────


@router.get("/summary")
async def get_semantic_layer_summary() -> dict[str, Any]:
    """获取语义层概览状态"""
    if not _HAS_SEMANTIC_LAYER:
        return {
            "total_indicators": 0,
            "categories": {},
            "dictionary_count": 0,
            "importer_status": "not_initialized",
            "status": "semantic_layer_not_initialized",
        }

    registry = _get_registry()
    if registry is None:
        return {
            "total_indicators": 0,
            "categories": {},
            "dictionary_count": 0,
            "importer_status": "registry_not_loaded",
            "status": "registry_not_loaded",
        }

    try:
        indicators = registry.list_all()
        categories = registry.list_dictionary_categories()
        importer_status = registry.get_importer_status()
    except Exception:
        logger.exception("读取语义层概览失败")
        return {
            "total_indicators": 0,
            "categories": {},
            "dictionary_count": 0,
            "importer_status": "unknown",
            "status": "read_error",
        }

    categories_count: dict[str, int] = {}
    for ind in indicators:
        d = ind.model_dump() if hasattr(ind, "model_dump") else {}
        cat = d.get("category", "unknown")
        categories_count[cat] = categories_count.get(cat, 0) + 1

    return {
        "total_indicators": len(indicators),
        "categories": categories_count,
        "dictionary_count": len(categories),
        "importer_status": importer_status or "unknown",
        "status": "ready",
    }
