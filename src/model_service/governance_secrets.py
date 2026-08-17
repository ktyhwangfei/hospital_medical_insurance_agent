"""模型治理凭据的认证加密边界。"""

import hashlib
import os
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceNotFoundError,
    ModelGovernanceStorage,
)
from src.model_service.governance_assets import GovernanceCredential


class GovernanceSecretError(RuntimeError):
    """治理密钥未安全配置或凭据无法解密。"""


class GovernanceCredentialVault:
    def __init__(self, storage: ModelGovernanceStorage) -> None:
        key = os.getenv("MODEL_GOVERNANCE_MASTER_KEY")
        if not key:
            raise GovernanceSecretError("缺少 MODEL_GOVERNANCE_MASTER_KEY")
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (UnicodeEncodeError, ValueError) as exc:
            raise GovernanceSecretError(
                "MODEL_GOVERNANCE_MASTER_KEY 格式无效"
            ) from exc
        self._storage = storage

    def put(
        self,
        credential_id: str,
        api_key: str,
        *,
        actor: str,
    ) -> GovernanceCredential:
        if not api_key:
            raise GovernanceSecretError("API Key 不能为空")
        try:
            revision = self._storage.get_credential(credential_id).revision + 1
        except ModelGovernanceNotFoundError:
            revision = 1
        credential = GovernanceCredential(
            credential_id=credential_id,
            encrypted_api_key=self._fernet.encrypt(api_key.encode("utf-8")).decode("ascii"),
            secret_fingerprint=hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
            revision=revision,
            updated_by=actor,
            updated_at=datetime.now(timezone.utc),
        )
        return self._storage.put_credential(credential)

    def reveal(self, credential_id: str) -> str:
        credential = self._storage.get_credential(credential_id)
        try:
            return self._fernet.decrypt(
                credential.encrypted_api_key.encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise GovernanceSecretError("模型凭据无法解密") from exc
