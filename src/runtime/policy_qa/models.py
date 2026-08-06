"""
医保政策问答RAG系统 - 数据模型

定义PolicyQA流程中使用的数据结构

v2 新增:
- TraceEvent / TraceEventStatus: 结构化执行链路事件
- AnswerabilityResult: 可回答性判断结果
- PolicyQATraceResponse: 完整链路响应（替代旧 PolicyQAResponse 作为最终结果）
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    user_id: str = ""
    role: str = ""


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
    """政策规则

    新增字段（RAG 政策卡片展示用）:
    - title: 政策标题（如 "城镇职工医保统筹基金支付比例"）
    - clause: 条文编号（如 "第十七条"）
    - evidence_text: 证据原文（法律条文完整文本）
    - matched_reason: 匹配原因（如 "险种=城镇职工, 人员类别=退休"）
    """
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
    # ★ 新增：RAG 政策卡片展示字段
    title: str = ""           # 政策标题
    clause: str = ""          # 条文编号
    evidence_text: str = ""   # 证据原文
    matched_reason: str = ""  # 匹配原因


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
    # 规则溯源：该分段对应的来源政策规则与条文原文
    rule_id: str = ""  # 来源政策规则ID（溯源用）
    policy_source: str = ""  # 政策条文原文，用于解释引用


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
    """政策问答响应

    detail: 完整内部数据（含调试信息，用于下游计算）— 前端禁止渲染
    public_detail: 结构化公共数据（前端渲染用，可程序化消费）
    public_message: 人性化步骤描述字符串（优先展示）
    answer: 单一政策解释文本
    answer_status: 回答状态（complete/unavailable）
    policy_cards: RAG 政策卡片列表，每项含 title/clause/evidence_text/matched_reason
    """
    step: str = ""
    status: str = ""  # running/done/streaming/error
    detail: dict[str, Any] = field(default_factory=dict)
    public_detail: dict[str, Any] = field(default_factory=dict)
    chunk: str = ""
    error: str = ""
    public_message: str = ""
    answer: str = ""
    answer_status: str = "unavailable"
    policy_cards: list[dict[str, Any]] = field(default_factory=list)  # RAG 政策卡片
    trace_event: dict[str, Any] | None = None


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
    rag_miss: bool = False   # ★ 新增: RAG 是否未命中政策规则


# ════════════════════════════════════════════════════════════════
# v2: 结构化执行链路事件模型 (Trace Events)
# ════════════════════════════════════════════════════════════════

class TraceEventStatus(Enum):
    """执行链路事件状态"""
    PENDING = "pending"    # 等待执行
    RUNNING = "running"    # 执行中
    SUCCESS = "success"    # 成功完成
    WARNING = "warning"    # 完成但有警告（如输出校验存在警告、政策规则部分缺失）
    FAILED = "failed"      # 执行失败
    SKIPPED = "skipped"    # 已跳过


@dataclass
class TraceEvent:
    """单条执行链路事件（符合前端 trace_events 契约）"""
    step_id: str                                    # 步骤标识: intent_detection, skill_routing, settlement_query...
    step_name: str                                  # 步骤中文名: 意图识别, Skill 匹配...
    status: str = "pending"                         # pending / running / success / failed / skipped
    started_at: str = ""                            # ISO 8601 开始时间
    finished_at: str = ""                           # ISO 8601 结束时间
    duration_ms: float = 0.0                        # 执行耗时（毫秒）
    summary: str = ""                               # 步骤摘要（前端直接渲染）
    details: dict[str, Any] = field(default_factory=dict)  # 结构化详情（前端折叠展示）
    error: str | None = None                        # 错误信息（仅 failed 状态）


@dataclass
class AnswerabilityResult:
    """可回答性判断结果"""
    can_answer: bool = False                        # 是否可以回答
    partial_answer: bool = False                    # 是否可以部分回答
    reason: str = ""                                # 判断原因
    missing_items: list[str] = field(default_factory=list)  # 缺失项列表
    checks: dict[str, bool] = field(default_factory=dict)   # 各项检查明细


class PolicyQARunStatus(Enum):
    """问答执行整体状态"""
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class PolicyQATraceResponse:
    """
    完整问答执行链路响应 — 前端唯一真相来源。
    
    替代旧 PolicyQAResponse 的零散 step 事件，
    提供结构化 run_id / status / can_answer / trace_events / result。
    """
    run_id: str = field(default_factory=lambda: f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}")
    status: str = "running"                         # PolicyQARunStatus: running / success / failed
    can_answer: bool = False                        # 可回答性标记
    partial_answer: bool = False                    # 部分可回答标记
    selected_skill_id: str = ""                     # 命中的 skill ID
    trace_events: list[TraceEvent] = field(default_factory=list)  # 执行链路事件列表
    result: dict[str, Any] = field(default_factory=dict)          # 最终结果
    

# ── TraceEvent 工厂方法 ─────────────────────────────────────────

def make_trace_event(
    step_id: str,
    step_name: str,
    status: str = "pending",
    summary: str = "",
    details: dict[str, Any] | None = None,
    duration_ms: float = 0.0,
    error: str | None = None,
) -> TraceEvent:
    """便捷创建 TraceEvent"""
    now = datetime.now(timezone.utc).isoformat()
    return TraceEvent(
        step_id=step_id,
        step_name=step_name,
        status=status,
        started_at=now if status in ("running",) else "",
        finished_at=now if status in ("success", "failed", "skipped") else "",
        duration_ms=duration_ms,
        summary=summary,
        details=details or {},
        error=error,
    )


def make_answerability(
    can_answer: bool = False,
    partial_answer: bool = False,
    reason: str = "",
    missing_items: list[str] | None = None,
    checks: dict[str, bool] | None = None,
) -> AnswerabilityResult:
    """便捷创建 AnswerabilityResult"""
    return AnswerabilityResult(
        can_answer=can_answer,
        partial_answer=partial_answer,
        reason=reason,
        missing_items=missing_items or [],
        checks=checks or {},
    )
