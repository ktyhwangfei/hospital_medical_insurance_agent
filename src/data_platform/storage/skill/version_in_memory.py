from src.data_platform.storage.skill.version_ports import SkillVersionConflictError
from src.domain.skill.version_models import SkillVersion


class InMemorySkillVersionStorage:
    """用于开发和测试的 Skill 版本内存存储。"""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], SkillVersion] = {}

    def save_version(self, version: SkillVersion) -> SkillVersion:
        existing_artifact = self.find_by_artifact_hash(
            version.skill_id, version.artifact_hash
        )
        if existing_artifact is not None:
            return existing_artifact

        for current in self._versions.values():
            if (
                current.skill_id == version.skill_id
                and current.semantic_version == version.semantic_version
            ):
                raise SkillVersionConflictError(
                    f"Skill {version.skill_id} 的语义版本 {version.semantic_version} 已绑定其他制品"
                )

        stored = version.model_copy(deep=True)
        self._versions[(version.skill_id, version.version_id)] = stored
        return stored.model_copy(deep=True)

    def get_version(self, skill_id: str, version_id: str) -> SkillVersion | None:
        version = self._versions.get((skill_id, version_id))
        return None if version is None else version.model_copy(deep=True)

    def find_by_artifact_hash(
        self, skill_id: str, artifact_hash: str
    ) -> SkillVersion | None:
        for version in self._versions.values():
            if version.skill_id == skill_id and version.artifact_hash == artifact_hash:
                return version.model_copy(deep=True)
        return None

    def list_versions(self, skill_id: str) -> list[SkillVersion]:
        versions = [
            version.model_copy(deep=True)
            for version in self._versions.values()
            if version.skill_id == skill_id
        ]
        return sorted(versions, key=lambda item: item.created_at, reverse=True)
