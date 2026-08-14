"""只读模型与提示词治理快照。"""

from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from src.config.model_routing import FALLBACK_CHAINS, MODEL_PARAMS, ROUTING_TABLE
from src.config.model_service import ModelServiceConfig


class PromptAsset(BaseModel):
    prompt_id: str
    name: str
    source_path: str
    source_kind: str
    scene: str | None = None
    model_type: str = "llm"
    gateway_status: str
    management_status: str
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
    type: str
    endpoint: str
    credential_status: str


class ModelGovernanceSnapshot(BaseModel):
    prompts: list[PromptAsset]
    models: list[ModelProfileSnapshot]
    routes: list[ModelRouteSnapshot]
    providers: list[ProviderSnapshot]
    citations: list[str]
    uncertainties: list[str]


_ASSETS = (
    ("intent.classify", "意图分类", "src/runtime/intent/prompts.py", "code", "intent_recognition", "routed", "source_managed"),
    ("intent.discriminate", "意图判别", "src/runtime/intent/graph/prompts.py", "code", "intent_recognition", "routed", "source_managed"),
    ("skill.route", "技能路由", "src/skill_infra/unified_router.py", "code", "skill_routing", "routed", "source_managed"),
    ("policy_qa.intent_detect", "政策问答意图识别", "src/runtime/policy_qa/intent_detector.py", "code", "policy_qa", "routed", "needs_verification"),
    ("policy_qa.patient_explain", "政策问答患者解释", "src/runtime/policy_qa/explanation_generator.py", "code", "policy_qa", "routed", "needs_verification"),
    ("policy.extract.schema", "政策结构化抽取", "src/semantic_layer/extraction_contract.py", "dynamic", "policy_qa", "routed", "source_managed"),
    ("policy.extract.legacy", "政策遗留抽取", "src/knowledge_extension/rule_explanation/pipeline_orchestrator.py", "code", "policy_qa", "routed", "needs_migration"),
    ("policy.fact_extract", "政策事实抽取", "src/knowledge_extension/rule_explanation/policy_fact/run_policy_fact_extraction.py", "code", None, "direct", "needs_migration"),
    ("policy.synonym_discovery", "政策同义词发现", "src/knowledge_extension/rule_explanation/policy_extract/llm_enhanced_extractor.py", "code", None, "unknown", "needs_verification"),
    ("policy.domain_discovery", "政策领域发现", "src/knowledge_extension/rule_explanation/policy_extract/llm_enhanced_extractor.py", "code", None, "unknown", "needs_verification"),
    ("skill.settlement_explain", "结算解释技能", "skills/settlement_explain_skill/prompt_template.yaml", "yaml", "fee_explanation", "routed", "needs_verification"),
)


def _endpoint(value: str) -> str:
    if value == "dummy":
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return "invalid"
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{parsed.scheme}://{host}{f':{parsed.port}' if parsed.port else ''}"
    except ValueError:
        return "invalid"


def build_governance_snapshot(config: ModelServiceConfig | None = None) -> ModelGovernanceSnapshot:
    config = config or ModelServiceConfig()
    prompts = []
    for prompt_id, name, source, kind, scene, gateway, management in _ASSETS:
        warnings = []
        if gateway == "direct":
            warnings.append("绕过统一网关")
        elif gateway == "unknown":
            warnings.append("调用可达性待核验")
        if scene and (scene, "llm") not in ROUTING_TABLE:
            warnings.append("使用 default 路由")
        prompts.append(PromptAsset(prompt_id=prompt_id, name=name, source_path=source, source_kind=kind, scene=scene, gateway_status=gateway, management_status=management, warnings=warnings))

    model_names = sorted({str(model) for model in MODEL_PARAMS} | {str(model) for model in ROUTING_TABLE.values()})
    models = [ModelProfileSnapshot(model_name=name, temperature=MODEL_PARAMS.get(name, {}).get("temperature", 0.7), max_tokens=MODEL_PARAMS.get(name, {}).get("max_tokens", 2048)) for name in model_names]

    route_keys = set(ROUTING_TABLE)
    for prompt in prompts:
        if prompt.scene and prompt.gateway_status == "routed":
            route_keys.add((prompt.scene, prompt.model_type))
    routes = []
    for scene, model_type in sorted(route_keys):
        explicit = (scene, model_type) in ROUTING_TABLE
        model = ROUTING_TABLE.get((scene, model_type)) or ROUTING_TABLE.get(("default", model_type))
        warnings = [] if explicit else ["未显式登记，解析为 default 路由"]
        routes.append(ModelRouteSnapshot(scene=scene, model_type=model_type, effective_model=model, explicit=explicit, fallbacks=list(FALLBACK_CHAINS.get(model, [])) if model else [], warnings=warnings))

    return ModelGovernanceSnapshot(
        prompts=prompts,
        models=models,
        routes=routes,
        providers=[ProviderSnapshot(provider_id="default", type="openai_compatible", endpoint=_endpoint(config.base_url), credential_status="configured" if config.api_key else "missing")],
        citations=["src/config/model_service.py", "src/config/model_routing.py", "docs/superpowers/specs/2026-08-14-提示词与模型统一治理设计.md"],
        uncertainties=["遗留提示词调用可达性仍待核验"],
    )
