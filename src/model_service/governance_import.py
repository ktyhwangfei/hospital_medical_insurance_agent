"""把当前代码配置投影为可编辑治理草稿内容。"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from src.model_service.governance import ModelGovernanceSnapshot, build_governance_snapshot
from src.model_service.governance_assets import (
    GovernanceAssetContent,
    ModelProfileAssetContent,
    PromptAssetContent,
    PromptVariable,
    RouteRuleAssetContent,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
        system_prompt=system_prompt.strip(),
        user_prompt_template=user_prompt.strip(),
        variables=_variables(*variables),
        output_mode="json" if "JSON" in user_prompt else "text",
    )


def _prompt_assets(snapshot: ModelGovernanceSnapshot) -> list[PromptAssetContent]:
    from src.knowledge_extension.rule_explanation.policy_fact.run_policy_fact_extraction import (
        SYSTEM_PROMPT,
        USER_PROMPT_TEMPLATE,
    )
    from src.runtime.policy_qa.explanation_generator import EXPLANATION_PROMPTS
    from src.runtime.policy_qa.intent_detector import INTENT_DETECTION_PROMPT

    metadata = {item.prompt_id: item for item in snapshot.prompts}
    templates: dict[str, tuple[str, str, tuple[str, ...]]] = {
        "intent.classify": (
            "",
            """你是医保智能体的意图识别模块。请分析用户消息，返回 JSON。

可用意图：
{intents_text}

用户消息：{message}

返回格式（仅返回 JSON，不要其他内容）：
{{"intent": "<意图标识>", "confidence": <0-1>, "entities": {{}}, "citations": ["LLM意图推理"]}}""",
            ("intents_text", "message"),
        ),
        "intent.discriminate": (
            "",
            """你是医保智能体的意图识别模块。请根据用户消息和候选意图列表，判断最可能的意图。

候选意图：
{candidates_text}

用户消息：{message}

请返回 JSON（仅返回 JSON，不要其他内容）：
{{"intent": "<意图标识>", "confidence": <0-1的置信度>, "entities": {{}}, "citations": ["推理依据"]}}""",
            ("candidates_text", "message"),
        ),
        "skill.route": (
            "",
            """你是医疗医保智能体的技能路由器。根据用户问题，判断是否需要交给某个技能处理。

可用技能：
{skills_text}

用户问题：{question}

判断规则：
1. 如果用户问题与某个技能的能力范围高度相关，返回该技能的 skill_id
2. 如果用户问题与任何技能都无关，返回 null
3. 医保费用解释、报销计算、政策咨询优先匹配费用解释类技能

仅返回 JSON：
{{"skill_id": "<skill_id或null>", "confidence": 0.0, "reasoning": "简短理由"}}""",
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
            """你是一个医保政策分析专家。请根据发布态语义 schema，从政策文本中提取政策事实和结构化规则。

## 提取契约
{schema_description}

## 政策文件
{title}

## 原文
{text}

只返回符合提取契约的 JSON 数组。""",
            ("schema_description", "title", "text"),
        ),
        "policy.extract.legacy": (
            "",
            """你是医保政策分析专家。请从政策文本中提取可独立理解的政策事实，并生成包含现有 19 个字段的结构化规则。

政策文件：{title}

政策原文：
{text}

只返回 JSON 数组；原文未提及的字段填空字符串，不得编造政策内容。""",
            ("title", "text"),
        ),
        "policy.fact_extract": (
            SYSTEM_PROMPT,
            USER_PROMPT_TEMPLATE.replace("{{ fact_json }}", "{fact_json}"),
            ("node_id", "policy_title", "policy_meta_json", "path_text", "text"),
        ),
        "policy.synonym_discovery": (
            "",
            """你是医保政策专家。请分析政策原文，找出已知值域的同义词、简称和别称。

当前已知值域：
{known_values_text}

政策原文片段：
{text_sample}

只返回包含 synonyms 和 new_values 的 JSON。""",
            ("known_values_text", "text_sample"),
        ),
        "policy.domain_discovery": (
            "",
            """你是医保政策专家。请分析政策原文，发现需要新增的值域字段。

当前已有字段：
{known_fields_text}

政策原文片段：
{text_sample}

只返回包含 new_domains 的 JSON。""",
            ("known_fields_text", "text_sample"),
        ),
    }
    skill = yaml.safe_load(
        (_PROJECT_ROOT / "skills/settlement_explain_skill/prompt_template.yaml").read_text(
            encoding="utf-8"
        )
    )
    templates["skill.settlement_explain"] = (
        skill["system_prompt"].replace("{", "{{").replace("}", "}}"),
        skill["user_prompt"].replace("{{ fact_json }}", "{fact_json}"),
        ("fact_json",),
    )

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
    provider_id = snapshot.providers[0].provider_id if snapshot.providers else "default"
    models = [
        ModelProfileAssetContent(
            asset_id=profile_ids[item.model_name],
            name=item.model_name,
            provider_id=provider_id,
            model_name=item.model_name,
            credential_ref="MODEL_API_KEY",
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
