"""Flow 编译器单元测试 — Phase 1。

核心断言：Golden Flow 编译产物与 #62 docs/processing/outpatient_processed_view.sql
的核心 SELECT/WHERE 语义等价（口径句 v4 全部 5 个条件 + 4 个聚合表达式）。
"""
from __future__ import annotations

import pytest

from src.domain.governed_flow.compiler import (
    CompiledFlowArtifact,
    FlowCompileError,
    compile_flow_view,
    compute_artifact_hash,
    derive_view_name,
)
from src.domain.governed_flow.models import (
    AggregateMeasure,
    AggregateNode,
    AggregateOperator,
    DerivedMetricNode,
    DerivedMetricSpec,
    DimensionBinding,
    DimensionNode,
    FilterNode,
    FilterOperator,
    FlowDefinition,
    FlowEdge,
    FlowFilterCondition,
    MetricOutputBinding,
    SourceContract,
    SourceNode,
)
from src.tests.unit.governed_flow.golden_flow import build_golden_flow

# 与 #62 视图一致的数据集解析（语义层种子里 o_trade → dbo.o_Trade，
# 编译器单测直接给最小解析器验证 SQL 等价性）
_GOLDEN_RESOLVER = {"o_trade": "o_Trade"}


def _compile(flow: FlowDefinition) -> CompiledFlowArtifact:
    return compile_flow_view(flow, dataset_resolver=_GOLDEN_RESOLVER.get)


