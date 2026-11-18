"""目录合规核验领域模型（Issue #85，限制性备注合规核验设计 V2.0 §4）。

规则以封闭 AST 表达、引用内部概念码；概念码经值域映射落到真实代码。
全部模型 frozen，规则发布后结构冻结。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FiniteAmount = Annotated[Decimal, Field(allow_inf_nan=False)]


class FieldReadStatus(StrEnum):
    PRESENT = "present"
    EMPTY = "empty"
    PLACEHOLDER = "placeholder"
    INVALID = "invalid"
    NOT_AVAILABLE = "not_available"
    FETCH_FAILED = "fetch_failed"
    AMBIGUOUS = "ambiguous"


class FieldObservation(BaseModel):
    """本次字段的取得质量；不代替条件核验结论。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: FieldReadStatus
    source: NonBlank
    association: Literal["same_line", "same_prescription", "same_settlement", "unknown"] = "unknown"
    reason: str = ""


class MatchStatus(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    NOT_EVALUATED = "not_evaluated"


class RuleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class RuleLookupStatus(StrEnum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    NOT_EVALUATED = "not_evaluated"
    AMBIGUOUS = "ambiguous"


class PriceBasis(StrEnum):
    UNKNOWN = "unknown"
    SALE_CEILING = "sale_ceiling"
    PAYMENT_STANDARD = "payment_standard"


class RestrictionConditionType(StrEnum):
    """限制条件类型（值域映射的挂载点）。"""
    DISEASE = "disease"            # 病种限制
    USAGE = "usage"                # 用途/检查限制
    INSTITUTION = "institution"    # 机构限制
    PRESCRIBER = "prescriber"      # 医师资质限制
    FILING = "filing"              # 备案限制
    PRICE_CAP = "price_cap"        # 支付标准限价
    POPULATION = "population"      # 人群限制（年龄/性别）


class ValueDomain(StrEnum):
    """内部标准值域。"""
    DIAGNOSIS = "diagnosis"
    PROCEDURE = "procedure"
    INSTITUTION_LEVEL = "institution_level"
    PRESCRIBER = "prescriber"
    POPULATION = "population"
    PRICE_UNIT = "price_unit"


class MappingScope(StrEnum):
    """映射作用域；解析优先级 hospital > regional > default。"""
    DEFAULT = "default"      # bjyb 基线
    REGIONAL = "regional"
    HOSPITAL = "hospital"


class MappingTargetType(StrEnum):
    """映射绑定的真实代码形态。"""
    ICD_PREFIX = "icd_prefix"            # 诊断编码前缀
    NAME_PATTERN = "name_pattern"        # 名称子串（诊断名/病历/收费项目名）
    DICT_CODE = "dict_code"              # 字典码（科室/职称等）
    PREDICATE = "predicate"              # 谓词参数（如 age>=18）
    SPEC_CONVERSION = "spec_conversion"  # 包装换算倍率（盒→限制单位的个数）


class VerdictStatus(StrEnum):
    """条件核验三态裁定（含不可核验）。"""
    SUPPORTED = "supported"                        # 有对应事实支持
    CONTRADICTED = "contradicted"                  # 有明确反证
    UNVERIFIABLE = "unverifiable"                  # 缺映射或缺数据源，无法核验
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # 资料不足，指明缺哪项


class ComplianceRiskTier(StrEnum):
    """行级风险分层。"""
    CONTRA = "contra"    # 明确反证 → 飞检自查候选
    SUSPECT = "suspect"  # 方向性疑点 → 重点人工复核
    REVIEW = "review"    # 资料不足 → 抽查建议
    CLEAR = "clear"      # 有支持 → 正常


class PriceCapSpec(BaseModel):
    """支付标准限价参数（来自 bz 原文，属规则而非映射）。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    unit: NonBlank
    strength_text: NonBlank
    basis: PriceBasis = PriceBasis.UNKNOWN


class RuleCondition(BaseModel):
    """单条原子限制条件。禁止自然语言裸条件：必须有概念码。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition_type: RestrictionConditionType = Field(validation_alias=AliasChoices("condition_type", "type"))
    concept_code: NonBlank = Field(validation_alias=AliasChoices("concept_code", "concept"))
    source_span: NonBlank
    price_cap: PriceCapSpec | None = None


class ConditionGroup(BaseModel):
    """条件组：组内任一满足（any_of），规则要求每组都满足（all_of）。

    覆盖实测 bz 形态"限：1.…；2.…。支付标准…"= 病种组(any_of) + 限价组。
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    conditions: Annotated[tuple[RuleCondition, ...], Field(min_length=1)]
    logic: Literal["any_of"] = "any_of"


class ComplianceRule(BaseModel):
    """合规验证规则（Aggregate Root）：一个受限项目一个目录版本一条。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: NonBlank
    item_code: NonBlank
    item_name: NonBlank
    catalog_effective_from: date
    catalog_effective_to: date
    condition_groups: Annotated[tuple[ConditionGroup, ...], Field(min_length=1)]
    source_bz: NonBlank
    revision: Annotated[int, Field(ge=1)] = 1
    status: RuleStatus = RuleStatus.DRAFT
    reviewed_by: str = ""
    catalog_source: str = ""

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        if self.catalog_effective_to < self.catalog_effective_from:
            raise ValueError("规则有效区间倒置")
        for group in self.condition_groups:
            for condition in group.conditions:
                if condition.condition_type == RestrictionConditionType.PRICE_CAP and condition.price_cap is None:
                    raise ValueError("价格条件缺少参数")
                if self.status == RuleStatus.PUBLISHED and condition.condition_type not in (
                    RestrictionConditionType.DISEASE, RestrictionConditionType.PRICE_CAP,
                ):
                    raise ValueError("未实现的核验器不能发布")
        if self.status == RuleStatus.PUBLISHED and not self.reviewed_by.strip():
            raise ValueError("发布规则须提供审核人")
        return self


class RuleLookupResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: RuleLookupStatus
    reason: NonBlank
    rule: ComplianceRule | None = None


class ValueDomainMapping(BaseModel):
    """值域映射：概念码 + 作用域 → 真实代码绑定。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    mapping_id: str
    domain: ValueDomain
    concept_code: str
    scope: MappingScope
    scope_key: str = ""     # hospital_code / region；default 为空
    target_type: MappingTargetType
    target_value: NonBlank
    source: str = "manual"  # 留痕：manual / official_pdf 等
    revision: Annotated[int, Field(ge=1)] = 1
    reviewed_by: str = ""


class DiagnosisFact(BaseModel):
    """同处方诊断事实。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str | None = None
    name: str | None = None
    medical_record: str = ""
    association: Literal["same_prescription", "same_settlement", "unknown"] = "unknown"


class SettlementLineContext(BaseModel):
    """规则核验的行级输入上下文（取数层装配，引擎只读）。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    hospital_code: str
    trade_date: date
    item_code: str
    item_name: str
    unit_price: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None
    count: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None
    specification: str | None = None
    fee: FiniteAmount
    fee_in: FiniteAmount
    fee_out: FiniteAmount
    same_recipe_diagnoses: tuple[DiagnosisFact, ...] = ()
    same_bill_item_names: tuple[str, ...] = ()
    section_name: str = ""
    dr_level: str = ""
    patient_birthday: date | None = None
    patient_sex: str = ""
    region_code: str = ""
    payment_base: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)] | None = None
    catalog_bz: str | None = None
    catalog_effective_from: date | None = None
    catalog_effective_to: date | None = None
    field_states: dict[str, FieldObservation] = Field(default_factory=dict)


class ConditionEvidence(BaseModel):
    """裁定证据：验证链路的可解释单元。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str       # diagnosis_match / price_check / mapping_missing / placeholder_input / ...
    summary: str    # 中文说明（含具体值）
    source: str     # 来源引用，如 o_Diagnose.DiagnoseCode=K27.400x004


class ConditionVerdict(BaseModel):
    """条件核验裁定：必须携带证据引用或缺失项说明。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: RuleCondition
    status: VerdictStatus
    evidence: tuple[ConditionEvidence, ...] = ()
    missing: str = ""       # 资料不足/不可核验时指明缺哪项
    match_status: MatchStatus = MatchStatus.NOT_EVALUATED
    used_mapping_ids: tuple[str, ...] = ()


class LineComplianceResult(BaseModel):
    """行级合规结果（Entity）：全部裁定 + 风险层 + 三分金额口径。"""
    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    rule_revision: int
    item_code: str
    item_name: str
    verdicts: tuple[ConditionVerdict, ...]
    risk_tier: ComplianceRiskTier
    fee: Decimal
    fee_in: Decimal
    fee_out: Decimal
    status: VerdictStatus
    rule_status: RuleStatus
    explanation_ready: bool
    engine_version: str = "1.1"
