"""Pydantic models for Business Semantic Registry and Runtime."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Design Time Models ────────────────────────────────────────────

class BusinessDomain(BaseModel):
    """业务域 — 纯目录，不参与运行时计算。"""
    domain_code: str = Field(..., max_length=64, description="域编码")
    name: str = Field(..., max_length=128, description="中文名称")
    description: Optional[str] = Field(None, description="业务说明")
    sort_order: int = Field(default=0, description="排序")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ObjectRelation(BaseModel):
    """对象关系 — 不作为一级模型，是 Business Object 的属性。"""
    target: str = Field(..., description="目标对象编码")
    type: str = Field(..., description="关系类型，如 belongs_to, has, contains")
    cardinality: str = Field(default="N:1", description="基数，如 1:1, 1:N, N:1")


class BusinessObject(BaseModel):
    """业务对象 — Registry 中的核心实体描述。"""
    object_code: str = Field(..., max_length=64, description="对象编码，如 Settlement")
    domain_code: str = Field(..., max_length=64, description="所属业务域编码")
    name: str = Field(..., max_length=128, description="中文名称")
    definition: Optional[str] = Field(None, description="标准业务定义")
    identifier: Optional[str] = Field(None, description="业务主键，如 settlement_id")
    source_object: Optional[str] = Field(None, max_length=256, description="领域模型类名")
    source_adapter_port: Optional[str] = Field(None, max_length=256, description="适配器接口名")
    relations: list[ObjectRelation] = Field(default_factory=list, description="对象关系")
    version: str = Field(default="1.0", max_length=32)
    status: str = Field(default="draft", max_length=32, description="draft / published")
    current_version: Optional[str] = Field(
        None, description="当前已发布版本号（str）；None=从未发布")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Metric(BaseModel):
    """业务指标 — Business Object 的可消费属性。"""
    metric_code: str = Field(..., max_length=256, description="复合编码，如 Settlement.deductible")
    object_code: str = Field(..., max_length=64, description="所属 Business Object")
    name: str = Field(..., max_length=256, description="中文名称")
    definition: Optional[str] = Field(None, description="标准业务定义")
    metric_type: str = Field(default="Atomic", description="Atomic / Derived")
    semantic_type: Optional[str] = Field(None, description="Amount / Ratio / Enum / Date / Count")
    unit: Optional[str] = Field(None, max_length=64)
    required: bool = Field(default=False)
    default_value: Optional[Any] = Field(None)
    source_object: Optional[str] = Field(None, max_length=256, description="领域模型类名")
    source_field: Optional[str] = Field(None, max_length=256, description="领域模型属性名")
    source_adapter_port: Optional[str] = Field(None, max_length=256, description="适配器接口名")
    transformation: Optional[dict[str, Any]] = Field(None, description="Derived 指标的计算逻辑")
    value_domain: Optional[str] = Field(None, max_length=128, description="值域编码，枚举型指标时填写")
    importance: str = Field(default="optional", description="core / optional")
    usage_count: int = Field(default=0, description="Skill 引用次数")
    quality_score: float = Field(default=0.0, description="数据质量评分")
    version: str = Field(default="1.0", max_length=32)
    status: str = Field(default="draft", max_length=32)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ObjectVersionMetric(BaseModel):
    """版本快照中的指标 — Metric 的不可变字段子集。

    发布时从 Metric 冻结，之后不再随 live Metric 变化。
    """
    metric_code: str
    name: str
    definition: Optional[str] = None
    metric_type: str = "Atomic"
    semantic_type: Optional[str] = None
    unit: Optional[str] = None
    required: bool = False
    source_object: Optional[str] = None
    source_field: Optional[str] = None
    source_adapter_port: Optional[str] = None
    value_domain: Optional[str] = None
    importance: str = "optional"

    @classmethod
    def from_metric(cls, m: "Metric") -> "ObjectVersionMetric":
        return cls(
            metric_code=m.metric_code, name=m.name, definition=m.definition,
            metric_type=m.metric_type, semantic_type=m.semantic_type, unit=m.unit,
            required=m.required, source_object=m.source_object,
            source_field=m.source_field, source_adapter_port=m.source_adapter_port,
            value_domain=m.value_domain, importance=m.importance,
        )


class BusinessObjectVersion(BaseModel):
    """对象发布版本快照 — 不可变。

    冻结某次发布时的对象元数据 + 该对象全部指标。Skill 运行时锁定读取此快照（阶段3）。
    """
    version_id: str = Field(..., description="版本快照唯一ID（UUID）")
    object_code: str
    version: str = Field(..., description="发布版本号，递增整数 str（'1','2'...）")
    snapshot: dict[str, Any] = Field(..., description="对象元数据快照")
    metrics: list[ObjectVersionMetric] = Field(default_factory=list)
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_by: Optional[str] = None
    changelog: Optional[str] = None


class ValueDomain(BaseModel):
    """值域 — 统一不同系统的枚举编码。"""
    domain_code: str = Field(..., max_length=128, description="值域编码，如 HOSPITAL_LEVEL")
    name: str = Field(..., max_length=256, description="中文名称")
    description: Optional[str] = Field(None)
    standard_values: list[str] = Field(default_factory=list, description="标准值列表")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ValueDomainMapping(BaseModel):
    """值域映射明细。"""
    id: Optional[int] = Field(None)
    domain_code: str = Field(..., max_length=128)
    source_value: str = Field(..., max_length=512, description="来源系统原始值")
    standard_value: str = Field(..., max_length=512, description="平台标准值")
    description: Optional[str] = Field(None)


# ── Run Time Models ───────────────────────────────────────────────

class ObjectMetricRequest(BaseModel):
    """Skill 声明：需要哪个 Object 的哪些 Metric。"""
    object_code: str = Field(..., description="Business Object 编码")
    metric_codes: list[str] = Field(..., min_length=1, description="需要的 Metric 编码列表")


class BusinessFactsRequest(BaseModel):
    """Builder 输入：Skill 声明的需求 + 业务上下文。"""
    objects: list[ObjectMetricRequest]
    context: dict[str, Any] = Field(default_factory=dict, description="patient_id, encounter_id, settlement_id…")


class FactsMeta(BaseModel):
    """Business Facts 元数据。"""
    version: str = Field(default="1.0")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = Field(default_factory=list)


class BusinessFactsResponse(BaseModel):
    """Builder 输出：标准化 Business Facts。"""
    facts: dict[str, dict[str, Any]] = Field(default_factory=dict, description="按 Object 分组的标准化数据")
    meta: FactsMeta = Field(default_factory=FactsMeta)
