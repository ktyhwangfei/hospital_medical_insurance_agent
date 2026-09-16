"""静态 Workflow 定义登记表（#68 四个真实问题中可落地的场景 + 三态入口）。

节点模型（#72）：外部 I/O 走 ToolNode，编排内部确定性计算走代码侧白名单
DomainNode，最终公开结果由 OutputNode 显式声明来源。
"""

from src.domain.workflow.models import (
    DomainNode,
    MissingEvidenceRule,
    OutputNode,
    WorkflowDefinition,
    WorkflowStep,
)
from src.runtime.tool_registry.builtin_tools import (
    TOOL_GET_REFUND_RECORD,
    TOOL_GET_SETTLEMENT_FACT,
)
from src.runtime.tool_registry.data_tools import (
    TOOL_GET_BENEFIT_STACKING,
    TOOL_GET_FEE_DETAIL,
    TOOL_PARSE_DATA_QUERY_INTENT,
    TOOL_QUERY_SEMANTIC_METRICS,
)
from src.runtime.tool_registry.knowledge_tools import TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP
from src.runtime.workflow.domain_nodes import (
    DOMAIN_HANDLER_VERSION,
    EVIDENCE_COMPLETENESS,
    EVIDENCE_MERGE,
    SAME_DRUG_COMPARE,
    SETTLEMENT_POLICY_COMPARE,
)

WF_REFUND_VERIFICATION = WorkflowDefinition(
    workflow_id="wf_refund_verification",
    name="退费核对",
    description="核对结算单是否存在对应退费/冲正记录，并调取费用明细供逐项比对（Issue #68 场景：退药未退款/多扣）",
    intent_keywords=["退费", "退款", "多扣", "未退款", "冲正", "退药"],
    missing_evidence_rules=[
        MissingEvidenceRule(
            field_name="settlement_id",
            clarify_message="请提供需要核对退费的结算单号后再继续。",
        ),
    ],
    steps=[
        WorkflowStep(
            step_id="fetch_settlement",
            tool_id=TOOL_GET_SETTLEMENT_FACT,
            description="查询结算单基础事实",
            input_mapping={"settlement_id": "context.settlement_id"},
        ),
        WorkflowStep(
            step_id="fetch_fee_detail",
            tool_id=TOOL_GET_FEE_DETAIL,
            description="查询逐项目费用明细（含国标码/先行自付），供退费项定位",
            input_mapping={"settlement_id": "context.settlement_id"},
        ),
        WorkflowStep(
            step_id="fetch_refund_record",
            tool_id=TOOL_GET_REFUND_RECORD,
            description="查询退费/冲正记录（医保端 tflydjh + HIS 端退费链路）",
            input_mapping={"settlement_id": "context.settlement_id"},
        ),
        OutputNode(
            step_id="public_result",
            source_ref="fetch_refund_record",
            description="公开结果取末端退费核对结论",
        ),
    ],
)

WF_SETTLEMENT_REIMBURSEMENT_DIFF = WorkflowDefinition(
    workflow_id="wf_settlement_reimbursement_diff",
    name="同药跨单报销差异核验",
    description=(
        "同一患者多张结算单的同一药品/项目费用事实对比：批量取费用明细（Tool）后"
        "按国标码对齐逐项对比（领域节点），差异归因边界如实声明"
        "（Issue #68 场景：同药三次报销比例不同）"
    ),
    intent_keywords=[
        "报销比例不同",
        "比例不一样",
        "同药",
        "同一药品",
        "同一患者",
        "三次结算",
        "跨结算",
        "比例差异",
    ],
    missing_evidence_rules=[
        MissingEvidenceRule(
            field_name="settlement_ids",
            clarify_message="请提供需要对比的至少两笔结算单号后再继续。",
        ),
    ],
    steps=[
        WorkflowStep(
            step_id="fetch_fee_details",
            tool_id=TOOL_GET_FEE_DETAIL,
            description="批量取多笔结算单费用明细（Tool：外部只读取数）",
            input_mapping={"settlement_ids": "context.settlement_ids"},
        ),
        DomainNode(
            step_id="same_drug_compare",
            handler_id=SAME_DRUG_COMPARE,
            handler_version=DOMAIN_HANDLER_VERSION,
            description="按国标码对齐后确定性对比单价/数量/医保内占比/先行自付（领域节点）",
            input_mapping={"fee_details": "fetch_fee_details.details"},
        ),
        OutputNode(
            step_id="public_result",
            source_ref="same_drug_compare",
            description="公开结果取同药对比结论",
        ),
    ],
)

