"""Memory 存储工厂

PostgreSQL 优先，失败时回退到内存实现。
通过 USE_MEMORY_STORAGE 环境变量控制。
"""

import logging
import os

from src.data_platform.storage.memory.ports import MemoryStore

logger = logging.getLogger(__name__)


def create_memory_store() -> MemoryStore:
    """创建业务记忆存储实例（PostgreSQL优先，失败时回退到内存实现）"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")

    if not use_memory:
        try:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.memory.postgres import PostgresMemoryStore
            store = PostgresMemoryStore(DATABASE_URL)
            logger.info("Using PostgreSQL memory store")
            return store
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL memory store, falling back to in-memory: {e}")

    from src.data_platform.storage.memory.in_memory import InMemoryMemoryStore
    logger.info("Using in-memory memory store")
    return InMemoryMemoryStore()


# 模块级单例
memory_store = create_memory_store()
