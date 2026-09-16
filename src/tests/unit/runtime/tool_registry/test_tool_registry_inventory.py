"""Tool Registry 全量登记测试：仅登记可独立调用的数据/知识能力。"""

import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from src.runtime.tool_registry.factory import get_tool_registry


def test_registry_registers_all_category_tools_bound() -> None:
    registry = get_tool_registry()
    tool_ids = set(registry.list_registered_tool_ids())

    expected_bound = {
        "tool_get_settlement_fact",
        "tool_query_semantic_metrics",
        "tool_retrieve_policy_evidence",
        "tool_match_trusted_question",
        "tool_comprehensive_knowledge_lookup",
    }
    assert expected_bound <= tool_ids
    for tool_id in expected_bound:
        assert registry.is_bound(tool_id), f"{tool_id} 应绑定实现"
    assert "tool_compare_settlement_vs_policy" not in tool_ids


def test_registry_tags_carry_category_taxonomy() -> None:
    registry = get_tool_registry()

    categories = {
        tool_id: (registry.get_tool(tool_id).definition.tags[0] if tool_id in registry.list_registered_tool_ids() else None)
        for tool_id in (
            "tool_get_settlement_fact",
            "tool_query_semantic_metrics",
            "tool_retrieve_policy_evidence",
            "tool_comprehensive_knowledge_lookup",
        )
    }
    assert set(categories.values()) == {"数据类", "知识类"}


def test_registry_keeps_refund_record_unbound_by_design() -> None:
    registry = get_tool_registry()

    assert "tool_get_refund_record" in registry.list_registered_tool_ids()
    assert not registry.is_bound("tool_get_refund_record")


def test_semantic_metric_tool_target_ref_within_whitelist() -> None:
    registry = get_tool_registry()
    version = registry.get_tool("tool_query_semantic_metrics")

    assert version is not None
    assert version.definition.target_ref.startswith("src.semantic_layer.")
