"""Session 存储相关模型定义"""

from dataclasses import dataclass
from enum import Enum


class SessionStorageHealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


@dataclass
class SessionStorageHealth:
    status: SessionStorageHealthStatus
    message: str = ""
    session_count: int = 0
