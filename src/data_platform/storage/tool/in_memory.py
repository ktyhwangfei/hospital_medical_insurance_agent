from src.data_platform.storage.tool.ports import ToolVersionConflictError
from src.domain.tool.models import ToolStatus, ToolVersion


class InMemoryToolVersionStorage:
    """用于开发和测试的 Tool 版本内存存储。"""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], ToolVersion] = {}

    def save_version(self, version: ToolVersion) -> ToolVersion:
        for current in self._versions.values():
            if (
                current.tool_id == version.tool_id
                and current.semantic_version == version.semantic_version
                and current.version_id != version.version_id
            ):
                raise ToolVersionConflictError(
                    f"Tool {version.tool_id} 的语义版本 {version.semantic_version} 已绑定其他制品"
                )

        existing = self._versions.get((version.tool_id, version.version_id))
        if existing is not None and (
            existing.semantic_version != version.semantic_version
            or existing.definition != version.definition
        ):
            raise ToolVersionConflictError(
                f"Tool 版本 {version.version_id} 已登记且内容不一致，"
                "内容变化必须登记新版本，禁止静默覆盖"
            )

        stored = version.model_copy(deep=True)
        self._versions[(version.tool_id, version.version_id)] = stored
        return stored.model_copy(deep=True)

    def get_version(self, tool_id: str, version_id: str) -> ToolVersion | None:
        version = self._versions.get((tool_id, version_id))
        return None if version is None else version.model_copy(deep=True)

    def list_versions(self, tool_id: str) -> list[ToolVersion]:
        versions = [
            version.model_copy(deep=True)
            for version in self._versions.values()
            if version.tool_id == tool_id
        ]
        return sorted(versions, key=lambda item: item.created_at, reverse=True)

    def get_latest_materialized(self, tool_id: str) -> ToolVersion | None:
        materialized = [
            version
            for version in self.list_versions(tool_id)
            if version.status == ToolStatus.MATERIALIZED
        ]
        return materialized[0] if materialized else None
