"""模型治理资产的运行时解析。"""

import os

from src.data_platform.storage.model_governance.factory import (
    get_model_governance_storage,
)
from src.data_platform.storage.model_governance.ports import ModelGovernanceStorage
from src.model_service.governance_assets import (
    GovernanceAssetPreview,
    GovernanceEnvironment,
    PromptAssetContent,
    PromptVariable,
    preview_asset,
)


class GovernanceRuntimeError(RuntimeError):
    """治理发布无法安全用于运行时。"""


def current_environment() -> GovernanceEnvironment:
    value = os.getenv("MODEL_GOVERNANCE_ENV", "dev")
    try:
        return GovernanceEnvironment(value)
    except ValueError as exc:
        raise GovernanceRuntimeError(f"不支持的治理环境: {value}") from exc


def render_governed_prompt(
    asset_id: str,
    *,
    variables: dict[str, str],
    fallback_system: str,
    fallback_user: str,
    storage: ModelGovernanceStorage | None = None,
    environment: GovernanceEnvironment | None = None,
) -> GovernanceAssetPreview:
    store = storage if storage is not None else get_model_governance_storage()
    try:
        active = store.get_active_release(
            asset_id,
            environment or current_environment(),
        )
    except Exception as exc:
        raise GovernanceRuntimeError(f"读取活动提示词失败: {asset_id}") from exc

    if active is None:
        content = PromptAssetContent(
            asset_id=asset_id,
            name=asset_id,
            scene="fallback",
            system_prompt=fallback_system,
            user_prompt_template=fallback_user,
            variables=[PromptVariable(name=name) for name in variables],
        )
        return preview_asset(content, variables)

    try:
        content = store.get_version(active.version_id).content
        if not isinstance(content, PromptAssetContent):
            raise TypeError("活动资产不是提示词")
        return preview_asset(content, variables)
    except Exception as exc:
        raise GovernanceRuntimeError(f"解析活动提示词失败: {asset_id}") from exc
