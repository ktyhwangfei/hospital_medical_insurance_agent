"""Skill 版本登记与资产目录应用服务。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.data_platform.storage.skill.version_ports import SkillVersionStorage
from src.domain.skill.draft_models import SkillExecutionContract
from src.domain.skill.version_models import SkillValidationStatus, SkillVersion
from src.skill_infra.artifact import SkillArtifactError, build_skill_artifact


class SkillNotFoundError(LookupError):
    """请求的 Skill 未被运行时加载。"""


class _SkillLoaderView(Protocol):
    def get(self, skill_id: str) -> Any | None: ...

    def get_all(self) -> dict[str, Any]: ...


class SkillCatalogEntry(BaseModel):
    """版本化 Skill 资产目录中的一行。"""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    skill_name: str
    business_action: str = ""
    business_object: str = ""
    description: str = ""
    execution_contract: SkillExecutionContract = Field(
        default_factory=SkillExecutionContract
    )
    include_keywords: list[str] = Field(default_factory=list)
    excluded_intents: list[str] = Field(default_factory=list)
    semantic_version: str
    artifact_hash: str
    artifact_status: str
    file_count: int
    registered_version: SkillVersion | None = None


class SkillCatalogPage(BaseModel):
    """Skill 资产目录分页结果。"""

    model_config = ConfigDict(frozen=True)

    items: list[SkillCatalogEntry]
    page: int
    page_size: int
    total: int


class SkillVersionService:
    def __init__(
        self,
        storage: SkillVersionStorage,
        loader: _SkillLoaderView,
        skills_root: str | Path,
        source_commit_resolver: Callable[[], str] | None = None,
    ) -> None:
        self._storage = storage
        self._loader = loader
        self._skills_root = Path(skills_root)
        self._source_commit_resolver = source_commit_resolver or self._resolve_source_commit

    def _resolve_source_commit(self) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(self._skills_root.parent), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("无法解析当前 Skill 源代码的 Git commit") from exc
        return result.stdout.strip().lower()

    def sync_version(
        self,
        skill_id: str,
        *,
        source_commit: str | None,
        created_by: str,
    ) -> SkillVersion:
        loaded_skill = self._loader.get(skill_id)
        if loaded_skill is None:
            raise SkillNotFoundError(f"未找到 Skill: {skill_id}")
        resolved_source_commit = (
            source_commit.strip().lower()
            if source_commit is not None
            else self._source_commit_resolver()
        )
        if not re.fullmatch(r"[0-9a-f]{7,64}", resolved_source_commit):
            raise ValueError("source_commit 必须是 7-64 位小写十六进制 Git SHA")
        if not created_by.strip():
            raise ValueError("created_by 不能为空")

        snapshot = build_skill_artifact(
            self._skills_root / skill_id,
            skills_root=self._skills_root,
        )
        if snapshot.skill_id != skill_id:
            raise SkillArtifactError(
                f"Manifest skill_id {snapshot.skill_id} 与目录 {skill_id} 不一致"
            )
        existing = self._storage.find_by_artifact_hash(skill_id, snapshot.artifact_hash)
        if existing is not None:
            return existing

        version = SkillVersion(
            version_id=uuid4().hex,
            skill_id=skill_id,
            semantic_version=snapshot.semantic_version,
            source_commit=resolved_source_commit,
            source_path=snapshot.source_path,
            artifact_hash=snapshot.artifact_hash,
            manifest_snapshot=snapshot.manifest_snapshot,
            dependency_snapshot=snapshot.dependency_snapshot,
            file_count=len(snapshot.file_paths),
            validation_status=SkillValidationStatus.PASSED,
            created_by=created_by.strip(),
        )
        return self._storage.save_version(version)

    def list_versions(self, skill_id: str) -> list[SkillVersion]:
        return self._storage.list_versions(skill_id)

    def get_version(self, skill_id: str, version_id: str) -> SkillVersion:
        version = self._storage.get_version(skill_id, version_id)
        if version is None:
            raise SkillNotFoundError(
                f"未找到 Skill {skill_id} 的版本: {version_id}"
            )
        return version

    def list_catalog(
        self,
        *,
        page: int,
        page_size: int,
        business_action: str = "",
        business_object: str = "",
        artifact_status: str = "",
        query: str = "",
    ) -> SkillCatalogPage:
        entries: list[SkillCatalogEntry] = []
        normalized_query = query.strip().lower()
        for skill_id, skill in sorted(self._loader.get_all().items()):
            if business_action and skill.business_action != business_action:
                continue
            if business_object and skill.business_object != business_object:
                continue
            if normalized_query and normalized_query not in (
                f"{skill.skill_id} {skill.skill_name}".lower()
            ):
                continue

            snapshot = build_skill_artifact(
                self._skills_root / skill_id,
                skills_root=self._skills_root,
            )
            versions = self._storage.list_versions(skill_id)
            matching_version = next(
                (
                    version
                    for version in versions
                    if version.artifact_hash == snapshot.artifact_hash
                ),
                None,
            )
            current_status = (
                "registered"
                if matching_version is not None
                else "changed"
                if versions
                else "unregistered"
            )
            if artifact_status and current_status != artifact_status:
                continue
            try:
                execution_contract = SkillExecutionContract.model_validate(
                    snapshot.manifest_snapshot.get("execution_contract") or {}
                )
            except ValidationError:
                execution_contract = SkillExecutionContract()
            entries.append(
                SkillCatalogEntry(
                    skill_id=skill.skill_id,
                    skill_name=skill.skill_name,
                    business_action=skill.business_action,
                    business_object=skill.business_object,
                    description=str(
                        snapshot.manifest_snapshot.get("description") or ""
                    ),
                    execution_contract=execution_contract,
                    include_keywords=skill.include_keywords,
                    excluded_intents=skill.excluded_intents,
                    semantic_version=snapshot.semantic_version,
                    artifact_hash=snapshot.artifact_hash,
                    artifact_status=current_status,
                    file_count=len(snapshot.file_paths),
                    registered_version=matching_version or (versions[0] if versions else None),
                )
            )

        total = len(entries)
        start = (page - 1) * page_size
        return SkillCatalogPage(
            items=entries[start : start + page_size],
            page=page,
            page_size=page_size,
            total=total,
        )
