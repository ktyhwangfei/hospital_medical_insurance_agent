from src.data_platform.storage.skill.models import SkillStorageHealth, SkillStorageHealthStatus
from src.domain.skill.models import Skill


class InMemorySkillStorage:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def save_skill(self, skill: Skill) -> None:
        self._skills[skill.skill_id] = skill.model_copy(deep=True)

    def get_skill(self, skill_id: str) -> Skill | None:
        skill = self._skills.get(skill_id)
        return None if skill is None else skill.model_copy(deep=True)

    def list_skills(self) -> list[Skill]:
        return [self._skills[key].model_copy(deep=True) for key in sorted(self._skills)]

    def list_skills_by_owner(self, owner: str) -> list[Skill]:
        return [s for s in self.list_skills() if s.owner == owner]

    def list_skills_by_role(self, role: str) -> list[Skill]:
        return [
            s for s in self.list_skills()
            if s.owner == role or role in s.required_roles
        ]

    def delete_skill(self, skill_id: str) -> bool:
        if skill_id in self._skills:
            del self._skills[skill_id]
            return True
        return False

    def health(self) -> SkillStorageHealth:
        return SkillStorageHealth(
            status=SkillStorageHealthStatus.HEALTHY,
            details={"backend": "in_memory"},
        )