class TestGoldenFlowCompile:
    def test_view_name_derivation(self):
        assert derive_view_name("flow_op_outpatient_processed") == "v_flow_flow_op_outpatient_processed"
        assert derive_view_name("非法 Flow-Id!") == "v_flow_flow_id"

    def test_golden_sql_equivalent_to_62_view(self):
        """编译产物必须携带 #62 视图的全部口径句 v4 条件与 4 个聚合表达式。"""
        artifact = _compile(build_golden_flow())
        sql = artifact.view_sql
        assert sql.startswith("CREATE OR ALTER VIEW v_flow_flow_op_outpatient_processed AS")
        assert "FROM o_Trade" in sql
        # 4 个聚合输出（与 v_op_outpatient_processed SELECT 一致）
        assert "COUNT(DISTINCT T_TradeNo) AS op_valid_settle_count" in sql
        assert "SUM(T_FeeAll) AS op_total_fee" in sql
        assert "SUM(T_FundPay) AS op_fund_pay" in sql
        assert "SUM(T_SelfPayAll) AS op_self_pay" in sql
        # 口径句 v4 全部 5 个条件（WHERE 以 AND 连接）
        assert "T_State IN (2, 3)" in sql
        assert "NP_Settle_State = 1" in sql
        assert "T_HasRefundmented != 1" in sql
        assert "(T_PartialReturnFlag IN ('') OR T_PartialReturnFlag IS NULL)" in sql
        assert "(T_CureType IN (11, 17, 18, 19) OR T_CureType IS NULL)" in sql
        # 全局单行快照：无 GROUP BY
        assert "GROUP BY" not in sql

    def test_query_plan_steps_present(self):
        artifact = _compile(build_golden_flow())
        node_ids = [s.node_id for s in artifact.query_plan]
        assert node_ids == ["src_trade", "filter_valid", "agg_snapshot", "gate_caliber"]
        gate = artifact.query_plan[-1]
        assert "op_total_fee = op_fund_pay + op_self_pay" in gate.description

    def test_artifact_hash_shape_and_determinism(self):
        flow = build_golden_flow()
        first = _compile(flow)
        second = _compile(build_golden_flow())
        assert first.artifact_hash == second.artifact_hash
        assert first.artifact_hash == compute_artifact_hash(first.view_sql)
        assert len(first.artifact_hash) == 64

    def test_content_change_changes_artifact_hash(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        condition = tampered.nodes[1].conditions[0]
        tampered.nodes[1].conditions[0] = condition.model_copy(
            update={"value": [2, 3, 9]}
        )
        assert _compile(tampered).artifact_hash != _compile(flow).artifact_hash


class TestCompileSecurity:
    """威胁模型 T5：标识符/字面量注入面必须全部拒绝。"""

    def test_injection_in_field_code_rejected(self):
        flow = build_golden_flow()
        evil = flow.model_copy(deep=True)
        evil.nodes[1].conditions[0] = FlowFilterCondition(
            field_code="T_State); DROP TABLE o_Trade; --",
            operator=FilterOperator.EQ, value=1,
        )
        with pytest.raises(FlowCompileError) as exc:
            _compile(evil)
        assert exc.value.args[0].startswith("FLOW_EXPRESSION_INVALID")

    def test_string_literal_quote_escaped(self):
        flow = build_golden_flow()
        quoted = flow.model_copy(deep=True)
        quoted.nodes[1].conditions[3] = FlowFilterCondition(
            field_code="T_PartialReturnFlag", operator=FilterOperator.EQ,
            value="'; DELETE FROM users; --",
        )
        artifact = _compile(quoted)
        # 内部单引号翻倍转义：'''= 包裹引号+转义后的内容引号
        assert "T_PartialReturnFlag = '''; DELETE FROM users; --'" in artifact.view_sql

    def test_derived_expression_call_rejected(self):
        flow = _flow_with_derived("__import__('os').system('dir')")
        with pytest.raises(FlowCompileError) as exc:
            _compile(flow)
        assert exc.value.args[0].startswith("FLOW_EXPRESSION_INVALID")

    def test_derived_expression_attribute_rejected(self):
        flow = _flow_with_derived("op_total_fee.__class__")
        with pytest.raises(FlowCompileError):
            _compile(flow)

    def test_derived_arithmetic_rendered(self):
        flow = _flow_with_derived("op_total_fee / op_valid_settle_count")
        artifact = _compile(flow)
        assert "(op_total_fee / op_valid_settle_count) AS avg_fee_per_trade" in artifact.view_sql


class TestCompileBoundaries:
    def test_branching_pipeline_rejected(self):
        flow = build_golden_flow()
        branched = flow.model_copy(deep=True)
        second_agg = branched.nodes[2].model_copy(deep=True)
        second_agg = second_agg.model_copy(update={"node_id": "agg_second"})
        branched.nodes.append(second_agg)
        branched.edges.append(FlowEdge(
            edge_id="e_branch", from_node="filter_valid", to_node="agg_second"
        ))
        with pytest.raises(FlowCompileError) as exc:
            _compile(branched)
        assert exc.value.args[0].startswith("FLOW_COMPILE_UNSUPPORTED")

    def test_join_without_resolver_rejected(self):
        flow = build_golden_flow()
        joined = _flow_with_join(build=False)
        with pytest.raises(FlowCompileError) as exc:
            _compile(joined)
        assert exc.value.args[0].startswith("FLOW_RELATION_NOT_REGISTERED")

    def test_join_with_resolver_renders_clause(self):
        joined = _flow_with_join()
        artifact = compile_flow_view(
            joined,
            dataset_resolver=_GOLDEN_RESOLVER.get,
            join_resolver=lambda code: "o_Trade.T_TradeNo = o_FeeItem.T_TradeNo",
        )
        assert "INNER JOIN <rel_trade_fee> ON o_Trade.T_TradeNo = o_FeeItem.T_TradeNo" in artifact.view_sql

    def test_non_view_materialization_rejected(self):
        flow = build_golden_flow()
        materialized = flow.model_copy(deep=True, update={"materialization": "materialized_table"})
        with pytest.raises(FlowCompileError) as exc:
            _compile(materialized)
        assert exc.value.args[0].startswith("FLOW_MATERIALIZATION_UNSUPPORTED")

    def test_dimension_node_adds_group_by(self):
        grouped = _flow_with_dimension()
        artifact = _compile(grouped)
        assert "GROUP BY T_CureType" in artifact.view_sql


# ── 测试辅助 ──────────────────────────────────────────────────────


def _flow_with_derived(expression: str) -> FlowDefinition:
    """在 golden flow 的 aggregate 与 quality_gate 之间插入派生指标节点（保持线性链）。"""
    flow = build_golden_flow()
    enriched = flow.model_copy(deep=True)
    enriched.nodes.append(DerivedMetricNode(
        node_id="derived_avg", name="次均费用",
        metrics=[DerivedMetricSpec(
            output_code="avg_fee_per_trade", expression=expression,
            dependencies=["op_total_fee"],
        )],
    ))
    # e3 原为 agg_snapshot→gate_caliber，改接派生节点再回到 gate
    enriched.edges = [
        e.model_copy(update={"to_node": "derived_avg"}) if e.edge_id == "e3" else e
        for e in enriched.edges
    ]
    enriched.edges.append(FlowEdge(edge_id="e_derived", from_node="derived_avg", to_node="gate_caliber"))
    return enriched


def _flow_with_join(*, build: bool = True) -> FlowDefinition:
    """在 filter 与 aggregate 之间插入 join 节点（保持线性链）。

    build=False 时仍构造链，但测试不传 join_resolver 以触发未登记拒绝。
    """
    flow = build_golden_flow()
    joined = flow.model_copy(deep=True)
    from src.domain.governed_flow.models import JoinNode
    joined.nodes.append(JoinNode(
        node_id="join_fee", name="关联费用明细", relation_code="rel_trade_fee"
    ))
    # e2 原为 filter_valid→agg_snapshot，改接 join 再回到 aggregate
    joined.edges = [
        e.model_copy(update={"to_node": "join_fee"}) if e.edge_id == "e2" else e
        for e in joined.edges
    ]
    joined.edges.append(FlowEdge(edge_id="e_join", from_node="join_fee", to_node="agg_snapshot"))
    return joined


def _flow_with_dimension() -> FlowDefinition:
    """在 aggregate 与 quality_gate 之间插入维度节点（保持线性链）。"""
    flow = build_golden_flow()
    grouped = flow.model_copy(deep=True)
    grouped.nodes.append(DimensionNode(
        node_id="dim_cure", name="门诊医疗类别维度",
        dimensions=[DimensionBinding(field_code="T_CureType", value_domain="MZ_CURE_TYPE")],
    ))
    grouped.edges = [
        e.model_copy(update={"to_node": "dim_cure"}) if e.edge_id == "e3" else e
        for e in grouped.edges
    ]
    grouped.edges.append(FlowEdge(edge_id="e_dim", from_node="dim_cure", to_node="gate_caliber"))
    return grouped
