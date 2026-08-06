"""开发与测试使用的 Skill 草稿与定义内存存储。

单一类同时实现 ``SkillDraftStorage`` 与 ``SkillDefinitionStorage`` 两个端口
（同属 Skill 管理工作台存储域，参照 ``governance_in_memory`` 一个类实现多能力的模式）。
所有返回值深拷贝，避免外部修改污染存储状态。
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock

from src.data_platform.storage.skill.draft_ports import (
    SkillDefinitionConflictError,
    SkillDefinitionNotFoundError,
    SkillDraftConflictError,
    SkillDraftNotFoundError,
)
from src.domain.skill.draft_models import (
    SkillDefinition,
    SkillDraft,
    SkillDraftStatus,
    SkillLifecycleStatus,
)


class InMemorySkillDraftStorage:
    """草稿 + 定义内存存储（线程安全）。"""

    def __init__(self) -> None:
        self._drafts: dict[str, SkillDraft] = {}
        self._definitions: dict[str, SkillDefinition] = {}
        self._lock = RLock()

    @staticmethod
    def _copy[T](value: T) -> T:
        return value.model_copy(deep=True)  # type: ignore[attr-defined, no-any-return]

    # ── SkillDraft ────────────────────────────────────────────────

    def save_draft(self, draft: SkillDraft) -> SkillDraft:
        with self._lock:
            if draft.draft_id in self._drafts:
                raise SkillDraftConflictError(f"草稿已存在: {draft.draft_id}")
            stored = self._copy(draft)
            self._drafts[draft.draft_id] = stored
            return self._copy(stored)

    def update_draft(
        self, draft: SkillDraft, *, expected_revision: int
    ) -> SkillDraft:
        with self._lock:
            current = self._drafts.get(draft.draft_id)
            if current is None or current.deleted_at is not None:
                raise SkillDraftNotFoundError(f"草稿不存在: {draft.draft_id}")
            if current.revision != expected_revision:
                raise SkillDraftConflictError("草稿 revision 已变化")
            if draft.revision != expected_revision + 1:
                raise SkillDraftConflictError("新 revision 必须递增 1")
            stored = self._copy(draft)
            self._drafts[draft.draft_id] = stored
            return self._copy(stored)

    def get_draft(self, draft_id: str) -> SkillDraft | None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None or draft.deleted_at is not None:
                return None
            return self._copy(draft)

    def list_drafts(
        self,
        *,
        include_deleted: bool = False,
        skill_id: str | None = None,
        status: SkillDraftStatus | None = None,
    ) -> list[SkillDraft]:
        with self._lock:
            result = []
            for draft in self._drafts.values():
                if not include_deleted and draft.deleted_at is not None:
                    continue
                if skill_id is not None and draft.skill_id != skill_id:
                    continue
                if status is not None and draft.status != status:
                    continue
                result.append(self._copy(draft))
            return sorted(result, key=lambda d: d.updated_at, reverse=True)

    def delete_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> SkillDraft:
        with self._lock:
            current = self._drafts.get(draft_id)
            if current is None or current.deleted_at is not None:
                raise SkillDraftNotFoundError(f"草稿不存在: {draft_id}")
            if current.revision != expected_revision:
                raise SkillDraftConflictError("草稿 revision 已变化")
            deleted = current.model_copy(
                update={
                    "revision": current.revision + 1,
                    "deleted_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                },
                deep=True,
            )
            self._drafts[draft_id] = deleted
            return self._copy(deleted)

    # ── SkillDefinition ───────────────────────────────────────────

    def save_definition(self, definition: SkillDefinition) -> SkillDefinition:
        with self._lock:
            if definition.skill_id in self._definitions:
                raise SkillDefinitionConflictError(
                    f"定义已存在: {definition.skill_id}"
                )
            stored = self._copy(definition)
            self._definitions[definition.skill_id] = stored
            return self._copy(stored)

    def update_definition(
        self, definition: SkillDefinition, *, expected_revision: int
    ) -> SkillDefinition:
        with self._lock:
            current = self._definitions.get(definition.skill_id)
            if current is None:
                raise SkillDefinitionNotFoundError(
                    f"定义不存在: {definition.skill_id}"
                )
            if current.revision != expected_revision:
                raise SkillDefinitionConflictError("定义 revision 已变化")
            if definition.revision != expected_revision + 1:
                raise SkillDefinitionConflictError("新 revision 必须递增 1")
            stored = self._copy(definition)
            self._definitions[definition.skill_id] = stored
            return self._copy(stored)

    def get_definition(self, skill_id: str) -> SkillDefinition | None:
        with self._lock:
            definition = self._definitions.get(skill_id)
            return None if definition is None else self._copy(definition)

    def list_definitions(
        self,
        *,
        lifecycle_status: SkillLifecycleStatus | None = None,
    ) -> list[SkillDefinition]:
        with self._lock:
            result = []
            for definition in self._definitions.values():
                if (
                    lifecycle_status is not None
                    and definition.lifecycle_status != lifecycle_status
                ):
                    continue
                result.append(self._copy(definition))
            return sorted(result, key=lambda d: d.skill_id)
