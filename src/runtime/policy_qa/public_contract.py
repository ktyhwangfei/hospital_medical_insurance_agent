"""Policy QA 面向调用方的安全公开结果契约。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from src.runtime.policy_qa.fee_decomposition.explanation_evidence import FormulaInput, RuleChoiceGroup
from src.runtime.policy_qa.fee_decomposition.field_explanations import FieldExplanationView

from src.runtime.policy_qa.fee_decomposition.settlement_facts import SettlementFactsView
from src.runtime.policy_qa.fee_decomposition.fee_items import FeeItemExplanation


class PolicyCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    excerpt: str
    doc_id: str = ""
    source_excerpt: str = ""  # 命中单元的原文段落（溯源页高亮用）


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    settlement_checked: bool
    calculation_checked: bool
    policy_count: int = Field(ge=0)
    message: str


class PolicyQACaseContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_type: str | None = None
    insurance_type: str | None = None
    service_type: str | None = None
    hospital_level: str | None = None
    deductible: float | None = None
    yearly_cycle_count: int | None = None
    basic_pooling_payment: float | None = None
    basic_pooling_self_pay: float | None = None
    large_amount_payment: float | None = None
    large_amount_self_pay: float | None = None
    personal_total_pay: float | None = None
    total_amount: float | None = None
    query_scope: Literal[
        "whole_admission", "segment", "whole_settlement", "fee_item"
    ] | None = None
    segment_count: int | None = Field(default=None, ge=0)
    matched_segment_count: int | None = Field(default=None, ge=0)
    coverage_status: Literal["complete", "partial", "unavailable"] | None = None
    stay_start_date: str | None = None
    stay_end_date: str | None = None


class PolicyQACalculationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_name: str | None = None
    description: str | None = None
    label: str | None = None
    formula: str | None = None
    result: str | None = None
    calculation: str | None = None
    note: str | None = None


class PolicyQADefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    plain_text: str = ""
    includes: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    excerpt: str
    score: float | None = Field(default=None, allow_inf_nan=False)
    doc_id: str = ""


class OutpatientContextCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str | float | int | bool | None = None
    status: Literal["present", "missing"]


class OutpatientAmountCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    equation: str
    # 数值算式（带单位的操作数展示），与 Skill 内部 AmountCheck.detail 对齐
    detail: str | None = None
    actual: float | None = None
    expected: float | None = None
    difference: float | None = None
    tolerance: float
    status: Literal["passed", "failed", "not_evaluable"]


class OutpatientFieldExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    value: float | None = None
    state: Literal["non_zero", "reported_zero", "missing", "not_applicable"]
    applicable: bool | None = None
    explanation: str
    citations: list[str] = Field(min_length=1)


class DecompositionOperandView(BaseModel):
    """计算操作数公开视图：统一中文展示名 + 有符号十进制值；中间量显式标识。"""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    value: str
    is_intermediate: bool = False
    input_ref: str | None = None
    calculation_ref: str | None = None


class DecompositionCalculationView(BaseModel):
    """单条计算记录公开视图（解释投影 1.1；不暴露内部物理引用）。"""

    model_config = ConfigDict(extra="forbid")

    calculation_id: str
    formula: str | None = Field(default=None, exclude_if=lambda value: value is None)
    display_name: str
    formula_id: str
    formula_version: str
    # 算式布局：sum=操作数带符号相连；subtract_rest=首项减其余；product=基数×比例；generic=逐项列出
    layout: Literal["sum", "subtract_rest", "product", "generic"] = "generic"
    operands: list[DecompositionOperandView] = Field(default_factory=list)
    unrounded_result: str | None = None
    rounding_rule: str | None = None
    result: str | None = None
    verification_status: Literal["verified", "unverified", "missing", "conflict"] = "unverified"
    verification_reason: str | None = None
    explainable: bool = False


class DecompositionSourceView(BaseModel):
    """来源公开视图：仅业务安全信息；内部快照路径/未批准文本不进入。"""

    model_config = ConfigDict(extra="forbid")

    ref_id: str
    title: str
    category: Literal["settlement_record", "policy_basis"]
    confirmation_status: str | None = None
    value: str | None = None
    values: list[str] = Field(default_factory=list)
    link: str | None = None


class DecompositionConditionView(BaseModel):
    """采用条件公开视图：业务描述 + 实际/期望展示值 + 判断结果。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    module_label: str
    description: str
    actual_display: str | None = None
    expected_display: str | None = None
    outcome: str
    calculation_refs: list[str] = Field(default_factory=list)


