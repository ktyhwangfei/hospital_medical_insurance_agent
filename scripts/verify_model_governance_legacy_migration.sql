\set ON_ERROR_STOP on

BEGIN;
CREATE SCHEMA task5_legacy_migration_verification;
SET LOCAL search_path TO task5_legacy_migration_verification, public;

CREATE TABLE model_governance_credentials (
    credential_id VARCHAR(128) PRIMARY KEY,
    encrypted_api_key TEXT NOT NULL,
    secret_fingerprint CHAR(64) NOT NULL,
    revision INTEGER NOT NULL,
    updated_by VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE model_governance_drafts (
    draft_id VARCHAR(64) PRIMARY KEY,
    content JSONB NOT NULL
);
CREATE TABLE model_governance_versions (
    version_id VARCHAR(64) PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    content JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL
);
CREATE TABLE model_governance_releases (
    release_id VARCHAR(64) PRIMARY KEY,
    version_id VARCHAR(64) NOT NULL
);
CREATE TABLE model_governance_connection_tests (
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

INSERT INTO model_governance_credentials VALUES
    ('credential.unique', 'encrypted-unique', repeat('a', 64), 3, 'legacy', now()),
    ('credential.ambiguous', 'encrypted-ambiguous', repeat('b', 64), 2, 'legacy', now()),
    ('credential.orphan', 'encrypted-orphan', repeat('c', 64), 1, 'legacy', now());
INSERT INTO model_governance_drafts VALUES
    ('draft-unique', '{"asset_type":"model_profile","credential_ref":"credential.unique","base_url":"https://models.example.test/v1///"}'),
    ('draft-ambiguous-a', '{"asset_type":"model_profile","credential_ref":"credential.ambiguous","base_url":"https://a.example.test/v1"}'),
    ('draft-ambiguous-b', '{"asset_type":"model_profile","credential_ref":"credential.ambiguous","base_url":"https://b.example.test/v1"}');
INSERT INTO model_governance_versions VALUES
    ('version-unique', 'model.unique', '{"asset_type":"model_profile","credential_ref":"credential.unique","base_url":"https://models.example.test/v1/"}', repeat('d', 64));
INSERT INTO model_governance_releases VALUES
    ('release-unique', 'version-unique');
INSERT INTO model_governance_connection_tests VALUES
    ('00000000-0000-0000-0000-000000000001', 'model.unique', repeat('d', 64), repeat('a', 64), TRUE, 1, '连接成功', 'legacy', now());

\ir model_governance_credentials_migration.sql

DO $$
BEGIN
    IF (SELECT endpoint_fingerprint FROM model_governance_credentials
        WHERE credential_id = 'credential.unique')
       IS DISTINCT FROM encode(
           sha256(convert_to('https://models.example.test/v1', 'UTF8')), 'hex'
       ) THEN
        RAISE EXCEPTION 'unique endpoint was not backfilled';
    END IF;
    IF EXISTS (
        SELECT 1 FROM model_governance_credentials
        WHERE credential_id IN ('credential.ambiguous', 'credential.orphan')
          AND endpoint_fingerprint IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'ambiguous or orphan endpoint must stay unbound';
    END IF;
    IF (SELECT count(*) FROM model_governance_credential_versions) <> 1 THEN
        RAISE EXCEPTION 'only the uniquely bound credential should be snapshotted';
    END IF;
    IF (SELECT count(*) FROM model_governance_release_credentials) <> 1 THEN
        RAISE EXCEPTION 'only the tested matching release should be bound';
    END IF;
END $$;

\ir model_governance_credentials_migration.sql

DO $$
BEGIN
    IF (SELECT count(*) FROM model_governance_credential_versions) <> 1
       OR (SELECT count(*) FROM model_governance_release_credentials) <> 1 THEN
        RAISE EXCEPTION 'migration is not idempotent';
    END IF;
END $$;

ROLLBACK;
