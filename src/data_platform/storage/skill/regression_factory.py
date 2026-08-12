"""Skill 回归案例池与回归用例存储工厂。

遵循 `USE_MEMORY_STORAGE` 环境变量：默认 PostgreSQL，开启时回退到内存实现。
"""

from __future__ import annotations

import os

from src.data_platform.storage.skill.regression_in_memory import (
    InMemorySkillRegressionStorage,
)
from src.data_platform.storage.skill.regression_ports import SkillRegressionStorage


_memory_instance: InMemorySkillRegressionStorage | None = None


def get_skill_regression_storage() -> SkillRegressionStorage:
    """返回全局共享的回归案例池存储实例。"""
    global _memory_instance
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        if _memory_instance is None:
            _memory_instance = InMemorySkillRegressionStorage()
        return _memory_instance
    # 延迟导入，避免在内存模式下加载 psycopg 依赖
    from src.data_platform.storage.skill.regression_postgres import (
        PostgresSkillRegressionStorage,
    )

    return PostgresSkillRegressionStorage()