class AmountSemanticsView(BaseModel):
    """金额口径：谁的钱、什么范围、能否与重算值直接比较（Issue #84 第 2 项）。"""

    model_config = ConfigDict(extra="forbid")

    owner: Literal["patient_benefit", "hospital_settlement", "book_record"] = "patient_benefit"
    owner_text: str = "患者待遇"
    scope: Literal["trade", "cycle"] = "trade"
    scope_text: str = "本笔"
    comparable: bool = False
    text: str = ""


class FieldBasisView(BaseModel):
    """字段依据链：计算、输入、规则组、规则与来源标题（Issue #84 第 3 项）。"""

    model_config = ConfigDict(extra="forbid")

    calculation_ids: list[str] = Field(default_factory=list)
    input_ids: list[str] = Field(default_factory=list)
    rule_group_ids: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    source_titles: list[str] = Field(default_factory=list)


class TraceView(BaseModel):
    """追溯元数据：公开结果用安全编号关联审计侧完整轨迹（Issue #84 第 4 项）。"""

    model_config = ConfigDict(extra="forbid")

    algorithm_version: str
    settlement_ref: str
    evidence_id: str
    rule_versions: list[str] = Field(default_factory=list)
    branch_count: int = 0
    full_trace_in_public: bool = False


class DecompositionStageView(BaseModel):
    """业务环节完整性：按环节说明已验证什么、采用什么前提、还缺什么（Issue #84 第 5 项）。"""

    model_config = ConfigDict(extra="forbid")

    stage_id: str
    label: str
    status: Literal["verified", "partial", "unavailable", "not_applicable"] = "unavailable"
    verified: list[str] = Field(default_factory=list)
    premise: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class DecompositionFieldView(BaseModel):
    """费用分解单字段公开视图（设计 §10/§11；金额为十进制字符串）。"""

    model_config = ConfigDict(extra="forbid")

    field_code: str
    label: str
    check_type: str
    check_status: str
    observed_amount: str | None = None
    calculated_amount: str | None = None
    difference: str | None = None
    explanation_level: str
    # 解释投影 1.1 增补：reason 与精确引用关联 + 确定性构成简述
    reason_code: str | None = None
    calculation_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    gap_refs: list[str] = Field(default_factory=list)
    brief: str | None = None
    explainable: bool = False
    explanation_reason: str | None = None
    # 解释投影 1.9 增补（Issue #84）：结论分级、金额口径、依据链
    conclusion: Literal["book_only", "reconciled", "recalculated", "basis_confirmed", "unexplained"] = "unexplained"
    conclusion_text: str = ""
    amount_semantics: AmountSemanticsView | None = None
    basis: FieldBasisView | None = None
    # 解释投影 1.10（阶段 B）：字段四要素固定说明（含义/构成/本单依据/解释边界，
    # 服务端确定性生成，缺项在 boundary 显式声明）
    explanation: FieldExplanationView | None = None


class DecompositionUncertaintyView(BaseModel):
    """费用分解不确定性公开视图（缺规则/缺数据显式列出）。"""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    # 解释投影 1.1 增补：精确关联 ID 与受影响字段
    id: str = ""
    affected_fields: list[str] = Field(default_factory=list)
    # 解释投影 1.9：缺口影响范围；global 表示未能定位到具体金额
    scope: Literal["field", "global"] = "field"


class DecompositionCoverageView(BaseModel):
    """费用分解覆盖统计（设计 §11 coverage）。"""

    model_config = ConfigDict(extra="forbid")

    target_field_count: int = Field(ge=0)
    independently_explained_count: int = Field(ge=0)
    amount_reconciled_count: int = Field(ge=0)
    observed_only_count: int = Field(ge=0)


