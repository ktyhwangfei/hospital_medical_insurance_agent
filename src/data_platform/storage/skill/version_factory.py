import os
from functools import lru_cache

from src.data_platform.storage.skill.version_ports import SkillVersionStorage


@lru_cache(maxsize=1)
def get_skill_version_storage() -> SkillVersionStorage:
    """按项目统一存储开关返回进程级 Skill 版本存储。"""

    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.skill.version_in_memory import (
            InMemorySkillVersionStorage,
        )

        return InMemorySkillVersionStorage()

    from src.data_platform.storage.skill.version_postgres import (
        PostgresSkillVersionStorage,
    )

    return PostgresSkillVersionStorage()
