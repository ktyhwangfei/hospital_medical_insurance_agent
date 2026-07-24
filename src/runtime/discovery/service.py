"""Discovery 服务层：编排扫描流程、映射判断、结果汇总。"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from src.runtime.discovery.config import DiscoverySourceConfig
from src.runtime.discovery.sqlserver_source import scan_sqlserver

logger = logging.getLogger(__name__)


def _get_registry_source_fields() -> set[str]:
    """从语义层 registry 获取所有已映射的 source_field（含完整路径和纯字段名）。"""
    try:
        from src.semantic_layer.registry import get_semantic_registry
        reg = get_semantic_registry()
        fields: set[str] = set()
        for m in reg._store.list_metrics():
            if m.source_field:
                s = m.source_field.lower().strip()
                fields.add(s)
                # 也加入纯字段名（不含表前缀），兼容只按字段名匹配
                if '.' in s:
                    fields.add(s.split('.', 1)[1])
        return fields
    except Exception as exc:
        logger.warning("获取 registry source fields 失败: %s", exc)
        return set()


def _is_mapped(field_name: str, table_name: str, source_fields: set[str]) -> bool:
    """检查字段是否已映射。同时匹配 table.field 和纯 field 两种格式。"""
    fn = field_name.lower().strip()
    full = f"{table_name.lower().strip()}.{fn}"
    return fn in source_fields or full in source_fields


def list_enabled_sqlserver_sources(meta_store) -> list[tuple[str | None, str, dict]]:
    """从 datasource 注册表取所有启用的 SQL Server 源（P7.2 多源扫描）。

    返回 [(datasource_id, name, connection_config), ...]；meta_store=None 返回 []。
    """
    if meta_store is None:
        return []
    sources: list[tuple[str | None, str, dict]] = []
    try:
        for ds in meta_store.list_datasources(enabled_only=True):
            if ds.get("type") != "sqlserver":
                continue
            sources.append((ds.get("id"), ds.get("name", ""), ds.get("connection_config") or {}))
    except Exception as exc:
        logger.warning("list_enabled_sqlserver_sources 失败: %s", exc)
    return sources


def run_discovery(source_config: dict | None = None, store=None, meta_store=None) -> dict:
    """执行 discovery 扫描，返回完整结果。

    多源（P7.2）：source_config 为空时从 datasource 注册表取多源逐个扫描合并。
    单源（兼容）：显式传 source_config 时仅扫描该源。
    """
    config = DiscoverySourceConfig(**(source_config or {}))
    source_fields = _get_registry_source_fields()

    # 确定扫描目标列表：[(ds_id, name, cfg), ...]
    if config.sqlserver:
        targets = [(None, "manual", config.sqlserver.model_dump())]
    else:
        targets = list_enabled_sqlserver_sources(meta_store)

    if not targets or not any(t[2].get("database") for t in targets):
        raise ValueError("未配置有效的 SQL Server 数据源，请在页面「数据源」中填写连接信息")

    tables: list[str] = []
    fields: list[dict[str, Any]] = []
    table_statuses: list[dict[str, Any]] = []

    for ds_id, _name, cfg in targets:
        if not cfg.get("database"):
            continue
        try:
            result = scan_sqlserver(cfg, store=store)
        except Exception as exc:
            logger.error("SQL Server 扫描失败 ds=%s: %s", ds_id, exc)
            raise
        tables.extend(result.get("tables", []))
        for f in result.get("fields", []):
            f["mapped"] = _is_mapped(f["field_name"], f.get("table_name", ""), source_fields)
            f["datasource_id"] = ds_id  # 标记来源（三段式寻址基础）
            fields.append(f)
        if "table_statuses" in result:
            table_statuses.extend(result["table_statuses"])
        logger.info("SQL Server 扫描完成 ds=%s: %d 表, %d 字段",
                    ds_id, len(result.get("tables", [])), len(result.get("fields", [])))

    mapped_count = sum(1 for f in fields if f["mapped"])

    return {
        "tables": tables,
        "total_tables": len(tables),
        "total_fields": len(fields),
        "mapped_fields": mapped_count,
        "unmapped_fields": len(fields) - mapped_count,
        "fields": fields,
        "table_statuses": table_statuses,
    }

