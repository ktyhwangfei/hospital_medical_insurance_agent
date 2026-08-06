"""PostgreSQL Skill 草稿与定义存储。

遵循 ``version_postgres`` / ``governance_postgres`` 模式：内联 schema 常量、
懒连接、``client.execute`` 返回 dict rows、JSONB 字段用 ``json.dumps`` 写入。

草稿表不设外键到 ``skills``：草稿的 ``skill_id`` 可指向尚未物化的全新 Skill。
乐观锁冲突与"不存在/已删除"通过二次查询区分，以满足端口契约。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.skill.draft_ports import (
    SkillDefinitionConflictError,
    SkillDefinitionNotFoundError,
    SkillDraftConflictError,
    SkillDraftNotFoundError,
)
from src.domain.skill.draft_models import (
    SkillDefinition,
    SkillDraft,
    SkillDraftSourceType,
    SkillDraftStatus,
    SkillLifecycleStatus,
)


SKILL_DRAFT_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_drafts (
    draft_id VARCHAR(128) PRIMARY KEY,
    skill_id VARCHAR(128) NOT NULL,
    skill_name VARCHAR(256) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_skill_id VARCHAR(128),
    structured_config JSONB NOT NULL DEFAULT '{}',
    raw_files JSONB NOT NULL DEFAULT '{}',
    validation_report JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'editing',
    revision INTEGER NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_skill_drafts_skill
    ON skill_drafts(skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_drafts_status
    ON skill_drafts(status);
CREATE INDEX IF NOT EXISTS idx_skill_drafts_updated
    ON skill_drafts(updated_at DESC);
"""

