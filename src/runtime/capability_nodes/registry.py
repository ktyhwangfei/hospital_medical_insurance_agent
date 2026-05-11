from __future__ import annotations

from src.runtime.capability_nodes.models import CapabilityNode


class CapabilityRegistry:
    """In-memory registry for CapabilityNode discovery and management.

    Provides registration, lookup by ID, discovery by capability tag,
    and full listing. Currently in-memory; can be backed by persistent
    storage in the future.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, CapabilityNode] = {}

    def register(self, node: CapabilityNode) -> None:
        """Register a capability node. Replaces any existing node with the same node_id."""
        self._nodes[node.node_id] = node

    def get_node(self, node_id: str) -> CapabilityNode | None:
        """Retrieve a node by its unique node_id."""
        return self._nodes.get(node_id)

    def find_by_capability(self, capability: str) -> list[CapabilityNode]:
        """Find all nodes that declare a given capability."""
        return [node for node in self._nodes.values() if capability in node.capabilities]

    def list_nodes(self) -> list[CapabilityNode]:
        """Return all registered nodes."""
        return list(self._nodes.values())

    def unregister(self, node_id: str) -> None:
        """Remove a node from the registry by node_id."""
        self._nodes.pop(node_id, None)
