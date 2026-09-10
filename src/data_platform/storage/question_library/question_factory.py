"""可信问题库存储工厂 — 默认 PostgreSQL，USE_MEMORY_STORAGE=1 回退内存。"""
from __future__ import annotations

import os

from src.data_platform.storage.question_library.question_in_memory import InMemoryTrustedQuestionStorage


def get_trusted_question_storage():
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        return InMemoryTrustedQuestionStorage()
    from src.data_platform.storage.question_library.question_postgres import (
        PostgresTrustedQuestionStorage,
    )

    return PostgresTrustedQuestionStorage()
