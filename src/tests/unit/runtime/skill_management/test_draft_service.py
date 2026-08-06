"""SkillDraftService 单元测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.data_platform.storage.skill.draft_in_memory import (
    InMemorySkillDraftStorage,
)
from src.data_platform.storage.skill.draft_ports import (
    SkillDraftConflictError,
    SkillDraftNotFoundError,
)
from src.domain.skill.draft_models import SkillDraftStatus
from src.runtime.skill_management.draft_service import SkillDraftService


def _service(
    *,
    loader=None,
    skills_root=None,
) -> SkillDraftService:
    return SkillDraftService(
        storage=InMemorySkillDraftStorage(),
        loader=loader,
        skills_root=skills_root or "/nonexistent-skills-root",
    )


def _fake_loader(skill_id: str = "src_skill"):
    """返回带 manifest/keywords 属性的假 Skill。"""
    return {
        skill_id: SimpleNamespace(
            skill_id=skill_id,
            skill_name="Source Skill",
            business_action="explain",
            business_object="settlement",
            include_keywords=["费用", "起付线"],
            excluded_intents=["退款"],
            manifest={"description": "源 Skill 说明", "owner": "信息科"},
        )
    }


class _FakeLoader:
    def __init__(self, skills: dict) -> None:
        self._skills = skills

    def get(self, skill_id: str):
        return self._skills.get(skill_id)


# ── 创建 ──────────────────────────────────────────────────────────


def test_create_from_template_builds_structured_config():
    service = _service()
    draft = service.create_from_template(
        skill_id="my_skill",
        skill_name="My Skill",
        created_by="u-admin",
        description="说明",
        business_action="explain",
        business_object="settlement",
        include_keywords=["费用"],
    )
    assert draft.draft_id.startswith("draft-")
    assert draft.skill_id == "my_skill"
    assert draft.source_type.value == "template"
    assert draft.status == SkillDraftStatus.EDITING
    assert draft.revision == 1
    cfg = draft.structured_config
    assert cfg["basic"]["skill_name"] == "My Skill"
    assert cfg["business_mounting"]["business_action"] == "explain"
    assert cfg["business_mounting"]["include_keywords"] == ["费用"]
    assert cfg["inputs"] == []
    assert cfg["schemas"] == {}


def test_create_from_template_generates_unique_ids():
    service = _service()
    d1 = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    d2 = service.create_from_template(
        skill_id="s2", skill_name="S2", created_by="u"
    )
    assert d1.draft_id != d2.draft_id


# ── 复制 ──────────────────────────────────────────────────────────


def test_copy_skill_records_source_and_config():
    loader = _FakeLoader(_fake_loader("src_skill"))
    service = _service(loader=loader)
    draft = service.copy_skill(
        source_skill_id="src_skill",
        new_skill_id="copied_skill",
        created_by="u-admin",
    )
    assert draft.source_type.value == "copy"
    assert draft.source_skill_id == "src_skill"
    assert draft.skill_id == "copied_skill"
    cfg = draft.structured_config
    assert cfg["basic"]["skill_name"] == "Source Skill"
    assert cfg["business_mounting"]["business_action"] == "explain"
    assert cfg["business_mounting"]["include_keywords"] == ["费用", "起付线"]


def test_copy_skill_source_not_found():
    loader = _FakeLoader({})
    service = _service(loader=loader)
    with pytest.raises(SkillDraftNotFoundError):
        service.copy_skill(
            source_skill_id="missing",
            new_skill_id="copied",
            created_by="u",
        )


def test_copy_skill_reads_source_files(tmp_path):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "src_skill"
    (skill_dir / "schemas").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Source", encoding="utf-8")
    (skill_dir / "skill_manifest.yaml").write_text("skill_id: src_skill", encoding="utf-8")
    (skill_dir / "schemas" / "input.schema.json").write_text("{}", encoding="utf-8")
    loader = _FakeLoader(_fake_loader("src_skill"))
    service = _service(loader=loader, skills_root=skills_root)
    draft = service.copy_skill(
        source_skill_id="src_skill",
        new_skill_id="copied",
        created_by="u",
    )
    assert "SKILL.md" in draft.raw_files
    assert "skill_manifest.yaml" in draft.raw_files
    assert "schemas/input.schema.json" in draft.raw_files


# ── 保存 ──────────────────────────────────────────────────────────


def test_save_draft_updates_config_and_increments_revision():
    service = _service()
    draft = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    new_cfg = {
        "basic": {"skill_id": "s1", "skill_name": "Renamed"},
        "business_mounting": {
            "business_action": "query",
            "business_object": "benefit",
            "include_keywords": [],
            "excluded_intents": [],
        },
        "inputs": [],
        "schemas": {},
    }
    saved = service.save_draft(
        draft_id=draft.draft_id,
        structured_config=new_cfg,
        expected_revision=1,
    )
    assert saved.revision == 2
    assert saved.skill_name == "Renamed"
    assert saved.structured_config["basic"]["skill_name"] == "Renamed"


def test_save_draft_resets_status_to_editing():
    service = _service()
    draft = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    # 先推进到 validated
    service.record_validation(
        draft_id=draft.draft_id,
        validation_report={"blocking": []},
        expected_revision=1,
        blocking_ok=True,
    )
    assert service.get_draft(draft.draft_id).status == SkillDraftStatus.VALIDATED
    # 保存后重置为 editing
    saved = service.save_draft(
        draft_id=draft.draft_id,
        structured_config={"basic": {"skill_name": "S1"}},
        expected_revision=2,
    )
    assert saved.status == SkillDraftStatus.EDITING


def test_save_draft_stale_revision_conflicts():
    service = _service()
    draft = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    service.save_draft(
        draft_id=draft.draft_id,
        structured_config={"basic": {"skill_name": "v2"}},
        expected_revision=1,
    )
    with pytest.raises(SkillDraftConflictError):
        service.save_draft(
            draft_id=draft.draft_id,
            structured_config={"basic": {"skill_name": "v3"}},
            expected_revision=1,  # 过期
        )


def test_save_draft_missing_not_found():
    service = _service()
    with pytest.raises(SkillDraftNotFoundError):
        service.save_draft(
            draft_id="nope",
            structured_config={},
            expected_revision=1,
        )


# ── 校验记录与物化 ────────────────────────────────────────────────


def test_record_validation_pass_advances_to_validated():
    service = _service()
    draft = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    result = service.record_validation(
        draft_id=draft.draft_id,
        validation_report={"blocking": [], "warnings": ["w1"]},
        expected_revision=1,
        blocking_ok=True,
    )
    assert result.status == SkillDraftStatus.VALIDATED
    assert result.validation_report["warnings"] == ["w1"]


def test_record_validation_fail_keeps_editing():
    service = _service()
    draft = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    result = service.record_validation(
        draft_id=draft.draft_id,
        validation_report={"blocking": ["err"]},
        expected_revision=1,
        blocking_ok=False,
    )
    assert result.status == SkillDraftStatus.EDITING


def test_mark_materialized_freezes_draft():
    service = _service()
    draft = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    result = service.mark_materialized(draft_id=draft.draft_id, expected_revision=1)
    assert result.status == SkillDraftStatus.MATERIALIZED


# ── 删除与列表 ────────────────────────────────────────────────────


def test_delete_draft_soft_deletes():
    service = _service()
    draft = service.create_from_template(
        skill_id="s1", skill_name="S1", created_by="u"
    )
    service.delete_draft(draft_id=draft.draft_id, expected_revision=1)
    assert service.get_draft(draft.draft_id) is None
    # include_deleted 可见
    assert (
        len(service.list_drafts(include_deleted=True)) == 1
    )


def test_list_drafts_filters_by_status():
    service = _service()
    d1 = service.create_from_template(skill_id="s1", skill_name="S1", created_by="u")
    service.create_from_template(skill_id="s2", skill_name="S2", created_by="u")
    service.record_validation(
        draft_id=d1.draft_id,
        validation_report={"blocking": []},
        expected_revision=1,
        blocking_ok=True,
    )
    validated = service.list_drafts(status=SkillDraftStatus.VALIDATED)
    assert {d.draft_id for d in validated} == {d1.draft_id}
    editing = service.list_drafts(status=SkillDraftStatus.EDITING)
    assert all(d.status == SkillDraftStatus.EDITING for d in editing)
