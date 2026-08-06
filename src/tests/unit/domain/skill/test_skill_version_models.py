from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.domain.skill.version_models import (
    SkillArtifactSnapshot,
    SkillValidationStatus,
    SkillVersion,
)


def _make_version(**updates: object) -> SkillVersion:
    values: dict[str, object] = {
        "version_id": "version-1",
        "skill_id": "demo_skill",
        "semantic_version": "1.0.0",
        "source_commit": "abc1234",
        "source_path": "skills/demo_skill",
        "artifact_hash": "a" * 64,
        "manifest_snapshot": {"skill_id": "demo_skill"},
        "dependency_snapshot": {"required_mcp": ["demo-server"]},
        "file_count": 3,
        "created_by": "tester",
        "created_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
    }
    values.update(updates)
    return SkillVersion(**values)


def test_skill_version_rejects_non_sha256_hash() -> None:
    with pytest.raises(ValidationError):
        _make_version(artifact_hash="bad")


def test_skill_version_is_immutable() -> None:
    version = _make_version()

    with pytest.raises(ValidationError):
        version.validation_status = SkillValidationStatus.PASSED


def test_artifact_snapshot_requires_at_least_one_file() -> None:
    with pytest.raises(ValidationError):
        SkillArtifactSnapshot(
            skill_id="demo_skill",
            semantic_version="1.0.0",
            source_path="skills/demo_skill",
            artifact_hash="a" * 64,
            manifest_snapshot={},
            dependency_snapshot={},
            file_paths=[],
        )
