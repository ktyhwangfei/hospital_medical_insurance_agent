"""租户隔离模块

提供多租户上下文管理，支持租户级别的数据隔离和资源分配。
"""
import logging
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TenantContext:
    """租户上下文

    携带当前请求的租户信息，贯穿整个请求生命周期。

    Attributes:
        tenant_id: 租户 ID
        hospital_id: 医院 ID（可选）
        department_id: 科室 ID（可选）
        metadata: 额外租户元数据
    """
    tenant_id: str
    hospital_id: str = ""
    department_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def isolation_key(self) -> str:
        """获取数据隔离键，用于多租户数据路由

        格式: tenant_id[:hospital_id[:department_id]]
        """
        parts = [self.tenant_id]
        if self.hospital_id:
            parts.append(self.hospital_id)
        if self.department_id:
            parts.append(self.department_id)
        return ":".join(parts)


# 线程/协程安全的租户上下文变量
_current_tenant: ContextVar[TenantContext | None] = ContextVar("current_tenant", default=None)


class TenantManager:
    """租户管理器

    管理租户上下文的生命周期，提供获取/设置/清除操作。
    """

    def get_current(self) -> TenantContext | None:
        """获取当前请求的租户上下文

        Returns:
            当前 TenantContext，未设置时返回 None
        """
        return _current_tenant.get()

    def set_current(self, context: TenantContext) -> None:
        """设置当前请求的租户上下文

        Args:
            context: 租户上下文
        """
        _current_tenant.set(context)
        logger.debug(
            "Tenant context set: tenant_id=%s, hospital_id=%s, department_id=%s",
            context.tenant_id,
            context.hospital_id,
            context.department_id,
        )

    def clear_current(self) -> None:
        """清除当前请求的租户上下文"""
        _current_tenant.set(None)

    def resolve_from_token(self, token_payload: dict[str, Any]) -> TenantContext | None:
        """从 Token 载荷解析租户上下文

        Args:
            token_payload: Token 解码后的载荷

        Returns:
            解析出的 TenantContext，无法解析时返回 None
        """
        tenant_id = token_payload.get("tenant_id", "")
        if not tenant_id:
            logger.warning("No tenant_id found in token payload")
            return None

        return TenantContext(
            tenant_id=tenant_id,
            hospital_id=token_payload.get("hospital_id", ""),
            department_id=token_payload.get("department_id", ""),
            metadata=token_payload.get("tenant_metadata", {}),
        )

    def reset(self) -> None:
        """重置租户管理器状态"""
        self.clear_current()


# 全局单例
tenant_manager = TenantManager()


__all__ = [
    "TenantContext",
    "TenantManager",
    "tenant_manager",
]
