"""结构化数据与政策知识统一指标/值域对齐 API。"""
from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from src.gateway.auth import AuthStatus, authenticator
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    CreateMetricDraft,
    DiscoveryEvidence,
    DimensionReviewConclusion,
    MetricSourceBinding,
    MetricSourceBindingDraft,
    ProposalStatus,
    ProposalType,
    RuleGovernanceDecision,
    RuleGovernanceDiagnosis,
    SemanticAlignmentService,
    SemanticProposal,
    SourceValueMapping,
    SourceValueMappingDraft,
    StandardValueProposal,
    StandardValueProposalDraft,
    get_semantic_alignment_service,
    match_database_evidence,
)
from src.knowledge_extension.rule_explanation.rule_governance import (
    diagnose_rule_governance,
)
from src.semantic_layer.models import Metric
from src.security.desensitization.detection import redact_sensitive_text
from src.shared.schemas.responses import error_detail


router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/semantic/alignment",
    tags=["semantic-alignment"],
)

logger = logging.getLogger(__name__)
_rule_governance_trace_store = None

def _get_service() -> SemanticAlignmentService:
    return get_semantic_alignment_service()


def get_rule_governance_trace_store():
    """规则治理 lineage 依赖；API 测试可替换为内存实现。"""
    global _rule_governance_trace_store
    if _rule_governance_trace_store is None:
        from src.knowledge_extension.rule_explanation.policy_compiler.trace_store import (
            InMemoryCompilationTraceStore,
            PostgresCompilationTraceStore,
        )

        _rule_governance_trace_store = (
            InMemoryCompilationTraceStore()
            if os.environ.get("USE_MEMORY_STORAGE") == "1"
            else PostgresCompilationTraceStore()
        )
    return _rule_governance_trace_store


def _get_discovery_fields() -> list[dict]:
    """读取最新 bjyb 扫描字段；不可用时不阻断政策提案审核。"""
    try:
        from src.runtime.api.semantic_routes import _get_discovery_store

        store = _get_discovery_store()
        latest = store.get_latest_result()
        if not latest:
            return []
        descriptions = store.get_all_field_descriptions()
        fields: list[dict] = []
        for raw in latest.get("fields", []):
            field = dict(raw)
            key = f"{field.get('table_name', '')}:{field.get('field_name', '')}".casefold()
            if description := descriptions.get(key):
                field["description"] = description.get("description") or field.get("description")
                field["remark"] = description.get("remark") or field.get("remark")
            fields.append(field)
        return fields
    except Exception:
        logger.warning("加载 bjyb 字段证据失败，保留 policy-only 提案", exc_info=True)
        return []


def _with_database_evidence(
    proposal: SemanticProposal, fields: list[dict]
) -> SemanticProposal:
    if not fields:
        return proposal
    candidate_values = [
        value.label for value in proposal.dimension_candidate.candidate_values
    ] if proposal.dimension_candidate else []
    definition = proposal.metric_draft.definition if proposal.metric_draft else ""
    database_evidence = match_database_evidence(
        proposal.concept,
        definition or "",
        candidate_values,
        fields,
    )
    if not database_evidence:
        return proposal
    known_refs = {item.source_ref for item in proposal.evidence}
    return proposal.model_copy(update={
        "evidence": proposal.evidence + [
            item for item in database_evidence if item.source_ref not in known_refs
        ],
    }, deep=True)


def _redact_evidence(evidence: DiscoveryEvidence) -> DiscoveryEvidence:
    redacted = evidence.model_copy(deep=True)
    redacted.excerpt = redact_sensitive_text(redacted.excerpt) if redacted.excerpt else None
    redacted.representative_questions = [redact_sensitive_text(item) for item in redacted.representative_questions]
    redacted.sample_values = [redact_sensitive_text(item) for item in redacted.sample_values]
    redacted.observations = [redact_sensitive_text(item) for item in redacted.observations]
    redacted.match_reasons = [redact_sensitive_text(item) for item in redacted.match_reasons]
    redacted.rejection_reasons = [redact_sensitive_text(item) for item in redacted.rejection_reasons]
    return redacted


