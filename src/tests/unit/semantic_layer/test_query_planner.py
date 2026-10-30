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


def _outpatient_registry(metric_permission: dict[str, str] | None = None,
                         metric_carrier: dict[str, dict] | None = None):
    metric_permission = metric_permission or {}
    metric_carrier = metric_carrier or {}
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
            field_code="mz_trade.total_fund", dataset_code="mz_trade",
            column_name="T_FundPay", name="统筹基金支付", field_role="fact",
            semantic_type="Amount", status="published",
        ),
        SemanticField(
            field_code="mz_trade.total_self", dataset_code="mz_trade",
            column_name="T_SelfPayAll", name="个人支付", field_role="fact",
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
        ObjectVersionMetric.from_metric(Metric(
            metric_code="mzjyxx.fund_pay", object_code="mzjyxx", name="统筹基金支付",
            fact_field_code="mz_trade.total_fund", aggregation="max",
            semantic_type="Amount", status="published",
        )),
        ObjectVersionMetric.from_metric(Metric(
            metric_code="mzjyxx.self_pay", object_code="mzjyxx", name="个人支付",
            fact_field_code="mz_trade.total_self", aggregation="max",
            semantic_type="Amount", status="published",
        )),
    ]
    # #60 查询层裁剪用：按指标短名挂 policy_carrier（生效区间）
    for _m in metrics:
        _carrier = metric_carrier.get(_m.metric_code.split(".")[-1])
        if _carrier:
            _m.policy_carrier = _carrier
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


def test_amount_metrics_coquery_preserves_tieout_on_same_grain():
    """#36 缺口4 勾稽保护：总费用/统筹/个人支付同 scope 聚合 → 同口径可复算 总=统筹+个人。

    planner 对同一结算把三金额指标做同一 common_grain 的单表聚合；本测试断言编译只有一个
    branch 覆盖三者 + 口径一致性(总=统筹+个人)可作为结果校验钩子(勾稽不被跨口径拆散)。
    """
    planner = SemanticQueryPlanner(_outpatient_registry())
    query = _outpatient_query(
        "whole_settlement",
        ["total_amount", "fund_pay", "self_pay"],
    )
    plan = planner.plan(query)
    assert len(plan.branches) == 1
    assert plan.branches[0].dataset == "mz_trade"
    agg_metrics = set(plan.branches[0].metrics)
    assert {"total_amount", "fund_pay", "self_pay"} <= agg_metrics
    # 同 scope 口径：勾稽恒等 总费用 = 统筹支付 + 个人支付
    assert plan.common_grain == ["outpatient_settlement"]

    result = planner.result_from_row(query, plan, {
        "total_amount": 100.0, "fund_pay": 70.0, "self_pay": 30.0,
        "_anchor_count": 1,
    }, duration_ms=1)
    row = result.rows[0]
    assert row["total_amount"] == row["fund_pay"] + row["self_pay"] == 100.0


def test_policy_carrier_effective_interval_clips_revoked_and_future_metrics():
    """#60 查询层生效期裁剪：已废止(effective_end<今日)/未生效(effective_start>今日)指标拒查；现行可查。

    日期相对真实「今日」构造，避免冻结时间依赖。
    """
    from datetime import date, timedelta

    yesterday = str(date.today() - timedelta(days=1))
    tomorrow = str(date.today() + timedelta(days=1))
    planner = SemanticQueryPlanner(_outpatient_registry(metric_carrier={
        # 已废止：废止日在昨日
        "fund_pay": {"doc_number": "京医保〔2024〕1号", "region_scope": "北京市",
                     "effective_start": "2024-01-01", "effective_end": yesterday},
        # 未生效：生效起在明日
        "self_pay": {"doc_number": "京医保〔2026〕9号", "region_scope": "北京市",
                     "effective_start": tomorrow},
        # 现行：end=null=现行，可查
        "total_amount": {"doc_number": "京医保〔2024〕1号", "region_scope": "北京市",
                         "effective_start": "2024-01-01"},
    }))

    with pytest.raises(SemanticQueryPlanningError, match="已废止"):
        planner.compile(_outpatient_query("whole_settlement", ["fund_pay"]))
    with pytest.raises(SemanticQueryPlanningError, match="未生效"):
        planner.compile(_outpatient_query("whole_settlement", ["self_pay"]))
    # 现行(end=null)与无承载指标照常编译（item_fee 为明细粒度，按既有口径分组查询）
    assert planner.compile(_outpatient_query("whole_settlement", ["total_amount"]))
    assert planner.compile(_outpatient_query(
        "fee_item", ["item_fee"], group_by=["mz_fee_item.item_name"],
    ))


# ── #78 缺陷修复：PG 数据源方言与传参（门诊 mzjyxx 已落 outpatient_postgres）──

class _PgCursor:
    """psycopg 风格游标：参数序列整体传入（非 splat）。"""

    def __init__(self, rows, columns):
        self._rows = rows
        self.description = [(name,) for name in columns]
        self.executed: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows


class _PgConnection:
    def __init__(self, rows, columns):
        self.cursor_instance = _PgCursor(rows, columns)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_compile_postgresql_dialect_uses_percent_s_and_quoted_identifiers():
    compiled = SemanticQueryPlanner(_outpatient_registry()).compile(
        _outpatient_query("whole_settlement", ["total_amount"]),
        dialect_kind="postgresql",
    )
    assert "%s" in compiled.sql
    assert "?" not in compiled.sql
    # PG 落地视图列名保留大小写，必须双引号包裹（AGENTS.md 已知陷阱）
    assert '"T_TradeNo"' in compiled.sql or '"T_FeeAll"' in compiled.sql


