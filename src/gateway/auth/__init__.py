"""认证鉴权模块

提供 Token 验证、权限校验、角色识别等认证鉴权功能。
"""
import logging
import base64
import hashlib
import hmac
import json
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class AuthStatus(StrEnum):
    """认证状态枚举"""
    SUCCESS = "success"                          # 认证通过
    INVALID_TOKEN = "invalid_token"              # 无效 Token
    EXPIRED_TOKEN = "expired_token"              # Token 已过期
    INSUFFICIENT_PERMISSION = "insufficient_permission"  # 权限不足


@dataclass
class AuthResult:
    """认证结果

    Attributes:
        status: 认证状态
        user_id: 用户 ID（认证成功时有效）
        roles: 用户角色列表
        permissions: 用户权限列表
        error_message: 错误信息（认证失败时）
        metadata: 额外元数据
    """
    status: AuthStatus
    user_id: str = ""
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """是否认证成功"""
        return self.status == AuthStatus.SUCCESS


# 高频接口权限白名单（不校验权限，仅校验 Token 有效性）
_PUBLIC_API_PATHS: set[str] = {
    "/health",
    "/version",
    "/api/v1/medical-insurance-ai-agent/chat",
    "/api/v1/medical-insurance-ai-agent/chat/stream",
}


class Authenticator:
    """认证鉴权器

    负责 Token 验证、解析与权限检查。
    支持多种 Token 格式和自定义校验逻辑。
    """

    # Token 前缀映射
    _TOKEN_PREFIXES: dict[str, str] = {
        "bearer ": "bearer",
        "token ": "token",
    }

    def __init__(self) -> None:
        self._token_blacklist: set[str] = set()

    def validate_token(self, token: str) -> AuthResult:
        """验证 Token 有效性

        Args:
            token: 原始 Authorization 头部值

        Returns:
            认证结果
        """
        # 去除前缀
        raw_token = self._strip_prefix(token)

        if not raw_token:
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="Token 格式无效或为空",
            )

        # 检查黑名单
        if raw_token in self._token_blacklist:
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="Token 已被撤销",
            )

        # 模拟解析 Token（生产环境对接 JWT / OAuth2）
        try:
            payload = self._decode_token(raw_token)
        except Exception as e:
            logger.warning("Token decode failed: %s", e)
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="Token 解析失败",
            )

        sub = payload.get("sub")
        exp = payload.get("exp")
        roles = payload.get("roles")
        permissions = payload.get("permissions")
        valid_claims = (
            isinstance(sub, str)
            and bool(sub.strip())
            and isinstance(exp, (int, float))
            and not isinstance(exp, bool)
            and math.isfinite(exp)
            and isinstance(roles, list)
            and all(isinstance(role, str) for role in roles)
            and isinstance(permissions, list)
            and all(isinstance(permission, str) for permission in permissions)
        )
        if not valid_claims:
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="Token claims 格式无效",
            )

        # 检查过期
        if exp <= datetime.now(timezone.utc).timestamp():
            return AuthResult(
                status=AuthStatus.EXPIRED_TOKEN,
                error_message="Token 已过期",
            )

        return AuthResult(
            status=AuthStatus.SUCCESS,
            user_id=sub,
            roles=roles,
            permissions=permissions,
            metadata={"payload": payload},
        )

    def validate_signed_token(self, token: str) -> AuthResult:
        """校验治理接口使用的 HS256 JWT；密钥缺失时关闭访问。"""
        raw_token = self._strip_prefix(token)
        secret = os.getenv("AUTH_JWT_SECRET", "")
        if not secret or raw_token in self._token_blacklist:
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="JWT 验签配置缺失或 Token 已失效",
            )
        parts = raw_token.split(".")
        if len(parts) != 3:
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="治理接口仅接受已签名 JWT",
            )
        try:
            header = json.loads(self._decode_base64url(parts[0]))
            signature = self._decode_base64url(parts[2])
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="JWT 格式无效",
            )
        if not isinstance(header, dict):
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="JWT header 格式无效",
            )
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{parts[0]}.{parts[1]}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        if header.get("alg") != "HS256" or not hmac.compare_digest(signature, expected):
            return AuthResult(
                status=AuthStatus.INVALID_TOKEN,
                error_message="JWT 签名无效",
            )
        return self.validate_token(raw_token)

    def check_permission(self, auth_result: AuthResult, required_permission: str) -> AuthResult:
        """检查权限

        Args:
            auth_result: 认证结果
            required_permission: 需要的权限标识

        Returns:
            修改后的认证结果
        """
        if not auth_result.is_success:
            return auth_result

        if required_permission in auth_result.permissions:
            return auth_result

        logger.warning(
            "Permission denied: user=%s, required=%s, has=%s",
            auth_result.user_id,
            required_permission,
            auth_result.permissions,
        )
        return AuthResult(
            status=AuthStatus.INSUFFICIENT_PERMISSION,
            user_id=auth_result.user_id,
            error_message=f"缺少权限: {required_permission}",
        )

    def is_public_path(self, path: str) -> bool:
        """判断路径是否为公开路径（无需权限校验）

        Args:
            path: 请求路径

        Returns:
            是否为公开路径
        """
        return path in _PUBLIC_API_PATHS

    def invalidate_token(self, token: str) -> None:
        """撤销 Token（加入黑名单）

        Args:
            token: 需要撤销的 Token
        """
        raw_token = self._strip_prefix(token)
        if raw_token:
            self._token_blacklist.add(raw_token)
            logger.info("Token invalidated: %s...", raw_token[:8])

    def reset(self) -> None:
        """清空黑名单"""
        self._token_blacklist.clear()

    @staticmethod
    def _strip_prefix(token: str) -> str:
        """去除 Authorization 头部的前缀

        Args:
            token: 原始 Authorization 值

        Returns:
            去除前缀后的 Token
        """
        token_lower = token.lower()
        for prefix, _ in Authenticator._TOKEN_PREFIXES.items():
            if token_lower.startswith(prefix):
                return token[len(prefix):].strip()
        return token.strip()

    @staticmethod
    def _decode_token(token: str) -> dict[str, Any]:
        """解码 Token（模拟实现，生产环境替换为真实 JWT 校验）

        Args:
            token: Token 字符串

        Returns:
            Token 载荷

        Raises:
            ValueError: Token 格式异常
        """
        parts = token.split(".")
        if len(parts) != 3:
            # 非 JWT 格式，尝试作为简单 Token 处理
            return {
                "sub": token,
                "roles": ["user"],
                "permissions": [],
                "exp": (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp(),
            }

        try:
            # 补齐 base64 填充
            payload_b64 = parts[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding

            decoded = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(decoded)
            if not isinstance(payload, dict):
                raise ValueError("JWT payload must be an object")
            return payload
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid token payload: {e}")

    @staticmethod
    def _decode_base64url(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


# 全局单例
authenticator = Authenticator()


__all__ = [
    "AuthStatus",
    "AuthResult",
    "Authenticator",
    "authenticator",
]
