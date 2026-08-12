"""结构化字段与政策知识字段的统一指标、值域对齐。"""
from __future__ import annotations

import hashlib
import os
import uuid
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from threading import RLock
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from src.domain.indicator.models import MetricFormula
from src.security.desensitization.detection import detect_sensitive_patterns
from src.semantic_layer.models import Metric
from src.semantic_layer.models import ValueDomain, ValueDomainMapping
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
    binding_id: str = ""
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
    metric_kind: str = "field"
    indexed: bool = False
    extraction_hint: str | None = None
    schema_version: int = Field(default=1, ge=1)
    source_binding: MetricSourceBindingDraft | None = None


class TriggerSource(StrEnum):
    EXTRACTION_UNKNOWN = "EXTRACTION_UNKNOWN"
    DEMAND_GAP = "DEMAND_GAP"
    DATA_SCAN = "DATA_SCAN"
    DERIVATION_PATTERN = "DERIVATION_PATTERN"


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    REVIEWING = "reviewing"
    ACCEPTED = "accepted"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ProposalType(StrEnum):
    METRIC = "metric"
    VALUE = "value"


class DiscoveryEvidence(BaseModel):
    """主动发现证据；四类信号共用的结构化超集。"""

    source_ref: str
    excerpt: str | None = None
    doc_id: str | None = None
    unit_id: str | None = None
    extraction_id: str | None = None
    occurrence_count: int = Field(default=1, ge=1)
    gap_signature: str | None = None
    representative_questions: list[str] = Field(default_factory=list)
    table_name: str | None = None
    field_name: str | None = None
    sample_values: list[str] = Field(default_factory=list)
    non_null_rate: float | None = None
    distinct_count: int | None = None
    base_metric_code: str | None = None
    operator: str | None = None
    observations: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)


class DiscoverySignal(BaseModel):
    trigger_source: TriggerSource
    evidence: DiscoveryEvidence
    object_code: str = "zcgz"
    concept: str = Field(min_length=1)
    metric_code: str | None = None
    metric_name: str | None = None
    definition: str | None = None
    metric_type: str = "Atomic"
    semantic_type: str | None = None
    unit: str | None = None
    value_domain: str | None = None
    metric_kind: str = "field"
    indexed: bool = False
    extraction_hint: str | None = None
    schema_version: int = Field(default=1, ge=1)
    axis_metric_code: str | None = None
    domain_code: str | None = None
    alias_target: str | None = None
    suggested_mappings: list[SourceValueMappingDraft] = Field(default_factory=list)
    formula: MetricFormula | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_trigger_evidence(self) -> "DiscoverySignal":
        evidence = self.evidence
        valid = {
            TriggerSource.EXTRACTION_UNKNOWN: bool(
                evidence.doc_id and evidence.unit_id and evidence.extraction_id and evidence.excerpt
            ),
            TriggerSource.DEMAND_GAP: bool(
                evidence.gap_signature
                and any(question.strip() for question in evidence.representative_questions)
            ),
            TriggerSource.DATA_SCAN: bool(
                evidence.table_name and evidence.field_name
                and evidence.non_null_rate is not None
                and evidence.distinct_count is not None
            ),
            TriggerSource.DERIVATION_PATTERN: bool(
                evidence.base_metric_code and evidence.operator
                and len(evidence.observations) >= 2 and evidence.rule_ids
            ),
        }[self.trigger_source]
        if not valid:
            raise ValueError(f"{self.trigger_source} evidence 不完整")
        return self


class SemanticProposal(BaseModel):
    proposal_id: str
    fingerprint: str
    proposal_type: ProposalType
    trigger_source: TriggerSource
    status: ProposalStatus = ProposalStatus.PROPOSED
    concept: str
    object_code: str = "zcgz"
    axis_metric_code: str | None = None
    metric_draft: CreateMetricDraft | None = None
    value_draft: StandardValueProposalDraft | None = None
    suggested_mappings: list[SourceValueMappingDraft] = Field(default_factory=list)
    mapping_only: bool = False
    formula: MetricFormula | None = None
    evidence: list[DiscoveryEvidence]
    confidence: float = Field(ge=0.0, le=1.0)
    occurrence_count: int = Field(ge=1)
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


