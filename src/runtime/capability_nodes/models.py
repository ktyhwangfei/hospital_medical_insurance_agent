from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityNode:
    """A governable business capability node that can be registered and discovered.

    Nodes represent reusable business capabilities (e.g., risk analysis, rule explanation)
    that the orchestrator can invoke. They are NOT autonomous agents — they are governed
    units with explicit input/output schemas and a status lifecycle.
    """

    node_id: str
    name: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    status: str = "active"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
