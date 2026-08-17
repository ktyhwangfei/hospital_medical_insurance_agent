CREATE TABLE IF NOT EXISTS model_governance_credentials (
    credential_id VARCHAR(128) PRIMARY KEY,
    encrypted_api_key TEXT NOT NULL,
    secret_fingerprint CHAR(64) NOT NULL,
    endpoint_fingerprint CHAR(64) NOT NULL,
    revision INTEGER NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
ALTER TABLE model_governance_credentials
    ADD COLUMN IF NOT EXISTS endpoint_fingerprint CHAR(64);

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

WITH model_endpoint_candidates AS (
    SELECT credential.credential_id,
           regexp_replace(version.content->>'base_url', '/+$', '')
               AS normalized_base_url
    FROM model_governance_releases AS release
    JOIN model_governance_versions AS version
      ON version.version_id = release.version_id
    JOIN model_governance_credentials AS credential
      ON credential.credential_id = version.content->>'credential_ref'
    JOIN model_governance_connection_tests AS connection_test
      ON connection_test.asset_id = version.asset_id
     AND connection_test.content_hash = version.content_hash
     AND connection_test.credential_fingerprint = credential.secret_fingerprint
     AND connection_test.succeeded = TRUE
    WHERE version.content->>'asset_type' = 'model_profile'
      AND version.content->>'base_url' <> ''
), unique_model_endpoints AS (
    SELECT credential_id, min(normalized_base_url) AS normalized_base_url
    FROM model_endpoint_candidates
    GROUP BY credential_id
    HAVING count(DISTINCT normalized_base_url) = 1
)
UPDATE model_governance_credentials AS credential
SET endpoint_fingerprint = encode(
    sha256(convert_to(endpoint.normalized_base_url, 'UTF8')), 'hex'
)
FROM unique_model_endpoints AS endpoint
WHERE credential.credential_id = endpoint.credential_id
  AND credential.endpoint_fingerprint IS NULL;

CREATE TABLE IF NOT EXISTS model_governance_credential_versions (
    credential_id VARCHAR(128) NOT NULL,
    revision INTEGER NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    secret_fingerprint CHAR(64) NOT NULL,
    endpoint_fingerprint CHAR(64) NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (credential_id, revision)
);
INSERT INTO model_governance_credential_versions
    (credential_id, revision, encrypted_api_key, secret_fingerprint,
     endpoint_fingerprint, updated_by, updated_at)
SELECT credential_id, revision, encrypted_api_key, secret_fingerprint,
       endpoint_fingerprint, updated_by, updated_at
FROM model_governance_credentials
WHERE endpoint_fingerprint IS NOT NULL
ON CONFLICT (credential_id, revision) DO NOTHING;

CREATE TABLE IF NOT EXISTS model_governance_release_credentials (
    release_id VARCHAR(64) PRIMARY KEY
        REFERENCES model_governance_releases(release_id),
    credential_id VARCHAR(128) NOT NULL,
    credential_revision INTEGER NOT NULL,
    credential_fingerprint CHAR(64) NOT NULL,
    FOREIGN KEY (credential_id, credential_revision)
        REFERENCES model_governance_credential_versions(credential_id, revision)
);

INSERT INTO model_governance_release_credentials
    (release_id, credential_id, credential_revision, credential_fingerprint)
SELECT release.release_id, credential.credential_id, credential.revision,
       credential.secret_fingerprint
FROM model_governance_releases AS release
JOIN model_governance_versions AS version
  ON version.version_id = release.version_id
JOIN model_governance_credentials AS credential
  ON credential.credential_id = version.content->>'credential_ref'
JOIN model_governance_credential_versions AS credential_version
  ON credential_version.credential_id = credential.credential_id
 AND credential_version.revision = credential.revision
 AND credential_version.secret_fingerprint = credential.secret_fingerprint
WHERE version.content->>'asset_type' = 'model_profile'
  AND credential.endpoint_fingerprint = encode(
      sha256(convert_to(
          regexp_replace(version.content->>'base_url', '/+$', ''), 'UTF8'
      )), 'hex'
  )
  AND EXISTS (
      SELECT 1
      FROM model_governance_connection_tests AS connection_test
      WHERE connection_test.asset_id = version.asset_id
        AND connection_test.content_hash = version.content_hash
        AND connection_test.credential_fingerprint = credential.secret_fingerprint
        AND connection_test.succeeded = TRUE
  )
ON CONFLICT (release_id) DO NOTHING;
