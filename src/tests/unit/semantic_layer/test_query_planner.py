import pytest
import re

from src.semantic_layer.models import (
    BusinessObjectVersion,
    DataQualityRule,
    DatasetKey,
    DatasetRelation,
    Metric,
    ObjectVersionMetric,
    SemanticDataset,
    SemanticField,
)
from src.semantic_layer.query_planner import (
    QueryAnchor,
    QueryFilter,
    QueryOrder,
    QueryScope,
    SemanticQuery,
    SemanticQueryPlanner,
    SemanticQueryPlanningError,
    SemanticQueryService,
)
from src.semantic_layer.registry import InMemoryRegistryStore, SemanticRegistry
from src.semantic_layer.seed import seed_semantic_layer


@pytest.fixture
def registry():
    store = InMemoryRegistryStore()
    seed_semantic_layer(store)
    registry = SemanticRegistry(store)
    registry.publish_object("inpatient_settlement")
    return registry


def _whole_admission_query(**updates):
    payload = {
        "object_code": "inpatient_settlement",
        "scope": QueryScope(
            entity_code="inpatient_admission",
            anchor=QueryAnchor(
                field_code="inpatient_registration.registration_id",
                value="1671213",
            ),
        ),
        "metrics": [
            "total_amount",
            "medical_insurance_inner_amount",
            "basic_pooling_payment",
            "basic_pooling_self_pay",
        ],
    }
    payload.update(updates)
    return SemanticQuery(**payload)


