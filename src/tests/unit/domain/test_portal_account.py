"""门户账号领域模型测试 — Issue #75（PBKDF2 哈希格式、校验、状态）。"""
from __future__ import annotations

import base64

from src.domain.portal_account import (
    PortalAccount,
    PortalAccountStatus,
    PortalPasswordHasher,
)


class TestPortalPasswordHasher:
    def test_hash_format_and_roundtrip(self):
        hasher = PortalPasswordHasher()
        stored = hasher.hash_password("Admin@123456")

        algorithm, iterations, salt_b64, _ = stored.split("$")
        assert algorithm == "pbkdf2"
        assert int(iterations) >= 600_000
        assert len(base64.b64decode(salt_b64)) == 16
        assert hasher.verify_password("Admin@123456", stored)
        assert not hasher.verify_password("wrong", stored)

    def test_same_password_produces_different_hashes(self):
        hasher = PortalPasswordHasher()

        assert hasher.hash_password("x") != hasher.hash_password("x")

    def test_verify_garbage_hash_returns_false(self):
        hasher = PortalPasswordHasher()

        assert not hasher.verify_password("x", "not-a-valid-hash")
        assert not hasher.verify_password("x", "bcrypt$10$abc$def")


class TestPortalAccount:
    def test_default_status_active(self):
        account = PortalAccount(username="u", password_hash="h", role="admin")

        assert account.status == PortalAccountStatus.ACTIVE
        assert account.is_active

    def test_disabled_account_not_active(self):
        account = PortalAccount(
            username="u", password_hash="h", role="admin", status=PortalAccountStatus.DISABLED
        )

        assert not account.is_active