def _redact_proposal(proposal: SemanticProposal) -> SemanticProposal:
    """仅脱敏展示文本，不改动路由、指纹、代码和来源定位字段。"""
    redacted = proposal.model_copy(deep=True)
    redacted.concept = redact_sensitive_text(redacted.concept)
    redacted.review_note = (
        redact_sensitive_text(redacted.review_note) if redacted.review_note else None
    )
    if redacted.metric_draft is not None:
        draft = redacted.metric_draft
        draft.name = redact_sensitive_text(draft.name)
        draft.definition = (
            redact_sensitive_text(draft.definition) if draft.definition else None
        )
        draft.extraction_hint = (
            redact_sensitive_text(draft.extraction_hint) if draft.extraction_hint else None
        )
        if draft.source_binding is not None:
            draft.source_binding.evidence = redact_sensitive_text(
                draft.source_binding.evidence
            )
    if redacted.value_draft is not None:
        redacted.value_draft.standard_value = redact_sensitive_text(
            redacted.value_draft.standard_value
        )
        redacted.value_draft.evidence = redact_sensitive_text(
            redacted.value_draft.evidence
        )
    if redacted.dimension_candidate is not None:
        candidate = redacted.dimension_candidate
        payload = candidate.model_dump(mode="python")
        payload["suggested_name"] = (
            redact_sensitive_text(payload["suggested_name"])
            if payload["suggested_name"] else None
        )
        for value in payload["candidate_values"]:
            value["label"] = redact_sensitive_text(value["label"])
            value["aliases"] = [redact_sensitive_text(item) for item in value["aliases"]]
        evidence = payload["evidence"]
        evidence["identity_signature"]["known_values"] = {
            key: redact_sensitive_text(value)
            for key, value in evidence["identity_signature"]["known_values"].items()
        }
        for value in evidence["conflict_values"]:
            value["raw_value"] = redact_sensitive_text(value["raw_value"])
            value["canonical_value"] = redact_sensitive_text(value["canonical_value"])
        evidence["evidence_texts"] = [
            redact_sensitive_text(item) for item in evidence["evidence_texts"]
        ]
        for mapping in evidence["partition_mappings"]:
            mapping["display_phrase"] = redact_sensitive_text(mapping["display_phrase"])
            mapping["canonical_phrase"] = redact_sensitive_text(mapping["canonical_phrase"])
            mapping["canonical_value"] = redact_sensitive_text(mapping["canonical_value"])
        redacted.dimension_candidate = candidate.__class__(**payload)
    for mapping in redacted.suggested_mappings:
        mapping.source_value = redact_sensitive_text(mapping.source_value)
        mapping.standard_value = redact_sensitive_text(mapping.standard_value)
    redacted.evidence = [_redact_evidence(evidence) for evidence in redacted.evidence]
    return redacted


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=error_detail("SEMANTIC_ALIGNMENT_INVALID", str(exc), {}),
    )


def _proposal_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "不存在" in message:
        status_code = 404
    elif any(marker in message for marker in (
        "非法状态转换", "状态已被并发修改", "只有 accepted",
        "已被其他提议占用", "已存在且不等价", "映射冲突",
        "当前状态不能提交", "不支持直接发布",
    )):
        status_code = 409
    else:
        status_code = 400
    return HTTPException(
        status_code=status_code,
        detail=error_detail("SEMANTIC_PROPOSAL_INVALID", message, {}),
    )


@dataclass(frozen=True)
class SemanticReviewPrincipal:
    user_id: str


def get_semantic_review_principal(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> SemanticReviewPrincipal:
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTHENTICATION_REQUIRED", "语义提议审核需要登录凭证"),
        )
    auth_result = authenticator.validate_signed_token(authorization)
    if (
        not auth_result.is_success
        or not isinstance(auth_result.user_id, str)
        or not auth_result.user_id.strip()
    ):
        raise HTTPException(
            status_code=401,
            detail=error_detail("INVALID_AUTHENTICATION", auth_result.error_message or "登录凭证缺少用户标识"),
        )
    permitted = authenticator.check_permission(auth_result, "semantic:review")
    if permitted.status == AuthStatus.INSUFFICIENT_PERMISSION:
        raise HTTPException(
            status_code=403,
            detail=error_detail("SEMANTIC_REVIEW_FORBIDDEN", permitted.error_message),
        )
    return SemanticReviewPrincipal(user_id=auth_result.user_id.strip())


SemanticReviewPrincipalDependency = Annotated[
    SemanticReviewPrincipal, Depends(get_semantic_review_principal)
]


class BatchBindingRequest(BaseModel):
    items: list[MetricSourceBindingDraft]


class BatchBindingResult(BaseModel):
    index: int
    metric_code: str
    status: str
    binding_id: str | None = None
    error: str | None = None


class ReviewRequest(BaseModel):
    reviewed_by: str


class RejectProposalRequest(BaseModel):
    reason: str


class ResolveDimensionProposalRequest(BaseModel):
    conclusion: DimensionReviewConclusion
    suggested_name: str | None = None
    suggested_code: str | None = None
    reason: str | None = None


class DatabaseEvidencePreviewRequest(BaseModel):
    concept: str
    definition: str
    candidate_values: list[str]


class RuleGovernanceDiagnosisRequest(BaseModel):
    release_id: str = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)


