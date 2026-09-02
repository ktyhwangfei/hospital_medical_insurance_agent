"""Policy QA 轨迹持久化存储

Issue #30 §3.1：每轮 QA 一行可重放公开快照。
- payload 只存公开契约字段（context_need / memory_updates / result / attempt_count / halt_reason），
  内部推理与提示词不入轨迹；
- 失败轮也落一行（answer_status=unavailable，无 result），保证对话序列完整；
- 读取方按 session 所有权校验后回放（见 runtime/policy_qa/session_lifecycle.py）。

遵循 ports/adapter 模式：默认 PostgreSQL，USE_MEMORY_STORAGE=1 回退内存。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Protocol

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

_TRAJECTORY_DDL = """
CREATE TABLE IF NOT EXISTS policy_qa_trajectories (
    qa_turn_id VARCHAR(80) PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'default',
    settlement_id VARCHAR(64) NOT NULL DEFAULT '',
    question TEXT NOT NULL DEFAULT '',
    answer_status VARCHAR(32) NOT NULL DEFAULT 'unavailable',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_traj_session_created
    ON policy_qa_trajectories(session_id, created_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TrajectoryStorage(Protocol):
    """轨迹存储端口"""

    def append_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        """写入一轮轨迹（幂等：同 qa_turn_id 覆盖）"""
        ...

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """按会话读取全部轮次（created_at 升序）"""
        ...

    def count_by_session(self, session_id: str) -> int:
        """会话轮次数（会话列表摘要用）"""
        ...


class InMemoryTrajectoryStorage:
    def __init__(self):
        self._turns: dict[str, dict[str, Any]] = {}

    def append_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        record = dict(turn)
        record.setdefault("created_at", _now())
        self._turns[str(record["qa_turn_id"])] = record
        return record

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        turns = [t for t in self._turns.values() if t.get("session_id") == session_id]
        turns.sort(key=lambda t: str(t.get("created_at", "")))
        return turns

    def count_by_session(self, session_id: str) -> int:
        return sum(1 for t in self._turns.values() if t.get("session_id") == session_id)


class PostgresTrajectoryStorage:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            client = PostgreSQLClient(self._database_url)
            client.execute(_TRAJECTORY_DDL)
            self._client = client
        return self._client

    def append_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        client = self._get_client()
        record = dict(turn)
        record.setdefault("created_at", _now())
        payload = record.get("payload") or {}
        client.execute(
            """INSERT INTO policy_qa_trajectories
                   (qa_turn_id, session_id, user_id, tenant_id, settlement_id,
                    question, answer_status, payload, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (qa_turn_id) DO UPDATE SET
                   answer_status = EXCLUDED.answer_status,
                   payload = EXCLUDED.payload""",
            (
                record["qa_turn_id"],
                record["session_id"],
                record.get("user_id", ""),
                record.get("tenant_id", "default"),
                record.get("settlement_id", ""),
                record.get("question", ""),
                record.get("answer_status", "unavailable"),
                json.dumps(payload, ensure_ascii=False),
                record["created_at"],
            ),
        )
        return record

    def list_by_session(self, session_id: str) -> list[dict[str, Any]]:
        client = self._get_client()
        rows = client.execute(
            """SELECT qa_turn_id, session_id, user_id, tenant_id, settlement_id,
                      question, answer_status, payload, created_at
               FROM policy_qa_trajectories
               WHERE session_id = %s ORDER BY created_at ASC""",
            (session_id,),
        )
        return [_row_to_turn(r) for r in rows]

    def count_by_session(self, session_id: str) -> int:
        client = self._get_client()
        rows = client.execute(
            "SELECT COUNT(*) AS cnt FROM policy_qa_trajectories WHERE session_id = %s",
            (session_id,),
        )
        return int(rows[0]["cnt"]) if rows else 0


def _row_to_turn(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = {}
    created_at = row.get("created_at")
    return {
        "qa_turn_id": row["qa_turn_id"],
        "session_id": row["session_id"],
        "user_id": row.get("user_id", ""),
        "tenant_id": row.get("tenant_id", "default"),
        "settlement_id": row.get("settlement_id", ""),
        "question": row.get("question", ""),
        "answer_status": row.get("answer_status", "unavailable"),
        "payload": payload if isinstance(payload, dict) else {},
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
    }


def create_trajectory_storage() -> TrajectoryStorage:
    """创建轨迹存储（PostgreSQL 优先，失败回退内存）"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if not use_memory:
        try:
            storage = PostgresTrajectoryStorage()
            storage._get_client()
            logger.info("Using PostgreSQL trajectory storage")
            return storage
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL trajectory storage, falling back to in-memory: {e}")
    logger.info("Using in-memory trajectory storage")
    return InMemoryTrajectoryStorage()


# 模块级单例（与 session factory 惯例一致）
trajectory_storage = create_trajectory_storage()
