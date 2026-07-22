"""
指标存储工厂函数

遵循 storage/skill/factory.py 的 create_skill_storage() 模式。
默认尝试 PostgreSQL 实现（待实现），失败时回退到 InMemoryIndicatorStorage。
通过 USE_MEMORY_STORAGE 环境变量强制使用内存实现。
"""
import logging
import os

from src.data_platform.storage.indicator.in_memory import InMemoryIndicatorStorage

logger = logging.getLogger(__name__)


def create_indicator_storage():
    """创建指标存储实例

    默认使用 PostgreSQL，回退到内存实现。
    USE_MEMORY_STORAGE=1 时直接使用内存实现。

    Returns:
        InMemoryIndicatorStorage 实例（当前仅内存实现，PostgreSQL 待后续补充）
    """
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")

    if not use_memory:
        try:
            # PostgreSQL 实现待后续补充
            # from src.config.production import DATABASE_URL
            # from src.data_platform.storage.indicator.postgres import PostgresIndicatorStorage
            # storage = PostgresIndicatorStorage(DATABASE_URL)
            # logger.info("Using PostgreSQL indicator storage")
            # return storage
            raise NotImplementedError("PostgreSQL indicator storage not yet implemented")
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL indicator storage, falling back to in-memory: {e}")

    logger.info("Using in-memory indicator storage")
    return InMemoryIndicatorStorage()
