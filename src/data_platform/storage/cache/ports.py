from typing import Protocol


class CachePort(Protocol):
    def get(self, key: str):
        raise NotImplementedError

    def set(self, key: str, value, ttl_seconds: int | None = None) -> None:
        raise NotImplementedError