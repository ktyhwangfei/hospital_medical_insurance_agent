"""Skill 目录制品快照与确定性哈希。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from src.domain.skill.version_models import SkillArtifactSnapshot


class SkillArtifactError(ValueError):
    """Skill 目录无法安全构建制品时抛出。"""


_DEPENDENCY_KEYS = (
    "allowed_tools",
    "locked_versions",
    "mcp_server",
    "needed_objects",
    "optional_mcp",
    "required_mcp",
    "required_settlement_fields",
)


def _dependency_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: manifest[key] for key in _DEPENDENCY_KEYS if key in manifest}


def _artifact_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        resolved_file = path.resolve()
        if not resolved_file.is_relative_to(skill_dir):
            raise SkillArtifactError(f"Skill 文件越界: {relative.as_posix()}")
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(skill_dir).as_posix())


def build_skill_artifact(
    skill_dir: str | Path,
    *,
    skills_root: str | Path,
) -> SkillArtifactSnapshot:
    """读取 Skill 目录并生成与遍历顺序无关的 SHA-256 制品快照。"""

    root = Path(skills_root).resolve()
    resolved_skill_dir = Path(skill_dir).resolve()
    if not resolved_skill_dir.is_relative_to(root):
        raise SkillArtifactError("Skill 路径必须位于 SKILLS_DIR 内")
    if not resolved_skill_dir.is_dir():
        raise SkillArtifactError("Skill 路径不是有效目录")

    manifest_path = resolved_skill_dir / "skill_manifest.yaml"
    if not manifest_path.is_file():
        raise SkillArtifactError("Skill 目录缺少 skill_manifest.yaml")

    raw_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw_manifest, dict):
        raise SkillArtifactError("skill_manifest.yaml 必须是对象结构")

    files = _artifact_files(resolved_skill_dir)
    digest = hashlib.sha256()
    file_paths: list[str] = []
    for path in files:
        relative = path.relative_to(resolved_skill_dir).as_posix()
        file_paths.append(relative)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    return SkillArtifactSnapshot(
        skill_id=str(raw_manifest.get("skill_id") or resolved_skill_dir.name),
        semantic_version=str(raw_manifest.get("version") or "1.0.0"),
        source_path=resolved_skill_dir.relative_to(root).as_posix(),
        artifact_hash=digest.hexdigest(),
        manifest_snapshot=raw_manifest,
        dependency_snapshot=_dependency_snapshot(raw_manifest),
        file_paths=file_paths,
    )
