import os
from functools import lru_cache

from src.data_platform.storage.skill.governance_ports import SkillGovernanceStorage


@lru_cache(maxsize=1)
def get_skill_governance_storage() -> SkillGovernanceStorage:
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.skill.governance_in_memory import (
            InMemorySkillGovernanceStorage,
        )

        return InMemorySkillGovernanceStorage()

    from src.data_platform.storage.skill.governance_postgres import (
        PostgresSkillGovernanceStorage,
    )

    return PostgresSkillGovernanceStorage()
