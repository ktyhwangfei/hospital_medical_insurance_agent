"""内存业务记忆存储实现

开发/测试环境使用，数据不持久化。
"""

from src.data_platform.storage.memory.ports import MemoryStore
from src.runtime.memory.models import BusinessMemory


class InMemoryMemoryStore:
    """内存业务记忆存储"""

    def __init__(self):
        self._memories: dict[str, BusinessMemory] = {}

    def save(self, memory: BusinessMemory) -> BusinessMemory:
        self._memories[memory.memory_id] = memory
        return memory

    def get(self, memory_id: str) -> BusinessMemory | None:
        return self._memories.get(memory_id)

    def list_by_session(self, session_id: str) -> list[BusinessMemory]:
        return [m for m in self._memories.values() if m.session_id == session_id]

    def list_by_session_and_type(self, session_id: str, type: str) -> list[BusinessMemory]:
        return [
            m for m in self._memories.values()
            if m.session_id == session_id and m.type == type
        ]

    def delete(self, memory_id: str) -> bool:
        if memory_id in self._memories:
            del self._memories[memory_id]
            return True
        return False

    def delete_by_session(self, session_id: str) -> int:
        to_delete = [m.memory_id for m in self._memories.values() if m.session_id == session_id]
        for mid in to_delete:
            del self._memories[mid]
        return len(to_delete)

    def delete_by_session_and_type(self, session_id: str, type: str) -> int:
        to_delete = [
            m.memory_id for m in self._memories.values()
            if m.session_id == session_id and m.type == type
        ]
        for mid in to_delete:
            del self._memories[mid]
        return len(to_delete)
