from src.model_service.governance import build_governance_snapshot
from src.model_service.governance_assets import (
    ModelProfileAssetContent,
    PromptAssetContent,
    RouteRuleAssetContent,
    validate_asset,
)
from src.model_service.governance_import import build_current_governance_assets


def test_current_snapshot_converts_every_prompt_model_and_route_to_valid_assets():
    snapshot = build_governance_snapshot()

    assets = build_current_governance_assets(snapshot)
    prompts = [item for item in assets if isinstance(item, PromptAssetContent)]
    models = [item for item in assets if isinstance(item, ModelProfileAssetContent)]
    routes = [item for item in assets if isinstance(item, RouteRuleAssetContent)]

    assert {item.asset_id for item in prompts} == {
        item.prompt_id for item in snapshot.prompts
    }
    assert {item.model_name for item in models} == {
        item.model_name for item in snapshot.models
    }
    assert {(item.scene, item.model_type) for item in routes} == {
        (item.scene, item.model_type) for item in snapshot.routes if item.effective_model
    }
    assert all(validate_asset(item) == [] for item in prompts)
    assert next(item for item in prompts if item.asset_id == "policy.fact_extract").system_prompt
    assert next(item for item in prompts if item.asset_id == "skill.route").system_prompt == ""


def test_routes_reference_the_imported_model_profile_ids():
    assets = build_current_governance_assets(build_governance_snapshot())
    profile_ids = {
        item.asset_id for item in assets if isinstance(item, ModelProfileAssetContent)
    }

    for route in (item for item in assets if isinstance(item, RouteRuleAssetContent)):
        assert route.profile_id in profile_ids
        assert set(route.fallback_profile_ids) <= profile_ids
