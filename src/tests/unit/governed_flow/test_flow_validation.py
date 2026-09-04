"""Flow 图与契约校验测试：白名单拒绝、fail closed 与 #62 Golden Flow 基准（Phase 0）。"""
import pytest

from src.domain.governed_flow.models import (
    ConsumerKind,
    ConsumerNode,
    MaterializationStrategy,
)
from src.domain.governed_flow.validation import (
    FlowValidationContext,
    validate_derived_expression,
    validate_flow_definition,
    validate_flow_for_publish,
)
from src.tests.unit.governed_flow.golden_flow import (
    CALIBER_V4,
    build_golden_flow,
    golden_validation_context,
)


class TestGoldenFlow:
    def test_golden_flow_validates_without_registry_context(self):
        report = validate_flow_definition(build_golden_flow())
        assert not report.has_blocking, [i.model_dump() for i in report.issues]

    def test_golden_flow_passes_publish_gate_with_signed_caliber(self):
        report = validate_flow_for_publish(build_golden_flow(), golden_validation_context())
        assert not report.has_blocking, [i.model_dump() for i in report.issues]

    def test_unsigned_caliber_blocks_publish_fail_closed(self):
        context = FlowValidationContext(signed_calibers={"另一条已签核口径句"})
        report = validate_flow_for_publish(build_golden_flow(), context)
        assert report.has_blocking
        assert "FLOW_CALIBER_NOT_SIGNED" in report.codes

    def test_empty_signed_set_skips_gate(self):
        # 集合为空=调用方未提供签核事实，跳过检查（Phase 1 服务层必须提供）
        report = validate_flow_for_publish(build_golden_flow(), FlowValidationContext())
        assert "FLOW_CALIBER_NOT_SIGNED" not in report.codes


class TestGraphRules:
    def test_cycle_detected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.edges.append(
            tampered.edges[0].model_copy(update={"edge_id": "e_back", "from_node": "consumer_qp", "to_node": "src_trade"})
        )
        report = validate_flow_definition(tampered)
        assert "FLOW_GRAPH_CYCLE" in report.codes

    def test_dangling_edge_detected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.edges.append(
            tampered.edges[0].model_copy(update={"edge_id": "e_bad", "to_node": "not_exist"})
        )
        report = validate_flow_definition(tampered)
        assert "FLOW_EDGE_DANGLING" in report.codes

    def test_duplicate_node_id_detected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.nodes.append(tampered.nodes[0].model_copy(deep=True))
        report = validate_flow_definition(tampered)
        assert "FLOW_NODE_DUPLICATE" in report.codes

    def test_source_with_incoming_edge_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.edges.append(
            tampered.edges[0].model_copy(update={"edge_id": "e_into_src", "from_node": "filter_valid", "to_node": "src_trade"})
        )
        report = validate_flow_definition(tampered)
        assert "FLOW_SOURCE_INVALID" in report.codes

    def test_missing_consumer_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.nodes = [n for n in tampered.nodes if n.node_id != "consumer_qp"]
        tampered.edges = [e for e in tampered.edges if e.to_node != "consumer_qp"]
        report = validate_flow_definition(tampered)
        assert "FLOW_CONSUMER_INVALID" in report.codes

    def test_consumer_with_outgoing_edge_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        # 加一个游离 source 供 consumer 指向（避免 dangling 干扰断言）
        tampered.edges.append(
            tampered.edges[0].model_copy(update={"edge_id": "e_out", "from_node": "consumer_qp", "to_node": "gate_caliber"})
        )
        report = validate_flow_definition(tampered)
        assert "FLOW_CONSUMER_INVALID" in report.codes


