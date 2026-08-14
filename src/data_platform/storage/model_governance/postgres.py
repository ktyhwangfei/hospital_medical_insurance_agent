"""PostgreSQL 模型治理存储。"""

import json
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.model_governance.ports import (
    ModelGovernanceConflictError,
    ModelGovernanceNotFoundError,
)
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.model_service.governance_assets import (
    GovernanceApproval,
    GovernanceAssetType,
    GovernanceDraft,
    GovernanceEnvironment,
    GovernanceRelease,
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

    def get_draft(self, draft_id: str) -> GovernanceDraft:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_drafts WHERE draft_id=%s", (draft_id,)
        )
        if not rows:
            raise ModelGovernanceNotFoundError("草稿不存在")
        return self._draft(rows[0])

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

    def get_approval(self, approval_id: str) -> GovernanceApproval:
        rows = self._get_client().execute(
            "SELECT * FROM model_governance_approvals WHERE approval_id=%s", (approval_id,)
        )
        if not rows:
            raise ModelGovernanceNotFoundError("审批记录不存在")
        return self._approval(rows[0])

    def publish(self, release: GovernanceRelease) -> GovernanceRelease:
        client = self._get_client()
        with client.transaction():
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
            except Exception as exc:
                raise ModelGovernanceConflictError("发布记录已存在") from exc
        return self._release(rows[0])

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
