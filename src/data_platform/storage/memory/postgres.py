"""PostgreSQL 业务记忆存储实现

生产环境使用，数据持久化到 PostgreSQL。
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from src.data_platform.storage.memory.ports import MemoryStore
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _memory_to_row(memory: BusinessMemory) -> tuple[Any, ...]:
    return (
        memory.memory_id,
        memory.session_id,
        memory.type.value,
        memory.ref_id,
        json.dumps(memory.object_snapshot, ensure_ascii=False, sort_keys=True),
        memory.importance,
        memory.confidence,
        memory.expire_policy.value,
        json.dumps(memory.relations, ensure_ascii=False, sort_keys=True),
        memory.version,
        memory.last_used_at,
        memory.created_at,
    )


def _row_to_memory(row: dict[str, Any]) -> BusinessMemory:
    snapshot = json.loads(row["object_snapshot"]) if isinstance(row["object_snapshot"], str) else (row["object_snapshot"] or {})
    relations = json.loads(row["relations"]) if isinstance(row["relations"], str) else (row["relations"] or [])
    return BusinessMemory(
        memory_id=row["memory_id"],
        session_id=row["session_id"],
        type=MemoryType(row["type"]),
        ref_id=row.get("ref_id"),
        object_snapshot=snapshot,
        importance=float(row.get("importance", 0.5)),
        confidence=float(row.get("confidence", 0.5)),
        expire_policy=ExpirePolicy(row.get("expire_policy", "topic")),
        relations=relations,
        version=int(row.get("version", 1)),
        last_used_at=row["last_used_at"],
        created_at=row["created_at"],
    )


class PostgresMemoryStore:
    """PostgreSQL 业务记忆存储"""

    # 建表 DDL（遵循项目约定：所有表通过 CREATE TABLE IF NOT EXISTS 自动建表）
    _DDL = """
    CREATE TABLE IF NOT EXISTS business_memories (
        memory_id VARCHAR(64) PRIMARY KEY,
        session_id VARCHAR(128) NOT NULL,
        type VARCHAR(32) NOT NULL,
        ref_id VARCHAR(128),
        object_snapshot JSONB,
        importance DOUBLE PRECISION,
        confidence DOUBLE PRECISION,
        expire_policy VARCHAR(16),
        relations JSONB,
        version INTEGER DEFAULT 1,
        last_used_at VARCHAR(64),
        created_at VARCHAR(64)
    )
    """

    def __init__(self, database_url: str):
        self._client = PostgreSQLClient(database_url)
        self._schema_ready = False

    def _ensure_schema(self) -> None:
        """确保 business_memories 表存在（首次使用时建表，失败降级不阻塞）。"""
        if self._schema_ready:
            return
        try:
            self._client.execute(self._DDL)
            self._schema_ready = True
        except Exception as e:
            # 建表失败（如数据库不可用）：记日志，后续操作走各自的降级路径
            logger.warning(f"Failed to ensure business_memories schema: {e}")

    def save(self, memory: BusinessMemory) -> BusinessMemory:
        sql = """insert into business_memories (
            memory_id, session_id, type, ref_id, object_snapshot,
            importance, confidence, expire_policy, relations,
            version, last_used_at, created_at
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (memory_id) do update set
            session_id = excluded.session_id,
            type = excluded.type,
            ref_id = excluded.ref_id,
            object_snapshot = excluded.object_snapshot,
            importance = excluded.importance,
            confidence = excluded.confidence,
            expire_policy = excluded.expire_policy,
            relations = excluded.relations,
            version = excluded.version,
            last_used_at = excluded.last_used_at"""
        self._ensure_schema()
        try:
            self._client.execute(sql, _memory_to_row(memory))
        except Exception:
            # 存储失败降级：记忆丢失不阻塞主流程
            pass
        return memory

    def get(self, memory_id: str) -> BusinessMemory | None:
        self._ensure_schema()
        try:
            rows = self._client.execute(
                "select * from business_memories where memory_id = %s", (memory_id,)
            )
            if not rows:
                return None
            return _row_to_memory(rows[0])
        except Exception:
            return None

    def list_by_session(self, session_id: str) -> list[BusinessMemory]:
        self._ensure_schema()
        try:
            rows = self._client.execute(
                "select * from business_memories where session_id = %s order by last_used_at desc",
                (session_id,),
            )
            return [_row_to_memory(r) for r in rows]
        except Exception:
            return []

    def list_by_session_and_type(self, session_id: str, type: str) -> list[BusinessMemory]:
        self._ensure_schema()
        try:
            rows = self._client.execute(
                "select * from business_memories where session_id = %s and type = %s order by last_used_at desc",
                (session_id, type),
            )
            return [_row_to_memory(r) for r in rows]
        except Exception:
            return []

    def delete(self, memory_id: str) -> bool:
        self._ensure_schema()
        try:
            self._client.execute(
                "delete from business_memories where memory_id = %s", (memory_id,)
            )
            return True
        except Exception:
            return False

    def delete_by_session(self, session_id: str) -> int:
        self._ensure_schema()
        try:
            rows = self._client.execute(
                "delete from business_memories where session_id = %s returning memory_id",
                (session_id,),
            )
            return len(rows)
        except Exception:
            return 0

    def delete_by_session_and_type(self, session_id: str, type: str) -> int:
        self._ensure_schema()
        try:
            rows = self._client.execute(
                "delete from business_memories where session_id = %s and type = %s returning memory_id",
                (session_id, type),
            )
            return len(rows)
        except Exception:
            return 0