def _merge_semantic_proposals(
    existing: SemanticProposal, incoming: SemanticProposal
) -> SemanticProposal:
    """同证据来源做替换，不把重跑次数累计成多源可信度。"""
    merged = existing.model_copy(deep=True)
    evidence_by_source = {item.source_ref: item for item in merged.evidence}
    new_sources = {
        item.source_ref for item in incoming.evidence
        if item.source_ref not in evidence_by_source
    }
    for item in incoming.evidence:
        evidence_by_source[item.source_ref] = item
    merged.evidence = list(evidence_by_source.values())
    merged.occurrence_count = sum(
        item.occurrence_count for item in merged.evidence
    )
    if new_sources:
        merged.confidence = min(1.0, merged.confidence + incoming.confidence)

    known_mappings = {
        (item.domain_code, item.binding_id, item.source_value)
        for item in merged.suggested_mappings
    }
    merged.suggested_mappings.extend(
        item for item in incoming.suggested_mappings
        if (item.domain_code, item.binding_id, item.source_value) not in known_mappings
    )
    merged.updated_at = incoming.updated_at
    return merged


def _landing_target_keys(proposal: SemanticProposal) -> list[str]:
    """一个正式落地目标只能由一个 proposal 声明。"""
    if proposal.proposal_type == ProposalType.METRIC:
        return [f"metric:{proposal.metric_draft.metric_code}"] if proposal.metric_draft else []
    if proposal.value_draft is None:
        return []
    keys: set[str] = set()
    if not proposal.mapping_only:
        keys.add(
            f"standard-value:{proposal.value_draft.domain_code}:{proposal.value_draft.standard_value}"
        )
    keys.update(
        f"value-mapping:{proposal.axis_metric_code}:{mapping.domain_code}:{mapping.source_value}"
        for mapping in proposal.suggested_mappings
    )
    return sorted(keys)


def _landing_lock_keys(proposal: SemanticProposal) -> list[str]:
    keys = set(_landing_target_keys(proposal))
    if proposal.proposal_type == ProposalType.VALUE and proposal.value_draft:
        # 串行同值域 JSON 数组的读-改-写，但不独占整个值域的未来提议。
        keys.add(f"value-domain:{proposal.value_draft.domain_code}")
    return sorted(keys)


class SemanticAlignmentStore(Protocol):
    def save_binding(self, binding: MetricSourceBinding) -> MetricSourceBinding: ...
    def get_binding(self, binding_id: str) -> MetricSourceBinding | None: ...
    def list_bindings(self, metric_code: str) -> list[MetricSourceBinding]: ...
    def save_value_mapping(self, mapping: SourceValueMapping) -> SourceValueMapping: ...
    def get_value_mapping(self, mapping_id: str) -> SourceValueMapping | None: ...
    def save_standard_value_proposal(self, proposal: StandardValueProposal) -> StandardValueProposal: ...
    def get_standard_value_proposal(self, proposal_id: str) -> StandardValueProposal | None: ...
    def save_proposal(self, proposal: SemanticProposal) -> SemanticProposal: ...
    def merge_proposal(self, proposal: SemanticProposal) -> SemanticProposal: ...
    def compare_and_set_proposal(
        self, proposal: SemanticProposal, expected_status: ProposalStatus,
    ) -> SemanticProposal | None: ...
    def lock_proposal(self, proposal_id: str) -> SemanticProposal | None: ...
    def lock_and_claim_landing_targets(self, proposal: SemanticProposal) -> None: ...
    def get_proposal(self, proposal_id: str) -> SemanticProposal | None: ...
    def get_proposal_by_fingerprint(self, fingerprint: str) -> SemanticProposal | None: ...
    def list_proposals(
        self, proposal_type: ProposalType | None = None,
        status: ProposalStatus | None = None,
    ) -> list[SemanticProposal]: ...