class DecompositionPathStep(BaseModel):
    """正向结算路径单步公开视图（解释投影 1.2）。

    status：applied=已结算出金额；zero_amount=已结算但金额为零（零金额≠不适用）；
    not_applicable=本单不适用；unknown=无法确定；observed_only=仅账面观测值。
    amount 为该步结算金额（十进制字符串）；一步多个金额时为 None，
    各金额由 field_refs 展开（后端不加总出新数）。
    """

    model_config = ConfigDict(extra="forbid")

    step_id: str
    condition_refs: list[str] = Field(default_factory=list, exclude_if=lambda value: not value)
    name: str
    status: Literal["applied", "zero_amount", "not_applicable", "unknown", "observed_only"]
    amount: str | None = None
    calculation_refs: list[str] = Field(default_factory=list)
    field_refs: list[str] = Field(default_factory=list)
    reason: str | None = None


class FeeDecompositionPublic(BaseModel):
    """结算费用分解公开结果（Issue #78，schema 版本化；不含审计级分支/计算细节）。

    公开投影 1.1：在保留原金额字段的基础上增补 calculations/sources/conditions
    与字段级引用关联；内部结果 schema_version 仍保持 1.0。
    公开投影 1.2：增补 settlement_facts（结算事实侧车）与 path_steps（正向结算
    路径）；两者可选缺省，旧 1.1 载荷（无两新块）仍可校验。
    公开投影 1.10（阶段 B）：字段级 explanation（四要素固定说明）与
    template_explanations（按模板 key 索引，覆盖内核未产出的展示字段）。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    formula_inputs: list[FormulaInput] = Field(default_factory=list, exclude_if=lambda value: not value)
    rule_choices: list[RuleChoiceGroup] = Field(default_factory=list, exclude_if=lambda value: not value)
    fee_items: list[FeeItemExplanation] = Field(default_factory=list, exclude_if=lambda value: not value)
    algorithm_version: str
    execution_status: Literal["complete", "partial", "unavailable"]
    reconciliation_status: str
    summary_text: str = ""
    summary_source: Literal["template", "model"] = "template"
    may_claim_full_explanation: bool = False
    fields: list[DecompositionFieldView] = Field(default_factory=list)
    uncertainties: list[DecompositionUncertaintyView] = Field(default_factory=list)
    coverage: DecompositionCoverageView | None = None
    calculations: list[DecompositionCalculationView] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    sources: list[DecompositionSourceView] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    conditions: list[DecompositionConditionView] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    settlement_facts: SettlementFactsView | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    path_steps: list[DecompositionPathStep] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    stages: list[DecompositionStageView] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    trace: TraceView | None = Field(default=None, exclude_if=lambda value: value is None)
    # 解释投影 1.10（阶段 B）：模板展示字段四要素固定说明，按模板 key 索引
    # （覆盖内核未产出分解记录的展示字段，如 beyond_cap；面板模板视图按 key 就地展开）
    template_explanations: dict[str, FieldExplanationView] = Field(
        default_factory=dict, exclude_if=lambda value: not value,
    )


class PolicyQAPublicResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    answer_status: Literal["complete", "partial", "unavailable"]
    case_context: PolicyQACaseContext | None = None
    calculation_steps: list[PolicyQACalculationStep] = Field(default_factory=list)
    definition: PolicyQADefinition | None = None
    warnings: list[str] = Field(default_factory=list)
    policy_evidence: list[PolicyEvidence] = Field(default_factory=list)
    citations: list[PolicyCitation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    verification_summary: VerificationSummary
    is_broad: bool = False
    scenario_id: str | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    context_checks: list[OutpatientContextCheck] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    amount_checks: list[OutpatientAmountCheck] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    field_explanations: list[OutpatientFieldExplanation] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    anomalies: list[str] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    next_actions: list[str] = Field(
        default_factory=list, exclude_if=lambda value: not value,
    )
    action_status: Literal["waiting_human_confirmation"] | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
    fee_decomposition: FeeDecompositionPublic | None = Field(
        default=None, exclude_if=lambda value: value is None,
    )
