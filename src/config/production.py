"""
生产环境配置文件
包含所有外部服务的连接信息
"""
import os
import logging
import tempfile

logger = logging.getLogger(__name__)

# 仅用于迁移期兼容无来源 release；生产默认必须关闭。
ALLOW_LEGACY_POLICY_RELEASES = os.getenv(
    "ALLOW_LEGACY_POLICY_RELEASES", "0"
).strip().lower() in {"1", "true", "yes", "on"}

# 候选政策 release 发布前的答案验证第二道门禁，默认关闭以兼容存量流程。
POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED = os.getenv(
    "POLICY_RELEASE_ANSWER_VERIFICATION_GATE_ENABLED", "0"
).strip().lower() in {"1", "true", "yes", "on"}

# PostgreSQL 配置
# 注：默认密码 postgres（见 AGENTS.md 生产环境配置；可用 POSTGRES_PASSWORD 覆盖）
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_DB = os.getenv("POSTGRES_DB", "hospital_mcp")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

_redis_auth = f":{REDIS_PASSWORD}@" if REDIS_PASSWORD else ""
REDIS_URL = os.getenv("REDIS_URL", f"redis://{_redis_auth}{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}")

# Milvus 配置
MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
MILVUS_USER = os.getenv("MILVUS_USER", "")
MILVUS_PASSWORD = os.getenv("MILVUS_PASSWORD", "")
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", "")

MILVUS_URI = os.getenv("MILVUS_URI", f"tcp://{MILVUS_HOST}:{MILVUS_PORT}")

# Skills 存储目录
SKILLS_DIR = os.getenv("SKILLS_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "skills"))

# 候选 Skill 仅写入隔离区；默认不启用行为执行 sandbox。
SKILL_CANDIDATE_ROOT = os.getenv(
    "SKILL_CANDIDATE_ROOT",
    os.path.join(tempfile.gettempdir(), "hospital-skill-candidates"),
)
SKILL_CANDIDATE_SANDBOX_ENABLED = os.getenv(
    "SKILL_CANDIDATE_SANDBOX_ENABLED", "0"
).strip().lower() in {"1", "true", "yes", "on"}
SKILL_CANDIDATE_RUNNER_IMAGE = os.getenv(
    "SKILL_CANDIDATE_RUNNER_IMAGE", "hospital-skill-candidate-runner:local"
)
SKILL_CANDIDATE_TIMEOUT_SECONDS = int(
    os.getenv("SKILL_CANDIDATE_TIMEOUT_SECONDS", "10")
)
SKILL_CANDIDATE_MEMORY_LIMIT = os.getenv(
    "SKILL_CANDIDATE_MEMORY_LIMIT", "128m"
)
SKILL_CANDIDATE_CPU_LIMIT = os.getenv("SKILL_CANDIDATE_CPU_LIMIT", "0.5")
SKILL_CANDIDATE_PIDS_LIMIT = int(os.getenv("SKILL_CANDIDATE_PIDS_LIMIT", "32"))

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

# ============================================================
# 数据源模式：决定结算解释等场景使用真实数据库还是模拟数据
# ============================================================
# "mock" (默认) — 使用内存中的模拟数据
# "real_db" — 查询真实 SQL Server 业务数据库
DATA_SOURCE_MODE = os.getenv("DATA_SOURCE_MODE", "mock")