@dataclass
class InMemorySemanticAlignmentStore:
    """测试与本地回退使用的语义对齐存储。"""

    bindings: dict[str, MetricSourceBinding] = field(default_factory=dict)
    value_mappings: dict[str, SourceValueMapping] = field(default_factory=dict)
    standard_value_proposals: dict[str, StandardValueProposal] = field(default_factory=dict)
    proposals: dict[str, SemanticProposal] = field(default_factory=dict)
    landing_target_claims: dict[str, str] = field(default_factory=dict)
    _operation_lock: RLock = field(default_factory=RLock, repr=False)

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

    def save_proposal(self, proposal: SemanticProposal) -> SemanticProposal:
        self.proposals[proposal.proposal_id] = proposal.model_copy(deep=True)
        return self.proposals[proposal.proposal_id].model_copy(deep=True)

    def merge_proposal(self, proposal: SemanticProposal) -> SemanticProposal:
        with self._operation_lock:
            existing = self.get_proposal_by_fingerprint(proposal.fingerprint)
            if existing is None:
                return self.save_proposal(proposal)
            return self.save_proposal(_merge_semantic_proposals(existing, proposal))

    def compare_and_set_proposal(
        self, proposal: SemanticProposal, expected_status: ProposalStatus,
    ) -> SemanticProposal | None:
        current = self.proposals.get(proposal.proposal_id)
        if current is None or current.status != expected_status:
            return None
        return self.save_proposal(proposal)

    def lock_proposal(self, proposal_id: str) -> SemanticProposal | None:
        return self.get_proposal(proposal_id)

    @contextmanager
    def registry_transaction(self, registry_store: object):
        with self._operation_lock:
            snapshot = deepcopy((
                self.bindings,
                self.value_mappings,
                self.standard_value_proposals,
                self.proposals,
                self.landing_target_claims,
            ))
            transaction = getattr(registry_store, "transaction", None)
            context = transaction() if transaction else nullcontext()
            try:
                with context:
                    yield
            except Exception:
                (
                    self.bindings,
                    self.value_mappings,
                    self.standard_value_proposals,
                    self.proposals,
                    self.landing_target_claims,
                ) = snapshot
                raise

    def lock_and_claim_landing_targets(self, proposal: SemanticProposal) -> None:
        with self._operation_lock:
            keys = _landing_target_keys(proposal)
            if any(
                self.landing_target_claims.get(key) not in {None, proposal.proposal_id}
                for key in keys
            ):
                raise ValueError("落地目标已被其他提议占用")
            self.landing_target_claims.update({key: proposal.proposal_id for key in keys})

    def get_proposal(self, proposal_id: str) -> SemanticProposal | None:
        item = self.proposals.get(proposal_id)
        return item.model_copy(deep=True) if item else None

    def get_proposal_by_fingerprint(self, fingerprint: str) -> SemanticProposal | None:
        return next(
            (item.model_copy(deep=True) for item in self.proposals.values()
             if item.fingerprint == fingerprint
             and item.status in {
                 ProposalStatus.PROPOSED,
                 ProposalStatus.REVIEWING,
                 ProposalStatus.ACCEPTED,
             }),
            None,
        )

    def list_proposals(
        self, proposal_type: ProposalType | None = None,
        status: ProposalStatus | None = None,
    ) -> list[SemanticProposal]:
        return [
            item.model_copy(deep=True) for item in self.proposals.values()
            if (proposal_type is None or item.proposal_type == proposal_type)
            and (status is None or item.status == status)
        ]


