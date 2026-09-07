"""可信问题库存储工厂。

遵循项目统一存储约定（``draft_factory`` 模式）：
``USE_MEMORY_STORAGE=1`` 回退内存实现，默认 PostgreSQL。
"""

import os
from functools import lru_cache


@lru_cache(maxsize=1)
def get_trusted_question_storage():
    """按项目统一存储开关返回进程级可信问题库存储。"""
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.trusted_question.trusted_question_in_memory import (
            InMemoryTrustedQuestionStorage,
        )

        return InMemoryTrustedQuestionStorage()

    from src.data_platform.storage.trusted_question.trusted_question_postgres import (
        PostgresTrustedQuestionStorage,
    )

    return PostgresTrustedQuestionStorage()
