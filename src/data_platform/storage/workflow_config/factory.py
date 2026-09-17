"""Workflow 治理配置存储工厂：默认 PostgreSQL，USE_MEMORY_STORAGE=1 回退内存。"""

from __future__ import annotations

import os


def get_workflow_config_storage():
    use_memory = os.getenv("USE_MEMORY_STORAGE", "").lower() in ("1", "true", "yes")
    if use_memory:
        from src.data_platform.storage.workflow_config.in_memory import (
            InMemoryWorkflowConfigStorage,
        )

        return InMemoryWorkflowConfigStorage()
    from src.data_platform.storage.workflow_config.postgres import (
        PostgresWorkflowConfigStorage,
    )

    return PostgresWorkflowConfigStorage()
