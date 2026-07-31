"""Memory 存储端口定义

遵循 ports/adapter 模式，支持 PostgreSQL / 内存双实现。
"""

from typing import Protocol

from src.runtime.memory.models import BusinessMemory


class MemoryStore(Protocol):
    """业务记忆存储接口"""

    def save(self, memory: BusinessMemory) -> BusinessMemory: ...

    def get(self, memory_id: str) -> BusinessMemory | None: ...

    def list_by_session(self, session_id: str) -> list[BusinessMemory]: ...

    def list_by_session_and_type(
        self, session_id: str, type: str
    ) -> list[BusinessMemory]: ...

    def delete(self, memory_id: str) -> bool: ...

    def delete_by_session(self, session_id: str) -> int: ...

    def delete_by_session_and_type(self, session_id: str, type: str) -> int: ...