def _outpatient_registry(metric_permission: dict[str, str] | None = None):
    metric_permission = metric_permission or {}
    store = InMemoryRegistryStore()
    datasets = [
        SemanticDataset(
            dataset_code="mz_trade", object_code="mzjyxx", datasource_id="bjybdb",
            table_name="o_Trade", name="门诊交易", status="published",
        ),
        SemanticDataset(
            dataset_code="mz_fee_item", object_code="mzjyxx", datasource_id="bjybdb",
            table_name="o_FeeItem", name="门诊费用明细", status="published",
        ),
    ]
    keys = [
        DatasetKey(
            key_code="mz_trade_pk", dataset_code="mz_trade",
            entity_code="outpatient_transaction", key_type="primary", columns=["T_TradeNo"],
        ),
        DatasetKey(
            key_code="mz_settlement_key", dataset_code="mz_trade",
            entity_code="outpatient_settlement", key_type="unique", columns=["T_SetTid"],
        ),
        DatasetKey(
            key_code="mz_fee_item_pk", dataset_code="mz_fee_item",
            entity_code="outpatient_fee_item", key_type="primary",
            columns=["T_TradeNo", "ItemId", "ItemNo"],
        ),
        DatasetKey(
            key_code="mz_fee_item_trade_fk", dataset_code="mz_fee_item",
            entity_code="outpatient_transaction", key_type="foreign", columns=["T_TradeNo"],
        ),
    ]
    fields = [
        SemanticField(
            field_code="mz_trade.settlement_id", dataset_code="mz_trade",
            column_name="T_SetTid", name="结算标识", field_role="identifier",
            semantic_type="String", nullable=False, status="published",
        ),
        SemanticField(
            field_code="mz_trade.trade_no", dataset_code="mz_trade",
            column_name="T_TradeNo", name="交易号", field_role="identifier",
            semantic_type="String", nullable=False, status="published",
        ),
        SemanticField(
            field_code="mz_trade.total_amount", dataset_code="mz_trade",
            column_name="T_FeeAll", name="费用总金额", field_role="fact",
            semantic_type="Amount", status="published",
        ),
        SemanticField(
            field_code="mz_fee_item.trade_no", dataset_code="mz_fee_item",
            column_name="T_TradeNo", name="交易号", field_role="identifier",
            semantic_type="String", nullable=False, status="published",
        ),
        SemanticField(
            field_code="mz_fee_item.item_id", dataset_code="mz_fee_item",
            column_name="ItemId", name="项目标识", field_role="identifier",
            semantic_type="String", nullable=False, status="published",
        ),
        SemanticField(
            field_code="mz_fee_item.item_no", dataset_code="mz_fee_item",
            column_name="ItemNo", name="项目序号", field_role="identifier",
            semantic_type="String", nullable=False, status="published",
        ),
        SemanticField(
            field_code="mz_fee_item.item_name", dataset_code="mz_fee_item",
            column_name="ItemName", name="项目名称", field_role="dimension",
            semantic_type="String", status="published",
        ),
        SemanticField(
            field_code="mz_fee_item.item_fee", dataset_code="mz_fee_item",
            column_name="Fee", name="项目金额", field_role="fact",
            semantic_type="Amount", status="published",
        ),
    ]
    relation = DatasetRelation(
        relation_code="mz_trade_to_fee_item", object_code="mzjyxx",
        from_dataset="mz_trade", from_key="mz_trade_pk",
        to_dataset="mz_fee_item", to_key="mz_fee_item_trade_fk",
        cardinality="one_to_many", status="published",
    )
    metrics = [
        ObjectVersionMetric.from_metric(
            Metric(
                metric_code="mzjyxx.total_amount", object_code="mzjyxx", name="费用总金额",
                fact_field_code="mz_trade.total_amount", aggregation="max", status="published",
            ).model_copy(update={"permission_level": metric_permission.get("total_amount")})
            if metric_permission.get("total_amount")
            else Metric(
                metric_code="mzjyxx.total_amount", object_code="mzjyxx", name="费用总金额",
                fact_field_code="mz_trade.total_amount", aggregation="max", status="published",
            ),
        ),
        ObjectVersionMetric.from_metric(
            Metric(
                metric_code="mzjyxx.item_fee", object_code="mzjyxx", name="项目金额",
                fact_field_code="mz_fee_item.item_fee", aggregation="sum", status="published",
            ).model_copy(update={"permission_level": metric_permission.get("item_fee")})
            if metric_permission.get("item_fee")
            else Metric(
                metric_code="mzjyxx.item_fee", object_code="mzjyxx", name="项目金额",
                fact_field_code="mz_fee_item.item_fee", aggregation="sum", status="published",
            ),
        ),
    ]
    rules = [
        DataQualityRule(
            rule_code="mz_fee_item_coverage", object_code="mzjyxx", rule_type="coverage",
            target_dataset_or_relation=relation.relation_code, severity="warning",
            parameters={"reference_dataset": "mz_fee_item"}, status="published",
        ),
        DataQualityRule(
            rule_code="mz_trade_unique", object_code="mzjyxx", rule_type="uniqueness",
            target_dataset_or_relation="mz_trade", severity="blocking",
            parameters={"key_code": "mz_trade_pk"}, status="published",
        ),
        DataQualityRule(
            rule_code="mz_fee_item_unique", object_code="mzjyxx", rule_type="uniqueness",
            target_dataset_or_relation="mz_fee_item", severity="blocking",
            parameters={"key_code": "mz_fee_item_pk"}, status="published",
        ),
    ]
    store.save_object_version(BusinessObjectVersion(
        version_id="mzjyxx-v1", object_code="mzjyxx", version="1",
        snapshot={"object_code": "mzjyxx"}, metrics=metrics, datasets=datasets,
        keys=keys, fields=fields, relations=[relation], quality_rules=rules,
    ))
    return SemanticRegistry(store)


def _outpatient_query(scope, metrics, **updates):
    payload = {
        "object_code": "mzjyxx",
        "scope": QueryScope(
            entity_code="outpatient_settlement",
            anchor=QueryAnchor(field_code="mz_trade.settlement_id", value="SET-001"),
            query_scope=scope,
        ),
        "metrics": metrics,
    }
    payload.update(updates)
    return SemanticQuery(**payload)


def test_admission_anchor_builds_two_preaggregated_fact_branches(registry):
    plan = SemanticQueryPlanner(registry).plan(_whole_admission_query())

    assert plan.scope.entity == "inpatient_admission"
    assert plan.scope.anchor_field == "inpatient_registration.registration_id"
    assert plan.query_scope == "whole_admission"
    assert plan.result_grain == ["inpatient_admission"]
    assert plan.common_grain == [
        "inpatient_admission",
        "fiscal_year",
        "segment_start_date",
    ]
    assert {branch.dataset for branch in plan.branches} == {
        "benefit_segments",
        "payment_segments",
    }
    assert all(branch.preaggregate_before_join for branch in plan.branches)
    assert any(join.left == "segment_spine" and join.right == "payment_segments" for join in plan.joins)
    assert "payment_segments_cover_segment_spine" in plan.quality_checks


