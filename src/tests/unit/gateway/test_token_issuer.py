"""JWT 签发器测试 — Issue #75（sign_token 与 Authenticator 验签互通）。"""
from __future__ import annotations

import time

import pytest

from src.gateway.auth import authenticator
from src.gateway.auth.token_issuer import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_ABSOLUTE_LIMIT_SECONDS,
    sign_token,
)


def test_signed_token_passes_validator(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "issuer-test-secret")
    token = sign_token("alice", ["admin"], ["workflow:write"])

    auth = authenticator.validate_signed_token(f"Bearer {token}")

    assert auth.is_success
    assert auth.user_id == "alice"
    assert auth.roles == ["admin"]
    assert auth.permissions == ["workflow:write"]
    payload = auth.metadata["payload"]
    assert payload["exp"] - payload["iat"] == ACCESS_TOKEN_TTL_SECONDS


def test_sign_token_without_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("AUTH_JWT_SECRET", raising=False)

    with pytest.raises(RuntimeError):
        sign_token("alice", ["admin"], [])


def test_tampered_token_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "issuer-test-secret")
    token = sign_token("alice", ["admin"], ["workflow:write"])
    header, _, signature = token.split(".")
    forged_payload = "eyJzdWIiOiJib2IifQ"  # {"sub":"bob"}
    forged = f"{header}.{forged_payload}.{signature}"

    auth = authenticator.validate_signed_token(forged)

    assert not auth.is_success


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "issuer-test-secret")
    token = sign_token("alice", ["admin"], [], ttl_seconds=-1)

    auth = authenticator.validate_signed_token(token)

    assert auth.status.value == "expired_token"
    assert not auth.is_success


def test_refresh_absolute_limit_constant():
    # 滑动续签绝对上限必须显著大于 access token 有效期（12h vs 2h）
    assert REFRESH_ABSOLUTE_LIMIT_SECONDS > ACCESS_TOKEN_TTL_SECONDS


def test_iat_claim_present(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_SECRET", "issuer-test-secret")
    before = int(time.time())
    token = sign_token("alice", [], [])
    payload = authenticator.validate_signed_token(token).metadata["payload"]

    assert before <= payload["iat"] <= int(time.time()) + 1
