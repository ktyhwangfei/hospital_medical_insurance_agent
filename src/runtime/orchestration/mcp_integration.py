import time
from collections.abc import Callable
from uuid import uuid4

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapabilitySelectionRequest, McpCapabilitySelectionResult
from src.knowledge_extension.mcp_registry.ports import McpRegistry


class McpRuntimeIntegration:
    def __init__(
        self,
        registry: McpRegistry,
        on_event: Callable[[str, dict], None] | None = None,
    ):
        self._registry = registry
        self._on_event = on_event

    def select_for_step(self, request: McpCapabilitySelectionRequest) -> McpCapabilitySelectionResult:
        # 生成调用 ID 并记录开始时间
        call_id = uuid4().hex[:8]
        tool_start = time.time()

        # 在 MCP 能力选择前发出 tool_call 事件
        if self._on_event:
            self._on_event("stream:tool_call", {
                "call_id": call_id,
                "tool_name": "mcp_capability_selection",
                "params": request.model_dump(mode="json"),
            })

        # 执行能力选择
        result = self._registry.select_capabilities(request)

        # 构建带审计追踪的最终结果（保持原有业务逻辑不变）
        audit_events = [
            AuditSummary(
                event_type="mcp_runtime_selection",
                summary={
                    "scenario": request.scenario,
                    "role": request.role,
                    "selected": [item.capability_id for item in result.selected_capabilities],
                    "excluded": result.excluded_capabilities,
                },
            ),
            *result.audit_events,
        ]
        status = KnowledgeExtensionStatus.NO_HIT if result.status is KnowledgeExtensionStatus.HIGH_RISK_BLOCKED else result.status
        final_result = result.model_copy(update={"status": status, "audit_events": audit_events}, deep=True)

        # 发出 tool_result 或 error 事件
        if self._on_event:
            duration_ms = int((time.time() - tool_start) * 1000)
            if result.status in (KnowledgeExtensionStatus.UNAVAILABLE,):
                self._on_event("stream:error", {
                    "call_id": call_id,
                    "error": "MCP capability selection unavailable",
                    "status": result.status.value,
                })
            else:
                self._on_event("stream:tool_result", {
                    "call_id": call_id,
                    "result": {
                        "status": final_result.status.value,
                        "selected_count": len(final_result.selected_capabilities),
                        "excluded_count": len(final_result.excluded_capabilities),
                    },
                    "duration_ms": duration_ms,
                })

        return final_result
