"""只读模型与提示词治理快照。"""

from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal

from pydantic import BaseModel, Field
import yaml

from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE
from src.config.model_service import ModelServiceConfig
from src.model_service.router import ModelRouter

SourceKind = Literal["code", "yaml", "dynamic"]
GatewayStatus = Literal["routed", "direct", "unknown"]
ManagementStatus = Literal["source_managed", "needs_migration", "needs_verification"]
ProviderType = Literal["openai_compatible", "development_fixture"]
CredentialStatus = Literal["configured", "missing", "not_applicable"]


class PromptParameters(BaseModel):
    temperature: float | None = None
    max_tokens: int | None = None


class PromptAsset(BaseModel):
    prompt_id: str
    name: str
    source_path: str
    related_source_paths: list[str] = Field(default_factory=list)
    source_kind: SourceKind
    scene: str | None = None
    model_type: str = "llm"
    gateway_status: GatewayStatus
    management_status: ManagementStatus
    declared_parameters: PromptParameters = Field(default_factory=PromptParameters)
    route_defaults: PromptParameters = Field(default_factory=PromptParameters)
    call_overrides: PromptParameters = Field(default_factory=PromptParameters)
    effective_parameters: PromptParameters = Field(default_factory=PromptParameters)
    warnings: list[str] = Field(default_factory=list)


class ModelProfileSnapshot(BaseModel):
    model_name: str
    temperature: float
    max_tokens: int


class ModelRouteSnapshot(BaseModel):
    scene: str
    model_type: str
    effective_model: str | None = None
    explicit: bool
    fallbacks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProviderSnapshot(BaseModel):
    provider_id: str
    type: ProviderType
    endpoint: str
    credential_status: CredentialStatus


class ModelGovernanceSnapshot(BaseModel):
    prompts: list[PromptAsset]
    models: list[ModelProfileSnapshot]
    routes: list[ModelRouteSnapshot]
    providers: list[ProviderSnapshot]
    citations: list[str]
    uncertainties: list[str]


