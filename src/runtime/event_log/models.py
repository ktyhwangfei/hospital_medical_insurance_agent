from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuntimeEvent:
    """Represents a runtime event for observability purposes.

    Separate from audit logging — audit is for compliance, events are for
    operational observability and debugging.
    """

    event_id: str
    event_type: str
    """One of: IntentDetected, WorkflowStarted, StepCompleted, AdapterCalled."""

    workflow_id: str
    step_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ''
