"""结构化字段与政策知识字段的统一指标、值域对齐。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from src.semantic_layer.models import Metric
from src.semantic_layer.registry import SemanticRegistry


AlignmentStatus = Literal["draft", "published", "rejected"]
SourceType = Literal["structured_field", "policy_knowledge"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


class MetricSourceBindingDraft(BaseModel):
    """将一个权威来源字段绑定到统一标准指标的草稿。"""

    metric_code: str = Field(min_length=3, max_length=256)
    source_type: SourceType
    source_ref: str = Field(min_length=1, max_length=512)
    source_field: str = Field(min_length=1, max_length=256)
    source_version: str = Field(min_length=1, max_length=128)
    evidence: str = Field(min_length=1)


class MetricSourceBinding(MetricSourceBindingDraft):
    binding_id: str
    status: AlignmentStatus = "draft"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class SourceValueMappingDraft(BaseModel):
    metric_code: str
    domain_code: str
    binding_id: str
    source_value: str
    standard_value: str


class SourceValueMapping(SourceValueMappingDraft):
    mapping_id: str
    status: AlignmentStatus = "draft"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class StandardValueProposalDraft(BaseModel):
    domain_code: str
    standard_value: str
    evidence: str
    source_ref: str


class StandardValueProposal(StandardValueProposalDraft):
    proposal_id: str
    status: AlignmentStatus = "draft"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class CreateMetricDraft(BaseModel):
    metric_code: str
    object_code: str
    name: str
    definition: str | None = None
    metric_type: str = "Atomic"
    semantic_type: str | None = None
    unit: str | None = None
    value_domain: str | None = None
    source_binding: MetricSourceBindingDraft


class SemanticAlignmentStore(Protocol):
    def save_binding(self, binding: MetricSourceBinding) -> MetricSourceBinding: ...
    def get_binding(self, binding_id: str) -> MetricSourceBinding | None: ...
    def list_bindings(self, metric_code: str) -> list[MetricSourceBinding]: ...
    def save_value_mapping(self, mapping: SourceValueMapping) -> SourceValueMapping: ...
    def get_value_mapping(self, mapping_id: str) -> SourceValueMapping | None: ...
    def save_standard_value_proposal(self, proposal: StandardValueProposal) -> StandardValueProposal: ...
    def get_standard_value_proposal(self, proposal_id: str) -> StandardValueProposal | None: ...


@dataclass
class InMemorySemanticAlignmentStore:
    """测试与本地回退使用的语义对齐存储。"""

    bindings: dict[str, MetricSourceBinding] = field(default_factory=dict)
    value_mappings: dict[str, SourceValueMapping] = field(default_factory=dict)
    standard_value_proposals: dict[str, StandardValueProposal] = field(default_factory=dict)

    def save_binding(self, binding: MetricSourceBinding) -> MetricSourceBinding:
        self.bindings[binding.binding_id] = binding.model_copy(deep=True)
        return self.bindings[binding.binding_id].model_copy(deep=True)

    def get_binding(self, binding_id: str) -> MetricSourceBinding | None:
        item = self.bindings.get(binding_id)
        return item.model_copy(deep=True) if item else None

    def list_bindings(self, metric_code: str) -> list[MetricSourceBinding]:
        return [
            item.model_copy(deep=True)
            for item in self.bindings.values()
            if item.metric_code == metric_code
        ]

    def save_value_mapping(self, mapping: SourceValueMapping) -> SourceValueMapping:
        self.value_mappings[mapping.mapping_id] = mapping.model_copy(deep=True)
        return self.value_mappings[mapping.mapping_id].model_copy(deep=True)

    def get_value_mapping(self, mapping_id: str) -> SourceValueMapping | None:
        item = self.value_mappings.get(mapping_id)
        return item.model_copy(deep=True) if item else None

    def save_standard_value_proposal(self, proposal: StandardValueProposal) -> StandardValueProposal:
        self.standard_value_proposals[proposal.proposal_id] = proposal.model_copy(deep=True)
        return self.standard_value_proposals[proposal.proposal_id].model_copy(deep=True)

    def get_standard_value_proposal(self, proposal_id: str) -> StandardValueProposal | None:
        item = self.standard_value_proposals.get(proposal_id)
        return item.model_copy(deep=True) if item else None


class SemanticAlignmentService:
    """统一指标和值域对齐的人工治理服务。"""

    def __init__(self, registry: SemanticRegistry, store: SemanticAlignmentStore) -> None:
        self._registry = registry
        self._store = store

    def bind_existing_metric(self, draft: MetricSourceBindingDraft) -> MetricSourceBinding:
        if self._registry.get_metric(draft.metric_code) is None:
            raise ValueError(f"标准指标不存在: {draft.metric_code}")
        binding_id = _stable_id(
            "mb",
            draft.metric_code,
            draft.source_type,
            draft.source_ref,
            draft.source_field,
            draft.source_version,
        )
        existing = self._store.get_binding(binding_id)
        if existing:
            return existing
        return self._store.save_binding(MetricSourceBinding(
            binding_id=binding_id,
            **draft.model_dump(),
        ))

    def approve_binding(self, binding_id: str, reviewed_by: str) -> MetricSourceBinding:
        binding = self._require_binding(binding_id)
        binding.status = "published"
        binding.reviewed_by = reviewed_by
        binding.reviewed_at = _now()
        return self._store.save_binding(binding)

    def list_metric_bindings(self, metric_code: str) -> list[MetricSourceBinding]:
        return self._store.list_bindings(metric_code)

    def create_metric_draft(self, request: CreateMetricDraft) -> Metric:
        if self._registry.get_object(request.object_code) is None:
            raise ValueError(f"语义对象不存在: {request.object_code}")
        if self._registry.get_metric(request.metric_code) is not None:
            raise ValueError(f"标准指标已存在: {request.metric_code}")
        if request.source_binding.metric_code != request.metric_code:
            raise ValueError("来源绑定的 metric_code 与待建指标不一致")
        metric = Metric(
            metric_code=request.metric_code,
            object_code=request.object_code,
            name=request.name,
            definition=request.definition,
            metric_type=request.metric_type,
            semantic_type=request.semantic_type,
            unit=request.unit,
            value_domain=request.value_domain,
            status="draft",
        )
        self._registry.save_metric_draft(metric)
        self.bind_existing_metric(request.source_binding)
        return metric

    def propose_value_mapping(self, draft: SourceValueMappingDraft) -> SourceValueMapping:
        metric = self._registry.get_metric(draft.metric_code)
        if metric is None:
            raise ValueError(f"标准指标不存在: {draft.metric_code}")
        binding = self._require_binding(draft.binding_id)
        if binding.metric_code != draft.metric_code:
            raise ValueError("来源绑定与标准指标不一致")
        domain = self._registry.get_value_domain(draft.domain_code)
        if domain is None:
            raise ValueError(f"标准值域不存在: {draft.domain_code}")
        if draft.standard_value not in domain.standard_values:
            raise ValueError("标准值尚未发布，请先提交新增标准值草稿")
        mapping_id = _stable_id("vm", draft.binding_id, draft.source_value)
        existing = self._store.get_value_mapping(mapping_id)
        if existing:
            return existing
        return self._store.save_value_mapping(SourceValueMapping(
            mapping_id=mapping_id,
            **draft.model_dump(),
        ))

    def approve_value_mapping(self, mapping_id: str, reviewed_by: str) -> SourceValueMapping:
        mapping = self._store.get_value_mapping(mapping_id)
        if mapping is None:
            raise ValueError(f"值域映射草稿不存在: {mapping_id}")
        mapping.status = "published"
        mapping.reviewed_by = reviewed_by
        mapping.reviewed_at = _now()
        return self._store.save_value_mapping(mapping)

    def resolve_source_value(self, binding_id: str, source_value: str) -> str:
        """按来源绑定解析标准值，避免不同系统的同名原始码互相覆盖。"""
        self._require_binding(binding_id)
        mapping_id = _stable_id("vm", binding_id, source_value)
        mapping = self._store.get_value_mapping(mapping_id)
        if mapping is None or mapping.status != "published":
            return source_value
        return mapping.standard_value

    def propose_standard_value(self, draft: StandardValueProposalDraft) -> StandardValueProposal:
        if self._registry.get_value_domain(draft.domain_code) is None:
            raise ValueError(f"标准值域不存在: {draft.domain_code}")
        proposal_id = _stable_id(
            "svp",
            draft.domain_code,
            draft.standard_value,
            draft.source_ref,
        )
        existing = self._store.get_standard_value_proposal(proposal_id)
        if existing:
            return existing
        return self._store.save_standard_value_proposal(StandardValueProposal(
            proposal_id=proposal_id,
            **draft.model_dump(),
        ))

    def approve_standard_value(self, proposal_id: str, reviewed_by: str) -> StandardValueProposal:
        proposal = self._store.get_standard_value_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"标准值草稿不存在: {proposal_id}")
        domain = self._registry.get_value_domain(proposal.domain_code)
        if domain is None:
            raise ValueError(f"标准值域不存在: {proposal.domain_code}")
        if proposal.standard_value not in domain.standard_values:
            domain.standard_values.append(proposal.standard_value)
            self._registry.save_value_domain(domain)
        proposal.status = "published"
        proposal.reviewed_by = reviewed_by
        proposal.reviewed_at = _now()
        return self._store.save_standard_value_proposal(proposal)

    def _require_binding(self, binding_id: str) -> MetricSourceBinding:
        binding = self._store.get_binding(binding_id)
        if binding is None:
            raise ValueError(f"来源绑定不存在: {binding_id}")
        return binding
