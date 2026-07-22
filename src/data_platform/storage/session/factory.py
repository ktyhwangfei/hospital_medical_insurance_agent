"""Session 存储工厂（PostgreSQL / 内存降级）"""

import logging
import os

logger = logging.getLogger(__name__)


def create_session_storage():
    """创建会话存储（PostgreSQL优先，失败时回退到内存实现）"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")

    if not use_memory:
        try:
            from src.data_platform.storage.session.postgres import PostgresSessionStorage
            storage = PostgresSessionStorage()
            storage._get_client()  # 触发连接测试
            logger.info("Using PostgreSQL session storage")
            return storage
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL session storage, falling back to in-memory: {e}")

    from src.data_platform.storage.session.in_memory import InMemorySessionStorage
    logger.info("Using in-memory session storage")
    return InMemorySessionStorage()


# 模块级单例
session_storage = create_session_storage()
