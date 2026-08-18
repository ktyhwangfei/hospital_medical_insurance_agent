"""模型治理资产的运行时解析。"""

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from src.data_platform.storage.model_governance.factory import (
    get_model_governance_storage,
)
from src.data_platform.storage.model_governance.ports import ModelGovernanceStorage
from src.model_service.governance_assets import (
    GovernanceAssetPreview,
    GovernanceAssetType,
    GovernanceEnvironment,
    GovernanceReleaseStatus,
    ModelProfileAssetContent,
    PromptAssetContent,
    PromptVariable,
    RouteRuleAssetContent,
    preview_asset,
)
from src.model_service.governance_secrets import GovernanceCredentialVault


class GovernanceRuntimeError(RuntimeError):
    """治理发布无法安全用于运行时。"""


class RuntimeModelProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: str
    model_name: str
    base_url: str
    api_key: SecretStr
    timeout_seconds: float
    temperature: float
    max_tokens: int


class RuntimeModelRoute(BaseModel):
    model_config = ConfigDict(frozen=True)

    primary: RuntimeModelProfile
    fallbacks: list[RuntimeModelProfile] = Field(default_factory=list)


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


def _runtime_profile(
    profile_id: str,
    *,
    storage: ModelGovernanceStorage,
    vault: GovernanceCredentialVault,
    environment: GovernanceEnvironment,
) -> RuntimeModelProfile:
    release = storage.get_active_release(profile_id, environment)
    if release is None:
        raise LookupError(f"模型未发布: {profile_id}")
    version = storage.get_version(release.version_id)
    content = version.content
    if (
        release.asset_id != version.asset_id
        or release.asset_type != GovernanceAssetType.MODEL_PROFILE
        or version.asset_type != GovernanceAssetType.MODEL_PROFILE
        or not isinstance(content, ModelProfileAssetContent)
        or content.asset_id != version.asset_id
    ):
        raise TypeError(f"模型发布身份不一致: {profile_id}")
    if not isinstance(content, ModelProfileAssetContent) or not content.enabled:
        raise TypeError(f"模型已停用或类型错误: {profile_id}")
    binding = storage.get_release_credential_binding(release.release_id)
    if binding.credential_id != content.credential_ref:
        raise ValueError(f"发布凭据绑定不匹配: {profile_id}")
    credential = storage.get_credential_revision(
        binding.credential_id, binding.credential_revision
    )
    if credential.secret_fingerprint != binding.credential_fingerprint:
        raise ValueError(f"发布凭据指纹不匹配: {profile_id}")
    api_key = vault.reveal_credential(credential, base_url=content.base_url)
    return RuntimeModelProfile(
        asset_id=content.asset_id,
        model_name=content.model_name,
        base_url=content.base_url,
        api_key=SecretStr(api_key),
        timeout_seconds=content.timeout_seconds,
        temperature=content.temperature,
        max_tokens=content.max_tokens,
    )


def resolve_governed_route(
    scene: str,
    model_type: str,
    *,
    storage: ModelGovernanceStorage | None = None,
    vault: GovernanceCredentialVault | None = None,
    environment: GovernanceEnvironment | None = None,
) -> RuntimeModelRoute | None:
    store = storage if storage is not None else get_model_governance_storage()
    target_environment = environment or current_environment()
    exact_matches: list[RouteRuleAssetContent] = []
    default_matches: list[RouteRuleAssetContent] = []
    try:
        # ponytail: 活动路由为小规模 O(n) 扫描；实测成为网关瓶颈时再加 PostgreSQL 场景索引。
        releases = store.list_releases(environment=target_environment)
        for release in releases:
            if release.status != GovernanceReleaseStatus.ACTIVE:
                continue
            version = store.get_version(release.version_id)
            content = version.content
            is_route_release = (
                release.asset_type == GovernanceAssetType.ROUTE_RULE
                or version.asset_type == GovernanceAssetType.ROUTE_RULE
                or isinstance(content, RouteRuleAssetContent)
            )
            if not is_route_release:
                continue
            if (
                release.asset_id != version.asset_id
                or release.asset_type != GovernanceAssetType.ROUTE_RULE
                or version.asset_type != GovernanceAssetType.ROUTE_RULE
                or not isinstance(content, RouteRuleAssetContent)
                or content.asset_id != version.asset_id
            ):
                raise TypeError(f"活动路由身份不一致: {release.asset_id}")
            if not content.enabled or content.model_type != model_type:
                continue
            if content.scene == scene:
                exact_matches.append(content)
            elif content.scene == "default":
                default_matches.append(content)
    except Exception as exc:
        raise GovernanceRuntimeError(f"读取治理路由失败: {scene}/{model_type}") from exc

    if len(exact_matches) > 1:
        raise GovernanceRuntimeError(f"存在重复治理路由: {scene}/{model_type}")
    if len(default_matches) > 1:
        raise GovernanceRuntimeError(f"存在重复默认治理路由: {model_type}")
    if exact_matches:
        route = exact_matches[0]
    elif default_matches:
        route = default_matches[0]
    else:
        return None

    try:
        credential_vault = vault if vault is not None else GovernanceCredentialVault(store)
        profiles = [
            _runtime_profile(
                profile_id,
                storage=store,
                vault=credential_vault,
                environment=target_environment,
            )
            for profile_id in [route.profile_id, *route.fallback_profile_ids]
        ]
    except Exception as exc:
        raise GovernanceRuntimeError(
            f"解析治理路由模型失败: {scene}/{model_type}"
        ) from exc
    return RuntimeModelRoute(primary=profiles[0], fallbacks=profiles[1:])
