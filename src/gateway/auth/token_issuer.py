"""JWT 签发 — 与 Authenticator 验签共用 AUTH_JWT_SECRET（HS256）。

设计见 docs/steering/Portal登录与授权-设计-V1.0.md（D4/D5）：
access token 2h，/auth/refresh 滑动续签，iat 绝对上限 12h 后强制重登。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone

ACCESS_TOKEN_TTL_SECONDS = 2 * 3600
# 滑动续签绝对上限：token 的 iat 距今超过该值拒绝续签，强制重新登录
REFRESH_ABSOLUTE_LIMIT_SECONDS = 12 * 3600


def _encode_base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_token(
    sub: str,
    roles: list[str],
    permissions: list[str],
    ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
) -> str:
    """签发 HS256 JWT。密钥缺失即抛错（fail-closed，绝不回退假数据）。"""
    secret = os.getenv("AUTH_JWT_SECRET", "")
    if not secret:
        raise RuntimeError("AUTH_JWT_SECRET 未配置，拒绝签发 token")
    now = datetime.now(timezone.utc)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": sub,
        "roles": list(roles),
        "permissions": list(permissions),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    signing_input = ".".join(
        [
            _encode_base64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _encode_base64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_encode_base64url(signature)}"
