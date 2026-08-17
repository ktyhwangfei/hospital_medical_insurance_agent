"""PostgreSQL 模型治理存储。"""

import json
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.model_governance.ports import (
    GovernanceCredentialPrecondition,
    GovernanceReleasePrecondition,
    ModelGovernanceConflictError,
    ModelGovernanceNotFoundError,
)
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetType,
    GovernanceConnectionTest,
    GovernanceCredential,
    GovernanceDraft,
    GovernanceEnvironment,
    GovernanceRelease,
    GovernanceReleaseCredentialBinding,
    GovernanceVersion,
)


MODEL_GOVERNANCE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_governance_drafts (
    draft_id VARCHAR(64) PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    asset_type VARCHAR(32) NOT NULL,
    content JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    revision INTEGER NOT NULL,
    validation_issues JSONB NOT NULL DEFAULT '[]',
    created_by VARCHAR(128) NOT NULL,
    last_edited_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_governance_drafts_type
    ON model_governance_drafts(asset_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS model_governance_approvals (
    approval_id VARCHAR(64) PRIMARY KEY,
    draft_id VARCHAR(64) NOT NULL,
    asset_id VARCHAR(128) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    approved_by VARCHAR(128) NOT NULL,
    reason TEXT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS model_governance_versions (
    version_id VARCHAR(64) PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    asset_type VARCHAR(32) NOT NULL,
    version_number INTEGER NOT NULL,
    content JSONB NOT NULL,
    content_hash CHAR(64) NOT NULL,
    approval_id VARCHAR(64) NOT NULL REFERENCES model_governance_approvals(approval_id),
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE(asset_id, version_number),
    UNIQUE(asset_id, content_hash)
);

CREATE TABLE IF NOT EXISTS model_governance_releases (
    release_id VARCHAR(64) PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    asset_type VARCHAR(32) NOT NULL,
    version_id VARCHAR(64) NOT NULL REFERENCES model_governance_versions(version_id),
    environment VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    previous_release_id VARCHAR(64) REFERENCES model_governance_releases(release_id),
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    retired_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_model_governance_active_release
    ON model_governance_releases(asset_id, environment) WHERE status = 'active';

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
"""


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False)


def _decoded(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PostgresModelGovernanceStorage:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            self._client.execute(MODEL_GOVERNANCE_TABLE_SCHEMA)
        return self._client

    @staticmethod
    def _draft(row: dict[str, Any]) -> GovernanceDraft:
        return GovernanceDraft.model_validate(
            {**row, "content": _decoded(row["content"]), "validation_issues": _decoded(row["validation_issues"])}
        )

    @staticmethod
    def _version(row: dict[str, Any]) -> GovernanceVersion:
        return GovernanceVersion.model_validate({**row, "content": _decoded(row["content"])})

    @staticmethod
    def _approval(row: dict[str, Any]) -> GovernanceApproval:
        return GovernanceApproval.model_validate(row)

    @staticmethod
    def _release(row: dict[str, Any]) -> GovernanceRelease:
        return GovernanceRelease.model_validate(row)

    @staticmethod
    def _credential(row: dict[str, Any]) -> GovernanceCredential:
        return GovernanceCredential.model_validate(row)

    @staticmethod
    def _connection_test(row: dict[str, Any]) -> GovernanceConnectionTest:
        return GovernanceConnectionTest.model_validate(row)

    @staticmethod
    def _release_credential_binding(
        row: dict[str, Any],
    ) -> GovernanceReleaseCredentialBinding:
        return GovernanceReleaseCredentialBinding.model_validate(row)

    def put_credential(
        self, credential: GovernanceCredential
    ) -> GovernanceCredential:
        client = self._get_client()
        with client.transaction():
            saved = self._put_credential(client, credential)
        return saved

    def _put_credential(
        self,
        client: PostgreSQLClient,
        credential: GovernanceCredential,
    ) -> GovernanceCredential:
        rows = client.execute(
            """INSERT INTO model_governance_credentials
               (credential_id, encrypted_api_key, secret_fingerprint,
                endpoint_fingerprint, revision, updated_by, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (credential_id) DO UPDATE SET
                 encrypted_api_key=EXCLUDED.encrypted_api_key,
                 secret_fingerprint=EXCLUDED.secret_fingerprint,
                 endpoint_fingerprint=EXCLUDED.endpoint_fingerprint,
                 revision=EXCLUDED.revision,
                 updated_by=EXCLUDED.updated_by,
                 updated_at=EXCLUDED.updated_at
               WHERE model_governance_credentials.revision = EXCLUDED.revision - 1
               RETURNING *""",
            (
                credential.credential_id,
                credential.encrypted_api_key,
                credential.secret_fingerprint,
                credential.endpoint_fingerprint,
                credential.revision,
                credential.updated_by,
                credential.updated_at,
            ),
        )
        if not rows:
            raise ModelGovernanceConflictError("凭据 revision 已变化")
        client.execute(
            """INSERT INTO model_governance_credential_versions
               (credential_id, revision, encrypted_api_key, secret_fingerprint,
                endpoint_fingerprint, updated_by, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                credential.credential_id,
                credential.revision,
                credential.encrypted_api_key,
                credential.secret_fingerprint,
                credential.endpoint_fingerprint,
                credential.updated_by,
                credential.updated_at,
            ),
        )
        return self._credential(rows[0])

    def get_credential(self, credential_id: str) -> GovernanceCredential:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_credentials WHERE credential_id=%s",
            (credential_id,),
        )
        if not rows:
            raise ModelGovernanceNotFoundError("凭据不存在")
        return self._credential(rows[0])

    def get_credential_revision(
        self, credential_id: str, revision: int
    ) -> GovernanceCredential:
        rows = self._get_client().execute(
            """SELECT * FROM model_governance_credential_versions
               WHERE credential_id=%s AND revision=%s""",
            (credential_id, revision),
        )
        if not rows:
            raise ModelGovernanceNotFoundError("凭据版本不存在")
        return self._credential(rows[0])

    def get_release_credential_binding(
        self, release_id: str
    ) -> GovernanceReleaseCredentialBinding:
        rows = self._get_client().execute(
            """SELECT * FROM model_governance_release_credentials
               WHERE release_id=%s""",
            (release_id,),
        )
        if not rows:
            raise ModelGovernanceNotFoundError("发布凭据绑定不存在")
        return self._release_credential_binding(rows[0])

    def save_connection_test(
        self, result: GovernanceConnectionTest
    ) -> GovernanceConnectionTest:
        try:
            rows = self._get_client().execute(
                """INSERT INTO model_governance_connection_tests
                   (test_id, asset_id, content_hash, credential_fingerprint, succeeded,
                    latency_ms, safe_message, tested_by, tested_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (
                    result.test_id,
                    result.asset_id,
                    result.content_hash,
                    result.credential_fingerprint,
                    result.succeeded,
                    result.latency_ms,
                    result.safe_message,
                    result.tested_by,
                    result.tested_at,
                ),
            )
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
            if sqlstate and str(sqlstate).startswith("23"):
                raise ModelGovernanceConflictError(
                    "连接测试记录已存在"
                ) from exc
            raise
        return self._connection_test(rows[0])

    def find_successful_connection_test(
        self,
        asset_id: str,
        content_hash: str,
        credential_fingerprint: str,
    ) -> GovernanceConnectionTest | None:
        rows = self._get_client().execute(
            """SELECT * FROM model_governance_connection_tests
               WHERE asset_id=%s AND content_hash=%s AND credential_fingerprint=%s
                 AND succeeded=TRUE
               ORDER BY tested_at DESC, test_id DESC LIMIT 1""",
            (asset_id, content_hash, credential_fingerprint),
        )
        return self._connection_test(rows[0]) if rows else None

    def create_draft(self, draft: GovernanceDraft) -> GovernanceDraft:
        sql = """INSERT INTO model_governance_drafts
            (draft_id, asset_id, asset_type, content, status, revision, validation_issues,
             created_by, last_edited_by, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *"""
        try:
            rows = self._get_client().execute(sql, (
                draft.draft_id, draft.asset_id, draft.asset_type.value, _json(draft.content),
                draft.status.value, draft.revision, _json(draft.validation_issues), draft.created_by,
                draft.last_edited_by, draft.created_at, draft.updated_at,
            ))
        except Exception as exc:
            raise ModelGovernanceConflictError("草稿已存在") from exc
        return self._draft(rows[0])

    def create_draft_with_credential(
        self,
        draft: GovernanceDraft,
        credential: GovernanceCredential,
    ) -> GovernanceDraft:
        sql = """INSERT INTO model_governance_drafts
            (draft_id, asset_id, asset_type, content, status, revision, validation_issues,
             created_by, last_edited_by, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *"""
        client = self._get_client()
        with client.transaction():
            try:
                rows = client.execute(
                    sql,
                    (
                        draft.draft_id,
                        draft.asset_id,
                        draft.asset_type.value,
                        _json(draft.content),
                        draft.status.value,
                        draft.revision,
                        _json(draft.validation_issues),
                        draft.created_by,
                        draft.last_edited_by,
                        draft.created_at,
                        draft.updated_at,
                    ),
                )
            except Exception as exc:
                sqlstate = getattr(exc, "sqlstate", None) or getattr(
                    exc, "pgcode", None
                )
                if sqlstate and str(sqlstate).startswith("23"):
                    raise ModelGovernanceConflictError("草稿已存在") from exc
                raise
            self._put_credential(client, credential)
        return self._draft(rows[0])

    def update_draft(self, draft: GovernanceDraft, *, expected_revision: int) -> GovernanceDraft:
        if draft.revision != expected_revision + 1:
            raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
        rows = self._get_client().execute(
            """UPDATE model_governance_drafts SET content=%s, status=%s, revision=%s,
               validation_issues=%s, last_edited_by=%s, updated_at=%s
               WHERE draft_id=%s AND revision=%s RETURNING *""",
            (_json(draft.content), draft.status.value, draft.revision, _json(draft.validation_issues),
             draft.last_edited_by, draft.updated_at, draft.draft_id, expected_revision),
        )
        if not rows:
            raise ModelGovernanceConflictError("草稿 revision 已变化或草稿不存在")
        return self._draft(rows[0])

    def update_draft_with_credential(
        self,
        draft: GovernanceDraft,
        credential: GovernanceCredential,
        *,
        expected_revision: int,
    ) -> GovernanceDraft:
        if draft.revision != expected_revision + 1:
            raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
        client = self._get_client()
        with client.transaction():
            rows = client.execute(
                """UPDATE model_governance_drafts SET content=%s, status=%s, revision=%s,
                   validation_issues=%s, last_edited_by=%s, updated_at=%s
                   WHERE draft_id=%s AND revision=%s RETURNING *""",
                (
                    _json(draft.content),
                    draft.status.value,
                    draft.revision,
                    _json(draft.validation_issues),
                    draft.last_edited_by,
                    draft.updated_at,
                    draft.draft_id,
                    expected_revision,
                ),
            )
            if not rows:
                raise ModelGovernanceConflictError(
                    "草稿 revision 已变化或草稿不存在"
                )
            self._put_credential(client, credential)
        return self._draft(rows[0])

    def get_draft(self, draft_id: str) -> GovernanceDraft:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_drafts WHERE draft_id=%s", (draft_id,)
        )
        if not rows:
            raise ModelGovernanceNotFoundError("草稿不存在")
        return self._draft(rows[0])

    def delete_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> GovernanceDraft:
        rows = self._get_client().execute(
            "DELETE FROM model_governance_drafts WHERE draft_id=%s AND revision=%s RETURNING *",
            (draft_id, expected_revision),
        )
        if rows:
            return self._draft(rows[0])
        exists = self._get_client().execute(
            "SELECT revision FROM model_governance_drafts WHERE draft_id=%s", (draft_id,)
        )
        if exists:
            raise ModelGovernanceConflictError("草稿 revision 已变化")
        raise ModelGovernanceNotFoundError("草稿不存在")

    def list_drafts(self, asset_type: GovernanceAssetType | None = None) -> list[GovernanceDraft]:
        if asset_type is None:
            rows = self._get_client().execute(
                "SELECT * FROM model_governance_drafts ORDER BY updated_at DESC"
            )
        else:
            rows = self._get_client().execute(
                "SELECT * FROM model_governance_drafts WHERE asset_type=%s ORDER BY updated_at DESC",
                (asset_type.value,),
            )
        return [self._draft(row) for row in rows]

    def save_version(self, version: GovernanceVersion) -> GovernanceVersion:
        existing = self._get_client().execute(
            "SELECT * FROM model_governance_versions WHERE asset_id=%s AND content_hash=%s",
            (version.asset_id, version.content_hash),
        )
        if existing:
            return self._version(existing[0])
        try:
            rows = self._get_client().execute(
                """INSERT INTO model_governance_versions
                   (version_id, asset_id, asset_type, version_number, content, content_hash,
                    approval_id, created_by, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (version.version_id, version.asset_id, version.asset_type.value,
                 version.version_number, _json(version.content), version.content_hash,
                 version.approval_id, version.created_by, version.created_at),
            )
        except Exception as exc:
            raise ModelGovernanceConflictError("版本已存在") from exc
        return self._version(rows[0])

    def get_version(self, version_id: str) -> GovernanceVersion:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_versions WHERE version_id=%s", (version_id,)
        )
        if not rows:
            raise ModelGovernanceNotFoundError("版本不存在")
        return self._version(rows[0])

    def list_versions(self, asset_id: str) -> list[GovernanceVersion]:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_versions WHERE asset_id=%s ORDER BY version_number DESC",
            (asset_id,),
        )
        return [self._version(row) for row in rows]

    def save_approval(self, approval: GovernanceApproval) -> GovernanceApproval:
        try:
            rows = self._get_client().execute(
                """INSERT INTO model_governance_approvals
                   (approval_id, draft_id, asset_id, content_hash, approved_by, reason, approved_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (approval.approval_id, approval.draft_id, approval.asset_id,
                 approval.content_hash, approval.approved_by, approval.reason, approval.approved_at),
            )
        except Exception as exc:
            raise ModelGovernanceConflictError("审批记录已存在") from exc
        return self._approval(rows[0])

    def approve_draft(
        self,
        draft: GovernanceDraft,
        approval: GovernanceApproval,
        *,
        expected_revision: int,
    ) -> GovernanceDraft:
        if draft.revision != expected_revision + 1:
            raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
        client = self._get_client()
        try:
            with client.transaction():
                client.execute(
                    """INSERT INTO model_governance_approvals
                       (approval_id, draft_id, asset_id, content_hash, approved_by, reason, approved_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (approval.approval_id, approval.draft_id, approval.asset_id,
                     approval.content_hash, approval.approved_by, approval.reason,
                     approval.approved_at),
                )
                rows = client.execute(
                    """UPDATE model_governance_drafts SET content=%s, status=%s, revision=%s,
                       validation_issues=%s, last_edited_by=%s, updated_at=%s
                       WHERE draft_id=%s AND revision=%s RETURNING *""",
                    (_json(draft.content), draft.status.value, draft.revision,
                     _json(draft.validation_issues), draft.last_edited_by, draft.updated_at,
                     draft.draft_id, expected_revision),
                )
                if not rows:
                    raise ModelGovernanceConflictError("草稿 revision 已变化或草稿不存在")
        except ModelGovernanceConflictError:
            raise
        except Exception as exc:
            raise ModelGovernanceConflictError("审批记录已存在") from exc
        return self._draft(rows[0])

    def get_approval(self, approval_id: str) -> GovernanceApproval:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_approvals WHERE approval_id=%s", (approval_id,)
        )
        if not rows:
            raise ModelGovernanceNotFoundError("审批记录不存在")
        return self._approval(rows[0])

    @staticmethod
    def _check_credential_precondition(
        client: PostgreSQLClient,
        precondition: GovernanceCredentialPrecondition | None,
    ) -> None:
        if precondition is None:
            return
        rows = client.execute(
            """SELECT secret_fingerprint, revision
               FROM model_governance_credentials
               WHERE credential_id=%s FOR UPDATE""",
            (precondition.credential_id,),
        )
        if (
            not rows
            or rows[0]["secret_fingerprint"] != precondition.expected_fingerprint
            or rows[0]["revision"] != precondition.expected_revision
        ):
            raise ModelGovernanceConflictError("模型凭据已变化")

    @staticmethod
    def _check_release_preconditions(
        client: PostgreSQLClient,
        preconditions: tuple[GovernanceReleasePrecondition, ...],
    ) -> None:
        for precondition in sorted(
            preconditions, key=lambda item: (item.asset_id, item.environment.value)
        ):
            rows = client.execute(
                """SELECT release_id, version_id FROM model_governance_releases
                   WHERE asset_id=%s AND environment=%s AND status='active'
                   FOR UPDATE""",
                (precondition.asset_id, precondition.environment.value),
            )
            if (
                not rows
                or rows[0]["release_id"] != precondition.expected_release_id
                or rows[0]["version_id"] != precondition.expected_version_id
            ):
                raise ModelGovernanceConflictError("引用的模型发布已变化")

    @staticmethod
    def _check_credential_binding(
        client: PostgreSQLClient,
        release: GovernanceRelease,
        binding: GovernanceReleaseCredentialBinding | None,
    ) -> None:
        if binding is None:
            return
        rows = client.execute(
            """SELECT secret_fingerprint
               FROM model_governance_credential_versions
               WHERE credential_id=%s AND revision=%s FOR SHARE""",
            (binding.credential_id, binding.credential_revision),
        )
        if (
            binding.release_id != release.release_id
            or not rows
            or rows[0]["secret_fingerprint"] != binding.credential_fingerprint
        ):
            raise ModelGovernanceConflictError("发布凭据绑定无效")

    @staticmethod
    def _insert_credential_binding(
        client: PostgreSQLClient,
        binding: GovernanceReleaseCredentialBinding | None,
    ) -> None:
        if binding is None:
            return
        client.execute(
            """INSERT INTO model_governance_release_credentials
               (release_id, credential_id, credential_revision,
                credential_fingerprint) VALUES (%s,%s,%s,%s)""",
            (
                binding.release_id,
                binding.credential_id,
                binding.credential_revision,
                binding.credential_fingerprint,
            ),
        )

    def publish(
        self,
        release: GovernanceRelease,
        *,
        credential_precondition: GovernanceCredentialPrecondition | None = None,
        credential_binding: GovernanceReleaseCredentialBinding | None = None,
        referenced_release_preconditions: tuple[
            GovernanceReleasePrecondition, ...
        ] = (),
    ) -> GovernanceRelease:
        client = self._get_client()
        with client.transaction():
            self._check_credential_precondition(client, credential_precondition)
            self._check_release_preconditions(
                client, referenced_release_preconditions
            )
            self._check_credential_binding(client, release, credential_binding)
            active_rows = client.execute(
                """SELECT * FROM model_governance_releases
                   WHERE asset_id=%s AND environment=%s AND status='active' FOR UPDATE""",
                (release.asset_id, release.environment.value),
            )
            active_id = active_rows[0]["release_id"] if active_rows else None
            if active_id != release.previous_release_id:
                raise ModelGovernanceConflictError("发布基线已变化")
            if active_id:
                client.execute(
                    """UPDATE model_governance_releases SET status='retired', retired_at=%s
                       WHERE release_id=%s""",
                    (datetime.now(timezone.utc), active_id),
                )
            try:
                rows = client.execute(
                    """INSERT INTO model_governance_releases
                       (release_id, asset_id, asset_type, version_id, environment, status,
                        previous_release_id, created_by, created_at, retired_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (release.release_id, release.asset_id, release.asset_type.value,
                     release.version_id, release.environment.value, release.status.value,
                     release.previous_release_id, release.created_by, release.created_at,
                     release.retired_at),
                )
                self._insert_credential_binding(client, credential_binding)
            except Exception as exc:
                sqlstate = getattr(exc, "sqlstate", None) or getattr(
                    exc, "pgcode", None
                )
                if sqlstate and str(sqlstate).startswith("23"):
                    raise ModelGovernanceConflictError(
                        "发布记录已存在"
                    ) from exc
                raise
        return self._release(rows[0])

    def publish_draft_version(
        self,
        draft: GovernanceDraft,
        version: GovernanceVersion,
        release: GovernanceRelease,
        *,
        expected_revision: int,
        credential_precondition: GovernanceCredentialPrecondition | None = None,
        credential_binding: GovernanceReleaseCredentialBinding | None = None,
        referenced_release_preconditions: tuple[
            GovernanceReleasePrecondition, ...
        ] = (),
    ) -> GovernanceRelease:
        if draft.revision != expected_revision + 1:
            raise ModelGovernanceConflictError("草稿 revision 必须递增 1")
        client = self._get_client()
        try:
            with client.transaction():
                draft_rows = client.execute(
                    """SELECT revision FROM model_governance_drafts
                       WHERE draft_id=%s FOR UPDATE""",
                    (draft.draft_id,),
                )
                if (
                    not draft_rows
                    or draft_rows[0]["revision"] != expected_revision
                ):
                    raise ModelGovernanceConflictError(
                        "草稿 revision 已变化或草稿不存在"
                    )
                self._check_credential_precondition(
                    client, credential_precondition
                )
                self._check_release_preconditions(
                    client, referenced_release_preconditions
                )
                self._check_credential_binding(
                    client, release, credential_binding
                )

                active_rows = client.execute(
                    """SELECT * FROM model_governance_releases
                       WHERE asset_id=%s AND environment=%s AND status='active'
                       FOR UPDATE""",
                    (release.asset_id, release.environment.value),
                )
                active_id = active_rows[0]["release_id"] if active_rows else None
                if active_id != release.previous_release_id:
                    raise ModelGovernanceConflictError("发布基线已变化")

                existing_versions = client.execute(
                    """SELECT * FROM model_governance_versions
                       WHERE asset_id=%s AND content_hash=%s FOR UPDATE""",
                    (version.asset_id, version.content_hash),
                )
                if existing_versions:
                    if existing_versions[0]["version_id"] != release.version_id:
                        raise ModelGovernanceConflictError(
                            "发布引用的版本已变化"
                        )
                else:
                    version_conflicts = client.execute(
                        """SELECT version_id FROM model_governance_versions
                           WHERE version_id=%s OR (asset_id=%s AND version_number=%s)
                           FOR UPDATE""",
                        (
                            version.version_id,
                            version.asset_id,
                            version.version_number,
                        ),
                    )
                    if version_conflicts:
                        raise ModelGovernanceConflictError("版本已存在")

                updated_rows = client.execute(
                    """UPDATE model_governance_drafts SET content=%s, status=%s,
                       revision=%s, validation_issues=%s, last_edited_by=%s,
                       updated_at=%s WHERE draft_id=%s AND revision=%s RETURNING *""",
                    (
                        _json(draft.content),
                        draft.status.value,
                        draft.revision,
                        _json(draft.validation_issues),
                        draft.last_edited_by,
                        draft.updated_at,
                        draft.draft_id,
                        expected_revision,
                    ),
                )
                if not updated_rows:
                    raise ModelGovernanceConflictError(
                        "草稿 revision 已变化或草稿不存在"
                    )

                if not existing_versions:
                    client.execute(
                        """INSERT INTO model_governance_versions
                           (version_id, asset_id, asset_type, version_number, content,
                            content_hash, approval_id, created_by, created_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            version.version_id,
                            version.asset_id,
                            version.asset_type.value,
                            version.version_number,
                            _json(version.content),
                            version.content_hash,
                            version.approval_id,
                            version.created_by,
                            version.created_at,
                        ),
                    )
                if active_id:
                    client.execute(
                        """UPDATE model_governance_releases
                           SET status='retired', retired_at=%s WHERE release_id=%s""",
                        (datetime.now(timezone.utc), active_id),
                    )
                release_rows = client.execute(
                    """INSERT INTO model_governance_releases
                       (release_id, asset_id, asset_type, version_id, environment, status,
                        previous_release_id, created_by, created_at, retired_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        release.release_id,
                        release.asset_id,
                        release.asset_type.value,
                        release.version_id,
                        release.environment.value,
                        release.status.value,
                        release.previous_release_id,
                        release.created_by,
                        release.created_at,
                        release.retired_at,
                    ),
                )
                self._insert_credential_binding(client, credential_binding)
        except ModelGovernanceConflictError:
            raise
        except Exception as exc:
            sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
            if sqlstate and str(sqlstate).startswith("23"):
                raise ModelGovernanceConflictError(
                    "发布记录或版本已存在"
                ) from exc
            raise
        return self._release(release_rows[0])

    def get_release(self, release_id: str) -> GovernanceRelease:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_releases WHERE release_id=%s", (release_id,)
        )
        if not rows:
            raise ModelGovernanceNotFoundError("发布记录不存在")
        return self._release(rows[0])

    def list_releases(
        self,
        asset_id: str | None = None,
        environment: GovernanceEnvironment | None = None,
    ) -> list[GovernanceRelease]:
        clauses: list[str] = []
        params: list[str] = []
        if asset_id is not None:
            clauses.append("asset_id=%s")
            params.append(asset_id)
        if environment is not None:
            clauses.append("environment=%s")
            params.append(environment.value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._get_client().execute(
            f"SELECT * FROM model_governance_releases{where} ORDER BY created_at DESC, release_id DESC",
            tuple(params),
        )
        return [self._release(row) for row in rows]

    def get_active_release(
        self, asset_id: str, environment: GovernanceEnvironment
    ) -> GovernanceRelease | None:
        rows = self._get_client().execute(
            """SELECT * FROM model_governance_releases
               WHERE asset_id=%s AND environment=%s AND status='active'""",
            (asset_id, environment.value),
        )
        return self._release(rows[0]) if rows else None
