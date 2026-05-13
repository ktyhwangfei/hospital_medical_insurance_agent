"""
缓存存储基类 — CachedStorageBase

所有域名缓存代理（Skill / MCP / Knowledge / Asset / Rule / Appeal）的公共基类。
提供统一的关键字构建、JSON 安全序列化、熔断器、安全读写及监控计数。
"""
import logging
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from src.data_platform.cache.config import (
    CACHE_KEY_PREFIX,
    CIRCUIT_BREAKER_THRESHOLD,
    CIRCUIT_BREAKER_WINDOW,
)
from src.data_platform.cache.ports import CacheClient

logger = logging.getLogger(__name__)


class CachedStorageBase:
    """缓存存储基类

    提供读穿透（read-through）缓存模式的全部公共逻辑，包含：
    - 缓存键构建 (make_key)
    - JSON 安全序列化 (json_safe_deep)
    - 熔断器 (circuit breaker)
    - 安全读写 (safe_get/set/delete)
    - 读穿透 (cached_read)
    - 写入失效 (invalidate_keys)
    - 健康监控 (health)
    """

    def __init__(
        self,
        cache: CacheClient,
        domain: str,
        default_ttl: int,
        enabled: bool = True,
    ):
        self._cache = cache
        self._domain = domain
        self._default_ttl = default_ttl
        self._enabled = enabled

        # ── Circuit breaker state ────────────────────────────────────
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._circuit_open = False

        # ── Monitoring counters ──────────────────────────────────────
        self._hits = 0
        self._misses = 0
        self._errors = 0

    # ── Key building ─────────────────────────────────────────────────

    def _make_key(self, *parts: str) -> str:
        """构建缓存键。

        格式: ``{CACHE_KEY_PREFIX}{domain}:{'/'.join(parts)}``

        示例::

            _make_key("get", "sk-001") -> "test:get/sk-001"
            _make_key("list")          -> "test:list"
            (with CACHE_KEY_PREFIX="tenant1:") -> "tenant1:test:get/sk-001"
        """
        joined = "/".join(parts)
        return f"{CACHE_KEY_PREFIX}{self._domain}:{joined}"

    # ── JSON-safe serialization ──────────────────────────────────────

    def _json_safe_deep(self, obj: Any) -> Any:
        """递归地将对象转换为 JSON 安全的 Python 类型。

        转换规则:
        - date / datetime → ISO 格式字符串
        - Decimal → float
        - bytes → UTF-8 解码字符串（非 UTF-8 用 replacement 字符替换）
        - set → list
        - dict → 递归转换所有值
        - list → 递归转换所有元素
        - 其他类型 → 原样返回
        """
        if isinstance(obj, date | datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if isinstance(obj, set):
            return [self._json_safe_deep(item) for item in obj]
        if isinstance(obj, dict):
            return {k: self._json_safe_deep(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._json_safe_deep(item) for item in obj]
        return obj

    def _to_cache_value(self, value: Any) -> Any:
        """将值转换为可缓存形式。

        处理 Pydantic 模型（model_dump）、列表、字典的递归转换。
        """
        if hasattr(value, "model_dump") and callable(value.model_dump):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [self._to_cache_value(item) for item in value]
        if isinstance(value, dict):
            return self._json_safe_deep(value)
        return value

    # ── Circuit breaker ──────────────────────────────────────────────

    def _should_try_cache(self) -> bool:
        """判断是否应该尝试缓存操作。

        满足以下任一条件时返回 False（跳过缓存）:
        - 缓存被禁用 (enabled=False)
        - 熔断器已打开且未到恢复时间窗口
        """
        if not self._enabled:
            return False
        if self._circuit_open:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= CIRCUIT_BREAKER_WINDOW:
                # ── 自动恢复 ─────────────────────────────────────
                self._failure_count = 0
                self._circuit_open = False
                logger.info(
                    "Circuit breaker auto-recovered for domain '%s' "
                    "after %.1fs window",
                    self._domain,
                    elapsed,
                )
                return True
            return False
        return True

    def _record_failure(self) -> None:
        """记录一次缓存操作失败，当达到阈值时打开熔断器。"""
        self._failure_count += 1
        self._errors += 1
        self._last_failure_time = time.time()
        if self._failure_count >= CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_open = True
            logger.warning(
                "Circuit breaker OPEN for domain '%s' after %d failures",
                self._domain,
                self._failure_count,
            )

    def _record_success(self) -> None:
        """记录一次成功操作，重置熔断器状态。"""
        self._failure_count = 0
        self._circuit_open = False

    # ── Safe cache operations ────────────────────────────────────────

    def _safe_get(self, key: str) -> dict[str, Any] | None:
        """安全地从缓存中读取值。

        失败时记录故障并返回 None，永不传播异常。
        """
        if not self._should_try_cache():
            return None
        try:
            return self._cache.get_json(key)
        except Exception as exc:
            logger.warning(
                "Cache GET failed for domain '%s' key '%s': %s",
                self._domain,
                key,
                exc,
            )
            self._record_failure()
            return None

    def _safe_set(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        """安全地写入缓存。

        失败时记录故障，永不传播异常。
        """
        if not self._enabled:
            return
        try:
            self._cache.set_json(key, value, ttl or self._default_ttl)
        except Exception as exc:
            logger.warning(
                "Cache SET failed for domain '%s' key '%s': %s",
                self._domain,
                key,
                exc,
            )
            self._record_failure()

    def _safe_delete(self, key: str) -> None:
        """安全地删除单个缓存键。"""
        if not self._enabled:
            return
        try:
            self._cache.delete(key)
        except Exception as exc:
            logger.warning(
                "Cache DELETE failed for domain '%s' key '%s': %s",
                self._domain,
                key,
                exc,
            )
            self._record_failure()

    def _safe_delete_pattern(self, prefix: str) -> None:
        """安全地按前缀批量删除缓存键。"""
        if not self._enabled:
            return
        try:
            self._cache.delete_pattern(prefix)
        except Exception as exc:
            logger.warning(
                "Cache DELETE_PATTERN failed for domain '%s' prefix '%s': %s",
                self._domain,
                prefix,
                exc,
            )
            self._record_failure()

    # ── Read-through cache pattern ───────────────────────────────────

    def _cached_read(
        self,
        key: str,
        fetch_fn: Callable[[], Any],
        ttl: int | None = None,
    ) -> Any:
        """读穿透缓存模式。

        流程:
        1. 若缓存可用，尝试读取缓存（命中则计数并返回）
        2. 通过 fetch_fn 获取原始数据
        3. 若结果非 None，写入缓存（防止缓存穿透）
        4. 返回原始数据
        """
        if self._should_try_cache():
            cached = self._safe_get(key)
            if cached is not None:
                self._hits += 1
                return cached
            self._misses += 1

        result = fetch_fn()
        if result is not None:
            self._safe_set(key, self._to_cache_value(result), ttl)
        return result

    # ── Write-through invalidation ───────────────────────────────────

    def _invalidate_keys(self, *key_parts: tuple[str, ...]) -> None:
        """批量失效缓存键。

        每个参数是一组键片段:
        - 最后一段为 ``*`` 时 → 按前缀批量删除 (delete_pattern)
        - 否则 → 删除单个键

        示例::

            _invalidate_keys(("get", "sk-001"), ("list", "*"))
            # 删除 test:get/sk-001 和所有 test:list/* 开头的键
        """
        if not self._enabled:
            return
        for parts in key_parts:
            if parts[-1] == "*":
                # Pattern deletion: strip trailing "*"
                prefix_parts = parts[:-1]
                pattern_key = self._make_key(*prefix_parts)
                self._safe_delete_pattern(pattern_key)
            else:
                key = self._make_key(*parts)
                self._safe_delete(key)

    # ── Monitoring ───────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        """返回缓存代理的健康监控状态。"""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "errors": self._errors,
            "circuit_open": self._circuit_open,
            "enabled": self._enabled,
        }
