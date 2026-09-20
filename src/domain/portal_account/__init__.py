"""门户账号领域模型（Issue #75 登录与授权最小切片）。

通用语言：**门户账号 PortalAccount / 门户角色 PortalRole**。
过渡账号体系：对接医院 SSO 前，用本地账号 + PBKDF2 密码哈希过渡，
SSO 接入后签发来源可替换，验签面不变。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from enum import StrEnum


class PortalAccountStatus(StrEnum):
    """门户账号状态"""

    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True)
class PortalAccount:
    """门户账号（值对象）：登录名 + 密码哈希 + 角色 + 状态。"""

    username: str
    password_hash: str
    role: str
    status: str = PortalAccountStatus.ACTIVE

    @property
    def is_active(self) -> bool:
        return self.status == PortalAccountStatus.ACTIVE


class PortalPasswordHasher:
    """PBKDF2-HMAC-SHA256 密码哈希（stdlib 实现，零新依赖）。

    存储格式: ``pbkdf2$<iterations>$<salt_b64>$<hash_b64>``
    """

    ALGORITHM = "pbkdf2"
    ITERATIONS = 600_000
    _SALT_BYTES = 16
    _HASH_BYTES = 32

    def hash_password(self, password: str) -> str:
        salt = os.urandom(self._SALT_BYTES)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, self.ITERATIONS, dklen=self._HASH_BYTES
        )
        return "$".join(
            [
                self.ALGORITHM,
                str(self.ITERATIONS),
                base64.b64encode(salt).decode("ascii"),
                base64.b64encode(digest).decode("ascii"),
            ]
        )

    def verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            algorithm, iterations, salt_b64, hash_b64 = stored_hash.split("$")
            if algorithm != self.ALGORITHM:
                return False
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
        except (ValueError, TypeError):
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations), dklen=len(expected)
        )
        return hmac.compare_digest(digest, expected)
