"""Discovery 服务层：通过数据治理中心的受控连接扫描单个数据源。"""
from __future__ import annotations

import logging
from typing import Any

from src.data_platform.outpatient_governance import ConnectionStatus
from src.runtime.discovery.sqlserver_source import scan_sqlserver

logger = logging.getLogger(__name__)


def _get_registry_source_fields() -> set[str]:
    try:
        from src.semantic_layer.registry import get_semantic_registry
        fields: set[str] = set()
        for metric in get_semantic_registry()._store.list_metrics():
            if metric.source_field:
                value = metric.source_field.lower().strip()
                fields.add(value)
                if '.' in value:
                    fields.add(value.split('.', 1)[1])
        return fields
    except Exception as exc:
        logger.warning("获取 registry source fields 失败: %s", exc)
        return set()


def _is_mapped(field_name: str, table_name: str, source_fields: set[str]) -> bool:
    name = field_name.lower().strip()
    return name in source_fields or f"{table_name.lower().strip()}.{name}" in source_fields


def run_discovery(
    *,
    datasource_id: str,
    governance_service,
    sample_limit: int = 10000,
    store=None,
) -> dict[str, Any]:
    """扫描一个已登记且连接健康的数据源，连接字段不进入任务或日志。"""
    source = next(
        (item for item in governance_service.list_sources() if item.source_id == datasource_id),
        None,
    )
    if source is None:
        raise ValueError("数据治理中心不存在该数据源")
    if source.connection_status is not ConnectionStatus.HEALTHY or not source.credential_configured:
        raise ValueError("数据源必须完成凭据配置并通过连接健康检测")

    result = scan_sqlserver(
        {"schema": source.schema_name, "sample_limit": sample_limit},
        store=store,
        connection=governance_service.open_source_connection(datasource_id),
    )
    source_fields = _get_registry_source_fields()
    for field in result.get("fields", []):
        field["mapped"] = _is_mapped(
            field["field_name"], field.get("table_name", ""), source_fields
        )
        field["datasource_id"] = datasource_id
    fields = result.get("fields", [])
    mapped_count = sum(1 for field in fields if field["mapped"])
    return {
        "tables": result.get("tables", []),
        "total_tables": len(result.get("tables", [])),
        "total_fields": len(fields),
        "mapped_fields": mapped_count,
        "unmapped_fields": len(fields) - mapped_count,
        "fields": fields,
        "table_statuses": result.get("table_statuses", []),
    }