def test_compiler_uses_bind_parameter_and_never_embeds_anchor(registry):
    compiled = SemanticQueryPlanner(registry).compile(_whole_admission_query())

    assert "1671213" not in compiled.sql
    assert compiled.params["anchor_value"] == "1671213"
    assert "benefit_segments" in compiled.sql
    assert "payment_segments" in compiled.sql
    assert compiled.sql.index("benefit_segments AS") < compiled.sql.index("joined_segments AS")
    assert compiled.sql.index("payment_segments AS") < compiled.sql.index("joined_segments AS")


def test_result_quality_reports_all_segments_and_totals(registry):
    planner = SemanticQueryPlanner(registry)
    result = planner.result_from_row(
        _whole_admission_query(),
        planner.plan(_whole_admission_query()),
        {
            "total_amount": 189085.85,
            "medical_insurance_inner_amount": 164411.81,
            "basic_pooling_payment": 145391.22,
            "basic_pooling_self_pay": 4962.67,
            "_anchor_count": 1,
            "_segment_count": 2,
            "_matched_segment_count": 2,
            "_extra_segment_count": 0,
            "_benefit_duplicate_count": 0,
            "_payment_duplicate_count": 0,
        },
        duration_ms=12,
    )

    assert result.quality_status == "complete"
    assert result.rows[0]["total_amount"] == 189085.85
    assert result.evidence.segment_count == 2
    assert result.evidence.matched_segment_count == 2
    assert result.query_scope == "whole_admission"


def test_missing_segment_is_partial_not_silently_complete(registry):
    planner = SemanticQueryPlanner(registry)
    query = _whole_admission_query()
    result = planner.result_from_row(
        query,
        planner.plan(query),
        {
            "total_amount": 100.0,
            "_anchor_count": 1,
            "_segment_count": 2,
            "_matched_segment_count": 1,
            "_extra_segment_count": 0,
            "_benefit_duplicate_count": 0,
            "_payment_duplicate_count": 0,
        },
        duration_ms=1,
    )

    assert result.quality_status == "partial"
    assert result.evidence.segment_count == 2
    assert result.evidence.matched_segment_count == 1
    assert result.warnings


def test_duplicate_segment_key_is_unavailable(registry):
    planner = SemanticQueryPlanner(registry)
    query = _whole_admission_query()
    result = planner.result_from_row(
        query,
        planner.plan(query),
        {
            "_anchor_count": 1,
            "_segment_count": 2,
            "_matched_segment_count": 2,
            "_extra_segment_count": 0,
            "_benefit_duplicate_count": 1,
            "_payment_duplicate_count": 0,
        },
        duration_ms=1,
    )

    assert result.quality_status == "unavailable"
    assert result.rows == []


def test_ambiguous_relation_path_is_blocked(registry):
    store = registry._store
    store.save_dataset_key(DatasetKey(
        key_code="payment_admission_fk",
        dataset_code="payment_segments",
        entity_code="inpatient_admission",
        key_type="foreign",
        columns=["djh"],
    ))
    store.save_dataset_relation(DatasetRelation(
        relation_code="registration_direct_to_payment",
        object_code="inpatient_settlement",
        from_dataset="inpatient_registration",
        from_key="registration_pk",
        to_dataset="payment_segments",
        to_key="payment_admission_fk",
        cardinality="one_to_many",
    ))
    with pytest.raises(ValueError, match="歧义"):
        registry.publish_object("inpatient_settlement")


def test_non_additive_metric_requires_restricted_dimension(registry):
    metric = registry._store.get_metric("inpatient_settlement.total_amount")
    metric.non_additive_dimensions = ["benefit_segments.segment_start_date"]
    registry._store.save_metric(metric)
    with pytest.raises(ValueError, match="不可加"):
        registry.publish_object("inpatient_settlement")


def test_derived_metric_compiles_from_registered_dependencies(registry):
    registry._store.save_metric(Metric(
        metric_code="inpatient_settlement.personal_gap",
        object_code="inpatient_settlement",
        name="费用差额",
        metric_type="derived",
        expression="total_amount - basic_pooling_payment",
        dependencies=["total_amount", "basic_pooling_payment"],
    ))
    registry.publish_object("inpatient_settlement")

    compiled = SemanticQueryPlanner(registry).compile(
        _whole_admission_query(metrics=["personal_gap"])
    )

    assert "personal_gap" in compiled.sql
    assert "total_amount" in compiled.sql
    assert "basic_pooling_payment" in compiled.sql


