from pathlib import Path
from types import SimpleNamespace

import pytest

from src.data_platform.storage.skill.version_in_memory import InMemorySkillVersionStorage
from src.runtime.skill_management.version_service import (
    SkillNotFoundError,
    SkillVersionService,
)


class _FakeLoader:
    def __init__(self, skills: dict[str, SimpleNamespace]) -> None:
        self._skills = skills

    def get(self, skill_id: str) -> SimpleNamespace | None:
        return self._skills.get(skill_id)

    def get_all(self) -> dict[str, SimpleNamespace]:
        return self._skills


def _write_skill(
    skills_root: Path,
    skill_id: str = "demo_skill",
    *,
    business_action: str = "explain",
) -> SimpleNamespace:
    skill_dir = skills_root / skill_id
    skill_dir.mkdir()
    manifest = {
        "skill_id": skill_id,
        "skill_name": f"{skill_id} name",
        "version": "1.0.0",
        "business_action": business_action,
        "business_object": "settlement",
        "supported_intents": ["费用"],
        "excluded_intents": [],
    }
    (skill_dir / "skill_manifest.yaml").write_text(
        "\n".join(
            [
                f"skill_id: {skill_id}",
                f"skill_name: {skill_id} name",
                'version: "1.0.0"',
                f"business_action: {business_action}",
                "business_object: settlement",
                "supported_intents: [费用]",
                "excluded_intents: []",
            ]
        ),
        encoding="utf-8",
    )
    (skill_dir / "assembler.py").write_text("def load():\n    return object()\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    return SimpleNamespace(
        skill_id=skill_id,
        skill_name=manifest["skill_name"],
        business_action=business_action,
        business_object="settlement",
        include_keywords=["费用"],
        excluded_intents=[],
        manifest=manifest,
    )


def _service(skills_root: Path, *skills: SimpleNamespace) -> SkillVersionService:
    loader = _FakeLoader({skill.skill_id: skill for skill in skills})
    return SkillVersionService(
        storage=InMemorySkillVersionStorage(),
        loader=loader,
        skills_root=skills_root,
    )


def test_sync_current_version_is_idempotent(tmp_path: Path) -> None:
    skill = _write_skill(tmp_path)
    service = _service(tmp_path, skill)

    first = service.sync_version(
        "demo_skill", source_commit="abc1234", created_by="tester"
    )
    second = service.sync_version(
        "demo_skill", source_commit="abc1234", created_by="tester"
    )

    assert first.version_id == second.version_id
    assert first.validation_status == "passed"
    assert len(service.list_versions("demo_skill")) == 1


def test_catalog_marks_changed_artifact(tmp_path: Path) -> None:
    skill = _write_skill(tmp_path)
    service = _service(tmp_path, skill)
    service.sync_version("demo_skill", source_commit="abc1234", created_by="tester")
    (tmp_path / "demo_skill" / "SKILL.md").write_text("changed", encoding="utf-8")

    catalog = service.list_catalog(page=1, page_size=20)

    assert catalog.items[0].artifact_status == "changed"
    assert catalog.items[0].registered_version is not None


def test_catalog_filters_before_paginating(tmp_path: Path) -> None:
    explain = _write_skill(tmp_path, "explain_skill", business_action="explain")
    query = _write_skill(tmp_path, "query_skill", business_action="query")
    service = _service(tmp_path, explain, query)

    catalog = service.list_catalog(
        page=1,
        page_size=1,
        business_action="query",
    )

    assert catalog.total == 1
    assert [item.skill_id for item in catalog.items] == ["query_skill"]


def test_sync_unknown_skill_raises_explicit_error(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(SkillNotFoundError, match="missing_skill"):
        service.sync_version(
            "missing_skill", source_commit="abc1234", created_by="tester"
        )
