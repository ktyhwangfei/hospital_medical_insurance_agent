from typing import Protocol

from src.domain.skill.version_models import SkillVersion


class SkillVersionConflictError(ValueError):
    """同一 Skill 的语义版本已指向其他制品。"""


class SkillVersionStorage(Protocol):
    def save_version(self, version: SkillVersion) -> SkillVersion: ...

    def get_version(self, skill_id: str, version_id: str) -> SkillVersion | None: ...

    def find_by_artifact_hash(
        self, skill_id: str, artifact_hash: str
    ) -> SkillVersion | None: ...

    def list_versions(self, skill_id: str) -> list[SkillVersion]: ...
