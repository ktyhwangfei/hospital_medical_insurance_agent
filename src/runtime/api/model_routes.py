"""
模型服务管理路由
涵盖模型配置、路由规则、退避链与参数、Provider 管理的 CRUD 接口（共 17 个端点）

分组:
  A. 模型配置管理 (2 端点) — GET/PUT /model-config
  B. 模型路由管理 (9 端点) — /model-routes/*
  C. Provider 管理 (6 端点) — /model-providers/*
"""

import logging
import time
import uuid
import urllib.request
import urllib.error

from fastapi import APIRouter, HTTPException

from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE
from src.config.model_service import ModelServiceConfig
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter()

# =============================================================================
# In-memory 存储（模块级变量）
# 没有接入持久化存储前，使用 dict 维护运行时状态
# =============================================================================

# ── 模型配置 ──────────────────────────────────────────────────────────────────
_model_config: dict = {
    "base_url": "https://api.siliconflow.cn/v1",
    "timeout": 30,
    "max_retries": 3,
    "default_model": "deepseek-ai/DeepSeek-V3.2",
}
_model_api_key: str = ""

# ── 路由规则 ──────────────────────────────────────────────────────────────────
_routes_store: dict[str, dict] = {}
_next_route_id: int = 1

# ── 退避链（初始值来自 config） ──────────────────────────────────────────────
_fallback_chains: dict[str, list[str]] = {}

# ── 模型参数（初始值来自 config） ────────────────────────────────────────────
_model_params_store: dict[str, dict] = {}

# ── Provider 注册表 ──────────────────────────────────────────────────────────
_providers_store: dict[str, dict] = {}


def _init_config() -> None:
    """从 ModelServiceConfig + ROUTING_TABLE / FALLBACK_CHAINS / MODEL_PARAMS 加载初始值"""
    global _model_config, _model_api_key, _fallback_chains, _model_params_store
    try:
        cfg = ModelServiceConfig()
        default_model = "deepseek-ai/DeepSeek-V3.2"
        for (_, mtype), mname in ROUTING_TABLE.items():
            if mtype == "llm" or (isinstance(mtype, str) and mtype == "llm"):
                default_model = mname
                break
            if hasattr(mtype, "value") and mtype.value == "llm":
                default_model = mname
                break
        _model_config = {
            "base_url": cfg.base_url,
            "timeout": cfg.default_timeout,
            "max_retries": cfg.max_retries,
            "default_model": default_model,
        }
        _model_api_key = cfg.api_key
    except Exception as exc:
        logger.warning("模型配置初始化失败，使用默认值: %s", exc)

    _fallback_chains = {k: list(v) for k, v in FALLBACK_CHAINS.items()}
    _model_params_store = {k: dict(v) for k, v in MODEL_PARAMS.items()}


_init_config()


def _mask_api_key(api_key: str) -> str:
    """脱敏 API Key：只保留首尾各 4 位"""
    if not api_key or len(api_key) <= 8:
        return "****"
    return api_key[:4] + "****" + api_key[-4:]


# =============================================================================
# Group A: 模型配置管理 (2 endpoints)
# =============================================================================


@router.get("/model-config")
def get_model_config() -> dict:
    """获取当前模型服务配置（不暴露 api_key）"""
    return dict(_model_config)


@router.put("/model-config")
def update_model_config(body: dict) -> dict:
    """更新模型服务配置

    接受可选字段: base_url, timeout, max_retries, default_model, api_key
    api_key 在请求中接收，但响应中不返回明文。
    """
    global _model_api_key
    allowed_fields = {"base_url", "timeout", "max_retries", "default_model", "api_key"}
    for key, value in body.items():
        if key not in allowed_fields:
            continue
        if key == "api_key":
            _model_api_key = str(value)
        else:
            _model_config[key] = value
    return dict(_model_config)


# =============================================================================
# Group B: 模型路由管理 (9 endpoints)
# =============================================================================
#
# 注意: 静态子路径（/fallbacks/, /params/）必须在前，参数化 /{route_id} 在后，
# 避免 FastAPI 路径冲突。
#


