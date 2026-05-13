"""测试 create_cache_client_optional() 安全工厂函数

场景:
  1. CACHE_ENABLED=0 → 返回 None
  2. CACHE_ENABLED=1 + create_cache_client 成功 → 返回 CacheClient
  3. CACHE_ENABLED=1 + create_cache_client 失败 → 返回 None（异常不传播）
"""
import os
from unittest.mock import patch

from src.data_platform.cache.ports import CacheClient


def _clean_env():
    """清理环境变量，避免干扰其他测试"""
    os.environ.pop("CACHE_ENABLED", None)


def test_cache_disabled_returns_none():
    """CACHE_ENABLED=0 → create_cache_client_optional() 返回 None"""
    _clean_env()
    os.environ["CACHE_ENABLED"] = "0"
    from src.data_platform.cache import create_cache_client_optional

    result = create_cache_client_optional()

    assert result is None
    _clean_env()


def test_create_failure_returns_none():
    """CACHE_ENABLED=1 但 create_cache_client 抛出异常 → 返回 None（异常不传播）"""
    _clean_env()
    os.environ["CACHE_ENABLED"] = "1"

    from src.data_platform.cache import create_cache_client_optional

    with patch("src.data_platform.cache.create_cache_client", side_effect=RuntimeError("Redis fail")):
        result = create_cache_client_optional()

        assert result is None

    _clean_env()


def test_cache_enabled_returns_cache_client():
    """CACHE_ENABLED=1 + create_cache_client 成功 → 返回 CacheClient 实例"""
    _clean_env()
    os.environ["CACHE_ENABLED"] = "1"

    from src.data_platform.cache import create_cache_client_optional

    mock_client = object()  # 使用 object() 冒充 CacheClient，只需验证返回值非 None 即可
    with patch("src.data_platform.cache.create_cache_client", return_value=mock_client):
        result = create_cache_client_optional()

        assert result is mock_client
        assert isinstance(result, object)  # 确保返回了 mock 对象（非 None）

    _clean_env()


def test_cache_enabled_default_is_enabled():
    """CACHE_ENABLED 未设置时默认启用（CACHE_ENABLED 默认 "1"）"""
    _clean_env()
    # 不设置 CACHE_ENABLED，应该默认为启用状态
    from src.data_platform.cache import create_cache_client_optional

    mock_client = object()
    with patch("src.data_platform.cache.create_cache_client", return_value=mock_client):
        result = create_cache_client_optional()

        assert result is mock_client

    _clean_env()


def test_cache_enabled_variants():
    """CACHE_ENABLED 接受多种 true 值变体"""
    _clean_env()
    from src.data_platform.cache import create_cache_client_optional

    for val in ("true", "yes", "1"):
        os.environ["CACHE_ENABLED"] = val
        with patch("src.data_platform.cache.create_cache_client", return_value=object()):
            result = create_cache_client_optional()
            assert result is not None, f"CACHE_ENABLED={val} 应启用缓存"

    _clean_env()
