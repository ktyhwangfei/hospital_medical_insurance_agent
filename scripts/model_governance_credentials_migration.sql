CREATE TABLE IF NOT EXISTS model_governance_credentials (
    credential_id VARCHAR(128) PRIMARY KEY,
    encrypted_api_key TEXT NOT NULL,
    secret_fingerprint CHAR(64) NOT NULL,
    revision INTEGER NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS model_governance_connection_tests (
    test_id UUID PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    credential_fingerprint CHAR(64) NOT NULL,
    succeeded BOOLEAN NOT NULL,
    latency_ms INTEGER NOT NULL,
    safe_message VARCHAR(500) NOT NULL,
    tested_by VARCHAR(128) NOT NULL,
    tested_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_governance_connection_success
ON model_governance_connection_tests
    (asset_id, content_hash, credential_fingerprint, tested_at DESC)
WHERE succeeded = TRUE;
