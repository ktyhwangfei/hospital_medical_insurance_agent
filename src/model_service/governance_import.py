"""把当前代码配置投影为可编辑治理草稿内容。"""

from __future__ import annotations

import re

from src.model_service.governance import ModelGovernanceSnapshot, build_governance_snapshot
from src.model_service.governance_assets import (
    GovernanceAssetContent,
    ModelProfileAssetContent,
    PromptAssetContent,
    PromptVariable,
    RouteRuleAssetContent,
)


def _variables(*names: str) -> list[PromptVariable]:
    return [PromptVariable(name=name, required=True) for name in names]


def _prompt(
    asset_id: str,
    name: str,
    scene: str | None,
    user_prompt: str,
    variables: tuple[str, ...],
    *,
    system_prompt: str = "",
) -> PromptAssetContent:
    return PromptAssetContent(
        asset_id=asset_id,
        name=name,
        scene=scene or "unrouted",
        system_prompt=system_prompt,
        user_prompt_template=user_prompt,
        variables=_variables(*variables),
        output_mode="json" if "JSON" in user_prompt else "text",
    )


def _prompt_assets(snapshot: ModelGovernanceSnapshot) -> list[PromptAssetContent]:
    from src.knowledge_extension.rule_explanation.pipeline_orchestrator import (
        LEGACY_FACT_EXTRACTION_PROMPT_TEMPLATE,
    )
    from src.knowledge_extension.rule_explanation.policy_extract.llm_enhanced_extractor import (
        DOMAIN_DISCOVERY_PROMPT_TEMPLATE,
        SYNONYM_DISCOVERY_PROMPT_TEMPLATE,
    )
    from src.knowledge_extension.rule_explanation.policy_fact.run_policy_fact_extraction import (
        SYSTEM_PROMPT,
        USER_PROMPT_TEMPLATE,
    )
    from src.runtime.intent.graph.prompts import (
        INTENT_DISCRIMINATION_PROMPT_TEMPLATE,
    )
    from src.runtime.intent.prompts import INTENT_CLASSIFICATION_PROMPT_TEMPLATE
    from src.runtime.policy_qa.explanation_generator import EXPLANATION_PROMPTS
    from src.runtime.policy_qa.intent_detector import INTENT_DETECTION_PROMPT
    from src.semantic_layer.extraction_contract import (
        SCHEMA_EXTRACTION_PROMPT_TEMPLATE,
    )
    from src.skill_infra.unified_router import SKILL_ROUTING_PROMPT_TEMPLATE
    from skills.settlement_explain_skill.strategies.pooling_self_pay.strategy import (
        load_settlement_explain_prompt_templates,
    )

    metadata = {item.prompt_id: item for item in snapshot.prompts}
    settlement_system_prompt, settlement_user_prompt = (
        load_settlement_explain_prompt_templates()
    )
    templates: dict[str, tuple[str, str, tuple[str, ...]]] = {
        "intent.classify": (
            "",
            INTENT_CLASSIFICATION_PROMPT_TEMPLATE,
            ("intents_text", "message"),
        ),
        "intent.discriminate": (
            "",
            INTENT_DISCRIMINATION_PROMPT_TEMPLATE,
            ("candidates_text", "message"),
        ),
        "skill.route": (
            "",
            SKILL_ROUTING_PROMPT_TEMPLATE,
            ("skills_text", "question"),
        ),
        "policy_qa.intent_detect": (
            "",
            INTENT_DETECTION_PROMPT,
            ("question",),
        ),
        "policy_qa.patient_explain": (
            "",
            EXPLANATION_PROMPTS["患者"],
            ("question", "decomposition_text", "policy_text", "RAG_MISS_NOTE"),
        ),
        "policy.extract.schema": (
            "",
            SCHEMA_EXTRACTION_PROMPT_TEMPLATE,
            (
                "schema_version",
                "fields_desc",
                "entities_desc",
                "relations_desc",
                "title",
                "text",
                "field_codes",
                "fields_json_example",
                "field_count",
            ),
        ),
        "policy.extract.legacy": (
            "",
            LEGACY_FACT_EXTRACTION_PROMPT_TEMPLATE,
            ("title", "text"),
        ),
        "policy.fact_extract": (
            SYSTEM_PROMPT,
            USER_PROMPT_TEMPLATE,
            ("node_id", "policy_title", "policy_meta_json", "path_text", "text"),
        ),
        "policy.synonym_discovery": (
            "",
            SYNONYM_DISCOVERY_PROMPT_TEMPLATE,
            ("known_values_text", "text_sample"),
        ),
        "policy.domain_discovery": (
            "",
            DOMAIN_DISCOVERY_PROMPT_TEMPLATE,
            ("known_fields_text", "text_sample"),
        ),
        "skill.settlement_explain": (
            settlement_system_prompt,
            settlement_user_prompt,
            ("fact_json",),
        ),
    }

    return [
        _prompt(
            prompt_id,
            item.name,
            item.scene,
            user_prompt,
            variables,
            system_prompt=system_prompt,
        )
        for prompt_id, (system_prompt, user_prompt, variables) in templates.items()
        if (item := metadata.get(prompt_id)) is not None
    ]


def _profile_ids(model_names: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    used: set[str] = set()
    for model_name in model_names:
        slug = re.sub(r"[^a-z0-9._-]+", "-", model_name.lower()).strip("-._")
        base = f"model.{slug or 'profile'}"
        asset_id = base
        index = 2
        while asset_id in used:
            asset_id = f"{base}-{index}"
            index += 1
        used.add(asset_id)
        result[model_name] = asset_id
    return result


def build_current_governance_assets(
    snapshot: ModelGovernanceSnapshot | None = None,
) -> list[GovernanceAssetContent]:
    """读取当前静态配置并转换为不影响运行时的治理资产。"""
    snapshot = snapshot or build_governance_snapshot()
    profile_ids = _profile_ids([item.model_name for item in snapshot.models])
    endpoint = snapshot.providers[0].endpoint if snapshot.providers else "invalid"
    base_url = endpoint if endpoint.startswith(("http://", "https://")) else "http://127.0.0.1"
    models = [
        ModelProfileAssetContent(
            asset_id=profile_ids[item.model_name],
            name=item.model_name,
            provider_id="openai_compatible",
            base_url=base_url,
            model_name=item.model_name,
            credential_ref="credential.default",
            timeout_seconds=30,
            temperature=item.temperature,
            max_tokens=item.max_tokens,
        )
        for item in snapshot.models
    ]
    routes = [
        RouteRuleAssetContent(
            asset_id=f"route.{item.scene}.{item.model_type}",
            name=f"{item.scene}/{item.model_type}",
            scene=item.scene,
            model_type=item.model_type,
            profile_id=profile_ids[item.effective_model],
            fallback_profile_ids=[
                profile_ids[model_name]
                for model_name in item.fallbacks
                if model_name in profile_ids
            ],
            enabled=True,
        )
        for item in snapshot.routes
        if item.effective_model in profile_ids
    ]
    return [*_prompt_assets(snapshot), *models, *routes]
