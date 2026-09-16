"""静态 Workflow 定义登记表（#68 四个真实问题中可落地的场景 + 三态入口）。"""

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
    TOOL_PARSE_DATA_QUERY_INTENT,
    TOOL_QUERY_FLOW_METRICS,
    TOOL_QUERY_SEMANTIC_METRICS,
)
from src.runtime.tool_registry.knowledge_tools import TOOL_COMPREHENSIVE_KNOWLEDGE_LOOKUP
from src.runtime.workflow.domain_nodes import (
    DOMAIN_HANDLER_VERSION,
    EVIDENCE_COMPLETENESS,
    EVIDENCE_MERGE,
    SETTLEMENT_POLICY_COMPARE,
)

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
            input_mapping={"settlement_id": "context.settlement_id"},
        ),
        WorkflowStep(
            step_id="fetch_refund_record",
            tool_id=TOOL_GET_REFUND_RECORD,
            description="查询退费/冲正记录",
            input_mapping={"settlement_id": "context.settlement_id"},
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
    description="自然语言解析为 Flow 消费契约指标码，经受控视图与勾稽门禁执行；指标不在目录内则澄清",
    intent_keywords=[
        # 运营聚合问法（金额向；不含「比例」类政策词，避免误伤政策咨询链路）
        "支付是多少", "支付金额", "支付总额", "支付一共",
        "门诊总费用", "门诊总金额", "费用总额", "结算总金额", "结算总额",
        "大额支付", "个人账户支付", "现金支付", "医保门诊结算",
        "门诊人次", "费用趋势", "科室排名", "药占比", "次均费用",
        "运营指标", "统计",
    ],
    missing_evidence_rules=[],
    steps=[
        WorkflowStep(
            step_id="parse_intent",
            tool_id=TOOL_PARSE_DATA_QUERY_INTENT,
            description="NL → 已发布消费契约指标码",
            input_mapping={"question": "context.question"},
        ),
        WorkflowStep(
            step_id="query_flow_metrics",
            tool_id=TOOL_QUERY_FLOW_METRICS,
            description="Flow 消费契约受控查询（勾稽门禁）",
            input_mapping={
                "metric_codes": "parse_intent.metric_codes",
                "dimensions": "parse_intent.dimensions",
                "clarification_needed": "parse_intent.clarification_needed",
                "clarification_message": "parse_intent.clarification_message",
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

# 关键词 fallback 仅承载没有显式 mode 的窄场景；政策问答继续走既有 Skill 管线，
# 运营问数只接受前端显式 DATA_QUERY mode，避免“报销比例”等重叠词误路由。
KEYWORD_ROUTED_WORKFLOWS: list[WorkflowDefinition] = [
    WF_REFUND_VERIFICATION,
    WF_OUTPATIENT_SETTLEMENT_EXPLAIN,
    # 运营问数参与关键词 fallback（2026-09-16 验收缺陷修复）：
    # 默认政策问答 Tab 下的运营金额问法（无结算单号、无 mode）必须路由到问数链，
    # 否则被政策问答链路答非所问（答政策条文而非数值）。
    # 词表已剔除比例类政策词；指标不在 Flow 消费契约内时由意图解析诚实澄清。
    WF_DATA_QUERY,
]
