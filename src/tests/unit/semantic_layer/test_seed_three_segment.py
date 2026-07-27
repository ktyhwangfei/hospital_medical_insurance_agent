"""P8.3 seed metric 三段式 source_field 路由验证。

[来源: docs/steering/政策知识管线开发计划.md §7.6 / §4.3 / Phase 8.3]

成功标准：数据库侧指标（yb_* 表）source_field 为三段式 `bjybdb.table.column`，
经 SemanticDataSource.build_query_plan 解析后 datasource_id=="bjybdb"（走 policy_datasource
注册表的可靠连接，而非可能为空的默认源 _resolve_source_config）。
政策侧 zcgz 保持两段式（走 Milvus 检索，不经 SQL ds 路由）。
"""
from src.runtime.discovery.semantic_source import (
    SemanticDataSource,
    parse_source_field,
)
from src.semantic_layer.registry import get_semantic_registry
from src.semantic_layer.seed import seed_semantic_layer


def _seeded_source() -> SemanticDataSource:
    """构造装好 seed 数据的 SemanticDataSource（注入全局 registry 单例）。"""
    seed_semantic_layer(get_semantic_registry()._store)
    return SemanticDataSource()


# ── parse_source_field 纯函数 ──────────────────────────────────

def test_parse_three_segment():
    ds, table, column = parse_source_field("bjybdb.yb_brdjxx.djh")
    assert (ds, table, column) == ("bjybdb", "yb_brdjxx", "djh")


def test_parse_two_segment_fallback():
    """两段式向后兼容（zcgz 政策指标保持两段式）。"""
    ds, table, column = parse_source_field("zcgz.rule_id")
    assert (ds, table, column) == (None, "zcgz", "rule_id")


# ── SemanticDataSource 路由 ────────────────────────────────────

def test_db_metrics_routed_to_bjybdb():
    """6 张 yb_* 表的代表指标应全部路由到 datasource_id=bjybdb。"""
    source = _seeded_source()
    plan = source.build_query_plan([
        "djxx.djh", "djxx.fund_type", "ypml.mzxj",
        "zydyxx.bcqfje", "zyfdxx.bdtczfje", "zyjyxx.rylb", "zyfymx.xmbm",
    ])
    assert plan["unmapped_count"] == 0, f"存在未映射: {plan['unmapped']}"
    ds_ids = {t["datasource_id"] for t in plan["tables"]}
    assert ds_ids == {"bjybdb"}, f"数据库侧指标应全部路由到 bjybdb，实际 {ds_ids}"
    # table 不应含 ds 前缀（前缀是 datasource_id，不是表名一部分）
    for t in plan["tables"]:
        assert not t["table"].startswith("bjybdb"), f"table 误含前缀: {t['table']}"


def test_ypml_table_resolved_from_full_source_field():
    """ypml.mzxj 原 source_field 仅列名 A_mzxj；三段式补全表名 yb_ypzdml。"""
    source = _seeded_source()
    r = source.resolve_metric("ypml.mzxj")
    assert not r.get("unmapped"), f"ypml.mzxj 未映射: {r}"
    assert (r["datasource_id"], r["table"], r["column"]) == ("bjybdb", "yb_ypzdml", "A_mzxj")


def test_zcgz_policy_metrics_not_routed_to_sql():
    """zcgz 政策指标保持两段式（datasource_id=None），不走 SQL 多源路由。

    政策规则走 Milvus policy_rules_v2 检索（rules_search_service），与 SQL 取数路径分离。
    """
    source = _seeded_source()
    r = source.resolve_metric("zcgz.rule_type")
    assert r["datasource_id"] is None, "zcgz 政策指标不应路由到 SQL datasource"
