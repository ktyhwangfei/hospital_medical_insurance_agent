from typing import Protocol

from src.domain.tool.models import ToolVersion


class ToolVersionConflictError(ValueError):
    """同一 Tool 的语义版本已指向其他制品。"""


class ToolVersionStorage(Protocol):
    def save_version(self, version: ToolVersion) -> ToolVersion: ...

    def get_version(self, tool_id: str, version_id: str) -> ToolVersion | None: ...

    def list_versions(self, tool_id: str) -> list[ToolVersion]: ...

    def get_latest_materialized(self, tool_id: str) -> ToolVersion | None: ...
