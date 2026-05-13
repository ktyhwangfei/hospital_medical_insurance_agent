"""限流熔断模块

基于令牌桶算法的限流器，支持按渠道/用户/IP 级别限流。
"""
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    """限流检查结果

    Attributes:
        allowed: 是否允许通过
        remaining: 剩余可用令牌数
        reset_after: 下次重置间隔（秒）
        retry_after: 建议重试等待时间（秒）
    """
    allowed: bool
    remaining: int
    reset_after: float
    retry_after: float = 0.0


@dataclass
class _TokenBucket:
    """令牌桶内部状态"""
    capacity: int              # 桶容量（最大突发）
    refill_rate: float         # 令牌补充速率（个/秒）
    tokens: float = field(init=False)   # 当前令牌数
    last_refill: float = field(init=False)  # 上次补充时间戳

    def __post_init__(self) -> None:
        self.tokens = float(self.capacity)
        self.last_refill = time.monotonic()

    def _refill(self) -> None:
        """补充令牌"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(float(self.capacity), self.tokens + new_tokens)
        self.last_refill = now

    def try_consume(self, count: int = 1) -> bool:
        """尝试消耗指定数量的令牌

        Args:
            count: 需要消耗的令牌数

        Returns:
            是否成功消耗
        """
        self._refill()
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False

    @property
    def remaining_tokens(self) -> int:
        """当前可用令牌数"""
        self._refill()
        return int(self.tokens)

    @property
    def wait_time(self) -> float:
        """等到下一个令牌可用所需的时间（秒）"""
        if self.tokens >= 1.0:
            return 0.0
        self._refill()
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate if self.refill_rate > 0 else float("inf")


class RateLimiter:
    """令牌桶限流器

    支持按不同粒度（全局、用户、IP、渠道）进行限流。
    每个 Key 对应一个独立的令牌桶。
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock: Lock = Lock()

        # 默认限流配置
        self._default_capacity: int = 100     # 默认桶容量
        self._default_rate: float = 10.0       # 默认补充速率

    def configure(self, capacity: int | None = None, rate: float | None = None) -> None:
        """更新默认限流配置

        Args:
            capacity: 桶容量（最大突发请求数）
            rate: 令牌补充速率（个/秒）
        """
        if capacity is not None:
            self._default_capacity = capacity
        if rate is not None:
            self._default_rate = rate
        logger.info(
            "RateLimiter default config updated: capacity=%d, rate=%.1f/s",
            self._default_capacity,
            self._default_rate,
        )

    def check(self, key: str, capacity: int | None = None, rate: float | None = None) -> RateLimitResult:
        """检查是否允许请求通过

        Args:
            key: 限流 Key（如 user_id, ip, channel）
            capacity: 覆盖默认桶容量
            rate: 覆盖默认补充速率

        Returns:
            限流检查结果
        """
        bucket = self._get_or_create_bucket(key, capacity, rate)

        with self._lock:
            allowed = bucket.try_consume(1)

        return RateLimitResult(
            allowed=allowed,
            remaining=bucket.remaining_tokens,
            reset_after=1.0 / bucket.refill_rate if bucket.refill_rate > 0 else 0.0,
            retry_after=bucket.wait_time if not allowed else 0.0,
        )

    def check_with(self, key: str, cost: int = 1) -> RateLimitResult:
        """检查是否允许消耗指定数量的令牌

        Args:
            key: 限流 Key
            cost: 消耗的令牌数

        Returns:
            限流检查结果
        """
        bucket = self._get_or_create_bucket(key)

        with self._lock:
            allowed = bucket.try_consume(cost)

        return RateLimitResult(
            allowed=allowed,
            remaining=bucket.remaining_tokens,
            reset_after=1.0 / bucket.refill_rate,
            retry_after=bucket.wait_time if not allowed else 0.0,
        )

    def remaining(self, key: str) -> int:
        """获取指定 Key 的剩余令牌数

        Args:
            key: 限流 Key

        Returns:
            剩余令牌数
        """
        bucket = self._buckets.get(key)
        if bucket is None:
            return self._default_capacity
        return bucket.remaining_tokens

    def reset(self, key: str | None = None) -> None:
        """重置限流器

        Args:
            key: 指定 Key，None 时重置所有
        """
        with self._lock:
            if key:
                self._buckets.pop(key, None)
                logger.debug("RateLimiter bucket reset: %s", key)
            else:
                self._buckets.clear()
                logger.info("RateLimiter all buckets reset")

    def _get_or_create_bucket(
        self,
        key: str,
        capacity: int | None = None,
        rate: float | None = None,
    ) -> _TokenBucket:
        """获取或创建令牌桶

        Args:
            key: 限流 Key
            capacity: 桶容量
            rate: 补充速率

        Returns:
            令牌桶实例
        """
        bucket = self._buckets.get(key)
        if bucket is None:
            with self._lock:
                # 双检锁
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = _TokenBucket(
                        capacity=capacity or self._default_capacity,
                        refill_rate=rate or self._default_rate,
                    )
                    self._buckets[key] = bucket
        return bucket


# 全局单例
rate_limiter = RateLimiter()


__all__ = [
    "RateLimitResult",
    "RateLimiter",
    "rate_limiter",
]
