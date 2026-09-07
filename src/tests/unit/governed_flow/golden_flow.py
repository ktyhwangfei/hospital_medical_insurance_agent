"""#62 Golden Flow 测试夹具：门诊有效结算四字段（口径句 v4，已签核）。

口径与视图唯一来源：issue-62 分支 docs/processing/registry.yaml +
outpatient_processed_view.sql（v_op_outpatient_processed）。
Phase 0 冻结：本夹具是 Flow DSL 表达力的基准用例，Phase 1 编译器
必须能把它编译为与该视图等价的 SQL。

2026-09-07 架构裁决（Phase 0 文档 §9）：加工视图落位 PG 落地库，
源从 SQL Server o_Trade 切换为 PG 治理视图 mz_trade（列名与源
o_Trade 契约一致），上游血缘经同步落地链路保留。
"""
from __future__ import annotations

from src.domain.governed_flow.models import (
    AggregateMeasure,
    AggregateNode,
    AggregateOperator,
    ConsumerKind,
    ConsumerNode,
    FilterNode,
    FilterOperator,
    FlowDefinition,
    FlowEdge,
    FlowFilterCondition,
    QualityCheck,
    QualityCheckType,
    MetricOutputBinding,
    QualityGateNode,
    SourceContract,
    SourceNode,
)

# 口径句 v4 全文（registry.yaml 四字段共用；发布门禁按全文精确匹配签核）
CALIBER_V4 = (
    "T_State IN (2,3) AND NP_Settle_State=1 AND T_HasRefundmented != 1 "
    "AND (T_PartialReturnFlag IS NULL OR T_PartialReturnFlag='') "
    "AND (T_CureType IN (11,17,18,19) OR T_CureType IS NULL)"
)

# mz_trade 契约字段：9 个（投影白名单 = 视图实际引用列；与源 o_Trade 契约列名一致）
O_TRADE_FIELDS = [
    "T_TradeNo", "T_State", "NP_Settle_State", "T_HasRefundmented",
    "T_PartialReturnFlag", "T_CureType", "T_FeeAll", "T_FundPay", "T_SelfPayAll",
]

GOLDEN_METRICS = [
    ("op_valid_settle_count", "门诊有效结算笔数", "T_TradeNo"),
    ("op_total_fee", "门诊总费用", "T_FeeAll"),
    ("op_fund_pay", "门诊统筹基金支付金额", "T_FundPay"),
    ("op_self_pay", "门诊个人支付金额", "T_SelfPayAll"),
]


def build_golden_flow() -> FlowDefinition:
    """构建 #62 Golden Flow：source → filter(口径句v4) → aggregate(4度量) → quality_gate → consumer。"""
    nodes = [
        SourceNode(
            node_id="src_trade", name="门诊结算落地表 mz_trade",
            dataset_code="mz_trade", object_code="mzjyxx",
            fields=O_TRADE_FIELDS,
            position={"x": 40, "y": 200},
        ),
        FilterNode(
            node_id="filter_valid", name="有效结算口径句 v4",
            conditions=[
                FlowFilterCondition(field_code="T_State", operator=FilterOperator.IN, value=[2, 3]),
                FlowFilterCondition(field_code="NP_Settle_State", operator=FilterOperator.EQ, value=1),
                FlowFilterCondition(field_code="T_HasRefundmented", operator=FilterOperator.NE, value=1),
                FlowFilterCondition(field_code="T_PartialReturnFlag", operator=FilterOperator.IN_OR_NULL, value=[""]),
                FlowFilterCondition(
                    field_code="T_CureType", operator=FilterOperator.IN_OR_NULL,
                    value=[11, 17, 18, 19], value_domain="MZ_CURE_TYPE",
                ),
            ],
            position={"x": 280, "y": 200},
        ),
        AggregateNode(
            node_id="agg_snapshot", name="门诊加工视图（全局单行预聚合）",
            group_by=[],
            measures=[
                AggregateMeasure(
                    output_code="op_valid_settle_count", source_field="T_TradeNo",
                    operator=AggregateOperator.COUNT_DISTINCT, distinct_key="T_TradeNo",
                ),
                AggregateMeasure(output_code="op_total_fee", source_field="T_FeeAll", operator=AggregateOperator.SUM),
                AggregateMeasure(output_code="op_fund_pay", source_field="T_FundPay", operator=AggregateOperator.SUM),
                AggregateMeasure(output_code="op_self_pay", source_field="T_SelfPayAll", operator=AggregateOperator.SUM),
            ],
            position={"x": 520, "y": 200},
        ),
        QualityGateNode(
            node_id="gate_caliber", name="口径签核与勾稽恒等门禁",
            checks=[
                QualityCheck(check_type=QualityCheckType.CALIBER_SIGNOFF, params={}),
                QualityCheck(
                    check_type=QualityCheckType.IDENTITY_ASSERTION,
                    params={"left": "op_total_fee", "right": ["op_fund_pay", "op_self_pay"], "tolerance": 0.0},
                ),
            ],
            position={"x": 760, "y": 200},
        ),
        ConsumerNode(
            node_id="consumer_qp", name="受控问数（query_planner）",
            consumer_kind=ConsumerKind.QUERY_PLANNER,
            consumes=[code for code, _, _ in GOLDEN_METRICS],
            position={"x": 1000, "y": 200},
        ),
    ]
    edges = [
        {"edge_id": "e1", "from_node": "src_trade", "to_node": "filter_valid"},
        {"edge_id": "e2", "from_node": "filter_valid", "to_node": "agg_snapshot"},
        {"edge_id": "e3", "from_node": "agg_snapshot", "to_node": "gate_caliber"},
        {"edge_id": "e4", "from_node": "gate_caliber", "to_node": "consumer_qp"},
    ]
    return FlowDefinition(
        flow_id="flow_op_outpatient_processed",
        name="门诊有效结算加工视图（#62 Golden Flow）",
        owner="data_governance",
        nodes=nodes,
        edges=[FlowEdge(**e) for e in edges],
        source_contracts=[
            SourceContract(dataset_code="mz_trade", object_code="mzjyxx", fields=O_TRADE_FIELDS)
        ],
        metric_outputs=[
            MetricOutputBinding(
                metric_code=code, name=name, node_id="agg_snapshot",
                policy_definition=CALIBER_V4,
            )
            for code, name, _ in GOLDEN_METRICS
        ],
    )


def golden_validation_context():
    """#62 已签核事实：数据集已登记、MZ_CURE_TYPE 值域、口径句 v4 已签核。"""
    from src.domain.governed_flow.validation import FlowValidationContext

    return FlowValidationContext(
        registered_datasets={"mz_trade"},
        value_domains={"MZ_CURE_TYPE": {"11", "17", "18", "19"}},
        signed_calibers={CALIBER_V4},
    )
