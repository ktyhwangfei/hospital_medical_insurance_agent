"""Business Facts Builder — consumes Registry + Adapters, produces standardized Facts."""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.semantic_layer.models import (
    BusinessFactsRequest, BusinessFactsResponse, FactsMeta,
)
from src.semantic_layer.registry import SemanticRegistry

logger = logging.getLogger(__name__)


class BusinessFactsBuilder:
    """Build standardized Business Facts from Registry metadata and adapter calls.

    Builder 不直连数据库。通过 Registry 获取 source_object → source_adapter_port 映射，
    调用对应的适配器 Protocol 接口获取领域模型实例，再从领域模型中提取 source_field 的值。
    """

    def __init__(
        self,
        registry: SemanticRegistry,
        adapter_builders: dict[str, Any],
    ):
        self._registry = registry
        self._adapter_builders = adapter_builders

    def build(self, request: BusinessFactsRequest) -> BusinessFactsResponse:
        facts: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []

        for obj_req in request.objects:
            object_code = obj_req.object_code
            obj_facts: dict[str, Any] = {}

            metrics = self._registry.get_metric_mapping(object_code, obj_req.metric_codes)
            if not metrics:
                warnings.append(f"No metrics found for object {object_code}")
                continue

            # 常量指标（无 adapter + 有 default_value）直接取固定值，不调 adapter
            adapter_groups: dict[str, list] = {}
            for metric in metrics:
                if metric.default_value is not None and not metric.source_adapter_port:
                    value = metric.default_value
                    if metric.value_domain:
                        value = self._registry.resolve_value(metric.value_domain, str(value))
                    obj_facts[metric.metric_code.split(".")[-1]] = value
                    continue
                port = metric.source_adapter_port
                if not port:
                    # P0-3: 空 source_adapter_port 不应静默路由到 'default'，
                    # 否则可能拿到错来源的数据。fail-fast：精确告警并跳过。
                    warnings.append(
                        f"Metric '{metric.metric_code}' has no source_adapter_port "
                        f"configured, skipped"
                    )
                    continue
                if port not in adapter_groups:
                    adapter_groups[port] = []
                adapter_groups[port].append(metric)

            for port, port_metrics in adapter_groups.items():
                adapter = self._adapter_builders.get(port)
                if adapter is None:
                    warnings.append(f"Adapter '{port}' not available for {object_code}")
                    continue

                adapter_data = self._call_adapter(adapter, port, request.context)
                if adapter_data is None:
                    warnings.append(f"Adapter '{port}' returned no data for {object_code}")
                    continue

                for metric in port_metrics:
                    value = self._extract_field(adapter_data, metric.source_field or "")
                    if value is None:
                        if metric.importance == "core" and metric.required:
                            warnings.append(
                                f"Core metric {metric.metric_code} missing from adapter"
                            )
                        continue

                    if metric.value_domain:
                        value = self._registry.resolve_value(metric.value_domain, str(value))

                    obj_facts[metric.metric_code.split(".")[-1]] = value

            if obj_facts:
                if object_code not in facts:
                    facts[object_code] = {}
                facts[object_code].update(obj_facts)

        return BusinessFactsResponse(
            facts=facts,
            meta=FactsMeta(warnings=warnings),
        )

    def _call_adapter(
        self, adapter: Any, port_name: str, context: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        try:
            if hasattr(adapter, "query_transaction"):
                patient_id = context.get("patient_id", "")
                encounter_id = context.get("encounter_id", "")
                result = adapter.query_transaction(
                    patient_id=patient_id, encounter_id=encounter_id
                )
            elif hasattr(adapter, "query_patient"):
                patient_id = context.get("patient_id", "")
                result = adapter.query_patient(patient_id=patient_id)
            else:
                logger.warning(f"Adapter '{port_name}' has no known query method")
                return None

            if hasattr(result, "status") and hasattr(result, "data"):
                if result.status and hasattr(result.status, "value"):
                    if result.status.value != "success":
                        logger.warning(f"Adapter '{port_name}' returned {result.status.value}")
                        return None
                return result.data if isinstance(result.data, dict) else {}

            return None
        except Exception as e:
            logger.exception(f"Error calling adapter '{port_name}': {e}")
            return None

    def _extract_field(self, data: dict[str, Any], field_name: str) -> Any:
        if not field_name:
            return None
        if "." in field_name:
            parts = field_name.split(".")
            # 三段式 ds.table.column：跳过首段 ds（adapter 业务对象 data 无 ds 层）
            if len(parts) >= 3:
                parts = parts[1:]
            current = data
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            return current
        return data.get(field_name)
