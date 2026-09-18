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
    except Exception as exc:
        logger.warning("获取 registry source fields 失败: %s", exc)
        return set()
    # 并入数据模型已确认映射（V3.0 数据建模层）：选表通道落地表与源表同名
    # （小写归一后 o_Diagnose == o_diagnose，列名直通匹配）
    try:
        from src.data_platform.storage.data_model.data_model_factory import (
            get_data_model_storage,
        )
        model_storage = get_data_model_storage()
        for model in model_storage.list_models():
            for mapping in model_storage.list_mappings(model.model_code):
                if mapping.status != "confirmed":
                    continue
                column = mapping.physical_column.lower().strip()
                fields.add(column)
                fields.add(f"{mapping.physical_table.lower().strip()}.{column}")
    except Exception as exc:
        logger.warning("获取数据模型映射失败: %s", exc)
    return fields


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


def check_model_semantic_consistency() -> dict:
    """元数据一致性校验（数据专家拷问轮 Q4）：模型层 vs 语义层字段定义比对。

    冻结契约（写入 V3.0 设计文档 §4.1）：
    - 数据模型是结构 master（字段、角色、映射的唯一权威在模型层）
    - 语义层消费模型定义派生 datasets/fields（物化时注册）
    - 本检查不自动同步，只报告漂移；两处不一致时告警（一致性任务比双向同步现实）
    """
    from src.data_platform.storage.data_model.data_model_factory import (
        get_data_model_storage,
    )
    from src.semantic_layer.registry import get_semantic_registry

    model_storage = get_data_model_storage()
    reg = get_semantic_registry()

    issues: list[dict] = []
    # 语义层已注册的物化 dataset（dwd_*），其 fields 应与模型定义一致
    for model in model_storage.list_models():
        if model.status != "published":
            continue
        dataset_code = model.model_code  # Slice 2 物化注册约定：视图名=模型编码
        dataset = reg._store.get_dataset(dataset_code)
        if dataset is None:
            continue  # 未物化的模型不参与比对（无派生面）

        # 模型声明字段 vs 语义版本字段
        model_fields = {f.field_code for f in model.fields}
        versions = reg.list_object_versions(dataset.object_code)
        if not versions:
            continue
        version = versions[-1]
        semantic_fields = {
            f.field_code.rsplit(".", 1)[-1]
            for f in version.fields if f.dataset_code == dataset_code
        }
        missing_in_semantic = model_fields - semantic_fields
        extra_in_semantic = semantic_fields - model_fields
        if missing_in_semantic:
            issues.append({
                "model": model.model_code,
                "issue": f"模型字段未同步到语义层: {sorted(missing_in_semantic)[:5]}",
                "severity": "warning",
            })
        if extra_in_semantic:
            issues.append({
                "model": model.model_code,
                "issue": f"语义层存在模型未声明字段: {sorted(extra_in_semantic)[:5]}",
                "severity": "warning",
            })

    return {"master": "data_model", "checked_datasets": sum(1 for m in model_storage.list_models() if m.status == "published"), "issues": issues}
