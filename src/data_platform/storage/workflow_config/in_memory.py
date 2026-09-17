"""Workflow 治理配置内存存储（开发/测试，USE_MEMORY_STORAGE=1 回退）。"""

from __future__ import annotations

from src.domain.workflow.models import WorkflowConfigOverride


class InMemoryWorkflowConfigStorage:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], WorkflowConfigOverride] = {}

    def list_overrides(self) -> list[WorkflowConfigOverride]:
        return [row.model_copy(deep=True) for row in self._rows.values()]

    def upsert_override(self, override: WorkflowConfigOverride) -> WorkflowConfigOverride:
        stored = override.model_copy(deep=True)
        self._rows[(stored.workflow_id, stored.hospital_code)] = stored
        return stored.model_copy(deep=True)