@router.get("/model-routes")
def list_model_routes() -> dict:
    """列出所有路由规则"""
    items = sorted(_routes_store.values(), key=lambda r: r.get("priority", 0))
    return {"items": items, "total": len(items)}


@router.post("/model-routes")
def create_model_route(body: dict) -> dict:
    """新增路由规则

    请求体: { scene, model_type, model_name, priority?, enabled? }
    """
    global _next_route_id
    route_id = str(_next_route_id)
    _next_route_id += 1
    route = {
        "route_id": route_id,
        "scene": body.get("scene", ""),
        "model_type": body.get("model_type", ""),
        "model_name": body.get("model_name", ""),
        "priority": body.get("priority", 0),
        "enabled": body.get("enabled", True),
    }
    _routes_store[route_id] = route
    return dict(route)


# -- 退避链子路径（必须在 {route_id} 之前注册） --


@router.get("/model-routes/fallbacks/{model_name}")
def get_model_fallbacks(model_name: str) -> dict:
    """查询指定模型的退避链"""
    chain = _fallback_chains.get(model_name, [])
    return {"model_name": model_name, "fallbacks": list(chain)}


@router.put("/model-routes/fallbacks/{model_name}")
def update_model_fallbacks(model_name: str, body: dict) -> dict:
    """更新退避链

    请求体: { fallbacks: [string] }
    """
    fallbacks = body.get("fallbacks", [])
    _fallback_chains[model_name] = list(fallbacks)
    return {"model_name": model_name, "fallbacks": list(fallbacks)}


# -- 模型参数子路径（必须在 {route_id} 之前注册） --


@router.get("/model-routes/params/{model_name}")
def get_model_params_route(model_name: str) -> dict:
    """查询模型参数"""
    params = _model_params_store.get(
        model_name, {"temperature": 0.7, "max_tokens": 2048}
    )
    return {"model_name": model_name, **params}


@router.put("/model-routes/params/{model_name}")
def update_model_params_route(model_name: str, body: dict) -> dict:
    """更新模型参数

    请求体: { temperature?, max_tokens?, top_p? }
    """
    allowed_params = {"temperature", "max_tokens", "top_p"}
    existing = dict(
        _model_params_store.get(model_name, {"temperature": 0.7, "max_tokens": 2048})
    )
    for key, value in body.items():
        if key in allowed_params:
            existing[key] = value
    _model_params_store[model_name] = existing
    return {"model_name": model_name, **existing}


# -- 参数化路由（有 route_id 路径参数，定义在静态路径之后） --


@router.get("/model-routes/{route_id}")
def get_model_route(route_id: str) -> dict:
    """获取指定路由规则详情"""
    route = _routes_store.get(route_id)
    if route is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "ROUTE_NOT_FOUND",
                "路由规则不存在",
                {"event_type": "route_not_found"},
            ),
        )
    return dict(route)


@router.put("/model-routes/{route_id}")
def update_model_route(route_id: str, body: dict) -> dict:
    """更新路由规则

    请求体: { scene?, model_type?, model_name?, priority?, enabled? }
    """
    route = _routes_store.get(route_id)
    if route is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "ROUTE_NOT_FOUND",
                "路由规则不存在",
                {"event_type": "route_not_found"},
            ),
        )
    allowed_fields = {"scene", "model_type", "model_name", "priority", "enabled"}
    for key, value in body.items():
        if key in allowed_fields:
            route[key] = value
    _routes_store[route_id] = route
    return dict(route)


@router.delete("/model-routes/{route_id}")
def delete_model_route(route_id: str) -> dict:
    """删除路由规则"""
    if route_id not in _routes_store:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "ROUTE_NOT_FOUND",
                "路由规则不存在",
                {"event_type": "route_not_found"},
            ),
        )
    del _routes_store[route_id]
    return {"deleted": True}


# =============================================================================
# Group C: Provider 管理 (6 endpoints)
# =============================================================================


@router.get("/model-providers")
def list_model_providers() -> dict:
    """列出所有已注册的 Provider（不暴露 api_key）"""
    items = []
    for p in _providers_store.values():
        item = dict(p)
        if item.get("api_key"):
            item["api_key"] = _mask_api_key(item["api_key"])
        items.append(item)
    return {"items": items, "total": len(items)}


