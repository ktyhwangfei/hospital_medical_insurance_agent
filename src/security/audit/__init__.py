import logging
import os

from src.security.audit.postgresql_store import PostgreSQLAuditLog

logger = logging.getLogger(__name__)


def create_audit_log():
    """创建审计日志实例（使用PostgreSQL，失败时回退到内存实现）"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    
    if not use_memory:
        try:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient
            client = PostgreSQLClient(DATABASE_URL)
            logger.info("Using PostgreSQL audit log")
            return PostgreSQLAuditLog(client)
        except Exception as e:
            logger.warning(f"Failed to create PostgreSQL audit log, falling back to in-memory: {e}")
    
    # 内存实现回退
    from src.security.audit.in_memory import InMemoryAuditLog
    logger.info("Using in-memory audit log")
    return InMemoryAuditLog()


audit_log = create_audit_log()

__all__ = [
    "PostgreSQLAuditLog",
    "audit_log",
]
