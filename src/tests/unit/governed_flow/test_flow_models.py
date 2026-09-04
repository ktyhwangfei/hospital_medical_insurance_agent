"""Flow DSL 契约测试：节点白名单、状态机、content_hash、字段级约束（Phase 0 冻结）。"""
import pytest
from pydantic import ValidationError

from src.domain.governed_flow.models import (
    FLOW_ERROR_CODES,
    FLOW_STATUS_TRANSITIONS,
    AggregateMeasure,
    AggregateOperator,
    ConsumerKind,
    FlowDefinition,
    FlowFilterCondition,
    FlowNodeType,
    FlowStatus,
    FilterOperator,
    transition_flow_status,
    compute_flow_content_hash,
    FlowNotFoundError,
    FlowRevisionConflictError,
    FlowStateInvalidError,
)
from src.tests.unit.governed_flow.golden_flow import build_golden_flow


class TestNodeWhitelist:
    def test_node_type_enum_frozen_eight(self):
        assert {t.value for t in FlowNodeType} == {
            "source", "filter", "join", "aggregate",
            "derived_metric", "dimension", "quality_gate", "consumer",
        }

    def test_aggregate_operator_whitelist(self):
        assert {op.value for op in AggregateOperator} == {
            "count", "count_distinct", "sum", "avg",
        }

    def test_unknown_node_type_rejected(self):
        flow = build_golden_flow()
        payload = flow.model_dump()
        payload["nodes"][0]["node_type"] = "script_executor"
        with pytest.raises(ValidationError):
            FlowDefinition.model_validate(payload)

    def test_count_distinct_requires_distinct_key(self):
        with pytest.raises(ValidationError):
            AggregateMeasure(
                output_code="op_cnt", source_field="T_TradeNo",
                operator=AggregateOperator.COUNT_DISTINCT,
            )

    def test_count_distinct_with_distinct_key_ok(self):
        measure = AggregateMeasure(
            output_code="op_cnt", source_field="T_TradeNo",
            operator=AggregateOperator.COUNT_DISTINCT, distinct_key="T_TradeNo",
        )
        assert measure.distinct_key == "T_TradeNo"


class TestFilterConditionContract:
    def test_eq_requires_value(self):
        with pytest.raises(ValidationError):
            FlowFilterCondition(field_code="T_State", operator=FilterOperator.EQ)

    def test_is_null_rejects_value(self):
        with pytest.raises(ValidationError):
            FlowFilterCondition(field_code="x", operator=FilterOperator.IS_NULL, value=1)

    def test_in_requires_list(self):
        with pytest.raises(ValidationError):
            FlowFilterCondition(field_code="T_State", operator=FilterOperator.IN, value=2)

    def test_in_or_null_accepts_list(self):
        condition = FlowFilterCondition(
            field_code="T_CureType", operator=FilterOperator.IN_OR_NULL,
            value=[11, 17], value_domain="MZ_CURE_TYPE",
        )
        assert condition.operator == FilterOperator.IN_OR_NULL


class TestStateMachine:
    def test_legal_full_path(self):
        states = [FlowStatus.DRAFT, FlowStatus.VALIDATING, FlowStatus.PENDING_REVIEW,
                  FlowStatus.PUBLISHED, FlowStatus.DEPRECATED]
        for current, target in zip(states, states[1:]):
            assert transition_flow_status(current, target) == target

    def test_draft_cannot_publish_directly(self):
        with pytest.raises(FlowStateInvalidError):
            transition_flow_status(FlowStatus.DRAFT, FlowStatus.PUBLISHED)

    def test_published_can_only_deprecate(self):
        assert FLOW_STATUS_TRANSITIONS[FlowStatus.PUBLISHED] == frozenset({FlowStatus.DEPRECATED})

    def test_deprecated_is_terminal(self):
        assert FLOW_STATUS_TRANSITIONS[FlowStatus.DEPRECATED] == frozenset()

    def test_review_reject_back_to_draft(self):
        assert transition_flow_status(FlowStatus.PENDING_REVIEW, FlowStatus.DRAFT) == FlowStatus.DRAFT


class TestContentHash:
    def test_hash_stable_across_instances(self):
        assert compute_flow_content_hash(build_golden_flow()) == compute_flow_content_hash(build_golden_flow())

    def test_hash_is_sha256_hex(self):
        value = compute_flow_content_hash(build_golden_flow())
        assert len(value) == 64 and int(value, 16) >= 0

    def test_caliber_change_changes_hash(self):
        flow = build_golden_flow()
        tampered = flow.model_copy(deep=True)
        tampered.metric_outputs[0].policy_definition += " AND extra"
        assert compute_flow_content_hash(tampered) != compute_flow_content_hash(flow)

    def test_position_and_lifecycle_fields_excluded_from_hash(self):
        flow = build_golden_flow()
        moved = flow.model_copy(deep=True)
        moved.nodes[0].position.x = 9999
        moved.revision = 42
        moved.status = FlowStatus.PUBLISHED
        assert compute_flow_content_hash(moved) == compute_flow_content_hash(flow)

    def test_node_order_does_not_change_hash(self):
        flow = build_golden_flow()
        reordered = flow.model_copy(deep=True)
        reordered.nodes.reverse()
        assert compute_flow_content_hash(reordered) == compute_flow_content_hash(flow)


class TestErrorCodes:
    def test_frozen_codes_complete(self):
        # 校验器实际发出的错误码必须都在冻结清单内（防新增逃逸）
        expected = {
            "FLOW_NODE_DUPLICATE", "FLOW_EDGE_DANGLING", "FLOW_GRAPH_CYCLE",
            "FLOW_NODE_TYPE_INVALID", "FLOW_SOURCE_INVALID", "FLOW_CONSUMER_INVALID",
            "FLOW_FIELD_NOT_IN_CONTRACT", "FLOW_DATASET_NOT_REGISTERED",
            "FLOW_RELATION_NOT_REGISTERED", "FLOW_OPERATOR_INVALID",
            "FLOW_EXPRESSION_INVALID", "FLOW_DEPENDENCY_NOT_PUBLISHED",
            "FLOW_VALUE_NOT_IN_DOMAIN", "FLOW_CURE_TYPE_DOMAIN_INVALID",
            "FLOW_METRIC_OUTPUT_NODE_INVALID", "FLOW_CALIBER_MISSING",
            "FLOW_CALIBER_NOT_SIGNED", "FLOW_IDENTITY_TARGET_INVALID",
            "FLOW_CONSUMES_UNKNOWN_METRIC", "FLOW_MATERIALIZATION_UNSUPPORTED",
            "FLOW_NOT_FOUND", "FLOW_REVISION_CONFLICT", "FLOW_STATE_INVALID",
        }
        assert expected <= FLOW_ERROR_CODES

    def test_exceptions_hierarchy(self):
        assert issubclass(FlowStateInvalidError, ValueError)
        assert issubclass(FlowRevisionConflictError, ValueError)
        assert issubclass(FlowNotFoundError, LookupError)


class TestConsumerKinds:
    def test_consumer_kind_whitelist(self):
        assert {k.value for k in ConsumerKind} == {
            "query_planner", "skill", "dashboard_card", "weekly_report", "assistant",
        }
