"""
Business Action — 平台最高层业务分类。

所有 Agent、Skill、Workflow、Prompt、Tool 都必须挂载到统一的 Business Action。
新增业务优先新增 Skill，而不是新增 Business Action。

原则：
- 稳定：几年不会变化
- 业务驱动：来自医院医保办实际工作
- 可扩展：新增 Skill 不新增 Action
- 动作唯一：每个 Skill 必须属于一个 Primary Action

参见：Business Action Specification V1.0
"""

from enum import StrEnum


class BusinessAction(StrEnum):
    """七类医保业务动作 — 平台允许存在的全部一级业务分类。

    原则上不得继续增加。
    """
    EXPLAIN = "explain"       # 解释：为什么（面向患者，解释已发生的事实）
    QUERY = "query"           # 查询：是什么（面向患者，查询已有数据）
    GUIDE = "guide"           # 导办：怎么办（面向患者，指导办理流程）
    VERIFY = "verify"         # 核验：对不对（面向患者/医保办，验证已有结果）
    COMPARE = "compare"       # 对比：有什么不同（面向患者，比较两个对象）
    EVALUATE = "evaluate"     # 评估：如果这样会怎样（面向患者/医保办，影响评估）
    ANALYZE = "analyze"       # 分析：有什么规律（面向管理者，统计分析）


# ── Action → 中文标签 ────────────────────────────────────────────

ACTION_LABELS: dict[BusinessAction, str] = {
    BusinessAction.EXPLAIN: "解释",
    BusinessAction.QUERY: "查询",
    BusinessAction.GUIDE: "导办",
    BusinessAction.VERIFY: "核验",
    BusinessAction.COMPARE: "对比",
    BusinessAction.EVALUATE: "评估",
    BusinessAction.ANALYZE: "分析",
}


# ── Action → 面向对象 ────────────────────────────────────────────

ACTION_AUDIENCE: dict[BusinessAction, str] = {
    BusinessAction.EXPLAIN: "患者",
    BusinessAction.QUERY: "患者",
    BusinessAction.GUIDE: "患者",
    BusinessAction.VERIFY: "患者 / 医保办",
    BusinessAction.COMPARE: "患者",
    BusinessAction.EVALUATE: "患者 / 医保办",
    BusinessAction.ANALYZE: "医保办 / 管理者",
}


class BusinessObject(StrEnum):
    """医保业务对象 — Business Action 操作的对象。

    Business Action 决定"做什么"，Business Object 决定"处理谁"，
    两者共同唯一确定一个 Skill。
    """
    SETTLEMENT = "settlement"           # 结算
    BENEFIT = "benefit"                 # 待遇
    POLICY = "policy"                   # 政策
    DIRECTORY = "directory"             # 目录
    CHRONIC_DISEASE = "chronic_disease" # 慢特病
    REFERRAL = "referral"               # 转诊转院
    APPEAL = "appeal"                   # 申诉
    MEDICAL_RECORD = "medical_record"   # 病案
    DRG_DIP = "drg_dip"                 # DRG/DIP
    COMPLAINT = "complaint"             # 投诉


# ── Object → 中文标签 ────────────────────────────────────────────

OBJECT_LABELS: dict[BusinessObject, str] = {
    BusinessObject.SETTLEMENT: "结算",
    BusinessObject.BENEFIT: "待遇",
    BusinessObject.POLICY: "政策",
    BusinessObject.DIRECTORY: "目录",
    BusinessObject.CHRONIC_DISEASE: "慢特病",
    BusinessObject.REFERRAL: "转诊转院",
    BusinessObject.APPEAL: "申诉",
    BusinessObject.MEDICAL_RECORD: "病案",
    BusinessObject.DRG_DIP: "DRG/DIP",
    BusinessObject.COMPLAINT: "投诉",
}


# ── Action × Object 能力矩阵 ─────────────────────────────────────

# 哪些 Action-Object 组合在当前平台有效
VALID_ACTION_OBJECT_PAIRS: frozenset[tuple[BusinessAction, BusinessObject]] = frozenset({
    # Explain
    (BusinessAction.EXPLAIN, BusinessObject.SETTLEMENT),
    (BusinessAction.EXPLAIN, BusinessObject.BENEFIT),
    (BusinessAction.EXPLAIN, BusinessObject.POLICY),
    (BusinessAction.EXPLAIN, BusinessObject.DIRECTORY),
    # Query
    (BusinessAction.QUERY, BusinessObject.SETTLEMENT),
    (BusinessAction.QUERY, BusinessObject.BENEFIT),
    (BusinessAction.QUERY, BusinessObject.POLICY),
    (BusinessAction.QUERY, BusinessObject.DIRECTORY),
    (BusinessAction.QUERY, BusinessObject.CHRONIC_DISEASE),
    # Guide
    (BusinessAction.GUIDE, BusinessObject.CHRONIC_DISEASE),
    (BusinessAction.GUIDE, BusinessObject.REFERRAL),
    (BusinessAction.GUIDE, BusinessObject.APPEAL),
    # Verify
    (BusinessAction.VERIFY, BusinessObject.SETTLEMENT),
    (BusinessAction.VERIFY, BusinessObject.BENEFIT),
    (BusinessAction.VERIFY, BusinessObject.DIRECTORY),
    (BusinessAction.VERIFY, BusinessObject.CHRONIC_DISEASE),
    (BusinessAction.VERIFY, BusinessObject.REFERRAL),
    (BusinessAction.VERIFY, BusinessObject.MEDICAL_RECORD),
    # Compare
    (BusinessAction.COMPARE, BusinessObject.SETTLEMENT),
    (BusinessAction.COMPARE, BusinessObject.BENEFIT),
    (BusinessAction.COMPARE, BusinessObject.POLICY),
    # Evaluate
    (BusinessAction.EVALUATE, BusinessObject.SETTLEMENT),
    (BusinessAction.EVALUATE, BusinessObject.BENEFIT),
    # Analyze
    (BusinessAction.ANALYZE, BusinessObject.SETTLEMENT),
    (BusinessAction.ANALYZE, BusinessObject.BENEFIT),
    (BusinessAction.ANALYZE, BusinessObject.COMPLAINT),
    (BusinessAction.ANALYZE, BusinessObject.DRG_DIP),
})


def is_valid_action_object(action: BusinessAction, obj: BusinessObject) -> bool:
    """判断给定的 Action-Object 组合是否有效。"""
    return (action, obj) in VALID_ACTION_OBJECT_PAIRS
