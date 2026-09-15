"""静态 Workflow 定义登记表（#68 四个真实问题中可落地的场景 + 三态入口）。"""

from src.domain.workflow.models import MissingEvidenceRule, WorkflowDefinition, WorkflowStep
from src.runtime.tool_registry.builtin_tools import (
    TOOL_GET_REFUND_RECORD,
    TOOL_GET_SETTLEMENT_FACT,
)
from src.runtime.tool_registry.calc_tools import TOOL_COMPARE_SETTLEMENT_VS_POLICY
from src.runtime.tool_registry.data_tools import (
    TOOL_PARSE_DATA_QUERY_INTENT,
    TOOL_QUERY_SEMANTIC_METRICS,
)
from src.runtime.tool_registry.knowledge_tools import TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP

WF_REFUND_VERIFICATION = WorkflowDefinition(
    workflow_id="wf_refund_verification",
    name="退费核对",
    description="核对结算单是否存在对应退费/冲正记录（Issue #68 场景：多扣未退款）",
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
        ),
        WorkflowStep(
            step_id="fetch_refund_record",
            tool_id=TOOL_GET_REFUND_RECORD,
            description="查询退费/冲正记录",
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
        ),
        WorkflowStep(
            step_id="retrieve_policy_evidence",
            tool_id="tool_retrieve_policy_evidence",
            description="按结算适用性维度检索政策证据（知识类：向量）",
            input_mapping={"settlement_fact": "fetch_settlement"},
        ),
        WorkflowStep(
            step_id="compare_settlement_vs_policy",
            tool_id=TOOL_COMPARE_SETTLEMENT_VS_POLICY,
            description="对比实际报销比例与政策分段比例（对比计算类）",
            input_mapping={
                "settlement_fact": "fetch_settlement",
                "policy_evidence": "retrieve_policy_evidence",
            },
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
    WF_OUTPATIENT_SETTLEMENT_EXPLAIN,
    WF_POLICY_CHAT,
    WF_DATA_QUERY,
]
