from src.knowledge_extension.assets.in_memory import build_default_asset_repository
from src.knowledge_extension.assets.models import AssetQuery, KnowledgeAssetStatus, KnowledgeAssetType


def test_default_assets_include_policy_error_code_rule_and_template():
    repo = build_default_asset_repository()

    assets = repo.list_assets(AssetQuery(role="medical_insurance_officer"))
    types = {asset.asset_type for asset in assets}

    assert KnowledgeAssetType.ERROR_CODE in types
    assert KnowledgeAssetType.POLICY in types
    assert KnowledgeAssetType.AUDIT_RULE in types
    assert KnowledgeAssetType.APPEAL_TEMPLATE in types


def test_inactive_assets_are_filtered_and_audited():
    repo = build_default_asset_repository()

    assets = repo.list_assets(AssetQuery(role="medical_insurance_officer", include_inactive=False))

    assert all(asset.status is KnowledgeAssetStatus.PUBLISHED for asset in assets)
    assert repo.audit_events


def test_role_scope_filters_internal_policy_without_leaking_content():
    repo = build_default_asset_repository()

    assets = repo.list_assets(AssetQuery(role="doctor", tenant_id="tenant-a", campus_id="north"))

    assert all(asset.asset_id != "asset-internal-policy-001" for asset in assets)
    assert any(event.event_type == "knowledge_asset_filtered" for event in repo.audit_events)


def test_chunks_trace_to_asset_and_version():
    repo = build_default_asset_repository()

    chunks = repo.list_chunks(AssetQuery(role="medical_insurance_officer", scenario="settlement_exception"))

    assert chunks
    assert all(chunk.asset_id for chunk in chunks)
    assert all(chunk.asset_version for chunk in chunks)


def test_duplicate_published_version_is_rejected():
    repo = build_default_asset_repository()
    original = repo.get_asset("asset-policy-001")

    result = repo.add_asset(original)

    assert result.status.value == "version_mismatch"
    assert "重复" in result.user_message
