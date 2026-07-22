"""Session 存储端口定义"""

from typing import Protocol

from src.data_platform.storage.session.models import SessionStorageHealth
from src.domain.session.models import Session


class SessionStorage(Protocol):
    """会话存储接口（ports/adapter 模式）"""

    def create_or_update_session(
        self, session_id: str, user_id: str, role: str = ""
    ) -> Session: ...

    def get_session(self, session_id: str) -> Session | None: ...

    def list_sessions_by_user(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[Session]: ...

    def list_sessions(
        self, limit: int = 50, offset: int = 0
    ) -> list[Session]: ...

    def health(self) -> SessionStorageHealth: ...
