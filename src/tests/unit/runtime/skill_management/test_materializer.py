"""SkillMaterializer 单元测试（P5）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.data_platform.storage.skill.draft_in_memory import (
    InMemorySkillDraftStorage,
)
from src.runtime.skill_management.draft_service import SkillDraftService
from src.runtime.skill_management.materializer import (
    SkillMaterializeError,
    SkillMaterializer,
)


class FakeVersionService:
    def __init__(self, *, fail_once=False):
        self.calls = 0
        self.fail_once = fail_once

    def sync_version(self, skill_id, *, source_commit, created_by):
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RuntimeError("simulated version registration failure")
        return SimpleNamespace(
            version_id="ver-1",
            skill_id=skill_id,
            semantic_version="1.0.0",
            artifact_hash="a" * 64,
        )


def _validated_draft(service, skill_id="new_skill"):
    draft = service.create_from_template(
        skill_id=skill_id,
        skill_name="New Skill",
        created_by="u-admin",
        business_action="explain",
        business_object="settlement",
    )
    service.record_validation(
        draft_id=draft.draft_id,
        validation_report={"blocking": []},
        expected_revision=draft.revision,
        blocking_ok=True,
    )
    return draft


def _materializer(tmp_path, *, version_service=None, storage=None):
    storage = storage or InMemorySkillDraftStorage()
    draft_service = SkillDraftService(storage=storage)
    return (
        SkillMaterializer(
            draft_service=draft_service,
            draft_storage=storage,
            version_service=version_service or FakeVersionService(),
            skills_root=tmp_path / "skills",
        ),
        draft_service,
        storage,
    )


def test_materialize_writes_files_and_registers_version(tmp_path):
    materializer, draft_service, _ = _materializer(tmp_path)
    draft = _validated_draft(draft_service)
    skills_root = tmp_path / "skills"
    skills_root.mkdir()

    result = materializer.materialize(
        draft_id=draft.draft_id,
        expected_revision=draft.revision,
        created_by="u-admin",
        reason="首次发布",
    )
    assert result.skill_id == "new_skill"
    assert result.version_id == "ver-1"
    assert (skills_root / "new_skill" / "skill_manifest.yaml").exists()
    assert (skills_root / "new_skill" / "assembler.py").exists()


def test_materialize_creates_enabled_definition(tmp_path):
    materializer, draft_service, storage = _materializer(tmp_path)
    draft = _validated_draft(draft_service)
    (tmp_path / "skills").mkdir()
    result = materializer.materialize(
        draft_id=draft.draft_id,
        expected_revision=draft.revision,
        created_by="u",
        reason="test",
    )
    defn = storage.get_definition("new_skill")
    assert defn is not None
    assert defn.lifecycle_status.value == "enabled"
    assert defn.current_version_id == "ver-1"


def test_materialize_marks_draft_materialized(tmp_path):
    materializer, draft_service, _ = _materializer(tmp_path)
    draft = _validated_draft(draft_service)
    (tmp_path / "skills").mkdir()
    materializer.materialize(
        draft_id=draft.draft_id,
        expected_revision=draft.revision,
        created_by="u",
        reason="test",
    )
    from src.domain.skill.draft_models import SkillDraftStatus

    assert draft_service.get_draft(draft.draft_id).status == SkillDraftStatus.MATERIALIZED


def test_materialize_rejects_non_validated_draft(tmp_path):
    materializer, draft_service, _ = _materializer(tmp_path)
    draft = draft_service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    (tmp_path / "skills").mkdir()
    with pytest.raises(SkillMaterializeError, match="validated"):
        materializer.materialize(
            draft_id=draft.draft_id,
            expected_revision=draft.revision,
            created_by="u",
            reason="test",
        )


def test_materialize_requires_reason(tmp_path):
    materializer, draft_service, _ = _materializer(tmp_path)
    draft = _validated_draft(draft_service)
    with pytest.raises(SkillMaterializeError, match="原因"):
        materializer.materialize(
            draft_id=draft.draft_id,
            expected_revision=draft.revision,
            created_by="u",
            reason="",
        )


def test_materialize_rejects_blocking_validation(tmp_path):
    materializer, draft_service, _ = _materializer(tmp_path)
    # 构造一个 skill_id 合法但 business_action 非法的草稿，强行设 validated
    draft = draft_service.create_from_template(
        skill_id="s1",
        skill_name="S1",
        created_by="u",
        business_action="explain",
        business_object="settlement",
    )
    # 改成非法 action 后标记 validated
    cfg = draft.structured_config
    cfg["business_mounting"]["business_action"] = "bogus"
    draft = draft_service.save_draft(
        draft_id=draft.draft_id,
        structured_config=cfg,
        expected_revision=draft.revision,
    )
    draft_service.record_validation(
        draft_id=draft.draft_id,
        validation_report={"blocking": []},
        expected_revision=draft.revision,
        blocking_ok=True,
    )
    (tmp_path / "skills").mkdir()
    with pytest.raises(SkillMaterializeError, match="blocking"):
        materializer.materialize(
            draft_id=draft.draft_id,
            expected_revision=draft_service.get_draft(draft.draft_id).revision,
            created_by="u",
            reason="test",
        )


def test_materialize_rolls_back_on_version_failure(tmp_path):
    version_service = FakeVersionService(fail_once=True)
    materializer, draft_service, _ = _materializer(
        tmp_path, version_service=version_service
    )
    draft = _validated_draft(draft_service)
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    with pytest.raises(RuntimeError):
        materializer.materialize(
            draft_id=draft.draft_id,
            expected_revision=draft.revision,
            created_by="u",
            reason="test",
        )
    # 版本登记失败后，写入的目录应被回滚
    assert not (skills_root / "new_skill").exists()


def test_materialize_overwrites_existing_skill_atomically(tmp_path):
    materializer, draft_service, _ = _materializer(tmp_path)
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "new_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "old_file.txt").write_text("old", encoding="utf-8")

    draft = _validated_draft(draft_service)
    result = materializer.materialize(
        draft_id=draft.draft_id,
        expected_revision=draft.revision,
        created_by="u",
        reason="升级",
    )
    assert result.artifact_written
    # 旧文件应被清除（原子替换）
    assert not (skill_dir / "old_file.txt").exists()
    assert (skill_dir / "skill_manifest.yaml").exists()
