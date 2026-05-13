"""
错误码知识库工厂
"""
import logging
import os

logger = logging.getLogger(__name__)


def create_knowledge_store():
    """创建知识存储实例"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    
    if not use_memory:
        try:
            from src.knowledge_extension.knowledge.postgres import PostgresKnowledgeStore
            store = PostgresKnowledgeStore()
            store.seed_data()
            # 有条件地包裹缓存层
            from src.data_platform.cache import create_cache_client_optional
            from src.data_platform.cache.config import CACHE_TTL_KNOWLEDGE, CACHE_ENABLED_KNOWLEDGE
            from src.knowledge_extension.knowledge.cached import CachedKnowledgeStore
            cache = create_cache_client_optional()
            if cache is not None and CACHE_ENABLED_KNOWLEDGE == "1":
                logger.info("Wrapping PostgresKnowledgeStore with CachedKnowledgeStore")
                return CachedKnowledgeStore(store, cache, CACHE_TTL_KNOWLEDGE)
            logger.info("Using PostgreSQL knowledge store (no cache)")
            return store
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL knowledge store, falling back to in-memory: {e}")
    
    # 返回内存实现的包装类
    from src.knowledge_extension.knowledge.in_memory import ERROR_CODE_KNOWLEDGE
    
    class InMemoryKnowledgeWrapper:
        def get_error_code(self, error_code: str):
            return ERROR_CODE_KNOWLEDGE.get(error_code)
        
        def list_error_codes(self):
            return [
                {'error_code': k, **v}
                for k, v in ERROR_CODE_KNOWLEDGE.items()
            ]
    
    logger.info("Using in-memory knowledge store")
    return InMemoryKnowledgeWrapper()
