from cryptography.fernet import Fernet
import pytest

from src.security.data_source_credentials import (
    DataSourceCredentialError,
    DataSourceCredentialVault,
    data_source_endpoint,
)


def test_datasource_password_is_encrypted_and_endpoint_bound(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATA_GOVERNANCE_MASTER_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    vault = DataSourceCredentialVault()
    endpoint = data_source_endpoint("DB.EXAMPLE", 1433, "bjybdb", "readonly")
    credential = vault.seal(
        credential_id="credential.bjybdb",
        password="secret-value",
        endpoint=endpoint,
        actor="admin-1",
        revision=1,
    )

    assert "secret-value" not in credential.model_dump_json()
    assert vault.reveal(credential, endpoint=endpoint) == "secret-value"
    with pytest.raises(DataSourceCredentialError, match="端点"):
        vault.reveal(
            credential,
            endpoint=data_source_endpoint("other.example", 1433, "bjybdb", "readonly"),
        )


@pytest.mark.parametrize("master_key", [None, "invalid-key"])
def test_vault_rejects_missing_or_invalid_master_key(monkeypatch, master_key) -> None:
    if master_key is None:
        monkeypatch.delenv("DATA_GOVERNANCE_MASTER_KEY", raising=False)
    else:
        monkeypatch.setenv("DATA_GOVERNANCE_MASTER_KEY", master_key)

    with pytest.raises(DataSourceCredentialError, match="DATA_GOVERNANCE_MASTER_KEY"):
        DataSourceCredentialVault()


def test_endpoint_is_canonical_and_does_not_include_password() -> None:
    assert data_source_endpoint(" DB.EXAMPLE ", 1433, " bjybdb ", " readonly ") == (
        "sqlserver://db.example:1433/bjybdb/readonly"
    )
