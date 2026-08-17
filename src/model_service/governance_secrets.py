"""模型治理凭据的认证加密边界。"""

import hashlib
import os
from datetime import datetime, timezone
from time import perf_counter
from typing import NamedTuple

from cryptography.fernet import Fernet, InvalidToken

from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceNotFoundError,
    ModelGovernanceStorage,
)
from src.model_service.governance_assets import (
    GovernanceCredential,
    ModelProfileAssetContent,
)
from src.model_service.exceptions import ModelAuthError, ModelTimeoutError
from src.model_service.models import Message, ModelRequest
from src.model_service.providers.openai_compatible import OpenAICompatibleProvider


class GovernanceSecretError(RuntimeError):
    """治理密钥未安全配置或凭据无法解密。"""


class GovernanceConnectionProbe(NamedTuple):
    succeeded: bool
    latency_ms: int
    safe_message: str


def endpoint_fingerprint(base_url: str) -> str:
    """端点绑定使用模型配置已规范化的 URL，任何变更都要求重新提交密钥。"""
    normalized = base_url.rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def probe_model_connection(
    content: ModelProfileAssetContent,
    api_key: str,
) -> GovernanceConnectionProbe:
    """发送不含业务数据的最小模型请求，只返回安全结果。"""
    started = perf_counter()
    try:
        response = OpenAICompatibleProvider(
            content.base_url,
            api_key,
            timeout=content.timeout_seconds,
        ).invoke(
            ModelRequest(
                messages=[Message(role="user", content="ping")],
                model_type=content.model_name,
                scene="model_governance_connection_test",
                max_tokens=1,
                temperature=0,
            )
        )
        if not response.content.strip():
            raise ValueError("模型响应为空")
    except ModelAuthError:
        succeeded, safe_message = False, "认证失败"
    except ModelTimeoutError:
        succeeded, safe_message = False, "连接超时"
    except Exception:
        succeeded, safe_message = False, "连接失败"
    else:
        succeeded, safe_message = True, "连接成功"
    return GovernanceConnectionProbe(
        succeeded,
        max(0, round((perf_counter() - started) * 1000)),
        safe_message,
    )


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
        base_url: str,
        actor: str,
    ) -> GovernanceCredential:
        return self._storage.put_credential(
            self.seal(credential_id, api_key, base_url=base_url, actor=actor)
        )

    def seal(
        self,
        credential_id: str,
        api_key: str,
        *,
        base_url: str,
        actor: str,
    ) -> GovernanceCredential:
        if not api_key:
            raise GovernanceSecretError("API Key 不能为空")
        try:
            revision = self._storage.get_credential(credential_id).revision + 1
        except ModelGovernanceNotFoundError:
            revision = 1
        return GovernanceCredential(
            credential_id=credential_id,
            encrypted_api_key=self._fernet.encrypt(api_key.encode("utf-8")).decode("ascii"),
            secret_fingerprint=hashlib.sha256(api_key.encode("utf-8")).hexdigest(),
            endpoint_fingerprint=endpoint_fingerprint(base_url),
            revision=revision,
            updated_by=actor,
            updated_at=datetime.now(timezone.utc),
        )

    def reveal(self, credential_id: str, *, base_url: str) -> str:
        return self.reveal_credential(
            self._storage.get_credential(credential_id), base_url=base_url
        )

    def reveal_credential(
        self, credential: GovernanceCredential, *, base_url: str
    ) -> str:
        if credential.endpoint_fingerprint is None:
            raise GovernanceSecretError("旧凭据需重新绑定/重新发布")
        if credential.endpoint_fingerprint != endpoint_fingerprint(base_url):
            raise GovernanceSecretError("模型凭据未获准用于该端点")
        try:
            return self._fernet.decrypt(
                credential.encrypted_api_key.encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
            raise GovernanceSecretError("模型凭据无法解密") from exc
