import pytest
from pydantic import ValidationError


def _assets():
    from src.model_service.governance_assets import (
        GovernanceValidationError,
        ModelProfileAssetContent,
        PromptAssetContent,
        PromptVariable,
        RouteRuleAssetContent,
        content_hash,
        preview_asset,
        validate_asset,
    )

    return {
        "GovernanceValidationError": GovernanceValidationError,
        "ModelProfileAssetContent": ModelProfileAssetContent,
        "PromptAssetContent": PromptAssetContent,
        "PromptVariable": PromptVariable,
        "RouteRuleAssetContent": RouteRuleAssetContent,
        "content_hash": content_hash,
        "preview_asset": preview_asset,
        "validate_asset": validate_asset,
    }


def test_prompt_preview_accepts_only_declared_complete_variables():
    api = _assets()
    content = api["PromptAssetContent"](
        asset_id="prompt.demo",
        name="演示提示词",
        scene="policy_qa",
        system_prompt="只输出可追溯事实",
        user_prompt_template="问题：{question}",
        variables=[api["PromptVariable"](name="question")],
    )

    assert api["validate_asset"](content) == []
    preview = api["preview_asset"](content, {"question": "什么是起付线"})
    assert preview.rendered_system_prompt == "只输出可追溯事实"
    assert preview.rendered_user_prompt == "问题：什么是起付线"

    with pytest.raises(api["GovernanceValidationError"], match="缺少变量"):
        api["preview_asset"](content, {})
    with pytest.raises(api["GovernanceValidationError"], match="未声明变量"):
        api["preview_asset"](
            content,
            {"question": "什么是起付线", "patient_name": "不应进入提示词"},
        )


def test_prompt_validation_rejects_unsafe_template_field_access():
    api = _assets()
    content = api["PromptAssetContent"](
        asset_id="prompt.unsafe",
        name="不安全提示词",
        scene="policy_qa",
        system_prompt="只输出事实",
        user_prompt_template="{question.__class__}",
        variables=[api["PromptVariable"](name="question")],
    )

    issues = api["validate_asset"](content)
    assert [issue.code for issue in issues] == ["UNSAFE_TEMPLATE_FIELD"]


def test_model_profile_accepts_secret_reference_not_secret_value():
    api = _assets()
    content = api["ModelProfileAssetContent"](
        asset_id="model.deepseek-chat",
        name="DeepSeek Chat",
        provider_id="openai_compatible",
        base_url="https://model.example/v1",
        model_name="deepseek-chat",
        credential_ref="credential.model.deepseek-chat",
        temperature=0.1,
        max_tokens=4096,
    )

    assert api["validate_asset"](content) == []
    with pytest.raises(ValidationError):
        api["ModelProfileAssetContent"](
            asset_id="model.invalid",
            name="非法模型",
            provider_id="openai_compatible",
            base_url="https://model.example/v1",
            model_name="deepseek-chat",
            credential_ref="sk_SECRET_value",
            temperature=0.1,
            max_tokens=4096,
        )


def test_route_validation_rejects_self_fallback_and_hash_is_stable():
    api = _assets()
    route = api["RouteRuleAssetContent"](
        asset_id="route.policy-qa",
        name="政策问答路由",
        scene="policy_qa",
        model_type="llm",
        profile_id="model.deepseek-chat",
        fallback_profile_ids=["model.deepseek-chat"],
    )

    issues = api["validate_asset"](route)
    assert [issue.code for issue in issues] == ["SELF_FALLBACK_NOT_ALLOWED"]
    assert api["content_hash"](route) == api["content_hash"](
        route.model_copy(deep=True)
    )
