from __future__ import annotations

from typing import Any, Callable

from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
from src.runtime.capability_nodes.registry import CapabilityRegistry


class CapabilityExecutor:
    """Executes capability nodes by routing to the appropriate handler.

    Each node_id maps to a handler function that performs the actual
    business logic (e.g., calling adapters, computing results).
    """

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "medical_record_risk_analysis": self._handle_medical_record_risk_analysis,
            "drg_dip_risk_analysis": self._handle_drg_dip_risk_analysis,
            "pre_audit_explanation": self._handle_pre_audit_explanation,
        }

    def execute(self, node_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute a capability node by its node_id with the given inputs.

        Args:
            node_id: The registered node identifier.
            inputs: Input parameters (typically includes patient_id, encounter_id).

        Returns:
            A dict with keys: status, node_id, result, and optionally error.
        """
        node = self._registry.get_node(node_id)
        if node is None:
            return {"status": "error", "node_id": node_id, "error": f"node not found: {node_id}"}

        if node.status != "active":
            return {"status": "error", "node_id": node_id, "error": f"node is not active: {node.status}"}

        handler = self._handlers.get(node_id)
        if handler is None:
            return {"status": "error", "node_id": node_id, "error": f"no handler registered for node: {node_id}"}

        try:
            result = handler(inputs)
            return {"status": "success", "node_id": node_id, "result": result}
        except Exception as exc:
            return {"status": "error", "node_id": node_id, "error": str(exc)}

    def _handle_medical_record_risk_analysis(self, inputs: dict[str, Any]) -> dict[str, Any]:
        patient_id = inputs.get("patient_id", "")
        encounter_id = inputs.get("encounter_id", "")
        adapter = InMemoryMedicalRecordAdapter()
        adapter_result = adapter.query_homepage(patient_id, encounter_id)
        return {
            "risk": adapter_result.data.get("risk", ""),
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "source_system": adapter_result.source_system,
            "source_record_id": adapter_result.source_record_id or "",
        }

    def _handle_drg_dip_risk_analysis(self, inputs: dict[str, Any]) -> dict[str, Any]:
        patient_id = inputs.get("patient_id", "")
        encounter_id = inputs.get("encounter_id", "")
        adapter = InMemoryDrgDipAdapter()
        adapter_result = adapter.query_group_result(patient_id, encounter_id)
        return {
            "risk": adapter_result.data.get("risk", ""),
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "source_system": adapter_result.source_system,
            "source_record_id": adapter_result.source_record_id or "",
        }

    def _handle_pre_audit_explanation(self, inputs: dict[str, Any]) -> dict[str, Any]:
        patient_id = inputs.get("patient_id", "")
        encounter_id = inputs.get("encounter_id", "")
        adapter = InMemoryPreAuditAdapter()
        adapter_result = adapter.query_audit_result(patient_id, encounter_id)
        return {
            "risk": adapter_result.data.get("risk", ""),
            "patient_id": patient_id,
            "encounter_id": encounter_id,
            "source_system": adapter_result.source_system,
            "source_record_id": adapter_result.source_record_id or "",
        }

    def register_handler(self, node_id: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Register a custom handler for a given node_id."""
        self._handlers[node_id] = handler