WF_BENEFIT_STACKING_ATTRIBUTION = WorkflowDefinition(
    workflow_id="wf_benefit_stacking_attribution",
    name="待遇叠加归因",
    description=(
        "查询结算单的特病登记状态与逐笔分摊事实（特病/大病/民政救助），"
        "叠加顺序规则未接入前仅陈述实际分摊并声明不确定性（Issue #68 场景：特病+低保二次报销个人支付偏高）"
    ),
    intent_keywords=[
        "特病",
        "低保",
        "二次报销",
        "待遇叠加",
        "血友病",
    ],
    missing_evidence_rules=[
        MissingEvidenceRule(
            field_name="settlement_id",
            clarify_message="请提供需要归因分析的结算单号后再继续。",
        ),
    ],
    steps=[
        WorkflowStep(
            step_id="fetch_settlement",
            tool_id=TOOL_GET_SETTLEMENT_FACT,
            description="查询结算单基础事实",
            input_mapping={"settlement_id": "context.settlement_id"},
        ),
        WorkflowStep(
            step_id="fetch_benefit_stacking",
            tool_id=TOOL_GET_BENEFIT_STACKING,
            description="查询特病登记与逐笔分摊事实（低保维度缺失时声明 uncertainties）",
            input_mapping={"settlement_id": "context.settlement_id"},
        ),
        OutputNode(
            step_id="public_result",
            source_ref="fetch_benefit_stacking",
            description="公开结果取待遇叠加分摊结论",
        ),
    ],
)

WF_OUTPATIENT_SETTLEMENT_EXPLAIN = WorkflowDefinition(
    workflow_id="wf_outpatient_settlement_explain",
    name="门诊结算解释",
    description=(
        "四个真实问题共享的标准核验链：查询结算事实 → 向量检索政策证据 → "
        "确定性对比实际报销比例与政策分段比例，结论可溯源到规则原文"
    ),
    intent_keywords=[
        "核对结算",
        "结算单核对",
        "核验结算",
        "结算单核验",
        "结算单对不对",
        "结算单对吗",
        "结算单有问题",
        "核一下结算",
    ],
    missing_evidence_rules=[
        MissingEvidenceRule(
            field_name="settlement_id",
            clarify_message="请提供需要核对解释的结算单号后再继续。",
        ),
    ],
    steps=[
        WorkflowStep(
            step_id="fetch_settlement",
            tool_id=TOOL_GET_SETTLEMENT_FACT,
            description="查询结算单事实（数据类：语义层结算 provider）",
            input_mapping={"settlement_id": "context.settlement_id"},
        ),
        WorkflowStep(
            step_id="retrieve_policy_evidence",
            tool_id="tool_retrieve_policy_evidence",
            description="按结算适用性维度检索政策证据（知识类：向量）",
            input_mapping={"settlement_fact": "fetch_settlement"},
        ),
        DomainNode(
            step_id="check_evidence",
            handler_id=EVIDENCE_COMPLETENESS,
            handler_version=DOMAIN_HANDLER_VERSION,
            description="校验结算事实与政策证据是否完整（确定性领域节点）",
            input_mapping={
                "settlement_fact": "fetch_settlement",
                "policy_evidence": "retrieve_policy_evidence",
            },
        ),
        DomainNode(
            step_id="compare_settlement_vs_policy",
            handler_id=SETTLEMENT_POLICY_COMPARE,
            handler_version=DOMAIN_HANDLER_VERSION,
            description="对比实际报销比例与政策分段比例（确定性领域节点）",
            input_mapping={
                "settlement_fact": "fetch_settlement",
                "policy_evidence": "retrieve_policy_evidence",
            },
        ),
        DomainNode(
            step_id="merge_evidence",
            handler_id=EVIDENCE_MERGE,
            handler_version=DOMAIN_HANDLER_VERSION,
            description="归并政策引用、对比结果与证据缺口",
            input_mapping={
                "policy_evidence": "retrieve_policy_evidence",
                "comparison": "compare_settlement_vs_policy",
                "evidence_check": "check_evidence",
            },
        ),
        OutputNode(
            step_id="public_result",
            source_ref="merge_evidence",
            description="声明经过校验和归并的公开结果来源",
        ),
    ],
)

