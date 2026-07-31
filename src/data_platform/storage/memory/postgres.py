"""PostgreSQL 业务记忆存储实现

生产环境使用，数据持久化到 PostgreSQL。
"""

import json
from datetime import UTC, datetime
from typing import Any

from src.data_platform.storage.memory.ports import MemoryStore
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType


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

    def __init__(self, database_url: str):
        self._client = PostgreSQLClient(database_url)

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
        try:
            self._client.execute(sql, _memory_to_row(memory))
        except RuntimeError:
            pass
        return memory

    def get(self, memory_id: str) -> BusinessMemory | None:
        try:
            rows = self._client.execute(
                "select * from business_memories where memory_id = %s", (memory_id,)
            )
            if not rows:
                return None
            return _row_to_memory(rows[0])
        except RuntimeError:
            return None

    def list_by_session(self, session_id: str) -> list[BusinessMemory]:
        try:
            rows = self._client.execute(
                "select * from business_memories where session_id = %s order by last_used_at desc",
                (session_id,),
            )
            return [_row_to_memory(r) for r in rows]
        except RuntimeError:
            return []

    def list_by_session_and_type(self, session_id: str, type: str) -> list[BusinessMemory]:
        try:
            rows = self._client.execute(
                "select * from business_memories where session_id = %s and type = %s order by last_used_at desc",
                (session_id, type),
            )
            return [_row_to_memory(r) for r in rows]
        except RuntimeError:
            return []

    def delete(self, memory_id: str) -> bool:
        try:
            self._client.execute(
                "delete from business_memories where memory_id = %s", (memory_id,)
            )
            return True
        except RuntimeError:
            return False

    def delete_by_session(self, session_id: str) -> int:
        try:
            rows = self._client.execute(
                "delete from business_memories where session_id = %s returning memory_id",
                (session_id,),
            )
            return len(rows)
        except RuntimeError:
            return 0

    def delete_by_session_and_type(self, session_id: str, type: str) -> int:
        try:
            rows = self._client.execute(
                "delete from business_memories where session_id = %s and type = %s returning memory_id",
                (session_id, type),
            )
            return len(rows)
        except RuntimeError:
            return 0