class SemanticAlignmentService:
    """统一指标和值域对齐的人工治理服务。"""

    def __init__(self, registry: SemanticRegistry, store: SemanticAlignmentStore) -> None:
        self._registry = registry
        self._store = store
        self._proposal_lock = RLock()

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
        if request.source_binding is None:
            raise ValueError("新建指标草稿必须包含来源绑定")
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
            metric_kind=request.metric_kind,
            indexed=request.indexed,
            extraction_hint=request.extraction_hint,
            schema_version=request.schema_version,
            status="draft",
        )
        self._registry.save_metric_draft(metric)
        self.bind_existing_metric(request.source_binding)
        return metric

    def intake_signal(self, signal: DiscoverySignal) -> SemanticProposal:
        """将主动信号路由为指标或值域提议，并合并同概念证据。"""
        if detect_sensitive_patterns(signal.model_dump_json()):
            raise ValueError("证据包含敏感信息，请脱敏后重试")

        metric = (
            self._registry.get_metric(signal.axis_metric_code)
            if signal.axis_metric_code else None
        )
        domain = (
            self._registry.get_value_domain(signal.domain_code)
            if signal.domain_code else None
        )
        if metric and metric.semantic_type == "Enum":
            domain = self._registry.get_value_domain(metric.value_domain or "")
        is_value = metric is not None and metric.semantic_type == "Enum" and domain is not None
        proposal_type = ProposalType.VALUE if is_value else ProposalType.METRIC
        if is_value and signal.alias_target and signal.alias_target not in domain.standard_values:
            raise ValueError(f"别名目标不是已有标准值: {signal.alias_target}")
        target = signal.alias_target or signal.concept
        mapping_only = bool(
            is_value
            and (signal.alias_target is not None or signal.concept in domain.standard_values)
        )
        incoming_mappings = list(signal.suggested_mappings)
        if mapping_only and not incoming_mappings:
            incoming_mappings.append(SourceValueMappingDraft(
                metric_code=metric.metric_code,
                domain_code=domain.domain_code,
                source_value=signal.concept,
                standard_value=target,
            ))
        fingerprint = self._proposal_fingerprint(signal, proposal_type, domain.domain_code if domain else None)
        existing = self._store.get_proposal_by_fingerprint(fingerprint)
        if existing:
            delta = existing.model_copy(deep=True, update={
                "evidence": [signal.evidence],
                "confidence": signal.confidence,
                "occurrence_count": signal.evidence.occurrence_count,
                "suggested_mappings": incoming_mappings,
                "updated_at": _now(),
            })
            return self._store.merge_proposal(delta)

        if proposal_type == ProposalType.VALUE:
            mappings = incoming_mappings
            value_draft = StandardValueProposalDraft(
                domain_code=domain.domain_code,
                standard_value=target,
                evidence=signal.evidence.excerpt or signal.concept,
                source_ref=signal.evidence.source_ref,
            )
            metric_draft = None
        else:
            mapping_only = False
            mappings = []
            value_draft = None
            metric_draft = CreateMetricDraft(
                metric_code=signal.metric_code or "",
                object_code=signal.object_code,
                name=signal.metric_name or signal.concept,
                definition=signal.definition,
                metric_type=signal.metric_type,
                semantic_type=signal.semantic_type,
                unit=signal.unit,
                value_domain=signal.value_domain,
                metric_kind=signal.metric_kind,
                indexed=signal.indexed,
                extraction_hint=signal.extraction_hint,
                schema_version=signal.schema_version,
            )

        return self._store.merge_proposal(SemanticProposal(
            proposal_id=f"sp_{uuid.uuid4().hex}",
            fingerprint=fingerprint,
            proposal_type=proposal_type,
            trigger_source=signal.trigger_source,
            concept=signal.concept,
            object_code=signal.object_code,
            axis_metric_code=signal.axis_metric_code,
            metric_draft=metric_draft,
            value_draft=value_draft,
            suggested_mappings=mappings,
            mapping_only=mapping_only,
            formula=signal.formula,
            evidence=[signal.evidence],
            confidence=signal.confidence,
            occurrence_count=signal.evidence.occurrence_count,
        ))

    def get_proposal(self, proposal_id: str) -> SemanticProposal | None:
        return self._store.get_proposal(proposal_id)

    def list_proposals(
        self, proposal_type: ProposalType | None = None,
        status: ProposalStatus | None = None,
    ) -> list[SemanticProposal]:
        return self._store.list_proposals(proposal_type, status)

    def transition_proposal(
        self,
        proposal_id: str,
        status: ProposalStatus,
        reviewed_by: str | None = None,
        review_note: str | None = None,
    ) -> SemanticProposal:
        with self._proposal_lock:
            proposal = self._require_proposal(proposal_id)
            expected = proposal.status
            allowed = {
                ProposalStatus.PROPOSED: {ProposalStatus.REVIEWING},
                ProposalStatus.REVIEWING: {ProposalStatus.ACCEPTED, ProposalStatus.REJECTED},
                ProposalStatus.ACCEPTED: {ProposalStatus.PUBLISHED, ProposalStatus.REJECTED},
            }
            if status not in allowed.get(expected, set()):
                raise ValueError(f"非法状态转换: {expected} -> {status}")
            if status == ProposalStatus.PUBLISHED:
                raise ValueError("请通过 publish_proposal 发布并执行注册表落地")
            if status == ProposalStatus.REJECTED and not (review_note or "").strip():
                raise ValueError("驳回原因 review_note 不能为空")
            if status == ProposalStatus.ACCEPTED:
                self._validate_acceptance(proposal)
            proposal.status = status
            proposal.reviewed_by = reviewed_by or proposal.reviewed_by
            proposal.review_note = review_note
            proposal.reviewed_at = _now()
            proposal.updated_at = proposal.reviewed_at
            saved = self._store.compare_and_set_proposal(proposal, expected)
            if saved is None:
                raise ValueError("提议状态已被并发修改，请刷新后重试")
            return saved

    def publish_proposal(
        self, proposal_id: str, reviewed_by: str | None = None
    ) -> SemanticProposal:
        with self._proposal_lock:
            transaction = getattr(self._store, "registry_transaction", None)
            context = transaction(self._registry._store) if transaction else nullcontext()
            with context:
                proposal = self._store.lock_proposal(proposal_id)
                if proposal is None:
                    raise ValueError(f"语义提议不存在: {proposal_id}")
                if proposal.status == ProposalStatus.PUBLISHED:
                    return proposal
                if proposal.status != ProposalStatus.ACCEPTED:
                    raise ValueError("只有 accepted 提议可以发布")
                self._store.lock_and_claim_landing_targets(proposal)
                if proposal.proposal_type == ProposalType.METRIC:
                    self._publish_metric_proposal(proposal)
                else:
                    self._publish_value_proposal(proposal)
                proposal.status = ProposalStatus.PUBLISHED
                proposal.reviewed_by = reviewed_by or proposal.reviewed_by
                proposal.reviewed_at = _now()
                proposal.updated_at = proposal.reviewed_at
                saved = self._store.compare_and_set_proposal(
                    proposal, ProposalStatus.ACCEPTED
                )
                if saved is None:
                    raise ValueError("提议状态已被并发修改，发布已回滚")
                return saved

    @staticmethod
    def _proposal_fingerprint(
        signal: DiscoverySignal, proposal_type: ProposalType, domain_code: str | None
    ) -> str:
        concept = " ".join(signal.concept.casefold().split())
        if proposal_type == ProposalType.METRIC:
            identity = (
                signal.evidence.gap_signature
                if signal.trigger_source == TriggerSource.DEMAND_GAP
                else concept
            )
            raw = "|".join((proposal_type, signal.object_code, identity or concept))
        else:
            raw = "|".join((
                proposal_type, signal.object_code, signal.axis_metric_code or "",
                domain_code or "", signal.alias_target or concept,
            ))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _validate_acceptance(self, proposal: SemanticProposal) -> None:
        if proposal.proposal_type != ProposalType.METRIC:
            return
        draft = proposal.metric_draft
        invalid = (
            draft is None
            or not draft.metric_code.strip()
            or self._registry.get_object(draft.object_code) is None
            or draft.metric_type not in {"Atomic", "Derived"}
            or draft.semantic_type not in {"Amount", "Ratio", "Enum", "Date", "Count", "String"}
            or draft.metric_kind not in {"field", "entity", "relation"}
            or (draft.semantic_type == "Enum" and not draft.value_domain)
            or (draft.metric_type == "Derived" and proposal.formula is None)
        )
        if invalid:
            raise ValueError("指标提议缺少接受所需的完整字段")

    def _publish_metric_proposal(self, proposal: SemanticProposal) -> None:
        draft = proposal.metric_draft
        if draft is None:
            raise ValueError("指标提议缺少指标草稿")
        existing = self._registry.get_metric(draft.metric_code)
        metric = Metric(
            metric_code=draft.metric_code,
            object_code=draft.object_code,
            name=draft.name,
            definition=draft.definition,
            metric_type=draft.metric_type,
            semantic_type=draft.semantic_type,
            unit=draft.unit,
            value_domain=draft.value_domain,
            transformation=(proposal.formula.model_dump() if proposal.formula else None),
            metric_kind=draft.metric_kind,
            indexed=draft.indexed,
            extraction_hint=draft.extraction_hint,
            schema_version=draft.schema_version,
            status="published",
        )
        if existing is not None:
            if existing.model_dump(exclude={"created_at", "updated_at"}) != metric.model_dump(
                exclude={"created_at", "updated_at"}
            ):
                raise ValueError(f"指标 {draft.metric_code} 已存在且不等价")
        else:
            self._registry.save_published_metric(metric)
        if draft.semantic_type == "Enum" and draft.value_domain:
            if self._registry.get_value_domain(draft.value_domain) is None:
                self._registry.save_value_domain(ValueDomain(
                    domain_code=draft.value_domain,
                    name=draft.name,
                ))

    def _publish_value_proposal(self, proposal: SemanticProposal) -> None:
        draft = proposal.value_draft
        if draft is None:
            raise ValueError("值域提议缺少值草稿")
        domain = self._registry.get_value_domain(draft.domain_code)
        if domain is None:
            raise ValueError(f"标准值域不存在: {draft.domain_code}")
        # 先完成所有校验；任一全局冲突时不得产生部分可消费映射。
        for mapping in proposal.suggested_mappings:
            if (
                mapping.metric_code != proposal.axis_metric_code
                or mapping.domain_code != draft.domain_code
                or mapping.standard_value != draft.standard_value
            ):
                raise ValueError("建议映射的指标轴、值域或标准目标与提议不一致")
            binding = self._require_binding(mapping.binding_id) if mapping.binding_id else None
            if binding is not None and binding.metric_code != mapping.metric_code:
                raise ValueError("建议映射的来源绑定与指标不一致")

        global_mappings = {
            mapping.source_value: mapping.standard_value
            for mapping in self._registry.get_value_mappings(draft.domain_code)
        }
        for mapping in proposal.suggested_mappings:
            existing_target = global_mappings.get(mapping.source_value)
            if existing_target is not None and existing_target != mapping.standard_value:
                raise ValueError(
                    f"全局值域映射冲突: {mapping.source_value} -> {existing_target}"
                )

        if not proposal.mapping_only and draft.standard_value not in domain.standard_values:
            domain.standard_values.append(draft.standard_value)
            self._registry.save_value_domain(domain)
        for mapping in proposal.suggested_mappings:
            if mapping.binding_id:
                self._store.save_value_mapping(SourceValueMapping(
                    mapping_id=_stable_id("vm", mapping.binding_id, mapping.source_value),
                    **mapping.model_dump(),
                    status="published",
                    reviewed_by=proposal.reviewed_by,
                    reviewed_at=_now(),
                ))
            if mapping.source_value not in global_mappings:
                self._registry.save_value_mapping(ValueDomainMapping(
                    domain_code=mapping.domain_code,
                    source_value=mapping.source_value,
                    standard_value=mapping.standard_value,
                    description=f"语义提议 {proposal.proposal_id}",
                ))

    def _require_proposal(self, proposal_id: str) -> SemanticProposal:
        proposal = self._store.get_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"语义提议不存在: {proposal_id}")
        return proposal

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


_semantic_alignment_service: SemanticAlignmentService | None = None
_semantic_alignment_service_lock = RLock()


def get_semantic_alignment_service() -> SemanticAlignmentService:
    """获取统一语义对齐服务，供语义层和政策工作台共同使用。"""
    global _semantic_alignment_service
    if _semantic_alignment_service is None:
        with _semantic_alignment_service_lock:
            if _semantic_alignment_service is None:
                from src.semantic_layer.registry import get_semantic_registry

                if os.environ.get("USE_MEMORY_STORAGE") == "1":
                    store: SemanticAlignmentStore = InMemorySemanticAlignmentStore()
                else:
                    from src.data_platform.storage.postgresql.semantic_alignment_store import (
                        PostgresSemanticAlignmentStore,
                    )
                    store = PostgresSemanticAlignmentStore()
                _semantic_alignment_service = SemanticAlignmentService(
                    get_semantic_registry(),
                    store,
                )
    return _semantic_alignment_service