_ASSETS = (
    ("skill.route", "技能路由", "src/skill_infra/unified_router.py", "code", "skill_routing", "routed", "source_managed"),
    ("policy.extract.schema", "政策结构化抽取", "src/semantic_layer/extraction_contract.py", "dynamic", "policy_fact_extraction", "routed", "source_managed"),
    ("policy.extract.legacy", "政策遗留抽取", "src/knowledge_extension/rule_explanation/pipeline_orchestrator.py", "code", "policy_fact_extraction", "routed", "needs_migration"),
    ("policy.fact_extract", "政策事实抽取", "src/knowledge_extension/rule_explanation/policy_fact/run_policy_fact_extraction.py", "code", None, "direct", "needs_migration"),
    ("policy.synonym_discovery", "政策同义词发现", "src/knowledge_extension/rule_explanation/policy_extract/llm_enhanced_extractor.py", "code", None, "unknown", "needs_verification"),
    ("policy.domain_discovery", "政策领域发现", "src/knowledge_extension/rule_explanation/policy_extract/llm_enhanced_extractor.py", "code", None, "unknown", "needs_verification"),
    ("skill.settlement_explain", "结算解释技能", "skills/settlement_explain_skill/prompt_template.yaml", "yaml", "fee_explanation", "routed", "needs_verification"),
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RELATED_SOURCES = {
    "policy.extract.schema": [
        "src/knowledge_extension/rule_explanation/pipeline_orchestrator.py"
    ],
    "policy.fact_extract": [
        "src/knowledge_extension/rule_explanation/policy_fact/deepseek_llm_client.py"
    ],
}
_CALL_OVERRIDES = {
    "policy.extract.schema": PromptParameters(max_tokens=8192),
    "policy.extract.legacy": PromptParameters(max_tokens=8192),
    "policy.fact_extract": PromptParameters(temperature=0.1, max_tokens=8192),
}


def _endpoint(value: str) -> str:
    if value == "dummy":
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "invalid"
        host = parsed.hostname
        port = parsed.port
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{parsed.scheme}://{host}{f':{port}' if port is not None else ''}"
    except ValueError:
        return "invalid"


def _declared_parameters(prompt_id: str, source_path: str) -> PromptParameters:
    if prompt_id != "skill.settlement_explain":
        return PromptParameters()
    content = yaml.safe_load((_PROJECT_ROOT / source_path).read_text(encoding="utf-8"))
    model_config = content.get("model_config", {}) if isinstance(content, dict) else {}
    return PromptParameters(
        temperature=model_config.get("temperature"),
        max_tokens=model_config.get("max_tokens"),
    )


def _effective_parameters(
    route_defaults: PromptParameters,
    call_overrides: PromptParameters,
) -> PromptParameters:
    return PromptParameters(
        temperature=(
            call_overrides.temperature
            if call_overrides.temperature is not None
            else route_defaults.temperature
        ),
        max_tokens=(
            call_overrides.max_tokens
            if call_overrides.max_tokens is not None
            else route_defaults.max_tokens
        ),
    )


def build_governance_snapshot(config: ModelServiceConfig | None = None) -> ModelGovernanceSnapshot:
    config = config or ModelServiceConfig()
    model_router = ModelRouter()
    prompts = []
    for prompt_id, name, source, kind, scene, gateway, management in _ASSETS:
        warnings = []
        if gateway == "direct":
            warnings.append("绕过统一网关")
        elif gateway == "unknown":
            warnings.append("调用可达性待核验")
        if scene and (scene, "llm") not in ROUTING_TABLE:
            warnings.append("使用 default 路由")
        declared = _declared_parameters(prompt_id, source)
        route_defaults = PromptParameters()
        if scene and gateway == "routed":
            model_name, _ = model_router.resolve(scene, "llm")
            route_defaults = PromptParameters(**model_router.get_model_params(model_name))
        call_overrides = _CALL_OVERRIDES.get(prompt_id, PromptParameters())
        effective = _effective_parameters(route_defaults, call_overrides)
        if prompt_id == "skill.settlement_explain" and declared != effective:
            warnings.append(
                f"声明参数 temperature={declared.temperature}/max_tokens="
                f"{declared.max_tokens} 与实际生效 temperature="
                f"{effective.temperature}/max_tokens={effective.max_tokens} 不一致"
            )
        prompts.append(
            PromptAsset(
                prompt_id=prompt_id,
                name=name,
                source_path=source,
                related_source_paths=_RELATED_SOURCES.get(prompt_id, []),
                source_kind=kind,
                scene=scene,
                gateway_status=gateway,
                management_status=management,
                declared_parameters=declared,
                route_defaults=route_defaults,
                call_overrides=call_overrides,
                effective_parameters=effective,
                warnings=warnings,
            )
        )

    fallback_models = {str(model) for model in FALLBACK_CHAINS}
    fallback_models.update(str(model) for chain in FALLBACK_CHAINS.values() for model in chain)
    model_names = sorted({str(model) for model in MODEL_PARAMS} | {str(model) for model in ROUTING_TABLE.values()} | fallback_models)
    models = [
        ModelProfileSnapshot(model_name=name, **model_router.get_model_params(name))
        for name in model_names
    ]

    route_keys = set(ROUTING_TABLE)
    for prompt in prompts:
        if prompt.scene and prompt.gateway_status == "routed":
            route_keys.add((prompt.scene, prompt.model_type))
    routes = []
    for scene, model_type in sorted(route_keys):
        explicit = (scene, model_type) in ROUTING_TABLE
        model, fallbacks = model_router.resolve(scene, model_type)
        warnings = [] if explicit else ["未显式登记，解析为 default 路由"]
        routes.append(ModelRouteSnapshot(scene=scene, model_type=model_type, effective_model=model, explicit=explicit, fallbacks=fallbacks, warnings=warnings))

    if config.base_url == "dummy":
        provider = ProviderSnapshot(
            provider_id="dummy",
            type="development_fixture",
            endpoint="dummy",
            credential_status="not_applicable",
        )
    else:
        provider = ProviderSnapshot(
            provider_id="default",
            type="openai_compatible",
            endpoint=_endpoint(config.base_url),
            credential_status="configured" if config.api_key else "missing",
        )

    return ModelGovernanceSnapshot(
        prompts=prompts,
        models=models,
        routes=routes,
        providers=[provider],
        citations=["src/config/model_service.py", "src/config/model_routing.py", "docs/superpowers/specs/2026-08-14-提示词与模型统一治理设计.md"],
        uncertainties=[
            "遗留提示词调用可达性仍待核验",
            "生产认证未接入，模型治理端点默认关闭",
        ],
    )
