"""SkillLifecycleService 单元测试（P6）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.data_platform.storage.skill.draft_in_memory import (
    InMemorySkillDraftStorage,
)
from src.data_platform.storage.skill.draft_ports import (
    SkillDefinitionNotFoundError,
)
from src.domain.skill.draft_models import (
    SkillDefinition,
    SkillLifecycleStatus,
)
from src.runtime.skill_management.lifecycle_service import (
    SkillLifecycleError,
    SkillLifecycleService,
)


def _storage_with_definition(
    skill_id="s1", *, lifecycle=SkillLifecycleStatus.ENABLED, revision=1
):
    storage = InMemorySkillDraftStorage()
    storage.save_definition(
        SkillDefinition(
            skill_id=skill_id,
            skill_name="S1",
            business_action="explain",
            business_object="settlement",
            lifecycle_status=lifecycle,
            revision=revision,
        )
    )
    return storage


def _service(storage, governance=None):
    return SkillLifecycleService(definition_storage=storage, governance_service=governance)


def test_disable_enabled_definition():
    storage = _storage_with_definition()
    service = _service(storage)
    result = service.disable(skill_id="s1", reason="停用", actor="u", expected_revision=1)
    assert result.lifecycle_status == SkillLifecycleStatus.DISABLED
    assert result.disabled_at is not None
    assert storage.get_definition("s1").revision == 2


def test_disable_non_enabled_rejected():
    storage = _storage_with_definition(lifecycle=SkillLifecycleStatus.DISABLED)
    service = _service(storage)
    with pytest.raises(SkillLifecycleError, match="只有 enabled"):
        service.disable(skill_id="s1", reason="x", actor="u", expected_revision=1)


def test_restore_disabled_definition():
    storage = _storage_with_definition(lifecycle=SkillLifecycleStatus.DISABLED)
    service = _service(storage)
    result = service.restore(skill_id="s1", reason="恢复", actor="u", expected_revision=1)
    assert result.lifecycle_status == SkillLifecycleStatus.ENABLED
    assert result.disabled_at is None


def test_restore_non_disabled_rejected():
    storage = _storage_with_definition(lifecycle=SkillLifecycleStatus.ENABLED)
    service = _service(storage)
    with pytest.raises(SkillLifecycleError, match="只有 disabled"):
        service.restore(skill_id="s1", reason="x", actor="u", expected_revision=1)


def test_archive_definition():
    storage = _storage_with_definition(lifecycle=SkillLifecycleStatus.ENABLED)
    service = _service(storage)
    result = service.archive(skill_id="s1", reason="归档", actor="u", expected_revision=1)
    assert result.lifecycle_status == SkillLifecycleStatus.ARCHIVED
    assert result.archived_at is not None


def test_archive_already_archived_rejected():
    storage = _storage_with_definition(lifecycle=SkillLifecycleStatus.ARCHIVED)
    service = _service(storage)
    with pytest.raises(SkillLifecycleError, match="已归档"):
        service.archive(skill_id="s1", reason="x", actor="u", expected_revision=1)


def test_missing_definition_not_found():
    service = _service(InMemorySkillDraftStorage())
    with pytest.raises(SkillDefinitionNotFoundError):
        service.disable(skill_id="missing", reason="x", actor="u", expected_revision=1)


def test_stale_revision_raises_lifecycle_error():
    storage = _storage_with_definition(revision=1)
    service = _service(storage)
    # 第一次 disable 成功 → revision 2
    service.disable(skill_id="s1", reason="x", actor="u", expected_revision=1)
    # 用过期 revision 再操作（restore 需 revision=2，传1）
    with pytest.raises(SkillLifecycleError, match="revision"):
        service.restore(skill_id="s1", reason="x", actor="u", expected_revision=1)


class _FakeGovernance:
    def __init__(self, active_releases):
        self._active = active_releases
        self.retired = []

    def list_active_releases(self, skill_id, environment):
        return self._active

    def find_release(self, skill_id, release_id):
        return next((r for r in self._active if r.release_id == release_id), None)

    def retire_release(self, skill_id, release_id, *, expected_revision):
        self.retired.append((skill_id, release_id, expected_revision))


def test_disable_retires_active_releases():
    release = SimpleNamespace(release_id="rel-1", revision=1)
    governance = _FakeGovernance([release])
    storage = _storage_with_definition()
    service = _service(storage, governance=governance)
    service.disable(skill_id="s1", reason="x", actor="u", expected_revision=1)
    assert governance.retired == [("s1", "rel-1", 1)]


def test_disable_without_governance_does_not_fail():
    storage = _storage_with_definition()
    service = _service(storage, governance=None)
    result = service.disable(skill_id="s1", reason="x", actor="u", expected_revision=1)
    assert result.lifecycle_status == SkillLifecycleStatus.DISABLED
