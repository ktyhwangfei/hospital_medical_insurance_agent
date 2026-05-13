"""测试 create_cache_client() 的 Redis 故障回退逻辑

场景:
  1. CACHE_FAIL_OPEN=1 (default) + Redis 失败 → InMemoryCacheClient
  2. CACHE_FAIL_OPEN=0 + Redis 失败 → 抛出异常
  3. Redis 可用 → RedisCacheClient
"""
import os
from unittest.mock import patch

import pytest

from src.data_platform.cache import create_cache_client
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.cache.redis_cache import RedisCacheClient


def _clean_env():
    """清理 CACHE_FAIL_OPEN 环境变量，避免干扰其他测试"""
    os.environ.pop("CACHE_FAIL_OPEN", None)


def test_fail_open_fallback_to_in_memory():
    """CACHE_FAIL_OPEN=1 且 Redis 不可用 → 返回 InMemoryCacheClient 且可正常读写"""
    _clean_env()
    os.environ["CACHE_FAIL_OPEN"] = "1"

    with patch("src.data_platform.cache.redis_cache.RedisCacheClient") as mock_cls:
        mock_cls.side_effect = ConnectionError("Redis unavailable")

        result = create_cache_client()

        assert isinstance(result, InMemoryCacheClient)
        # 验证回退后的 InMemoryCacheClient 可正常读写
        result.set_json("test_key", {"ok": True}, 60)
        assert result.get_json("test_key") == {"ok": True}

    _clean_env()


def test_fail_closed_raises_exception():
    """CACHE_FAIL_OPEN=0 且 Redis 不可用 → 抛出异常"""
    _clean_env()
    os.environ["CACHE_FAIL_OPEN"] = "0"

    with patch("src.data_platform.cache.redis_cache.RedisCacheClient") as mock_cls:
        mock_cls.side_effect = ConnectionError("Redis unavailable")

        with pytest.raises(Exception) as exc_info:
            create_cache_client()

        assert "Redis" in str(exc_info.value) or "Redis" in str(exc_info._excinfo[1])

    _clean_env()


def test_redis_available_returns_redis_cache():
    """Redis 可用 → 返回 RedisCacheClient 实例"""
    _clean_env()
    os.environ["CACHE_FAIL_OPEN"] = "1"

    with patch("src.data_platform.cache.redis_cache.RedisCacheClient") as mock_cls:
        mock_instance = mock_cls.return_value

        result = create_cache_client()

        assert result is mock_instance
        assert not isinstance(result, InMemoryCacheClient)

    _clean_env()
