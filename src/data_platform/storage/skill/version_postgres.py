"""PostgreSQL Skill 版本存储。"""

from __future__ import annotations

import json
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.skill.postgres import SKILL_TABLE_SCHEMA
from src.data_platform.storage.skill.version_ports import SkillVersionConflictError
from src.domain.skill.version_models import SkillValidationIssue, SkillVersion


SKILL_VERSION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_versions (
    version_id VARCHAR(64) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL REFERENCES skills(skill_id),
    semantic_version VARCHAR(64) NOT NULL,
    source_commit VARCHAR(64) NOT NULL,
    source_path TEXT NOT NULL,
    artifact_hash VARCHAR(64) NOT NULL,
    manifest_snapshot JSONB NOT NULL DEFAULT '{}',
    dependency_snapshot JSONB NOT NULL DEFAULT '{}',
    file_count INTEGER NOT NULL,
    validation_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    validation_issues JSONB NOT NULL DEFAULT '[]',
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(skill_id, semantic_version),
    UNIQUE(skill_id, artifact_hash)
);
CREATE INDEX IF NOT EXISTS idx_skill_versions_skill_created
    ON skill_versions(skill_id, created_at DESC);
"""


class PostgresSkillVersionStorage:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        client: PostgreSQLClient | None = None,
    ) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client = client
        self._schema_ensured = False

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
        if not self._schema_ensured:
            self._client.execute(SKILL_TABLE_SCHEMA)
            self._client.execute(SKILL_VERSION_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    def save_version(self, version: SkillVersion) -> SkillVersion:
        existing_artifact = self.find_by_artifact_hash(
            version.skill_id, version.artifact_hash
        )
        if existing_artifact is not None:
            return existing_artifact

        existing_semantic_version = self._find_by_semantic_version(
            version.skill_id, version.semantic_version
        )
        if existing_semantic_version is not None:
            raise SkillVersionConflictError(
                f"Skill {version.skill_id} 的语义版本 {version.semantic_version} 已绑定其他制品"
            )

        client = self._get_client()
        manifest = version.manifest_snapshot
        skill_name = str(manifest.get("skill_name") or version.skill_id)
        description = str(manifest.get("description") or f"{skill_name} Skill")
        parent_sql = """
            INSERT INTO skills (skill_id, name, description, owner, skill_metadata)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (skill_id) DO NOTHING
        """
        insert_sql = """
            INSERT INTO skill_versions (
                version_id, skill_id, semantic_version, source_commit, source_path,
                artifact_hash, manifest_snapshot, dependency_snapshot, file_count,
                validation_status, validation_issues, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """
        params = (
            version.version_id,
            version.skill_id,
            version.semantic_version,
            version.source_commit,
            version.source_path,
            version.artifact_hash,
            json.dumps(version.manifest_snapshot, ensure_ascii=False),
            json.dumps(version.dependency_snapshot, ensure_ascii=False),
            version.file_count,
            version.validation_status.value,
            json.dumps(
                [issue.model_dump() for issue in version.validation_issues],
                ensure_ascii=False,
            ),
            version.created_by,
            version.created_at,
        )
        try:
            with client.transaction():
                client.execute(
                    parent_sql,
                    (
                        version.skill_id,
                        skill_name,
                        description,
                        "information_department",
                        json.dumps({"version": version.semantic_version}),
                    ),
                )
                rows = client.execute(insert_sql, params)
        except SkillVersionConflictError:
            raise
        except Exception as exc:
            existing_artifact = self.find_by_artifact_hash(
                version.skill_id, version.artifact_hash
            )
            if existing_artifact is not None:
                return existing_artifact
            existing_semantic_version = self._find_by_semantic_version(
                version.skill_id, version.semantic_version
            )
            if existing_semantic_version is not None:
                raise SkillVersionConflictError(
                    f"Skill {version.skill_id} 的语义版本 {version.semantic_version} 已绑定其他制品"
                ) from exc
            raise
        return version if not rows else self._row_to_version(rows[0])

    def get_version(self, skill_id: str, version_id: str) -> SkillVersion | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_versions WHERE skill_id = %s AND version_id = %s",
            (skill_id, version_id),
        )
        return None if not rows else self._row_to_version(rows[0])

    def find_by_artifact_hash(
        self, skill_id: str, artifact_hash: str
    ) -> SkillVersion | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_versions WHERE skill_id = %s AND artifact_hash = %s",
            (skill_id, artifact_hash),
        )
        return None if not rows else self._row_to_version(rows[0])

    def _find_by_semantic_version(
        self, skill_id: str, semantic_version: str
    ) -> SkillVersion | None:
        rows = self._get_client().execute(
            "SELECT * FROM skill_versions WHERE skill_id = %s AND semantic_version = %s",
            (skill_id, semantic_version),
        )
        return None if not rows else self._row_to_version(rows[0])

    def list_versions(self, skill_id: str) -> list[SkillVersion]:
        rows = self._get_client().execute(
            "SELECT * FROM skill_versions WHERE skill_id = %s ORDER BY created_at DESC",
            (skill_id,),
        )
        return [self._row_to_version(row) for row in rows]

    @staticmethod
    def _json_value(value: object, default: object) -> object:
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    @classmethod
    def _row_to_version(cls, row: dict[str, Any]) -> SkillVersion:
        issues = cls._json_value(row.get("validation_issues"), [])
        return SkillVersion(
            version_id=row["version_id"],
            skill_id=row["skill_id"],
            semantic_version=row["semantic_version"],
            source_commit=row["source_commit"],
            source_path=row["source_path"],
            artifact_hash=row["artifact_hash"],
            manifest_snapshot=cls._json_value(row.get("manifest_snapshot"), {}),
            dependency_snapshot=cls._json_value(
                row.get("dependency_snapshot"), {}
            ),
            file_count=row["file_count"],
            validation_status=row["validation_status"],
            validation_issues=[SkillValidationIssue(**issue) for issue in issues],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )
