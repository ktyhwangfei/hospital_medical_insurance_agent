"""SQL Server 数据源密码的认证加密边界。"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from src.data_platform.outpatient_governance import DataSourceCredential


class DataSourceCredentialError(RuntimeError):
    """数据源主密钥未配置或凭据不能安全使用。"""


def data_source_endpoint(host: str, port: int, database: str, username: str) -> str:
    return (
        f"sqlserver://{host.strip().lower()}:{port}/"
        f"{database.strip()}/{username.strip()}"
    )


class DataSourceCredentialVault:
    def __init__(self) -> None:
        key = os.getenv("DATA_GOVERNANCE_MASTER_KEY")
        if not key:
            raise DataSourceCredentialError("缺少 DATA_GOVERNANCE_MASTER_KEY")
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (UnicodeEncodeError, ValueError) as exc:
            raise DataSourceCredentialError(
                "DATA_GOVERNANCE_MASTER_KEY 格式无效"
            ) from exc

    def seal(
        self,
        *,
        credential_id: str,
        password: str,
        endpoint: str,
        actor: str,
        revision: int,
    ) -> DataSourceCredential:
        if not password:
            raise DataSourceCredentialError("数据源密码不能为空")
        return DataSourceCredential(
            credential_id=credential_id,
            encrypted_password=self._fernet.encrypt(password.encode("utf-8")).decode("ascii"),
            secret_fingerprint=_fingerprint(password),
            endpoint_fingerprint=_fingerprint(endpoint),
            revision=revision,
            updated_by=actor,
            updated_at=datetime.now(timezone.utc),
        )

    def reveal(self, credential: DataSourceCredential, *, endpoint: str) -> str:
        if credential.endpoint_fingerprint != _fingerprint(endpoint):
            raise DataSourceCredentialError("数据源凭据未获准用于该端点")
        try:
            return self._fernet.decrypt(
                credential.encrypted_password.encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise DataSourceCredentialError("数据源凭据无法解密") from exc


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
