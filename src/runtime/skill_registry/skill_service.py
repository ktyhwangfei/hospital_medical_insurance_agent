from src.data_platform.storage.skill.ports import SkillStorage
from src.domain.skill.models import Skill


class SkillService:
    def __init__(self, skill_storage: SkillStorage) -> None:
        self._storage = skill_storage

    def create_skill(self, skill: Skill) -> Skill:
        if skill.allowed_tools:
            self._validate_allowed_tools(skill.allowed_tools)
        self._storage.save_skill(skill)
        return skill

    def get_skill(self, skill_id: str) -> Skill | None:
        return self._storage.get_skill(skill_id)

    def list_skills(self) -> list[Skill]:
        return self._storage.list_skills()

    def list_skills_by_role(self, role: str) -> list[Skill]:
        return self._storage.list_skills_by_role(role)

    def update_skill(self, skill_id: str, skill: Skill) -> Skill | None:
        existing = self._storage.get_skill(skill_id)
        if existing is None:
            return None
        if skill.allowed_tools:
            self._validate_allowed_tools(skill.allowed_tools)
        self._storage.save_skill(skill)
        return skill

    def delete_skill(self, skill_id: str) -> bool:
        return self._storage.delete_skill(skill_id)

    def _validate_allowed_tools(self, allowed_tools: list[str]) -> None:
        if not isinstance(allowed_tools, list):
            raise ValueError("allowed_tools 必须是列表")
        for pattern in allowed_tools:
            if not isinstance(pattern, str) or not pattern.strip():
                raise ValueError(f"无效的工具模式: {pattern}")