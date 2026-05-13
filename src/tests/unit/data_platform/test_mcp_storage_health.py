import pytest
from pydantic import ValidationError

from src.config.mcp import McpSettings, load_mcp_settings
from src.data_platform.persistence.executors import UnavailableDatabaseExecutor
from src.data_platform.persistence.models import DatabaseBackend
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage
from src.data_platform.storage.mcp.models import McpStorageHealthStatus
from src.data_platform.storage.mcp.redis_cache import RedisMcpCache


def test_mcp_settings_reads_defaults():
    settings = McpSettings()

    assert settings.postgres_dsn == "postgresql://localhost:5432/hospital_mcp"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.connection_timeout_seconds == 10
    assert settings.persistence_backend == "in_memory"
    assert settings.cache_backend == "in_memory"
    assert settings.database_schema_auto_init is False


def test_load_mcp_settings_reads_environment_overrides(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_POSTGRES_DSN", "postgresql://db:5432/mcp")
    monkeypatch.setenv("MCP_REDIS_URL", "redis://cache:6379/1")
    monkeypatch.setenv("MCP_CONNECTION_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("MCP_PERSISTENCE_BACKEND", "postgresql")
    monkeypatch.setenv("MCP_CACHE_BACKEND", "redis")
    monkeypatch.setenv("MCP_DATABASE_SCHEMA_AUTO_INIT", "true")

    settings = load_mcp_settings()

    assert settings.postgres_dsn == "postgresql://db:5432/mcp"
    assert settings.redis_url == "redis://cache:6379/1"
    assert settings.connection_timeout_seconds == 15
    assert settings.persistence_backend == "postgresql"
    assert settings.cache_backend == "redis"
    assert settings.database_schema_auto_init is True


def test_load_mcp_settings_rejects_non_integer_timeout(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_CONNECTION_TIMEOUT_SECONDS", "not-an-integer")

    with pytest.raises(ValidationError):
        load_mcp_settings()


def test_postgres_storage_reports_unhealthy_without_driver_connection():
    executor = UnavailableDatabaseExecutor(DatabaseBackend.POSTGRESQL, "driver_not_installed")
    storage = PostgresMcpStorage(executor=executor)

    health = storage.health()

    assert health.status == McpStorageHealthStatus.UNHEALTHY
    assert health.postgres_available is False
    assert health.redis_available is False
    assert health.details["backend"] == "postgresql"
    assert health.details["reason"] == "driver_not_installed"


def test_redis_cache_reports_healthy_with_in_memory_fallback():
    cache = RedisMcpCache()

    health = cache.health()

    assert health.status == McpStorageHealthStatus.HEALTHY
    assert health.postgres_available is False
    assert health.redis_available is True
    assert health.details["backend"] == "in_memory"
