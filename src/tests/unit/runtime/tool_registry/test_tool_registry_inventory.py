"""Tool Registry 全量登记测试：数据/知识/对比计算三类工具的注册与绑定。"""

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
        "tool_compare_settlement_vs_policy",
    }
    assert expected_bound <= tool_ids
    for tool_id in expected_bound:
        assert registry.is_bound(tool_id), f"{tool_id} 应绑定实现"


def test_registry_tags_carry_category_taxonomy() -> None:
    registry = get_tool_registry()

    categories = {
        tool_id: (registry.get_tool(tool_id).definition.tags[0] if tool_id in registry.list_registered_tool_ids() else None)
        for tool_id in (
            "tool_get_settlement_fact",
            "tool_query_semantic_metrics",
            "tool_retrieve_policy_evidence",
            "tool_comprehensive_knowledge_lookup",
            "tool_compare_settlement_vs_policy",
        )
    }
    assert set(categories.values()) == {"数据类", "知识类", "对比计算类"}


def test_registry_binds_refund_record_with_real_source() -> None:
    """2026-09-16 盘点后：退费记录接入真实数据源（HIS o_Trade 链路 + 住院 tflydjh）并绑定实现。"""
    registry = get_tool_registry()

    assert "tool_get_refund_record" in registry.list_registered_tool_ids()
    assert registry.is_bound("tool_get_refund_record")


def test_semantic_metric_tool_target_ref_within_whitelist() -> None:
    registry = get_tool_registry()
    version = registry.get_tool("tool_query_semantic_metrics")

    assert version is not None
    assert version.definition.target_ref.startswith("src.semantic_layer.")