def test_group_filter_order_and_limit_are_compiled_from_registered_fields(registry):
    compiled = SemanticQueryPlanner(registry).compile(_whole_admission_query(
        group_by=["benefit_segments.segment_start_date"],
        filters=[QueryFilter(
            field_code="benefit_segments.segment_end_date",
            operator="gte",
            value="2025-01-01",
        )],
        order_by=[QueryOrder(field_code="total_amount", direction="desc")],
        limit=10,
    ))

    assert "GROUP BY" in compiled.sql
    assert "ORDER BY" in compiled.sql
    assert "2025-01-01" not in compiled.sql
    assert "2025-01-01" in compiled.params.values()


def test_filter_on_non_scope_fact_dataset_fails_closed(registry):
    with pytest.raises(SemanticQueryPlanningError, match="只允许锚点或 coverage"):
        SemanticQueryPlanner(registry).compile(_whole_admission_query(
            filters=[QueryFilter(
                field_code="payment_segments.total_amount",
                operator="gt",
                value=0,
            )],
        ))


def test_explicit_segment_scope_groups_by_registered_segment_key(registry):
    query = _whole_admission_query(scope=QueryScope(
        entity_code="inpatient_admission",
        anchor=QueryAnchor(
            field_code="inpatient_registration.registration_id",
            value="1671213",
        ),
        query_scope="segment",
    ))

    compiled = SemanticQueryPlanner(registry).compile(query)

    assert compiled.plan.result_grain == ["admission_segment"]
    assert "segment_start_date" in compiled.sql
    assert "GROUP BY" in compiled.sql

    planner = SemanticQueryPlanner(registry)
    result = planner.result_from_rows(query, compiled.plan, [
        {"segment_start_date": "2025-01-01", "total_amount": 100,
         "_anchor_count": 1, "_segment_count": 2, "_matched_segment_count": 2,
         "_extra_segment_count": 0, "_benefit_duplicate_count": 0, "_payment_duplicate_count": 0},
        {"segment_start_date": "2025-04-01", "total_amount": 200,
         "_anchor_count": 1, "_segment_count": 2, "_matched_segment_count": 2,
         "_extra_segment_count": 0, "_benefit_duplicate_count": 0, "_payment_duplicate_count": 0},
    ], duration_ms=1)
    assert [row["total_amount"] for row in result.rows] == [100, 200]


def test_sample_anchor_reads_one_non_null_value_from_published_identifier(registry):
    class Cursor:
        sql = ""

        def execute(self, sql, *values):
            self.sql = sql
            self.values = values

        def fetchone(self):
            return ("1671213",)

    class Connection:
        def __init__(self):
            self.cursor_instance = Cursor()
            self.closed = False

        def cursor(self):
            return self.cursor_instance

        def close(self):
            self.closed = True

    connection = Connection()

    value = SemanticQueryService(registry, lambda _datasource_id: connection).sample_anchor(
        "inpatient_settlement",
        "inpatient_admission",
        "inpatient_registration.registration_id",
    )

    assert value == "1671213"
    assert "NEWID" in connection.cursor_instance.sql.upper()
    assert connection.closed is True


def test_sample_anchor_rejects_field_that_cannot_locate_entity(registry):
    connected = False

    def connect(_datasource_id):
        nonlocal connected
        connected = True

    with pytest.raises(SemanticQueryPlanningError, match="identifier"):
        SemanticQueryService(registry, connect).sample_anchor(
            "inpatient_settlement",
            "inpatient_admission",
            "payment_segments.total_amount",
        )

    assert connected is False


def test_outpatient_whole_settlement_compiles_from_anchor_dataset():
    compiled = SemanticQueryPlanner(_outpatient_registry()).compile(
        _outpatient_query("whole_settlement", ["total_amount"])
    )

    assert compiled.plan.result_grain == ["outpatient_settlement"]
    assert "SET-001" not in compiled.sql
    assert compiled.params["anchor_value"] == "SET-001"
    assert "o_Trade" in compiled.sql


