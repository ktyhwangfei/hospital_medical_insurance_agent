"""Memory Manager — 业务记忆生命周期管理

负责记忆的增删改查、过期策略执行、压缩和刷新。
是 Runtime 的核心组件之一。
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.data_platform.storage.memory.ports import MemoryStore
from src.runtime.context.models import RuntimeContext
from src.runtime.memory.models import BusinessMemory, ExpirePolicy, MemoryType

logger = logging.getLogger(__name__)

# 默认时间过期阈值（分钟）
DEFAULT_TIME_EXPIRE_MINUTES = 30


class MemoryManager:
    """业务记忆管理器

    职责：
    - Memory Merge（合并同对象多次观察）
    - Memory Replace（覆盖过期快照）
    - Memory Expire（按策略失效）
    - Memory Refresh（下探语义层刷新）
    - Memory Compression（多轮压缩为结论）
    - Memory Replay（会话恢复时重建）
    """

    def __init__(self, store: MemoryStore, time_expire_minutes: int = DEFAULT_TIME_EXPIRE_MINUTES):
        self._store = store
        self._time_expire_minutes = time_expire_minutes

    # ── 基础 CRUD ──────────────────────────────────────────────────

    def upsert(self, memory: BusinessMemory) -> BusinessMemory:
        """新增或更新记忆。如果同 session + type + ref_id 已存在，则覆盖。"""
        # 检查是否已有同对象记忆
        existing = self._store.list_by_session_and_type(memory.session_id, memory.type.value)
        for e in existing:
            if e.ref_id == memory.ref_id:
                # 覆盖：保留 memory_id，更新快照和元数据
                memory.memory_id = e.memory_id
                memory.created_at = e.created_at  # 保留创建时间
                logger.debug(f"Memory replaced: {memory.memory_id} ({memory.type})")
                break
        return self._store.save(memory)

    def get(self, memory_id: str) -> BusinessMemory | None:
        return self._store.get(memory_id)

    def get_by_session(self, session_id: str) -> list[BusinessMemory]:
        return self._store.list_by_session(session_id)

    def get_by_session_and_type(self, session_id: str, type: MemoryType) -> list[BusinessMemory]:
        return self._store.list_by_session_and_type(session_id, type.value)

    def get_or_resolve(
        self, session_id: str, type: MemoryType, ref_id: str | None = None
    ) -> BusinessMemory | None:
        """获取指定类型的记忆，若 ref_id 提供则精确匹配。"""
        memories = self._store.list_by_session_and_type(session_id, type.value)
        if ref_id is not None:
            for m in memories:
                if m.ref_id == ref_id:
                    return m
            return None
        return memories[0] if memories else None

    # ── 生命周期管理 ────────────────────────────────────────────────

    def expire_by_policy(self, session_id: str, policy: ExpirePolicy) -> int:
        """按过期策略清除记忆。"""
        memories = self._store.list_by_session(session_id)
        to_delete = [m.memory_id for m in memories if m.expire_policy == policy]
        count = 0
        for mid in to_delete:
            if self._store.delete(mid):
                count += 1
        logger.info(f"Expired {count} memories by policy {policy.value} for session {session_id}")
        return count

    def expire_on_topic_change(self, session_id: str, new_topic: str) -> int:
        """话题切换时，清除 TOPIC 策略的记忆。"""
        # 同时清除 SESSION 策略的记忆（如果会话已结束）
        count = self.expire_by_policy(session_id, ExpirePolicy.TOPIC)
        logger.info(f"Topic change to '{new_topic}': expired {count} memories for session {session_id}")
        return count

    def expire_by_time(self, session_id: str) -> int:
        """清除超过时间阈值的 TIME 策略记忆。

        检查每条 TIME 策略记忆的 last_used_at，如果超过配置的阈值则删除。
        """
        from datetime import datetime

        memories = self._store.list_by_session(session_id)
        now = datetime.now(UTC)
        to_delete = []

        for m in memories:
            if m.expire_policy != ExpirePolicy.TIME:
                continue
            try:
                # 解析 last_used_at（ISO 格式）
                last_used = datetime.fromisoformat(m.last_used_at.replace("Z", "+00:00"))
                elapsed_minutes = (now - last_used).total_seconds() / 60
                if elapsed_minutes > self._time_expire_minutes:
                    to_delete.append(m.memory_id)
            except (ValueError, TypeError):
                # 解析失败，保守处理：不过期
                continue

        count = 0
        for mid in to_delete:
            if self._store.delete(mid):
                count += 1

        if count > 0:
            logger.info(
                f"Expired {count} TIME-policy memories for session {session_id} "
                f"(threshold={self._time_expire_minutes}min)"
            )
        return count

    def invalidate_object(self, session_id: str, object_kind: str) -> int:
        """使指定类型的对象记忆失效。"""
        return self._store.delete_by_session_and_type(session_id, object_kind)

    def compress(self, session_id: str, keep_types: list[MemoryType] | None = None) -> None:
        """压缩会话记忆：将低重要性记忆合并为摘要。

        当前实现：简单删除 importance < 0.3 的非 STICKY 记忆。
        后续可扩展为调用模型服务生成摘要。
        """
        memories = self._store.list_by_session(session_id)
        keep_type_values = {t.value for t in (keep_types or [])}
        to_delete = []
        for m in memories:
            if m.expire_policy == ExpirePolicy.STICKY:
                continue
            if keep_type_values and m.type.value in keep_type_values:
                continue
            if m.importance < 0.3:
                to_delete.append(m.memory_id)
        for mid in to_delete:
            self._store.delete(mid)
        logger.info(f"Compressed {len(to_delete)} low-importance memories for session {session_id}")

    def refresh(self, memory: BusinessMemory, new_snapshot: dict[str, Any]) -> BusinessMemory:
        """刷新记忆快照（版本 +1）。"""
        memory.object_snapshot = new_snapshot
        memory.version += 1
        return self._store.save(memory)

    # ── 会话恢复 ────────────────────────────────────────────────────

    def replay_session(self, session_id: str) -> list[BusinessMemory]:
        """恢复会话的所有记忆（按 last_used_at 排序）。"""
        return self._store.list_by_session(session_id)

    def build_context_memories(
        self, context: RuntimeContext
    ) -> list[BusinessMemory]:
        """为当前请求构建记忆上下文（用于注入 RuntimeContext）。"""
        if not context.session_id:
            return []
        # 先清理时间过期的记忆
        self.expire_by_time(context.session_id)
        memories = self._store.list_by_session(context.session_id)
        # 按 importance + recency 排序
        memories.sort(key=lambda m: (m.importance, m.last_used_at), reverse=True)
        return memories