@router.post("/model-providers")
def create_model_provider(body: dict) -> dict:
    """注册新的 Provider

    请求体: { provider_id?, provider_type, base_url, api_key, default_headers?, enabled? }
    默认 provider_id 自动生成 UUID。
    """
    provider_id = body.get("provider_id", str(uuid.uuid4()))
    if provider_id in _providers_store:
        raise HTTPException(
            status_code=409,
            detail=error_detail(
                "PROVIDER_EXISTS",
                f"Provider {provider_id} 已存在",
                {"event_type": "provider_exists"},
            ),
        )
    provider = {
        "provider_id": provider_id,
        "provider_type": body.get("provider_type", "openai_compatible"),
        "base_url": body.get("base_url", ""),
        "api_key": body.get("api_key", ""),
        "default_headers": body.get("default_headers", {}),
        "enabled": body.get("enabled", True),
    }
    _providers_store[provider_id] = provider
    resp = dict(provider)
    if resp.get("api_key"):
        resp["api_key"] = _mask_api_key(resp["api_key"])
    return resp


@router.get("/model-providers/{provider_id}")
def get_model_provider(provider_id: str) -> dict:
    """查看 Provider 详情（不暴露 api_key）"""
    provider = _providers_store.get(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "PROVIDER_NOT_FOUND",
                "Provider 不存在",
                {"event_type": "provider_not_found"},
            ),
        )
    resp = dict(provider)
    if resp.get("api_key"):
        resp["api_key"] = _mask_api_key(resp["api_key"])
    return resp


@router.put("/model-providers/{provider_id}")
def update_model_provider(provider_id: str, body: dict) -> dict:
    """更新 Provider 配置

    请求体: { provider_type?, base_url?, api_key?, default_headers?, enabled? }
    """
    provider = _providers_store.get(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "PROVIDER_NOT_FOUND",
                "Provider 不存在",
                {"event_type": "provider_not_found"},
            ),
        )
    allowed_fields = {
        "provider_type",
        "base_url",
        "api_key",
        "default_headers",
        "enabled",
    }
    for key, value in body.items():
        if key in allowed_fields:
            provider[key] = value
    _providers_store[provider_id] = provider
    resp = dict(provider)
    if resp.get("api_key"):
        resp["api_key"] = _mask_api_key(resp["api_key"])
    return resp


@router.delete("/model-providers/{provider_id}")
def delete_model_provider(provider_id: str) -> dict:
    """移除 Provider"""
    if provider_id not in _providers_store:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "PROVIDER_NOT_FOUND",
                "Provider 不存在",
                {"event_type": "provider_not_found"},
            ),
        )
    del _providers_store[provider_id]
    return {"deleted": True}


@router.post("/model-providers/{provider_id}/test")
def test_model_provider(provider_id: str) -> dict:
    """Provider 连通性测试

    向 Provider 的 base_url 发 GET 请求验证可达性。
    返回: { success, latency_ms, error }
    """
    provider = _providers_store.get(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "PROVIDER_NOT_FOUND",
                "Provider 不存在",
                {"event_type": "provider_not_found"},
            ),
        )
    base_url = provider.get("base_url", "").rstrip("/")
    if not base_url:
        return {"success": False, "latency_ms": 0, "error": "base_url 为空"}

    start = time.time()
    try:
        req = urllib.request.Request(base_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            latency_ms = int((time.time() - start) * 1000)
            if resp.status < 500:
                return {"success": True, "latency_ms": latency_ms, "error": None}
            return {
                "success": False,
                "latency_ms": latency_ms,
                "error": f"HTTP {resp.status}",
            }
    except urllib.error.HTTPError as exc:
        latency_ms = int((time.time() - start) * 1000)
        return {
            "success": False,
            "latency_ms": latency_ms,
            "error": f"HTTP {exc.code}: {exc.reason}",
        }
    except urllib.error.URLError as exc:
        latency_ms = int((time.time() - start) * 1000)
        return {
            "success": False,
            "latency_ms": latency_ms,
            "error": f"连接失败: {exc.reason}",
        }
    except Exception as exc:
        latency_ms = int((time.time() - start) * 1000)
        return {"success": False, "latency_ms": latency_ms, "error": str(exc)}