SKILL_DEFINITION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_definitions (
    skill_id VARCHAR(128) PRIMARY KEY,
    skill_name VARCHAR(256) NOT NULL,
    business_action VARCHAR(128) NOT NULL,
    business_object VARCHAR(128) NOT NULL,
    lifecycle_status VARCHAR(32) NOT NULL DEFAULT 'enabled',
    semantic_dependency_changed BOOLEAN NOT NULL DEFAULT FALSE,
    current_version_id VARCHAR(128),
    revision INTEGER NOT NULL DEFAULT 1,
    disabled_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_definitions_lifecycle
    ON skill_definitions(lifecycle_status);
"""


class PostgresSkillDraftStorage:
    """草稿 + 定义 PostgreSQL 存储。"""

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
            self._client.execute(SKILL_DRAFT_TABLE_SCHEMA)
            self._client.execute(SKILL_DEFINITION_TABLE_SCHEMA)
            self._schema_ensured = True
        return self._client

    # ── SkillDraft ────────────────────────────────────────────────

    def save_draft(self, draft: SkillDraft) -> SkillDraft:
        client = self._get_client()
        existing = client.execute(
            "SELECT draft_id FROM skill_drafts WHERE draft_id = %s",
            (draft.draft_id,),
        )
        if existing:
            raise SkillDraftConflictError(f"草稿已存在: {draft.draft_id}")
        client.execute(
            """
            INSERT INTO skill_drafts (
                draft_id, skill_id, skill_name, source_type, source_skill_id,
                structured_config, raw_files, validation_report, status, revision,
                created_by, created_at, updated_at, deleted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                draft.draft_id,
                draft.skill_id,
                draft.skill_name,
                draft.source_type.value,
                draft.source_skill_id,
                json.dumps(draft.structured_config, ensure_ascii=False),
                json.dumps(draft.raw_files, ensure_ascii=False),
                json.dumps(draft.validation_report, ensure_ascii=False)
                if draft.validation_report is not None
                else None,
                draft.status.value,
                draft.revision,
                draft.created_by,
                draft.created_at,
                draft.updated_at,
                None,
            ),
        )
        return draft.model_copy(deep=True)

    def update_draft(
        self, draft: SkillDraft, *, expected_revision: int
    ) -> SkillDraft:
        if draft.revision != expected_revision + 1:
            raise SkillDraftConflictError("新 revision 必须递增 1")
        client = self._get_client()
        rows = client.execute(
            """
            UPDATE skill_drafts SET
                skill_id = %s, skill_name = %s, source_type = %s,
                source_skill_id = %s, structured_config = %s, raw_files = %s,
                validation_report = %s, status = %s, revision = %s,
                updated_at = %s
            WHERE draft_id = %s AND revision = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (
                draft.skill_id,
                draft.skill_name,
                draft.source_type.value,
                draft.source_skill_id,
                json.dumps(draft.structured_config, ensure_ascii=False),
                json.dumps(draft.raw_files, ensure_ascii=False),
                json.dumps(draft.validation_report, ensure_ascii=False)
                if draft.validation_report is not None
                else None,
                draft.status.value,
                draft.revision,
                draft.updated_at,
                draft.draft_id,
                expected_revision,
            ),
        )
        if not rows:
            self._raise_draft_missing_or_conflict(draft.draft_id, expected_revision)
        return self._row_to_draft(rows[0])

    def get_draft(self, draft_id: str) -> SkillDraft | None:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM skill_drafts WHERE draft_id = %s AND deleted_at IS NULL",
            (draft_id,),
        )
        return None if not rows else self._row_to_draft(rows[0])

    def list_drafts(
        self,
        *,
        include_deleted: bool = False,
        skill_id: str | None = None,
        status: SkillDraftStatus | None = None,
    ) -> list[SkillDraft]:
        clauses = []
        params: list[Any] = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if skill_id is not None:
            clauses.append("skill_id = %s")
            params.append(skill_id)
        if status is not None:
            clauses.append("status = %s")
            params.append(status.value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        client = self._get_client()
        rows = client.execute(
            f"SELECT * FROM skill_drafts{where} ORDER BY updated_at DESC",  # noqa: S608
            tuple(params),
        )
        return [self._row_to_draft(row) for row in rows]

    def delete_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> SkillDraft:
        client = self._get_client()
        now = datetime.now(timezone.utc)
        rows = client.execute(
            """
            UPDATE skill_drafts SET
                revision = %s, deleted_at = %s, updated_at = %s
            WHERE draft_id = %s AND revision = %s AND deleted_at IS NULL
            RETURNING *
            """,
            (expected_revision + 1, now, now, draft_id, expected_revision),
        )
        if not rows:
            self._raise_draft_missing_or_conflict(draft_id, expected_revision)
        return self._row_to_draft(rows[0])

    def _raise_draft_missing_or_conflict(
        self, draft_id: str, expected_revision: int
    ) -> None:
        client = self._get_client()
        existing = client.execute(
            "SELECT revision, deleted_at FROM skill_drafts WHERE draft_id = %s",
            (draft_id,),
        )
        if not existing or existing[0]["deleted_at"] is not None:
            raise SkillDraftNotFoundError(f"草稿不存在: {draft_id}")
        raise SkillDraftConflictError("草稿 revision 已变化")

    @staticmethod
    def _json_value(value: object, default: object) -> object:
        if value is None:
            return default
        return json.loads(value) if isinstance(value, str) else value

    @classmethod
    def _row_to_draft(cls, row: dict[str, Any]) -> SkillDraft:
        return SkillDraft(
            draft_id=row["draft_id"],
            skill_id=row["skill_id"],
            skill_name=row["skill_name"],
            source_type=SkillDraftSourceType(row["source_type"]),
            source_skill_id=row["source_skill_id"],
            structured_config=cls._json_value(row.get("structured_config"), {}),
            raw_files=cls._json_value(row.get("raw_files"), {}),
            validation_report=cls._json_value(row.get("validation_report"), None)
            or None,
            status=SkillDraftStatus(row["status"]),
            revision=row["revision"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            deleted_at=row["deleted_at"],
        )

    # ── SkillDefinition ───────────────────────────────────────────

    def save_definition(self, definition: SkillDefinition) -> SkillDefinition:
        client = self._get_client()
        existing = client.execute(
            "SELECT skill_id FROM skill_definitions WHERE skill_id = %s",
            (definition.skill_id,),
        )
        if existing:
            raise SkillDefinitionConflictError(
                f"定义已存在: {definition.skill_id}"
            )
        client.execute(
            """
            INSERT INTO skill_definitions (
                skill_id, skill_name, business_action, business_object,
                lifecycle_status, semantic_dependency_changed, current_version_id,
                revision, disabled_at, archived_at, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                definition.skill_id,
                definition.skill_name,
                definition.business_action,
                definition.business_object,
                definition.lifecycle_status.value,
                definition.semantic_dependency_changed,
                definition.current_version_id,
                definition.revision,
                definition.disabled_at,
                definition.archived_at,
                definition.created_at,
                definition.updated_at,
            ),
        )
        return definition.model_copy(deep=True)

    def update_definition(
        self, definition: SkillDefinition, *, expected_revision: int
    ) -> SkillDefinition:
        if definition.revision != expected_revision + 1:
            raise SkillDefinitionConflictError("新 revision 必须递增 1")
        client = self._get_client()
        rows = client.execute(
            """
            UPDATE skill_definitions SET
                skill_name = %s, business_action = %s, business_object = %s,
                lifecycle_status = %s, semantic_dependency_changed = %s,
                current_version_id = %s, revision = %s,
                disabled_at = %s, archived_at = %s, updated_at = %s
            WHERE skill_id = %s AND revision = %s
            RETURNING *
            """,
            (
                definition.skill_name,
                definition.business_action,
                definition.business_object,
                definition.lifecycle_status.value,
                definition.semantic_dependency_changed,
                definition.current_version_id,
                definition.revision,
                definition.disabled_at,
                definition.archived_at,
                definition.updated_at,
                definition.skill_id,
                expected_revision,
            ),
        )
        if not rows:
            self._raise_definition_missing_or_conflict(definition.skill_id)
        return self._row_to_definition(rows[0])

    def get_definition(self, skill_id: str) -> SkillDefinition | None:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM skill_definitions WHERE skill_id = %s",
            (skill_id,),
        )
        return None if not rows else self._row_to_definition(rows[0])

    def list_definitions(
        self,
        *,
        lifecycle_status: SkillLifecycleStatus | None = None,
    ) -> list[SkillDefinition]:
        client = self._get_client()
        if lifecycle_status is not None:
            rows = client.execute(
                "SELECT * FROM skill_definitions WHERE lifecycle_status = %s ORDER BY skill_id",
                (lifecycle_status.value,),
            )
        else:
            rows = client.execute(
                "SELECT * FROM skill_definitions ORDER BY skill_id", ()
            )
        return [self._row_to_definition(row) for row in rows]

    def _raise_definition_missing_or_conflict(self, skill_id: str) -> None:
        client = self._get_client()
        existing = client.execute(
            "SELECT skill_id FROM skill_definitions WHERE skill_id = %s",
            (skill_id,),
        )
        if not existing:
            raise SkillDefinitionNotFoundError(f"定义不存在: {skill_id}")
        raise SkillDefinitionConflictError("定义 revision 已变化")

    @classmethod
    def _row_to_definition(cls, row: dict[str, Any]) -> SkillDefinition:
        return SkillDefinition(
            skill_id=row["skill_id"],
            skill_name=row["skill_name"],
            business_action=row["business_action"],
            business_object=row["business_object"],
            lifecycle_status=SkillLifecycleStatus(row["lifecycle_status"]),
            semantic_dependency_changed=row["semantic_dependency_changed"],
            current_version_id=row["current_version_id"],
            revision=row["revision"],
            disabled_at=row["disabled_at"],
            archived_at=row["archived_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
