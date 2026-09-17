"""住院结算查询模型分段日期列映射回归测试（42S22 事故修复）。

事故背景：种子曾把分段结束日期映射到不存在的列（yb_dyxxzy.bcjsrq /
yb_zyfdxx.bdjsrq），编译 SQL 报 42S22 使 settlement_query 整体失败；
且草稿提前返回 + 发布提前返回两条守卫使存量库无法自愈。
修复：seed 列映射纠正为 bcqsrq/bdjzrq + ensure_inpatient_query_model_columns
幂等自愈（修草稿 + 重发布冻结快照）。
"""
import pytest

from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import (
    _seed_settlement_query_model,
    ensure_inpatient_query_model_columns,
)


@pytest.fixture
def store():
    return InMemoryRegistryStore()


class TestSeedSegmentColumns:
    """种子必须映射到真实表存在的列（bjybdb INFORMATION_SCHEMA 实测口径）。"""

    def test_segment_end_date_maps_to_real_columns(self, store):
        _seed_settlement_query_model(store)

        benefit_end = store.get_field("benefit_segments.segment_end_date")
        assert benefit_end.column_name == "bcqsrq", "yb_dyxxzy 无 bcjsrq 列（42S22 事故列）"
        assert benefit_end.nullable is False, "与同列 segment_start_date 的 nullable 必须一致"

        payment_end = store.get_field("payment_segments.segment_end_date")
        assert payment_end.column_name == "bdjzrq", "yb_zyfdxx 无 bdjsrq 列（42S22 事故列）"

        key = store.get_dataset_key("payment_segment_pk")
        assert list(key.columns) == ["djh", "bdqsrq", "bdjzrq"]


def _corrupt_to_stale_columns(store):
    """复刻事故现场：草稿字段/键回退到旧列并发布出冻结旧快照。"""
    for code, column in (
        ("benefit_segments.segment_end_date", "bcjsrq"),
        ("payment_segments.segment_end_date", "bdjsrq"),
    ):
        field = store.get_field(code)
        store.save_field(field.model_copy(update={
            "column_name": column,
            "nullable": code.startswith("benefit_"),
        }))
    key = store.get_dataset_key("payment_segment_pk")
    store.save_dataset_key(key.model_copy(update={"columns": ["djh", "bdqsrq", "bdjsrq"]}))


class TestSelfHeal:
    def test_heal_repairs_stale_draft_and_republishes_snapshot(self, store):
        registry = SemanticRegistry(store)
        _seed_settlement_query_model(store)
        registry.publish_object("inpatient_settlement", changelog="v1")
        _corrupt_to_stale_columns(store)
        registry.publish_object("inpatient_settlement", changelog="v2-stale")

        actions = ensure_inpatient_query_model_columns(store, registry)

        assert any("benefit_segments.segment_end_date" in a for a in actions)
        assert any("payment_segments.segment_end_date" in a for a in actions)
        assert any("payment_segment_pk" in a for a in actions)
        assert any("republished" in a for a in actions)

        # 草稿已纠正
        assert store.get_field("benefit_segments.segment_end_date").column_name == "bcqsrq"
        assert store.get_field("payment_segments.segment_end_date").column_name == "bdjzrq"
        assert list(store.get_dataset_key("payment_segment_pk").columns) == ["djh", "bdqsrq", "bdjzrq"]

        # 运行时读的最新已发布冻结快照也已纠正（旧快照曾使 42S22 复发）
        latest = store.list_object_versions("inpatient_settlement")[-1]
        published = {f.field_code: f for f in latest.fields}
        assert published["benefit_segments.segment_end_date"].column_name == "bcqsrq"
        assert published["payment_segments.segment_end_date"].column_name == "bdjzrq"
        published_keys = {k.key_code: list(k.columns) for k in latest.keys}
        assert published_keys["payment_segment_pk"] == ["djh", "bdqsrq", "bdjzrq"]

    def test_heal_idempotent_when_already_correct(self, store):
        registry = SemanticRegistry(store)
        _seed_settlement_query_model(store)
        registry.publish_object("inpatient_settlement", changelog="v1")

        assert ensure_inpatient_query_model_columns(store, registry) == []
        assert ensure_inpatient_query_model_columns(store, registry) == []
        assert len(store.list_object_versions("inpatient_settlement")) == 1, "幂等：不重发布"
