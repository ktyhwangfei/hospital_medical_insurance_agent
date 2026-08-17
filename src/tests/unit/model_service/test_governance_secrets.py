import hashlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.data_platform.storage.model_governance.in_memory import (
    InMemoryModelGovernanceStorage,
)
from src.model_service.governance_assets import (
    GovernanceConnectionTest,
    ModelProfileAssetContent,
)


MASTER_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


def test_vault_encrypts_secret_and_never_stores_plaintext(monkeypatch):
    from src.model_service.governance_secrets import GovernanceCredentialVault

    monkeypatch.setenv("MODEL_GOVERNANCE_MASTER_KEY", MASTER_KEY)
    storage = InMemoryModelGovernanceStorage()
    vault = GovernanceCredentialVault(storage)
    api_key = "sk-" + "plain-secret"

    saved = vault.put(
        "credential.demo",
        api_key,
        base_url="https://models.example.test/v1",
        actor="editor",
    )

    stored = storage.get_credential("credential.demo")
    assert stored == saved
    assert stored.encrypted_api_key != api_key
    assert api_key not in stored.model_dump_json()
    assert stored.secret_fingerprint == hashlib.sha256(api_key.encode()).hexdigest()
    assert vault.reveal(
        "credential.demo", base_url="https://models.example.test/v1"
    ) == api_key


@pytest.mark.parametrize("master_key", [None, "not-a-fernet-key"])
def test_vault_fails_closed_without_valid_master_key(monkeypatch, master_key):
    from src.model_service.governance_secrets import (
        GovernanceCredentialVault,
        GovernanceSecretError,
    )

    if master_key is None:
        monkeypatch.delenv("MODEL_GOVERNANCE_MASTER_KEY", raising=False)
    else:
        monkeypatch.setenv("MODEL_GOVERNANCE_MASTER_KEY", master_key)

    with pytest.raises(GovernanceSecretError, match="MODEL_GOVERNANCE_MASTER_KEY"):
        GovernanceCredentialVault(InMemoryModelGovernanceStorage())


def test_model_profile_accepts_only_safe_openai_compatible_url():
    profile = ModelProfileAssetContent(
        asset_id="model.demo",
        name="demo",
        base_url="https://models.example.test/v1///",
        model_name="demo-model",
        credential_ref="credential.demo",
        temperature=0.2,
        max_tokens=1024,
    )

    assert profile.provider_id == "openai_compatible"
    assert profile.base_url == "https://models.example.test/v1"
    assert profile.timeout_seconds == 30

    for unsafe_url in (
        "ftp://models.example.test/v1",
        "https://user:password@models.example.test/v1",
        "https://models.example.test:bad/v1",
        "https://models.example.test:65536/v1",
        "https://models .example.test/v1",
        "https:///v1",
    ):
        with pytest.raises(ValidationError):
            ModelProfileAssetContent(
                asset_id="model.demo",
                name="demo",
                base_url=unsafe_url,
                model_name="demo-model",
                credential_ref="credential.demo",
                temperature=0.2,
                max_tokens=1024,
            )


def test_connection_test_id_is_a_uuid():
    with pytest.raises(ValidationError):
        GovernanceConnectionTest(
            test_id="not-a-uuid",
            asset_id="model.demo",
            content_hash="a" * 64,
            credential_fingerprint="b" * 64,
            succeeded=True,
            latency_ms=1,
            safe_message="连接成功",
            tested_by="editor",
        )


def test_k8s_governance_environment_comes_from_existing_configmap():
    root = Path(__file__).resolve().parents[4]
    deployment = (root / "deploy/k8s/deployment.yaml").read_text(encoding="utf-8")
    configmap = (root / "deploy/k8s/configmap.yaml").read_text(encoding="utf-8")

    env_block = deployment.split("- name: MODEL_GOVERNANCE_ENV", 1)[1].split(
        "- name: MODEL_GOVERNANCE_MASTER_KEY", 1
    )[0]
    assert "configMapKeyRef:" in env_block
    assert "name: medical-insurance-ai-agent-config" in env_block
    assert "key: MODEL_GOVERNANCE_ENV" in env_block
    assert "MODEL_GOVERNANCE_ENV:" in configmap
