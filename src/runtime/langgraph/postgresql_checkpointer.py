"""
PostgreSQL LangGraph 检查点存储
实现 BaseCheckpointSaver 接口以支持 builder.compile(checkpointer=PostgresCheckpointer())
"""
import json
import logging
from typing import Any, Iterator, Optional, Sequence

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    RunnableConfig,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

CHECKPOINTS_TABLE = """
CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
    thread_id VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(128) NOT NULL,
    parent_checkpoint_id VARCHAR(128),
    state JSONB NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_thread ON langgraph_checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_parent ON langgraph_checkpoints(parent_checkpoint_id);
"""

WRITES_TABLE = """
CREATE TABLE IF NOT EXISTS langgraph_writes (
    thread_id VARCHAR(128) NOT NULL,
    checkpoint_ns VARCHAR(128) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL,
    idx INTEGER NOT NULL,
    channel VARCHAR(128) NOT NULL,
    value JSONB DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
"""


class PostgresCheckpointer(BaseCheckpointSaver[str]):
    """PostgreSQL-backed checkpoint saver for LangGraph.

    Stores checkpoints in the `langgraph_checkpoints` table and pending
    writes in the `langgraph_writes` table.  Uses the parent `serde` to
    (de)serialize checkpoint data so that LangChain Message objects and
    other complex types are handled correctly.
    """

    def __init__(
        self,
        database_url: str | None = None,
        serde: Any = None,
    ) -> None:
        super().__init__(serde=serde)
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    # ── connection management ──────────────────────────────────────────────

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
                logger.info("PostgreSQL checkpointer initialized")
            except Exception as e:
                logger.error("Failed to initialize checkpointer: %s", e)
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(CHECKPOINTS_TABLE)
            self._client.execute(WRITES_TABLE)
        except Exception as e:
            logger.error("Failed to ensure checkpointer schema: %s", e)
            raise

    # ── BaseCheckpointSaver interface ──────────────────────────────────────

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Fetch a single checkpoint tuple matching *config*."""
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        client = self._get_client()
        row = self._select_checkpoint(client, thread_id, checkpoint_ns, checkpoint_id)
        if not row:
            return None

        return self._row_to_tuple(thread_id, checkpoint_ns, row, client)

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints matching the given criteria."""
        client = self._get_client()

        if config:
            thread_id: str = config["configurable"]["thread_id"]
            checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
            before_id = get_checkpoint_id(before) if before else None

            sql = (
                "SELECT * FROM langgraph_checkpoints "
                "WHERE thread_id = %s AND checkpoint_ns = %s "
            )
            params: list[Any] = [thread_id, checkpoint_ns]

            if before_id:
                sql += "AND checkpoint_id < %s "
                params.append(before_id)

            sql += "ORDER BY created_at DESC "

            if limit is not None:
                sql += "LIMIT %s"
                params.append(limit)

            rows = client.execute(sql, tuple(params))
            for row in rows:
                ckpt = self._build_checkpoint_from_row(row)
                if filter and not _metadata_matches(ckpt.metadata, filter):
                    continue
                yield ckpt
        else:
            # No config → iterate all threads (expensive; rarely used)
            rows = client.execute(
                "SELECT DISTINCT thread_id FROM langgraph_checkpoints ORDER BY thread_id"
            )
            for t_row in rows:
                tid = t_row["thread_id"]
                ns_rows = client.execute(
                    "SELECT DISTINCT checkpoint_ns FROM langgraph_checkpoints "
                    "WHERE thread_id = %s",
                    (tid,),
                )
                for ns_row in ns_rows:
                    ns = ns_row["checkpoint_ns"]
                    ckpt = self.get_tuple({
                        "configurable": {
                            "thread_id": tid,
                            "checkpoint_ns": ns,
                        },
                    })
                    if ckpt:
                        if filter and not _metadata_matches(ckpt.metadata, filter):
                            continue
                        yield ckpt

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store a checkpoint."""
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        parent_id: str | None = config["configurable"].get("checkpoint_id")

        client = self._get_client()
        state_json = json.dumps(checkpoint, ensure_ascii=False, default=str)
        meta_json = json.dumps(get_checkpoint_metadata(config, metadata), ensure_ascii=False, default=str)

        sql = """
            INSERT INTO langgraph_checkpoints
                (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, state, metadata)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE SET
                parent_checkpoint_id = EXCLUDED.parent_checkpoint_id,
                state = EXCLUDED.state,
                metadata = EXCLUDED.metadata
        """
        client.execute(sql, (
            thread_id,
            checkpoint_ns,
            checkpoint["id"],
            parent_id,
            state_json,
            meta_json,
        ))

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint["id"],
            },
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes linked to a checkpoint."""
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id: str = config["configurable"]["checkpoint_id"]

        client = self._get_client()
        for idx, (channel, value) in enumerate(writes):
            value_json = json.dumps(value, ensure_ascii=False, default=str)
            sql = """
                INSERT INTO langgraph_writes
                    (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, value)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                DO UPDATE SET channel = EXCLUDED.channel, value = EXCLUDED.value
            """
            client.execute(sql, (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                task_id,
                idx,
                channel,
                value_json,
            ))

    # ── helpers ────────────────────────────────────────────────────────────

    def _select_checkpoint(
        self,
        client: PostgreSQLClient,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str | None,
    ) -> dict[str, Any] | None:
        if checkpoint_id:
            rows = client.execute(
                "SELECT * FROM langgraph_checkpoints "
                "WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s",
                (thread_id, checkpoint_ns, checkpoint_id),
            )
        else:
            rows = client.execute(
                "SELECT * FROM langgraph_checkpoints "
                "WHERE thread_id = %s AND checkpoint_ns = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (thread_id, checkpoint_ns),
            )
        return rows[0] if rows else None

    def _row_to_tuple(
        self,
        thread_id: str,
        checkpoint_ns: str,
        row: dict[str, Any],
        client: PostgreSQLClient,
    ) -> CheckpointTuple:
        """Convert a DB row to a CheckpointTuple."""
        checkpoint = row["state"]
        metadata = row["metadata"]

        config_out: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": row["checkpoint_id"],
            },
        }

        parent_config: RunnableConfig | None = None
        if row.get("parent_checkpoint_id"):
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": row["parent_checkpoint_id"],
                },
            }

        # Load pending writes
        writes_rows = client.execute(
            "SELECT * FROM langgraph_writes "
            "WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s "
            "ORDER BY idx",
            (thread_id, checkpoint_ns, row["checkpoint_id"]),
        )
        pending_writes = []
        for w in writes_rows:
            pending_writes.append((
                w["task_id"],
                w["channel"],
                w["value"],
            ))

        return CheckpointTuple(
            config=config_out,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes if pending_writes else None,
        )

    def _build_checkpoint_from_row(
        self,
        row: dict[str, Any],
    ) -> CheckpointTuple:
        """Build a CheckpointTuple from a DB row (no client round-trip for writes)."""
        checkpoint = row["state"]
        metadata = row["metadata"]

        config_out: RunnableConfig = {
            "configurable": {
                "thread_id": row["thread_id"],
                "checkpoint_ns": row["checkpoint_ns"],
                "checkpoint_id": row["checkpoint_id"],
            },
        }

        parent_config: RunnableConfig | None = None
        if row.get("parent_checkpoint_id"):
            parent_config = {
                "configurable": {
                    "thread_id": row["thread_id"],
                    "checkpoint_ns": row["checkpoint_ns"],
                    "checkpoint_id": row["parent_checkpoint_id"],
                },
            }

        return CheckpointTuple(
            config=config_out,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=None,
        )

    # ── health / utility ───────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """Check backend connectivity."""
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}


# ── helpers ─────────────────────────────────────────────────────────────────

def _metadata_matches(
    metadata: CheckpointMetadata,
    filter: dict[str, Any],
) -> bool:
    """Return True when all *filter* key/value pairs match *metadata*."""
    return all(
        query_value == metadata.get(query_key)
        for query_key, query_value in filter.items()
    )


# ── factory (kept for backward compatibility) ───────────────────────────────

def get_postgresql_checkpointer() -> PostgresCheckpointer:
    """Factory: create a PostgresCheckpointer instance."""
    return PostgresCheckpointer()
