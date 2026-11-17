"""筛查规则存储工厂。默认写 bjyb 的 SQL Server，USE_MEMORY_STORAGE=1 回退内存。"""
from __future__ import annotations

import os

from src.data_platform.storage.screening_rules.in_memory import (
    InMemoryScreeningRuleStorage,
)


def get_screening_rule_storage():
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        return InMemoryScreeningRuleStorage()
    from src.data_platform.storage.screening_rules.sqlserver import (
        SqlServerScreeningRuleStorage,
    )

    return SqlServerScreeningRuleStorage()