def test_outpatient_fee_items_compile_at_registered_detail_grain():
    query = _outpatient_query(
        "fee_item", ["item_fee"], group_by=["mz_fee_item.item_name"],
    )

    compiled = SemanticQueryPlanner(_outpatient_registry()).compile(query)

    assert compiled.plan.result_grain == ["outpatient_fee_item"]
    assert "o_FeeItem" in compiled.sql
    assert "GROUP BY" in compiled.sql


def test_outpatient_missing_fee_items_is_partial():
    planner = SemanticQueryPlanner(_outpatient_registry())
    query = _outpatient_query(
        "fee_item", ["item_fee"], group_by=["mz_fee_item.item_name"],
    )
    plan = planner.plan(query)

    result = planner.result_from_rows(query, plan, [{
        "_anchor_count": 1,
        "_reference_count": 0,
        "_matched_reference_count": 0,
        "_extra_reference_count": 0,
        "_detail_duplicate_count": 0,
    }], duration_ms=1)

    assert result.quality_status == "partial"
    assert result.rows == []


def test_deferred_outpatient_metric_is_rejected_as_unavailable():
    """#36 缺口1：请求口径未定的暂缓指标(次均费用)在解析阶段即被拒，带回原消息。

    就医人次/次均费用与 insured_encounter_count 口诀暂未落地前绝不可进入任何查询，
    拒绝原因须可读（含「就诊人次口径未定」），而非落入「未发布于查询模型」的泛化误报。
    """
    planner = SemanticQueryPlanner(_outpatient_registry())
    for code in ("average_fee", "mzjyxx.average_fee", "insured_encounter_count"):
        with pytest.raises(SemanticQueryPlanningError, match="就诊人次口径未定"):
            planner.compile(_outpatient_query("whole_settlement", [code]))


def test_summary_permission_metric_rejects_ungrouped_detail_rows():
    """#36 缺口2：permission_level=summary 的指标只在分组聚合后可用，禁止明细行输出。

    item_fee 标 summary → fee_item 明细查询不分组(逐行明细) → 拒绝；带 group_by 聚合 → 放行。
    """
    planner = SemanticQueryPlanner(_outpatient_registry(metric_permission={"item_fee": "summary"}))

    # 无 group_by → 明细行 → 拒绝
    with pytest.raises(SemanticQueryPlanningError, match="仅授权汇总口径"):
        planner.compile(_outpatient_query("fee_item", ["item_fee"]))
    # 有 group_by → 分组聚合 → 放行
    compiled = planner.compile(
        _outpatient_query("fee_item", ["item_fee"], group_by=["mz_fee_item.item_name"])
    )
    assert compiled is not None


def test_public_permission_metric_still_allows_detail_rows():
    """对照：非 summary 的指标明细查询不受限（缺缺2不漏放也勿误杀）。"""
    planner = SemanticQueryPlanner(_outpatient_registry(metric_permission={"item_fee": "detail"}))
    compiled = planner.compile(_outpatient_query("fee_item", ["item_fee"]))
    assert compiled is not None


def test_compile_exit_sql_is_readonly_select_whitelist():
    """#36 缺口3：compile 出口 SQL 白名单终检——只产出只读 SELECT 聚合(无 DML/注释/分号)。"""
    planner = SemanticQueryPlanner(_outpatient_registry())
    compiled = planner.compile(_outpatient_query("whole_settlement", ["total_amount"]))
    sql = compiled.sql
    # 允许 WITH…SELECT 的只读 CTE 形态(planner 聚合走 CTE)；仍必须是 SELECT 系只读
    assert bool(re.match(r"(?is)^\s*(WITH\b|SELECT\b)", sql))
    low = sql.lower()
    for kw in ("insert", "update", "delete", "drop", "alter", "drop table", ";", "--", "/*"):
        assert kw not in sql.lower()
    # 直接验证 dml 字符串被守卫拦下
    for bad in ("UPDATE x SET y=1", "DELETE FROM x", "INSERT INTO", "DROP TABLE t", "SELECT 1; DROP", "/* leak */ SELECT 1"):
        try:
            planner._assert_read_only_select(bad)
            raise AssertionError(f"未拦截: {bad!r}")
        except SemanticQueryPlanningError:
            pass