class RuleGovernanceDraftRequest(RuleGovernanceDiagnosisRequest):
    issue_id: str = Field(min_length=1)
    decision: RuleGovernanceDecision
    review_note: str | None = None


def _diagnose_rule_governance(
    request: RuleGovernanceDiagnosisRequest,
) -> RuleGovernanceDiagnosis:
    try:
        return diagnose_rule_governance(
            request.release_id,
            request.rule_ids,
            get_rule_governance_trace_store(),
            _get_discovery_fields(),
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/rule-diagnoses", response_model=RuleGovernanceDiagnosis)
def diagnose_rules(
    request: RuleGovernanceDiagnosisRequest,
    principal: SemanticReviewPrincipalDependency,
) -> RuleGovernanceDiagnosis:
    del principal
    diagnosis = _diagnose_rule_governance(request)
    redacted = diagnosis.model_copy(deep=True)
    for rule in redacted.rules:
        rule.excerpt = redact_sensitive_text(rule.excerpt)
    for issue in redacted.items:
        issue.policy_evidence = [_redact_evidence(item) for item in issue.policy_evidence]
        issue.database_evidence = [_redact_evidence(item) for item in issue.database_evidence]
    return redacted


@router.post(
    "/rule-governance-drafts",
    response_model=SemanticProposal,
    status_code=201,
)
def create_rule_governance_draft(
    request: RuleGovernanceDraftRequest,
    principal: SemanticReviewPrincipalDependency,
) -> SemanticProposal:
    del principal
    diagnosis = _diagnose_rule_governance(request)
    try:
        return _redact_proposal(_get_service().create_rule_governance_draft(
            diagnosis,
            request.issue_id,
            request.decision,
            review_note=request.review_note,
        ))
    except ValueError as exc:
        raise _proposal_error(exc) from exc


@router.post("/database-evidence-preview", response_model=list[DiscoveryEvidence])
def preview_database_evidence(
    request: DatabaseEvidencePreviewRequest,
    principal: SemanticReviewPrincipalDependency,
) -> list[DiscoveryEvidence]:
    del principal
    return [
        _redact_evidence(evidence)
        for evidence in match_database_evidence(
            request.concept,
            request.definition,
            request.candidate_values,
            _get_discovery_fields(),
        )
    ]


@router.get("/proposals", response_model=list[SemanticProposal])
def list_semantic_proposals(
    principal: SemanticReviewPrincipalDependency,
    proposal_type: ProposalType | None = None,
    status: ProposalStatus | None = None,
) -> list[SemanticProposal]:
    del principal
    fields = _get_discovery_fields()
    return [
        _redact_proposal(_with_database_evidence(proposal, fields))
        for proposal in _get_service().list_proposals(proposal_type, status)
    ]


@router.get("/proposals/{proposal_id}", response_model=SemanticProposal)
def get_semantic_proposal(
    proposal_id: str,
    principal: SemanticReviewPrincipalDependency,
) -> SemanticProposal:
    del principal
    service = _get_service()
    proposal = service.get_proposal(proposal_id)
    if proposal is None:
        raise _proposal_error(ValueError(f"语义提议不存在: {proposal_id}"))
    return _redact_proposal(_with_database_evidence(proposal, _get_discovery_fields()))


@router.post("/proposals/{proposal_id}/review", response_model=SemanticProposal)
def review_semantic_proposal(
    proposal_id: str,
    principal: SemanticReviewPrincipalDependency,
) -> SemanticProposal:
    service = _get_service()
    proposal = service.get_proposal(proposal_id)
    if proposal is None:
        raise _proposal_error(ValueError(f"语义提议不存在: {proposal_id}"))
    if proposal.status != ProposalStatus.PROPOSED:
        return _redact_proposal(proposal)
    try:
        return _redact_proposal(service.transition_proposal(
            proposal_id, ProposalStatus.REVIEWING, reviewed_by=principal.user_id
        ))
    except ValueError as exc:
        # 并发打开时，另一请求已进入 reviewing 也应保持可读。
        current = service.get_proposal(proposal_id)
        if current is not None and current.status != ProposalStatus.PROPOSED:
            return _redact_proposal(current)
        raise _proposal_error(exc) from exc


@router.post("/proposals/{proposal_id}/accept", response_model=SemanticProposal)
def accept_semantic_proposal(
    proposal_id: str,
    principal: SemanticReviewPrincipalDependency,
) -> SemanticProposal:
    try:
        return _redact_proposal(_get_service().transition_proposal(
            proposal_id, ProposalStatus.ACCEPTED, reviewed_by=principal.user_id
        ))
    except ValueError as exc:
        raise _proposal_error(exc) from exc


@router.post("/proposals/{proposal_id}/publish", response_model=SemanticProposal)
def publish_semantic_proposal(
    proposal_id: str,
    principal: SemanticReviewPrincipalDependency,
) -> SemanticProposal:
    try:
        return _redact_proposal(
            _get_service().publish_proposal(proposal_id, principal.user_id)
        )
    except ValueError as exc:
        raise _proposal_error(exc) from exc


@router.post("/proposals/{proposal_id}/reject", response_model=SemanticProposal)
def reject_semantic_proposal(
    proposal_id: str,
    request: RejectProposalRequest,
    principal: SemanticReviewPrincipalDependency,
) -> SemanticProposal:
    if not request.reason.strip():
        raise _bad_request(ValueError("驳回原因 reason 不能为空"))
    try:
        return _redact_proposal(_get_service().transition_proposal(
            proposal_id,
            ProposalStatus.REJECTED,
            reviewed_by=principal.user_id,
            review_note=request.reason.strip(),
        ))
    except ValueError as exc:
        raise _proposal_error(exc) from exc


@router.post("/proposals/{proposal_id}/resolve", response_model=SemanticProposal)
def resolve_dimension_proposal(
    proposal_id: str,
    request: ResolveDimensionProposalRequest,
    principal: SemanticReviewPrincipalDependency,
) -> SemanticProposal:
    try:
        return _redact_proposal(_get_service().resolve_dimension_proposal(
            proposal_id,
            request.conclusion,
            reviewed_by=principal.user_id,
            suggested_name=request.suggested_name,
            suggested_code=request.suggested_code,
            review_note=request.reason,
        ))
    except ValueError as exc:
        raise _proposal_error(exc) from exc


@router.post("/bindings", response_model=MetricSourceBinding, status_code=201)
def bind_existing_metric(
    request: MetricSourceBindingDraft,
    principal: SemanticReviewPrincipalDependency,
) -> MetricSourceBinding:
    del principal
    try:
        return _get_service().bind_existing_metric(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/bindings/batch", response_model=list[BatchBindingResult])
def bind_existing_metrics_batch(
    request: BatchBindingRequest,
    principal: SemanticReviewPrincipalDependency,
) -> list[BatchBindingResult]:
    del principal
    results: list[BatchBindingResult] = []
    for index, item in enumerate(request.items):
        try:
            binding = _get_service().bind_existing_metric(item)
            results.append(BatchBindingResult(
                index=index,
                metric_code=item.metric_code,
                status="created",
                binding_id=binding.binding_id,
            ))
        except ValueError as exc:
            results.append(BatchBindingResult(
                index=index,
                metric_code=item.metric_code,
                status="error",
                error=str(exc),
            ))
    return results


@router.get("/bindings/{metric_code:path}", response_model=list[MetricSourceBinding])
def list_metric_bindings(metric_code: str) -> list[MetricSourceBinding]:
    return _get_service().list_metric_bindings(metric_code)


@router.post("/bindings/{binding_id}/publish", response_model=MetricSourceBinding)
def publish_binding(
    binding_id: str,
    request: ReviewRequest,
    principal: SemanticReviewPrincipalDependency,
) -> MetricSourceBinding:
    del request
    try:
        return _get_service().approve_binding(binding_id, principal.user_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/metrics", response_model=Metric, status_code=201)
def create_metric_draft(
    request: CreateMetricDraft,
    principal: SemanticReviewPrincipalDependency,
) -> Metric:
    del principal
    try:
        return _get_service().create_metric_draft(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/value-mappings", response_model=SourceValueMapping, status_code=201)
def propose_value_mapping(
    request: SourceValueMappingDraft,
    principal: SemanticReviewPrincipalDependency,
) -> SourceValueMapping:
    del principal
    try:
        return _get_service().propose_value_mapping(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/value-mappings/{mapping_id}/publish", response_model=SourceValueMapping)
def publish_value_mapping(
    mapping_id: str,
    request: ReviewRequest,
    principal: SemanticReviewPrincipalDependency,
) -> SourceValueMapping:
    del request
    try:
        return _get_service().approve_value_mapping(mapping_id, principal.user_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/standard-values", response_model=StandardValueProposal, status_code=201)
def propose_standard_value(
    request: StandardValueProposalDraft,
    principal: SemanticReviewPrincipalDependency,
) -> StandardValueProposal:
    del principal
    try:
        return _get_service().propose_standard_value(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/standard-values/{proposal_id}/publish", response_model=StandardValueProposal)
def publish_standard_value(
    proposal_id: str,
    request: ReviewRequest,
    principal: SemanticReviewPrincipalDependency,
) -> StandardValueProposal:
    del request
    try:
        return _get_service().approve_standard_value(proposal_id, principal.user_id)
    except ValueError as exc:
        raise _bad_request(exc) from exc
