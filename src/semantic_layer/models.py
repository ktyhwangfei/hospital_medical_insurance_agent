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
