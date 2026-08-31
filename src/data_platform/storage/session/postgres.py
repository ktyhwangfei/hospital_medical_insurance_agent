"""PostgreSQL 实现的会话存储"""

import logging
from datetime import datetime, timezone

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.session.models import (
    SessionStorageHealth,
    SessionStorageHealthStatus,
)
from src.domain.session.models import Session

logger = logging.getLogger(__name__)

_SESSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(128) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active DESC);
"""

# Issue #30 §3.2：会话生命周期状态列（旧库需 ALTER 补列，与 CREATE 双写）
_SESSION_STATUS_DDL = """
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'active';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS status_reason TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_session(row: dict) -> Session:
    def _iso(key: str) -> str:
        val = row.get(key)
        return val.isoformat() if hasattr(val, "isoformat") else str(val or "")

    return Session(
        session_id=row["session_id"],
        user_id=row["user_id"],
        role=row.get("role", ""),
        status=row.get("status") or "active",
        status_reason=row.get("status_reason") or "",
        status_updated_at=_iso("status_updated_at"),
        created_at=_iso("created_at"),
        last_active=_iso("last_active"),
    )


class PostgresSessionStorage:
    """PostgreSQL 会话存储实现"""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
                logger.info("PostgreSQL session storage initialized")
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL session storage: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(_SESSION_TABLE_DDL)
            self._client.execute(_SESSION_STATUS_DDL)
        except Exception as e:
            logger.warning(f"Failed to ensure sessions schema: {e}")

    def create_or_update_session(
        self, session_id: str, user_id: str, role: str = ""
    ) -> Session:
        client = self._get_client()
        now = _now()
        try:
            client.execute(
                """INSERT INTO sessions (session_id, user_id, role, created_at, last_active)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (session_id) DO UPDATE SET
                       last_active = EXCLUDED.last_active,
                       role = EXCLUDED.role""",
                (session_id, user_id, role, now, now),
            )
        except Exception as e:
            logger.warning(f"Failed to upsert session {session_id}: {e}")
        # 状态列：新建回读 DEFAULT，已存在时 ON CONFLICT 未触碰状态，回读保持原值
        rows = client.execute(
            "SELECT * FROM sessions WHERE session_id = %s", (session_id,)
        )
        return _row_to_session(rows[0]) if rows else Session(
            session_id=session_id, user_id=user_id, role=role,
            created_at=now, last_active=now,
        )

    def get_session(self, session_id: str) -> Session | None:
        try:
            client = self._get_client()
            rows = client.execute(
                "SELECT * FROM sessions WHERE session_id = %s", (session_id,)
            )
            if not rows:
                return None
            return _row_to_session(rows[0])
        except Exception as e:
            logger.warning(f"Failed to get session {session_id}: {e}")
            return None

    def list_sessions_by_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[Session]:
        try:
            client = self._get_client()
            rows = client.execute(
                "SELECT * FROM sessions WHERE user_id = %s ORDER BY last_active DESC LIMIT %s OFFSET %s",
                (user_id, limit, offset),
            )
            return [_row_to_session(r) for r in rows]
        except Exception as e:
            logger.warning(f"Failed to list sessions for user {user_id}: {e}")
            return []

    def list_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> list[Session]:
        try:
            client = self._get_client()
            rows = client.execute(
                "SELECT * FROM sessions ORDER BY last_active DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            return [_row_to_session(r) for r in rows]
        except Exception as e:
            logger.warning(f"Failed to list sessions: {e}")
            return []

    def update_session_status(
        self, session_id: str, status: str, reason: str = ""
    ) -> Session | None:
        try:
            client = self._get_client()
            client.execute(
                """UPDATE sessions
                   SET status = %s, status_reason = %s, status_updated_at = CURRENT_TIMESTAMP
                   WHERE session_id = %s""",
                (status, reason or None, session_id),
            )
            return self.get_session(session_id)
        except Exception as e:
            logger.warning(f"Failed to update session status {session_id}: {e}")
            return None

    def health(self) -> SessionStorageHealth:
        try:
            client = self._get_client()
            rows = client.execute("SELECT COUNT(*) as cnt FROM sessions")
            count = rows[0]["cnt"] if rows else 0
            return SessionStorageHealth(
                status=SessionStorageHealthStatus.HEALTHY,
                message="PostgreSQL session storage is healthy",
                session_count=count,
            )
        except Exception as e:
            return SessionStorageHealth(
                status=SessionStorageHealthStatus.UNHEALTHY,
                message=f"PostgreSQL session storage error: {e}",
            )
