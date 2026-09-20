"""门户认证服务（Issue #75）：账号校验、token 签发/续期、登录限流。"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from src.config.security_policy.portal_roles import permissions_for_role
from src.data_platform.storage.portal_account.account_ports import PortalAccountStore
from src.domain.portal_account import PortalAccount, PortalPasswordHasher
from src.gateway.auth import authenticator
from src.gateway.auth.token_issuer import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_ABSOLUTE_LIMIT_SECONDS,
    sign_token,
)

logger = logging.getLogger(__name__)

# 种子账号环境变量：PORTAL_SEED_ACCOUNTS=[{"username","password","role"}]
SEED_ACCOUNTS_ENV = "PORTAL_SEED_ACCOUNTS"

# 登录限流：同一 key 10 分钟内失败 5 次即熔断 10 分钟（防爆破）
_LOGIN_WINDOW_SECONDS = 600
_LOGIN_MAX_FAILURES = 5


class PortalAuthError(Exception):
    """认证失败，code 与前端/文档约定的 error_code 对齐。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LoginRateLimiter:
    """进程内登录失败限流（单进程部署下有效；多副本归 #43 收敛）。"""

    def __init__(self) -> None:
        self._failures: dict[str, list[float]] = {}

    def is_blocked(self, key: str) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        failures = [t for t in self._failures.get(key, []) if now - t < _LOGIN_WINDOW_SECONDS]
        self._failures[key] = failures
        return len(failures) >= _LOGIN_MAX_FAILURES

    def record_failure(self, key: str) -> None:
        now = datetime.now(timezone.utc).timestamp()
        self._failures.setdefault(key, []).append(now)


class PortalAuthService:
    def __init__(
        self,
        store: PortalAccountStore,
        hasher: PortalPasswordHasher | None = None,
    ) -> None:
        self._store = store
        self._hasher = hasher or PortalPasswordHasher()
        self._rate_limiter = LoginRateLimiter()

    # -- 种子初始化 --

    def seed_from_env(self) -> None:
        """从 PORTAL_SEED_ACCOUNTS 幂等种子初始化（仅当 username 不存在时插入）。"""
        raw = os.getenv(SEED_ACCOUNTS_ENV, "").strip()
        if not raw:
            return
        try:
            entries = json.loads(raw)
            if not isinstance(entries, list):
                raise ValueError("PORTAL_SEED_ACCOUNTS 必须是 JSON 数组")
        except (ValueError, TypeError) as e:
            logger.warning("PORTAL_SEED_ACCOUNTS 解析失败，跳过种子初始化: %s", e)
            return
        for entry in entries:
            try:
                username = str(entry["username"]).strip()
                password = str(entry["password"])
                role = str(entry["role"]).strip()
            except (KeyError, TypeError):
                logger.warning("PORTAL_SEED_ACCOUNTS 条目缺字段，跳过: %s", entry)
                continue
            if not username or self._store.get_by_username(username) is not None:
                continue
            if not permissions_for_role(role):
                logger.warning("PORTAL_SEED_ACCOUNTS 未知角色 %s，跳过账号 %s", role, username)
                continue
            self._store.create_account(
                PortalAccount(
                    username=username,
                    password_hash=self._hasher.hash_password(password),
                    role=role,
                )
            )
            logger.info("门户账号种子初始化完成: %s (role=%s)", username, role)

    # -- 登录 / 签发 --

    def authenticate(self, username: str, password: str, rate_limit_key: str) -> PortalAccount:
        """校验账号密码；错误统一 AUTH_INVALID_CREDENTIALS（不区分用户不存在/密码错误）。"""
        if self._rate_limiter.is_blocked(rate_limit_key):
            raise PortalAuthError("RATE_LIMITED", "登录失败次数过多，请 10 分钟后再试")
        account = self._store.get_by_username(username)
        if (
            account is None
            or not account.is_active
            or not self._hasher.verify_password(password, account.password_hash)
        ):
            self._rate_limiter.record_failure(rate_limit_key)
            raise PortalAuthError("AUTH_INVALID_CREDENTIALS", "账号或密码错误")
        return account

    def issue_token(self, account: PortalAccount) -> str:
        permissions = permissions_for_role(account.role)
        if not permissions:
            raise PortalAuthError("ROLE_MISCONFIGURED", f"角色 {account.role} 未配置权限")
        return sign_token(
            sub=account.username,
            roles=[account.role],
            permissions=permissions,
        )

    # -- 续期 --

    def refresh(self, authorization: str) -> str:
        """持未过期 token 滑动续签；iat 超绝对上限（12h）拒绝，强制重登。"""
        auth = authenticator.validate_signed_token(authorization)
        if not auth.is_success:
            raise PortalAuthError("EXPIRED_TOKEN", auth.error_message or "登录凭据无效")
        payload = auth.metadata.get("payload", {})
        iat = payload.get("iat")
        now = datetime.now(timezone.utc).timestamp()
        if not isinstance(iat, (int, float)) or now - iat > REFRESH_ABSOLUTE_LIMIT_SECONDS:
            raise PortalAuthError("EXPIRED_TOKEN", "会话已超时可续期上限，请重新登录")
        return sign_token(sub=auth.user_id, roles=auth.roles, permissions=auth.permissions)


__all__ = [
    "PortalAuthService",
    "PortalAuthError",
    "ACCESS_TOKEN_TTL_SECONDS",
]
