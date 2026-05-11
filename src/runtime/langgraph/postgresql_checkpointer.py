"""PostgreSQL checkpointer stub for LangGraph.

This module provides a PostgreSQL-backed checkpointer for LangGraph agent graphs.
The current implementation is a stub that delegates to MemorySaver as a fallback.
A full PostgreSQL implementation should persist checkpoints to the database for
fault tolerance and cross-session continuity.
"""

from langgraph.checkpoint.memory import MemorySaver


class PostgreSQLCheckpointer:
    """PostgreSQL-backed checkpointer stub for LangGraph.

    For now, delegates to MemorySaver. A TODO marks where to integrate
    with PostgreSQLClient for real persistence.

    TODO: Implement real PostgreSQL checkpointing using
    src.data_platform.storage.postgresql.client.PostgreSQLClient.
    The checkpointer should persist checkpoint snapshots to a
    'checkpoints' table with columns:
      - thread_id (varchar, PK)
      - checkpoint_ns (varchar, PK)
      - checkpoint_id (varchar, PK)
      - parent_checkpoint_id (varchar, nullable)
      - state (jsonb)
      - created_at (timestamptz)
    """

    def __init__(self):
        self._memory = MemorySaver()

    @property
    def put(self):
        """Write a checkpoint."""
        return self._memory.put

    @property
    def put_writes(self):
        """Write intermediate writes (pending writes)."""
        return self._memory.put_writes

    @property
    def get_tuple(self):
        """Get a checkpoint tuple."""
        return self._memory.get_tuple

    @property
    def list(self):
        """List checkpoints."""
        return self._memory.list


def get_postgresql_checkpointer() -> PostgreSQLCheckpointer:
    """Factory: create a PostgreSQLCheckpointer instance."""
    return PostgreSQLCheckpointer()
