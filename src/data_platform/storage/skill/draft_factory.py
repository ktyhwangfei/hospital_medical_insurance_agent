"""Skill 草稿与定义存储工厂。

遵循项目统一存储约定（``version_factory`` / ``governance_factory`` 模式）：
``USE_MEMORY_STORAGE=1`` 回退内存实现，默认 PostgreSQL。
工厂返回的对象同时实现 ``SkillDraftStorage`` 与 ``SkillDefinitionStorage``。
"""

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_skill_draft_storage():
    """按项目统一存储开关返回进程级 Skill 草稿+定义存储。"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.skill.draft_in_memory import (
            InMemorySkillDraftStorage,
        )

        return InMemorySkillDraftStorage()

    from src.data_platform.storage.skill.draft_postgres import (
        PostgresSkillDraftStorage,
    )

    return PostgresSkillDraftStorage()
