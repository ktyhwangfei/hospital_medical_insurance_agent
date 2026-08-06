"""Skill 草稿与定义存储端口（port/adapter 模式）。

遵循项目统一存储约定：默认 PostgreSQL，``USE_MEMORY_STORAGE=1`` 回退内存实现。
所有写操作携带乐观锁 ``expected_revision``，冲突时抛对应 ConflictError。
"""

from __future__ import annotations

from typing import Protocol

from src.domain.skill.draft_models import (
    SkillDefinition,
    SkillDraft,
    SkillDraftStatus,
    SkillLifecycleStatus,
)


class SkillDraftConflictError(ValueError):
    """草稿 revision 冲突、唯一性冲突或非法状态转换。"""


class SkillDraftNotFoundError(LookupError):
    """草稿不存在（含已软删）。"""


class SkillDefinitionConflictError(ValueError):
    """定义 revision 冲突或非法状态转换。"""


class SkillDefinitionNotFoundError(LookupError):
    """定义不存在。"""


class SkillDraftStorage(Protocol):
    def save_draft(self, draft: SkillDraft) -> SkillDraft:
        """新建草稿；draft_id 已存在或 skill_id 重复占位时抛 ConflictError。"""
        ...

    def update_draft(
        self, draft: SkillDraft, *, expected_revision: int
    ) -> SkillDraft:
        """乐观锁更新；新 revision 必须 = expected_revision + 1，否则 ConflictError。"""
        ...

    def get_draft(self, draft_id: str) -> SkillDraft | None:
        """按 draft_id 取草稿；已软删返回 None。"""
        ...

    def list_drafts(
        self,
        *,
        include_deleted: bool = False,
        skill_id: str | None = None,
        status: SkillDraftStatus | None = None,
    ) -> list[SkillDraft]:
        """列出草稿；默认排除已删除，按 updated_at 倒序。"""
        ...

    def delete_draft(
        self, draft_id: str, *, expected_revision: int
    ) -> SkillDraft:
        """软删草稿（置 deleted_at），乐观锁；已删除则 NotFoundError。"""
        ...


class SkillDefinitionStorage(Protocol):
    def save_definition(self, definition: SkillDefinition) -> SkillDefinition:
        """新建定义；skill_id 已存在时抛 ConflictError（用 update_definition 改）。"""
        ...

    def update_definition(
        self, definition: SkillDefinition, *, expected_revision: int
    ) -> SkillDefinition:
        """乐观锁更新；新 revision 必须 = expected_revision + 1，否则 ConflictError。"""
        ...

    def get_definition(self, skill_id: str) -> SkillDefinition | None: ...

    def list_definitions(
        self,
        *,
        lifecycle_status: SkillLifecycleStatus | None = None,
    ) -> list[SkillDefinition]:
        """列出定义；按 skill_id 升序。"""
        ...
