"""
医保政策问答RAG系统 - 数据模型

定义PolicyQA流程中使用的数据结构
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PolicyQAIntent(Enum):
    """政策问答意图类型"""
    FEE_DECOMPOSITION = "fee_decomposition"  # 费用分解
    TREATMENT_DECOMPOSITION = "treatment_decomposition"  # 待遇分解
    DEDUCTIBLE = "deductible"  # 起付线
    PAYMENT_RATIO = "payment_ratio"  # 报销比例
    CAP_AMOUNT = "cap_amount"  # 封顶线
    GENERAL = "general"  # 通用问答


@dataclass
class PolicyQARequest:
    """政策问答请求"""
    question: str
    settlement_id: str
    session_id: str | None = None


@dataclass
class PolicyQAIntentResult:
    """意图识别结果"""
    intent: PolicyQAIntent
    settlement_id: str
    need_patient_data: bool = True
    query_type: str = ""
    target_fee_item: str | None = None
    target_fee_label: str | None = None
    confidence: float = 0.0


@dataclass
class SQLQueryResult:
    """SQL查询结果"""
    yb_zyfdxx: dict[str, Any] = field(default_factory=dict)  # 待遇分解表
    yb_zyfymx: list[dict[str, Any]] = field(default_factory=list)  # 费用明细表
    yb_dyxxnd: dict[str, Any] = field(default_factory=dict)  # 年度累计表
    yb_dyxxzy: dict[str, Any] = field(default_factory=dict)  # 住院信息表
    yb_brdjxx: dict[str, Any] = field(default_factory=dict)  # 患者登记表


@dataclass
class RewrittenQuestion:
    """重写后的问题"""
    original: str = ""
    rewritten: str = ""
    search_query: str = ""
    explanation_context: dict[str, Any] = field(default_factory=dict)
    semantic_mappings: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PolicyRule:
    """政策规则"""
    rule_id: str = ""
    fact_id: str = ""
    policy_id: str = ""
    clause_id: str = ""
    source_text: str = ""
    insu_type: str = ""
    med_type: str = ""
    hosp_lv: str = ""
    psn_type: str = ""
    setl_type: str = ""
    payment_ratio: str = ""
    deductible_amount: str = ""
    cap_amount: str = ""
    time_period: str = ""
    admission_order: str = ""
    amount_band: str = ""
    priority: str = ""
    rule_type: str = ""
    rule_value: str = ""
    score: float = 0.0


@dataclass
class SegmentInfo:
    """分段计算信息"""
    lower: float = 0.0
    upper: float = 0.0
    amount: float = 0.0
    base_ratio: float = 0.0
    person_ratio: float = 0.0
    actual_ratio: float = 0.0
    pay: float = 0.0
    calculation: str = ""
    rule_id: str = ""          # 来源政策规则ID（溯源用）
    policy_source: str = ""    # 来源政策条文原文（溯源用）
    # 规则溯源：该分段对应的政策规则
    rule_id: str = ""
    policy_source: str = ""  # 政策条文原文，用于解释时引用


@dataclass
class SegmentCalculationResult:
    """分段计算结果"""
    segments: list[SegmentInfo] = field(default_factory=list)
    total_pay: float = 0.0
    authoritative_amount: float | None = None
    reconciliation_difference: float | None = None
    reconciliation_tolerance: float = 0.01
    reconciliation_matched: bool | None = None
    reconciliation_message: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class TreatmentItem:
    """待遇分解项"""
    value: float = 0.0
    source: str = ""
    policy: str | None = None
    calculation: str | None = None


@dataclass
class TreatmentDecomposition:
    """待遇分解"""
    total_fee: TreatmentItem = field(default_factory=TreatmentItem)  # 总费用
    in_scope: TreatmentItem = field(default_factory=TreatmentItem)  # 医保内
    deductible: TreatmentItem = field(default_factory=TreatmentItem)  # 起付线
    pooling_amount: float = 0.0  # 统筹内金额（分段计算基数）
    pooling_self_pay: TreatmentItem = field(default_factory=TreatmentItem)  # 统筹自付
    pooling_payment: TreatmentItem = field(default_factory=TreatmentItem)  # 统筹支付
    major_payment: TreatmentItem = field(default_factory=TreatmentItem)  # 大额支付
    major_self_pay: TreatmentItem = field(default_factory=TreatmentItem)  # 大额自付
    personal_liability: TreatmentItem = field(default_factory=TreatmentItem)  # 个人应负
    out_of_scope: TreatmentItem = field(default_factory=TreatmentItem)  # 医保外


@dataclass
class FeeCategory:
    """费用分类"""
    category: str  # 甲类/乙类/丙类
    total_amount: float = 0.0
    in_scope_amount: float = 0.0
    out_of_scope_amount: float = 0.0
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FeeDecomposition:
    """费用分解"""
    categories: list[FeeCategory] = field(default_factory=list)
    total_amount: float = 0.0
    in_scope_total: float = 0.0
    out_of_scope_total: float = 0.0


@dataclass
class EvidenceItem:
    """溯源证据项"""
    item: str = ""
    value: float = 0.0
    source_table: str = ""
    source_field: str = ""
    policy_rule: dict[str, Any] = field(default_factory=dict)
    calculation: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeeDecompositionResult:
    """费用分解完整结果"""
    treatment: TreatmentDecomposition = field(default_factory=TreatmentDecomposition)
    fees: FeeDecomposition = field(default_factory=FeeDecomposition)
    segments: SegmentCalculationResult = field(default_factory=SegmentCalculationResult)
    evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass
class PolicyQAResponse:
    """政策问答响应"""
    step: str = ""
    status: str = ""  # running/done/streaming/error
    detail: dict[str, Any] = field(default_factory=dict)
    chunk: str = ""
    error: str = ""


@dataclass
class ExplanationContext:
    """解释生成上下文"""
    question: str = ""
    intent: PolicyQAIntentResult = field(default_factory=lambda: PolicyQAIntentResult(
        intent=PolicyQAIntent.GENERAL,
        settlement_id="",
    ))
    sql_result: SQLQueryResult = field(default_factory=SQLQueryResult)
    rewritten_question: RewrittenQuestion = field(default_factory=RewrittenQuestion)
    policy_rules: list[PolicyRule] = field(default_factory=list)
    decomposition: FeeDecompositionResult = field(default_factory=FeeDecompositionResult)
    user_role: str = "患者"  # 患者/收费员/医生/医保管理员