def test_execute_postgresql_datasource_compiles_pg_and_passes_params_as_sequence():
    """缺陷复现：门诊语义查询模型 §9 后落 outpatient_postgres（PG），执行通道此前
    固定 mssql qmark + pyodbc splat，psycopg 下无法运行（policy-qa 门诊追问
    POLICY_QA_FAILED 的根因之一）。"""
    conn = _PgConnection(rows=[(100.0, 1)], columns=["total_amount", "_anchor_count"])
    service = SemanticQueryService(
        _outpatient_registry(),
        lambda _datasource_id: conn,
        datasource_kind=lambda _datasource_id: "postgresql",
    )

    result = service.execute(_outpatient_query("whole_settlement", ["total_amount"]))

    sql, params = conn.cursor_instance.executed[0]
    assert "%s" in sql and "?" not in sql
    assert isinstance(params, (list, tuple))  # psycopg 传参约定：参数序列整体传入
    assert conn.closed is True
    assert result.rows[0]["total_amount"] == 100.0


def test_execute_without_kind_resolver_keeps_mssql_qmark_splat():
    """未注入方言解析时保持 mssql 行为（住院等存量链路不回归）。"""
    executed: list[tuple] = []

    class Cursor:
        description = [("total_amount",), ("_anchor_count",)]

        def execute(self, sql, *values):
            executed.append((sql, values))

        def fetchall(self):
            return [(100.0, 1)]

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    service = SemanticQueryService(_outpatient_registry(), lambda _ds: Connection())
    result = service.execute(_outpatient_query("whole_settlement", ["total_amount"]))

    sql, values = executed[0]
    assert "?" in sql and "%s" not in sql
    assert "SET-001" in values
    assert result.rows[0]["total_amount"] == 100.0


# ── #78：执行期数据源偏好（默认 SQL Server 直库，PG 落地库为后续演进）──

def _two_datasource_registry():
    """mzjyxx 双版本：v1 落 SQL Server（o_Trade/o_FeeItem@bjybdb），
    v2 落 PG 落地库（public.mz_trade/mz_fee_item@outpatient_postgres）。"""
    registry = _outpatient_registry()
    store = registry._store
    v1 = store._object_versions["mzjyxx"][0]
    pg_tables = {"mz_trade": "mz_trade", "mz_fee_item": "mz_fee_item"}
    pg_datasets = [
        item.model_copy(update={
            "datasource_id": "outpatient_postgres",
            "schema_name": "public",
            "table_name": pg_tables[item.dataset_code],
        })
        for item in v1.datasets
    ]
    store.save_object_version(v1.model_copy(update={
        "version_id": "mzjyxx-v2", "version": "2", "datasets": pg_datasets,
    }))
    return registry


def _kind_resolver(datasource_id):
    return "postgresql" if datasource_id == "outpatient_postgres" else "mssql"


def test_execute_sqlserver_mode_prefers_latest_all_mssql_version():
    """默认（sqlserver）：多版本时选数据集全落 SQL Server 的最近版本执行。"""
    executed: list[tuple] = []

    class Cursor:
        description = [("total_amount",), ("_anchor_count",)]

        def execute(self, sql, *values):
            executed.append((sql, values))

        def fetchall(self):
            return [(100.0, 1)]

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    service = SemanticQueryService(
        _two_datasource_registry(),
        lambda _ds: Connection(),
        datasource_kind=_kind_resolver,
        datasource_mode="sqlserver",
    )
    result = service.execute(_outpatient_query("whole_settlement", ["total_amount"]))

    sql = executed[0][0]
    assert "o_Trade" in sql and "?" in sql  # v1（SQL Server）编译
    assert "public" not in sql
    assert result.rows[0]["total_amount"] == 100.0


def test_execute_registry_mode_uses_latest_published_version():
    """datasource_mode=registry：恢复按注册中心最新发布版本执行（含 PG 落地库）。"""
    conn = _PgConnection(rows=[(100.0, 1)], columns=["total_amount", "_anchor_count"])
    service = SemanticQueryService(
        _two_datasource_registry(),
        lambda _ds: conn,
        datasource_kind=_kind_resolver,
        datasource_mode="registry",
    )
    result = service.execute(_outpatient_query("whole_settlement", ["total_amount"]))

    sql, params = conn.cursor_instance.executed[0]
    assert "%s" in sql and "public" in sql  # v2（PG 落地库）编译
    assert isinstance(params, list)
    assert result.rows[0]["total_amount"] == 100.0


def test_sqlserver_mode_falls_back_to_latest_when_no_mssql_version():
    """全部版本都在 PG 时回落最新版（PG-only 模型不受影响）。"""
    registry = _two_datasource_registry()
    store = registry._store
    v2 = store._object_versions["mzjyxx"][1]
    # 把 v1 也改成 PG：两版全 PG，选择器只能回落最新
    store._object_versions["mzjyxx"][0] = store._object_versions["mzjyxx"][1]

    conn = _PgConnection(rows=[(100.0, 1)], columns=["total_amount", "_anchor_count"])
    service = SemanticQueryService(
        registry,
        lambda _ds: conn,
        datasource_kind=_kind_resolver,
        datasource_mode="sqlserver",
    )
    result = service.execute(_outpatient_query("whole_settlement", ["total_amount"]))

    sql, _params = conn.cursor_instance.executed[0]
    assert "%s" in sql  # 回落最新（PG）版本
    assert result.rows[0]["total_amount"] == 100.0
