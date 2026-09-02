"""活动发布版 collection 统一解析（Issue #33 P0-1）。

所有政策规则/事实读路径必须通过本模块解析目标 collection，替代此前两套
互不一致的实现（structured_policy_retriever 的 ORM + 行数比较、
rules_search_service 的裸 SQL + 命名拼接）：

- ``policy_active_release`` 指向 active release 且其集合存在且非空 → 读 release 产物，
  promote 后 Runtime 立即可见（issue 验收标准 1）；
- 无 active release / 指针读取失败 / 集合不存在或为空 → 回退主集合。

完整性判定为「存在且非空」：构建期健康检查（release_index.build）与 promote
门禁已保证产物质量；读路径不再与主集合比较行数（删除型发布行数合法下降，
行数比较会误判不完整）。

写入纪律：回填/迁移脚本必须用 ``resolve_rules_collection()`` 定位写入目标，
禁止直写 ``policy_rules_v2``——存在 active release 时 Runtime 读不到主集合变更。
"""
from __future__ import annotations

import logging
from typing import Any

from pymilvus import MilvusClient

logger = logging.getLogger(__name__)

# 无 active release 时的回退主集合（与 policy_rules_search.COLLECTION_NAME 同源语义）
FALLBACK_RULES_COLLECTION = "policy_rules_v2"
FALLBACK_FACTS_COLLECTION = "policy_facts"

_store: Any | None = None


def _get_store() -> Any:
    """release 指针存储单例（延迟构造，避免模块导入即连库）。"""
    global _store
    if _store is None:
        from src.data_platform.storage.postgresql.policy_quality_store import (
            PostgresPolicyQualityStore,
        )

        _store = PostgresPolicyQualityStore()
    return _store


def get_active_release() -> Any | None:
    """读 active release 指针（best-effort，任何失败返回 None 走回退）。"""
    try:
        return _get_store().get_active_release()
    except Exception as exc:
        logger.warning("[ReleaseResolver] active release unavailable: %s", exc)
        return None


def _collection_ready(client: Any, name: str) -> bool:
    """集合存在且非空即为完整产物。"""
    if not name:
        return False
    if name not in set(client.list_collections() or []):
        return False
    return int(client.get_collection_stats(name).get("row_count", 0)) > 0


def _resolve(host: str, port: str, attr: str, fallback: str) -> str:
    active = get_active_release()
    name = str(getattr(active, attr, "") or "") if active else ""
    if not name:
        return fallback
    try:
        client = MilvusClient(uri=f"http://{host}:{port}")
        if _collection_ready(client, name):
            return name
        logger.warning(
            "[ReleaseResolver] release collection not ready: %s, fallback to %s",
            name,
            fallback,
        )
    except Exception as exc:
        logger.warning(
            "[ReleaseResolver] milvus probe failed (%s), fallback to %s", exc, fallback
        )
    return fallback


def resolve_rules_collection(host: str = "127.0.0.1", port: str = "19530") -> str:
    """解析政策规则读路径目标 collection（active release 优先，否则 policy_rules_v2）。"""
    return _resolve(host, port, "rules_collection", FALLBACK_RULES_COLLECTION)


def resolve_facts_collection(host: str = "127.0.0.1", port: str = "19530") -> str:
    """解析政策事实读路径目标 collection（active release 优先，否则 policy_facts）。"""
    return _resolve(host, port, "facts_collection", FALLBACK_FACTS_COLLECTION)


def split_milvus_uri(uri: str) -> tuple[str, str]:
    """``http://host:port`` → (host, port)，供持有 uri 的调用方接入 resolver。"""
    stripped = uri.split("://", 1)[-1]
    host, _, port = stripped.partition(":")
    return host or "127.0.0.1", port or "19530"
