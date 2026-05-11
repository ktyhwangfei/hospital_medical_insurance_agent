from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from src.runtime.event_log.models import RuntimeEvent


class EventLogService:
    """In-memory event log for runtime observability.

    Records operational events (intent detected, workflow started, steps
    completed, adapter calls) separate from audit logging. Audit is for
    compliance; event log is for debugging and operational insight.
    """

    def __init__(self) -> None:
        self._events: list[RuntimeEvent] = []
        self._by_workflow: dict[str, list[RuntimeEvent]] = {}

    def record_event(
        self,
        event_type: str,
        workflow_id: str,
        step_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        """Record a runtime event.

        Args:
            event_type: Type of event (IntentDetected, WorkflowStarted, etc.).
            workflow_id: Associated workflow identifier.
            step_id: Optional step identifier.
            payload: Optional event payload data.

        Returns:
            The created RuntimeEvent.
        """
        event = RuntimeEvent(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            workflow_id=workflow_id,
            step_id=step_id,
            payload=payload or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._events.append(event)

        if workflow_id not in self._by_workflow:
            self._by_workflow[workflow_id] = []
        self._by_workflow[workflow_id].append(event)

        return event

    def get_events(self, workflow_id: str) -> list[RuntimeEvent]:
        """Get all runtime events for a given workflow.

        Args:
            workflow_id: Workflow identifier.

        Returns:
            List of RuntimeEvent instances for the workflow.
        """
        return self._by_workflow.get(workflow_id, [])

    def get_all_events(self) -> list[RuntimeEvent]:
        """Get all recorded runtime events."""
        return list(self._events)


# Module-level singleton for convenience
event_log_service = EventLogService()
