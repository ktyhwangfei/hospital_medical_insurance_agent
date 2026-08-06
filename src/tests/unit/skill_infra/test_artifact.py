from pathlib import Path

import pytest

from src.skill_infra.artifact import SkillArtifactError, build_skill_artifact


def _write_skill(skills_root: Path) -> Path:
    skill_dir = skills_root / "demo_skill"
    skill_dir.mkdir()
    (skill_dir / "skill_manifest.yaml").write_text(
        """
skill_id: demo_skill
skill_name: Demo Skill
version: 1.2.3
required_mcp:
  - demo-server
needed_objects:
  - object_code: settlement
    metrics: [amount]
""".strip(),
        encoding="utf-8",
    )
    (skill_dir / "assembler.py").write_text("def load():\n    return object()\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    return skill_dir


def test_build_artifact_snapshot_is_stable_and_ignores_pycache(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path)
    first = build_skill_artifact(skill_dir, skills_root=tmp_path)
    cache_dir = skill_dir / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "assembler.pyc").write_bytes(b"cache")

    second = build_skill_artifact(skill_dir, skills_root=tmp_path)

    assert first.artifact_hash == second.artifact_hash
    assert first.file_paths == second.file_paths
    assert first.semantic_version == "1.2.3"
    assert first.source_path == "demo_skill"
    assert first.dependency_snapshot == {
        "needed_objects": [{"object_code": "settlement", "metrics": ["amount"]}],
        "required_mcp": ["demo-server"],
    }


def test_build_artifact_snapshot_changes_when_source_changes(tmp_path: Path) -> None:
    skill_dir = _write_skill(tmp_path)
    first = build_skill_artifact(skill_dir, skills_root=tmp_path)

    (skill_dir / "SKILL.md").write_text("# Changed\n", encoding="utf-8")
    second = build_skill_artifact(skill_dir, skills_root=tmp_path)

    assert first.artifact_hash != second.artifact_hash


def test_build_artifact_snapshot_rejects_path_outside_skills_root(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    outside = tmp_path / "outside-skill"
    outside.mkdir()

    with pytest.raises(SkillArtifactError, match="SKILLS_DIR"):
        build_skill_artifact(outside, skills_root=skills_root)


def test_build_artifact_snapshot_requires_manifest(tmp_path: Path) -> None:
    skill_dir = tmp_path / "demo_skill"
    skill_dir.mkdir()
    (skill_dir / "assembler.py").write_text("", encoding="utf-8")

    with pytest.raises(SkillArtifactError, match="skill_manifest.yaml"):
        build_skill_artifact(skill_dir, skills_root=tmp_path)
