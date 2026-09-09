"""Flow DSL 契约测试：节点白名单、状态机、content_hash、字段级约束（Phase 0 冻结）。"""
import pytest
from pydantic import ValidationError

from src.domain.governed_flow.models import (
    FLOW_CALLER_ROLE_LEVELS,
    FLOW_ERROR_CODES,
    FLOW_STATUS_TRANSITIONS,
    MAX_FLOW_EDGES,
    MAX_FLOW_NODES,
    AggregateMeasure,
    AggregateOperator,
    ConsumerKind,
    FlowDefinition,
    FlowFilterCondition,
    FlowNodeType,
    FlowStatus,
    FilterOperator,
    PermissionLevel,
    caller_permission_level,
    transition_flow_status,
    compute_flow_content_hash,
    FlowNotFoundError,
    FlowRevisionConflictError,
    FlowStateInvalidError,
    FlowArtifactMismatchError,
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
            "FLOW_CONSUMES_UNKNOWN_METRIC", "FLOW_MATERIALIZATION_UNSUPPORTED", "FLOW_COMPILE_UNSUPPORTED",
            "FLOW_NOT_FOUND", "FLOW_REVISION_CONFLICT", "FLOW_STATE_INVALID",
            # Phase 3 消费契约接线（24 → 26）
            "FLOW_ARTIFACT_MISMATCH", "FLOW_CONSUME_DIMENSION_FORBIDDEN",
            # Phase 3 指标码驱动消费接入点（26 → 27）
            "FLOW_CONSUME_AMBIGUOUS",
            # T11 消费侧强制：detail 级维度对 summary 调用方拒止（27 → 28）
            "FLOW_CONSUME_DIMENSION_PERMISSION_DENIED",
        }
        assert expected <= FLOW_ERROR_CODES

    def test_exceptions_hierarchy(self):
        assert issubclass(FlowStateInvalidError, ValueError)
        assert issubclass(FlowArtifactMismatchError, FlowStateInvalidError)
        assert issubclass(FlowRevisionConflictError, ValueError)
        assert issubclass(FlowNotFoundError, LookupError)


class TestCallerPermissionLevel:
    """T11 消费侧强制：调用方角色 → 维度权限级别冻结映射。"""

    def test_mapping_covers_all_canonical_roles(self):
        # 角色集合与平台 ALL_ROLES 同源，防止新增角色后映射漏配
        from src.config.security_policy.rules import ALL_ROLES

        assert set(FLOW_CALLER_ROLE_LEVELS) == ALL_ROLES

    def test_detail_roles_are_governance_owners(self):
        # 信息科（治理特权，infra_skill_routes 先例）+ 医保办（医保数据业务主，
        # security_policy 字段可见特权先例）可下钻 detail；其余一律 summary
        detail = {
            role for role, level in FLOW_CALLER_ROLE_LEVELS.items()
            if level == PermissionLevel.DETAIL
        }
        assert detail == {"information_department", "medical_office"}

    def test_unknown_or_missing_role_tightens_to_summary(self):
        assert caller_permission_level(None) == PermissionLevel.SUMMARY
        assert caller_permission_level("") == PermissionLevel.SUMMARY
        assert caller_permission_level("intern") == PermissionLevel.SUMMARY
        assert caller_permission_level("information_department") == PermissionLevel.DETAIL


class TestConsumerKinds:
    def test_consumer_kind_whitelist(self):
        assert {k.value for k in ConsumerKind} == {
            "query_planner", "skill", "dashboard_card", "weekly_report", "assistant",
        }


class TestGraphSizeLimits:
    """T13 大 payload DoS 加固：节点/边数量上限（Phase 0 §4 遗留，Phase 2 补齐）。"""

    @staticmethod
    def _padded_payload(extra_nodes: int, extra_edges: int) -> dict:
        payload = build_golden_flow().model_dump()
        filter_node = next(n for n in payload["nodes"] if n["node_type"] == "filter")
        for i in range(extra_nodes):
            pad = {**filter_node, "node_id": f"filter_pad_{i}"}
            payload["nodes"].append(pad)
        for i in range(extra_edges):
            payload["edges"].append({
                "edge_id": f"e_pad_{i}",
                "from_node": "src_trade", "to_node": "filter_valid",
            })
        return payload

    def test_oversized_nodes_rejected(self):
        payload = self._padded_payload(extra_nodes=MAX_FLOW_NODES, extra_edges=0)
        with pytest.raises(ValidationError):
            FlowDefinition.model_validate(payload)

    def test_oversized_edges_rejected(self):
        payload = self._padded_payload(extra_nodes=0, extra_edges=MAX_FLOW_EDGES)
        with pytest.raises(ValidationError):
            FlowDefinition.model_validate(payload)

    def test_boundary_at_limits_accepted(self):
        # 金标 5 节点/4 边 + 补齐到恰好上限必须可建（上限不是白名单拒绝面）
        payload = self._padded_payload(
            extra_nodes=MAX_FLOW_NODES - 5, extra_edges=MAX_FLOW_EDGES - 4,
        )
        flow = FlowDefinition.model_validate(payload)
        assert len(flow.nodes) == MAX_FLOW_NODES
        assert len(flow.edges) == MAX_FLOW_EDGES
