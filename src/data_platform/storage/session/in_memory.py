"""内存实现的会话存储（降级/测试用）"""

import logging
from datetime import datetime, timezone

from src.data_platform.storage.session.models import (
    SessionStorageHealth,
    SessionStorageHealthStatus,
)
from src.domain.session.models import Session

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemorySessionStorage:
    """内存会话存储实现"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def create_or_update_session(
        self, session_id: str, user_id: str, role: str = ""
    ) -> Session:
        now = _now()
        if session_id in self._sessions:
            existing = self._sessions[session_id]
            session = Session(
                session_id=session_id,
                user_id=user_id,
                role=role or existing.role,
                # 生命周期状态不随活跃刷新重置（Issue #30 §3.2）
                status=existing.status,
                status_reason=existing.status_reason,
                status_updated_at=existing.status_updated_at,
                created_at=existing.created_at,
                last_active=now,
            )
        else:
            session = Session(
                session_id=session_id,
                user_id=user_id,
                role=role,
                created_at=now,
                last_active=now,
            )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_sessions_by_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[Session]:
        result = [
            s for s in self._sessions.values() if s.user_id == user_id
        ]
        result.sort(key=lambda s: s.last_active, reverse=True)
        return result[offset:offset + limit]

    def list_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> list[Session]:
        result = list(self._sessions.values())
        result.sort(key=lambda s: s.last_active, reverse=True)
        return result[offset:offset + limit]

    def update_session_status(
        self, session_id: str, status: str, reason: str = ""
    ) -> Session | None:
        existing = self._sessions.get(session_id)
        if existing is None:
            return None
        updated = existing.model_copy(update={
            "status": status,
            "status_reason": reason,
            "status_updated_at": _now(),
        })
        self._sessions[session_id] = updated
        return updated

    def health(self) -> SessionStorageHealth:
        return SessionStorageHealth(
            status=SessionStorageHealthStatus.HEALTHY,
            message="In-memory session storage is healthy",
            session_count=len(self._sessions),
        )