class TestContractRules:
    def test_field_outside_contract_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.nodes[1].conditions[0].field_code = "T_SecretColumn"
        report = validate_flow_definition(tampered)
        assert "FLOW_FIELD_NOT_IN_CONTRACT" in report.codes

    def test_unregistered_dataset_rejected_when_context_provided(self):
        context = FlowValidationContext(registered_datasets={"other_ds"})
        report = validate_flow_definition(build_golden_flow(), context)
        assert "FLOW_DATASET_NOT_REGISTERED" in report.codes

    def test_unregistered_join_relation_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        from src.domain.governed_flow.models import JoinNode
        join = JoinNode(node_id="join_fee", name="关联费用明细", relation_code="rel_not_registered")
        tampered.nodes.append(join)
        report = validate_flow_definition(tampered, FlowValidationContext(registered_relations={"rel_ok"}))
        assert "FLOW_RELATION_NOT_REGISTERED" in report.codes

    def test_cure_type_without_mz_domain_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.nodes[1].conditions[4].value_domain = None
        report = validate_flow_definition(tampered)
        assert "FLOW_CURE_TYPE_DOMAIN_INVALID" in report.codes

    def test_cure_type_with_wrong_domain_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.nodes[1].conditions[4].value_domain = "med_type"  # 两域不混用
        report = validate_flow_definition(tampered)
        assert "FLOW_CURE_TYPE_DOMAIN_INVALID" in report.codes

    def test_value_outside_declared_domain_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.nodes[1].conditions[4].value = [11, 99]  # 99 不在 MZ_CURE_TYPE
        report = validate_flow_definition(tampered, golden_validation_context())
        assert "FLOW_VALUE_NOT_IN_DOMAIN" in report.codes

    def test_consume_unknown_metric_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        consumer = [n for n in tampered.nodes if isinstance(n, ConsumerNode)][0]
        consumer.consumes.append("op_not_produced")
        report = validate_flow_definition(tampered)
        assert "FLOW_CONSUMES_UNKNOWN_METRIC" in report.codes

    def test_identity_target_missing_rejected(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        gate = [n for n in tampered.nodes if n.node_id == "gate_caliber"][0]
        gate.checks[1].params["left"] = "op_unknown_metric"
        report = validate_flow_definition(tampered)
        assert "FLOW_IDENTITY_TARGET_INVALID" in report.codes

    def test_unsupported_materialization_rejected(self):
        flow = build_golden_flow()
        # model_copy 不校验，模拟未来枚举扩张时的防御检查
        tampered = flow.model_copy(update={"materialization": "materialized_table"})
        report = validate_flow_definition(tampered)
        assert "FLOW_MATERIALIZATION_UNSUPPORTED" in report.codes


class TestDerivedExpression:
    def test_valid_arithmetic(self):
        assert validate_derived_expression("a - b - c", ["a", "b", "c"]) is None

    def test_function_call_rejected(self):
        error = validate_derived_expression("eval('x')", [])
        assert error is not None

    def test_import_rejected(self):
        error = validate_derived_expression("__import__('os')", [])
        assert error is not None

    def test_undeclared_variable_rejected(self):
        error = validate_derived_expression("a + b", ["a"])
        assert error is not None and "b" in error

    def test_string_constant_rejected(self):
        error = validate_derived_expression("'x' + 1", [])
        assert error is not None

    def test_syntax_error_reported(self):
        assert validate_derived_expression("a +", ["a"]) is not None

    def test_dependency_not_published_blocks_when_context_provided(self):
        flow = build_golden_flow()
        from src.domain.governed_flow.models import DerivedMetricNode, DerivedMetricSpec
        derived = DerivedMetricNode(
            node_id="derived_avg",
            name="次均费用（口径未定，禁发布）",
            metrics=[DerivedMetricSpec(
                output_code="op_avg_fee_draft",
                expression="op_total_fee / op_valid_settle_count",
                dependencies=["op_total_fee", "op_valid_settle_count"],
            )],
        )
        tampered = flow.model_copy(deep=True)
        tampered.nodes.append(derived)
        context = FlowValidationContext(published_metrics={"op_other"})
        report = validate_flow_definition(tampered, context)
        assert "FLOW_DEPENDENCY_NOT_PUBLISHED" in report.codes

    def test_published_dependency_passes(self):
        flow = build_golden_flow()
        from src.domain.governed_flow.models import DerivedMetricNode, DerivedMetricSpec
        derived = DerivedMetricNode(
            node_id="derived_avg",
            name="次均费用（口径未定，禁发布）",
            metrics=[DerivedMetricSpec(
                output_code="op_avg_fee_draft",
                expression="op_total_fee / op_valid_settle_count",
                dependencies=["op_total_fee", "op_valid_settle_count"],
            )],
        )
        tampered = flow.model_copy(deep=True)
        tampered.nodes.append(derived)
        context = FlowValidationContext(
            published_metrics={"op_total_fee", "op_valid_settle_count"},
        )
        report = validate_flow_definition(tampered, context)
        assert "FLOW_DEPENDENCY_NOT_PUBLISHED" not in report.codes
