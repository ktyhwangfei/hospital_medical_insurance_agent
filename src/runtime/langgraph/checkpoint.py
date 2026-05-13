import logging

from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)


def get_checkpointer():
    """获取检查点实例（优先 PostgreSQL，失败回退 MemorySaver）"""
    try:
        from src.runtime.langgraph.postgresql_checkpointer import PostgresCheckpointer
        cp = PostgresCheckpointer()
        logger.info("Using PostgreSQL checkpointer")
        return cp
    except Exception as e:
        logger.warning(f"Failed to create PostgreSQL checkpointer: {e}, fallback to MemorySaver")
        return MemorySaver()


# 保留向后兼容
def get_memory_checkpointer() -> MemorySaver:
    return MemorySaver()
