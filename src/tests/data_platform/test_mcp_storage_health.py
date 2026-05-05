from src.config.mcp import McpSettings
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage
from src.data_platform.storage.mcp.redis_cache import RedisMcpCache


def test_mcp_settings_reads_defaults():
    settings = McpSettings()

    assert settings.postgres_dsn == "postgresql://localhost:5432/hospital_mcp"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.connection_timeout_seconds == 10


def test_postgres_storage_reports_unhealthy_without_driver_connection():
    storage = PostgresMcpStorage(dsn="postgresql://invalid:5432/missing")

    health = storage.health()

    assert health.postgres_available is False
    assert health.details["backend"] == "postgresql"


def test_redis_cache_reports_unhealthy_without_driver_connection():
    cache = RedisMcpCache(redis_url="redis://invalid:6379/0")

    health = cache.health()

    assert health.redis_available is False
    assert health.details["backend"] == "redis"
