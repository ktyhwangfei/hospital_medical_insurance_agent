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
        from src.runtime.api.semantic_routes import get_registry
        reg = get_registry()
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


def run_discovery(source_config: dict | None = None, store=None) -> dict:
    """执行 discovery 扫描，返回完整结果。支持增量扫描（需传入 store）。"""
    config = DiscoverySourceConfig(**(source_config or {}))
    source_fields = _get_registry_source_fields()

    # 确定实际使用的配置
    cfg = config.sqlserver.model_dump() if config.sqlserver else {}
    tables: list[str] = []
    fields: list[dict[str, Any]] = []

    if not cfg.get("database"):
        raise ValueError("未配置有效的 SQL Server 数据源，请在页面「数据源」中填写连接信息")

    try:
        result = scan_sqlserver(cfg, store=store)
        tables = result["tables"]
        for f in result["fields"]:
            f["mapped"] = _is_mapped(f["field_name"], f.get("table_name", ""), source_fields)
            fields.append(f)
        # 保留 table_statuses 供 SSE 进度使用
        if "table_statuses" in result:
            result["table_statuses"] = result["table_statuses"]
        logger.info("SQL Server 扫描完成: %d 表, %d 字段", len(tables), len(fields))
    except Exception as exc:
        logger.error("SQL Server 扫描失败: %s", exc)
        raise

    mapped_count = sum(1 for f in fields if f["mapped"])
    unmapped_count = len(fields) - mapped_count

    return {
        "tables": tables,
        "total_tables": len(tables),
        "total_fields": len(fields),
        "mapped_fields": mapped_count,
        "unmapped_fields": len(fields) - mapped_count,
        "fields": fields,
    }

