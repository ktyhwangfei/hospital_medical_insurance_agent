"""
指标领域模型 - 语义层的纯数据模型定义

包含 IndicatorDefinition（Entity）、IndicatorValue（Value Object）、
IndicatorContext（Value Object）、DictionaryEntry（Value Object）等。

v3.0 新增：BusinessObject（L1）、MetricFormula（Metric Layer）、
SemanticMapping（CRUD 管理）、IndicatorSource 增强（L3 数据源映射）。

遵循 DDD 分层，对标 domain/skill/models.py 的 Pydantic BaseModel + field_validator 模式。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class IndicatorCategory(StrEnum):
    """指标语义分类"""
    DIMENSION = "dimension"      # 维度指标：用于过滤和路由（如 insu_type, med_type）
    NUMERIC = "numeric"          # 数值指标：用于对标和计算（如 deductible_amount）
    CONDITION = "condition"      # 条件指标：规则适用条件（如 amount_band）
    META = "meta"                # 元指标：规则本身属性（如 rule_id, source_text）


class ProcessingType(StrEnum):
    """加工类型（来自数据模型1 政策规则表）"""
    TOKENIZE = "分词"            # 文本分词（如 "城镇职工" → 拆分为可检索 token）
    RAW = "raw"                  # 原值不动


@dataclass(frozen=True)
class IndicatorSource:
    """指标取值来源（Value Object）— L3 数据层映射"""
    type: str = "sql"            # "sql" | "adapter" | "milvus" | "derived"
    # L3 显式化数据源映射（v3.0 新增，向后兼容）
    data_source: str = ""        # 数据源名称："sqlserver_yb" | "his" | "emr"
    table_name: str = ""         # 表名："yb_settlement"
    field_name: str = ""         # 物理字段名："TCZF_PAY"
    # 保留原有
    adapter: str | None = None
    sql_template: str | None = None
    sql_params: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NormalizationRule:
    """标准化规则（Value Object）"""
    field_name_mapping: dict[str, str] = field(default_factory=dict)
    dictionary_ref: str | None = None       # 引用字典类别名
    dictionary_path: str | None = None      # 字典文件路径
    unit_scale: float = 1.0                 # 单位缩放系数
    validation_min: float | None = None     # 最小值校验
    validation_max: float | None = None     # 最大值校验
    required: bool = False                  # 是否必填


class MetricFormula(BaseModel):
    """结构化计算公式 — Metric Layer（v3.0 新增）

    将 computation 字符串增强为结构化公式定义，
    支持 expression + dependencies + type 的显式声明。
    参考 dbt Semantic Layer / MetricFlow 设计思想。
    """
    expression: str                     # "total_fee - self_fee - first_pay_fee"
    dependencies: list[str] = Field(default_factory=list)
    type: str = "arithmetic"            # "arithmetic" | "conditional" | "ratio" | "aggregation"


class IndicatorDefinition(BaseModel):
    """指标定义（Entity）

    静态元数据，对应 Excel 政策规则表的一行。
    使用 Pydantic BaseModel + field_validator，类似 domain/skill/models.py 的 Skill。
    """
    indicator_id: str
    name: str                                # 中文名（AI 看到的名称）
    business_object: str = ""                # L1 归属："Settlement" | "Patient" | "Hospital" | "Policy"
    description: str = ""                    # 业务说明
    category: IndicatorCategory = IndicatorCategory.META
    value_type: str = "string"               # "float" | "int" | "string" | "enum"
    unit: str = ""                           # "元" | "%" | "次" | ""
    processing_type: ProcessingType = ProcessingType.RAW
    is_nested: bool = False                  # 是否嵌套（如 psn_type 包含多种人群）

    # 取值来源
    source: IndicatorSource = Field(default_factory=IndicatorSource)
    # 标准化规则
    normalization: NormalizationRule = Field(default_factory=NormalizationRule)
    # 语义标签（用于 LLM 理解和关键词匹配）
    semantic_tags: list[str] = Field(default_factory=list)
    # 依赖关系（派生指标用）
    depends_on: list[str] = Field(default_factory=list)
    computation: str | None = None
    formula: MetricFormula | None = None    # 结构化公式（v3.0 新增）

    # 政策检索相关字段
    policy_field: str = ""                   # 对应 Milvus policy_rules 集合中的字段名
    use_in_filter: bool = False              # 是否用于标量过滤
    use_in_embedding: bool = False           # 是否用于向量嵌入
    embedding_template: str = ""             # 嵌入模板（如 "险种：{value}"）
    filter_op: str = "=="                    # 过滤操作符

    # 技能关联
    used_by_strategies: list[str] = Field(default_factory=list)

    @field_validator("indicator_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        """指标ID不能为空"""
        if not value or not value.strip():
            raise ValueError("指标ID不能为空")
        return value.strip()

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        """指标名称不能为空"""
        if not value or not value.strip():
            raise ValueError("指标名称不能为空")
        return value.strip()


class IndicatorValue(BaseModel):
    """指标值（Value Object）

    运行时实例，每次查询生成。包含取值和元数据（来源、置信度、时间戳）。
    """
    definition_id: str           # 关联的 IndicatorDefinition.indicator_id
    value: Any = None            # 标准化后的值
    raw_value: Any = None        # 原始值（未标准化）
    unit: str = ""               # 单位（覆盖定义中的默认单位）
    source: str = ""             # "sql" | "adapter" | "milvus" | "derived"
    confidence: float = 1.0      # 置信度 0.0~1.0
    timestamp: datetime = Field(default_factory=datetime.now)
    context: dict[str, Any] = Field(default_factory=dict)  # 取值的附加上下文


class IndicatorContext(BaseModel):
    """指标上下文（Value Object）

    某次查询的完整指标快照。包含所有已取值、缺失指标列表和质量状态。
    """
    patient_id: str = ""
    encounter_id: str = ""
    settlement_id: str = ""
    indicators: dict[str, IndicatorValue] = Field(default_factory=dict)
    missing_indicators: list[str] = Field(default_factory=list)
    quality: str = "complete"    # "complete" | "degraded" | "missing"
    confidence: float = 1.0      # 整体置信度


class DictionaryEntry(BaseModel):
    """标准化字典条目（Value Object）

    对应 Excel 字典 Sheet 的一行。包含标准值、同义词列表和业务描述。
    用于将外部系统值（如 "310"）标准化为统一值（如 "城镇职工"）。
    """
    category: str                # 字典类别（"险种类别" / "医疗类别" / ...）
    standard_value: str          # 标准化后的值
    synonyms: list[str] = Field(default_factory=list)   # 同义词列表
    description: str = ""        # 业务描述
    code: str | None = None      # 外部系统代码（可选）


# ── v3.0 新增模型 ──

class BusinessObject(BaseModel):
    """业务对象定义 — L1 业务对象层（v3.0 新增）

    定义医保业务中的核心业务对象（患者、结算记录、医疗机构、医保政策）。
    每个业务对象是一组相关指标的容器，为语义层提供顶层组织维度。
    """
    object_id: str                    # "Settlement" | "Patient" | "Hospital" | "Policy"
    name: str                         # 中文名："结算记录"
    description: str = ""             # 业务说明
    fields: list[str] = Field(default_factory=list)  # 该对象包含的 indicator_id 列表


class SemanticMapping(BaseModel):
    """语义映射条目 — 可 CRUD 管理的口语→术语映射（v3.0 新增）

    用于将用户口语（如 "三甲医院"）标准化为系统术语（如 "三级"）。
    通过 CRUD API 和 Admin UI 进行可视化管理，替代原有的硬编码 DEFAULT_MAPPING。
    """
    mapping_id: str                    # 唯一标识，如 "hosp_lv_001"
    category: str                      # 映射分类："hospital_level" | "insurance_type" | ...
    raw_value: str                     # 用户口语值，如 "三甲医院"
    normalized_value: str              # 系统标准值，如 "三级"
    synonyms: list[str] = Field(default_factory=list)  # 同义词列表
    confidence: float = 1.0            # 映射置信度 0.0~1.0
    source: str = "manual"             # "manual" | "imported" | "auto_learned"
    enabled: bool = True               # 是否启用
    description: str = ""              # 业务说明
    created_at: str = ""               # ISO 时间戳（创建时填写）
    updated_at: str = ""               # ISO 时间戳（更新时填写）