WF_POLICY_CHAT = WorkflowDefinition(
    workflow_id="wf_policy_chat",
    name="政策问答",
    description="纯政策知识问答：综合知识检索（先可信问题库命中，未命中则向量政策证据）",
    intent_keywords=[
        "政策",
        "报销比例",
        "医保目录",
        "能报多少",
        "报销范围",
        "医保待遇",
    ],
    missing_evidence_rules=[],
    steps=[
        WorkflowStep(
            step_id="knowledge_lookup",
            tool_id=TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP,
            description="综合知识检索（结构化+向量两级融合）",
            input_mapping={"question": "context.question"},
        ),
    ],
)

WF_DATA_QUERY = WorkflowDefinition(
    workflow_id="wf_data_query",
    name="运营指标问数",
    description="自然语言解析为语义指标查询参数，走语义层固定 SQL 执行；指标不在目录内则澄清",
    intent_keywords=[
        "门诊人次",
        "费用趋势",
        "科室排名",
        "药占比",
        "次均费用",
        "报销比例",
        "运营指标",
        "统计",
    ],
    missing_evidence_rules=[],
    steps=[
        WorkflowStep(
            step_id="parse_intent",
            tool_id=TOOL_PARSE_DATA_QUERY_INTENT,
            description="NL → 已发布语义指标参数",
            input_mapping={"question": "context.question"},
        ),
        WorkflowStep(
            step_id="query_semantic_metrics",
            tool_id=TOOL_QUERY_SEMANTIC_METRICS,
            description="语义层受控查询",
            input_mapping={
                "object_code": "parse_intent.object_code",
                "entity_code": "parse_intent.entity_code",
                "anchor_field": "parse_intent.anchor_field",
                "anchor_value": "parse_intent.anchor_value",
                "metrics": "parse_intent.metrics",
                "query_scope": "parse_intent.query_scope",
            },
        ),
    ],
)

ALL_WORKFLOWS: list[WorkflowDefinition] = [
    WF_REFUND_VERIFICATION,
    WF_SETTLEMENT_REIMBURSEMENT_DIFF,
    WF_BENEFIT_STACKING_ATTRIBUTION,
    WF_OUTPATIENT_SETTLEMENT_EXPLAIN,
    WF_POLICY_CHAT,
    WF_DATA_QUERY,
]

# 关键词 fallback 仅承载没有显式 mode 的窄场景；政策问答继续走既有 Skill 管线，
# 运营问数只接受前端显式 DATA_QUERY mode，避免“报销比例”等重叠词误路由。
# 同药跨单/待遇叠加的关键词高度特异（同药/三次结算/特病/低保等），参与 fallback。
KEYWORD_ROUTED_WORKFLOWS: list[WorkflowDefinition] = [
    WF_REFUND_VERIFICATION,
    WF_SETTLEMENT_REIMBURSEMENT_DIFF,
    WF_BENEFIT_STACKING_ATTRIBUTION,
    WF_OUTPATIENT_SETTLEMENT_EXPLAIN,
]
