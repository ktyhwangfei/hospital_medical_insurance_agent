"""
生产环境配置文件
包含所有外部服务的连接信息
"""
import os
import logging

logger = logging.getLogger(__name__)

# PostgreSQL 配置
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "123456")
POSTGRES_DB = os.getenv("POSTGRES_DB", "hospital_mcp")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

REDIS_URL = os.getenv("REDIS_URL", f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

# Milvus 配置
MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19121"))

MILVUS_URI = os.getenv("MILVUS_URI", f"tcp://{MILVUS_HOST}:{MILVUS_PORT}")

# Skills 存储目录
SKILLS_DIR = os.getenv("SKILLS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "skills"))

# 日志配置
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# 连接池配置
POSTGRES_MIN_CONNECTIONS = int(os.getenv("POSTGRES_MIN_CONNECTIONS", "1"))
POSTGRES_MAX_CONNECTIONS = int(os.getenv("POSTGRES_MAX_CONNECTIONS", "10"))

REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "10"))

# 重试配置
DB_RETRY_ATTEMPTS = int(os.getenv("DB_RETRY_ATTEMPTS", "3"))
DB_RETRY_DELAY = float(os.getenv("DB_RETRY_DELAY", "1.0"))


def get_database_url() -> str:
    """获取数据库连接URL"""
    return DATABASE_URL


def get_redis_url() -> str:
    """获取Redis连接URL"""
    return REDIS_URL


def get_milvus_uri() -> str:
    """获取Milvus连接URI"""
    return MILVUS_URI


def get_skills_dir() -> str:
    """获取技能存储目录"""
    os.makedirs(SKILLS_DIR, exist_ok=True)
    return SKILLS_DIR


def log_config() -> None:
    """记录当前配置（隐藏敏感信息）"""
    logger.info("=== 系统配置 ===")
    logger.info(f"PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
    logger.info(f"Redis: {REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")
    logger.info(f"Milvus: {MILVUS_HOST}:{MILVUS_PORT}")
    logger.info(f"Skills目录: {SKILLS_DIR}")
    logger.info(f"日志级别: {LOG_LEVEL}")
    logger.info("================")


# ============================================================
# 缓存配置
# ============================================================
# 全局缓存开关
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "1")
# Redis 故障时回退到 InMemory 缓存
CACHE_FAIL_OPEN = os.getenv("CACHE_FAIL_OPEN", "1")
# 缓存键全局前缀（多租户隔离）
CACHE_KEY_PREFIX = os.getenv("CACHE_KEY_PREFIX", "")

# 各域 TTL（秒）
CACHE_TTL_SKILL = os.getenv("CACHE_TTL_SKILL", "3600")         # 1h
CACHE_TTL_MCP = os.getenv("CACHE_TTL_MCP", "3600")             # 1h
CACHE_TTL_KNOWLEDGE = os.getenv("CACHE_TTL_KNOWLEDGE", "7200") # 2h
CACHE_TTL_RULE = os.getenv("CACHE_TTL_RULE", "7200")           # 2h
CACHE_TTL_ASSET = os.getenv("CACHE_TTL_ASSET", "1800")         # 30m
CACHE_TTL_APPEAL = os.getenv("CACHE_TTL_APPEAL", "7200")       # 2h

# 各域缓存开关
CACHE_ENABLED_SKILL = os.getenv("CACHE_ENABLED_SKILL", "1")
CACHE_ENABLED_MCP = os.getenv("CACHE_ENABLED_MCP", "1")
CACHE_ENABLED_KNOWLEDGE = os.getenv("CACHE_ENABLED_KNOWLEDGE", "1")
CACHE_ENABLED_RULE = os.getenv("CACHE_ENABLED_RULE", "1")
CACHE_ENABLED_ASSET = os.getenv("CACHE_ENABLED_ASSET", "1")
CACHE_ENABLED_APPEAL = os.getenv("CACHE_ENABLED_APPEAL", "1")
