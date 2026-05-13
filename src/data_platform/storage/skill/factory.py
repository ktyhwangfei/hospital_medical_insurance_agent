import logging
import os

from src.data_platform.storage.skill.ports import SkillStorage

logger = logging.getLogger(__name__)


def create_skill_storage() -> SkillStorage:
    """创建技能存储实例（默认使用PostgreSQL，失败时回退到内存实现）"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    
    if not use_memory:
        try:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.skill.postgres import PostgresSkillStorage
            storage = PostgresSkillStorage(DATABASE_URL)

            # 尝试包装缓存 (read-through + write-through invalidate)
            from src.data_platform.cache import create_cache_client_optional
            from src.data_platform.cache.config import CACHE_TTL_SKILL, CACHE_ENABLED_SKILL
            from src.data_platform.storage.skill.cached import CachedSkillStorage
            cache = create_cache_client_optional()
            if cache is not None and CACHE_ENABLED_SKILL == "1":
                logger.info("Wrapping PostgresSkillStorage with CachedSkillStorage")
                return CachedSkillStorage(storage, cache, CACHE_TTL_SKILL)

            logger.info("Using PostgreSQL skill storage")
            return storage
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL skill storage, falling back to in-memory: {e}")
    
    from src.data_platform.storage.skill.in_memory import InMemorySkillStorage
    logger.info("Using in-memory skill storage")
    return InMemorySkillStorage()
