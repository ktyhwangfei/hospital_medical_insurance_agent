"""结构化数据与政策知识统一指标/值域对齐 API。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from src.gateway.auth import AuthStatus, authenticator
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    CreateMetricDraft,
    MetricSourceBinding,
    MetricSourceBindingDraft,
    ProposalStatus,
    ProposalType,
    SemanticAlignmentService,
    SemanticProposal,
    SourceValueMapping,
    SourceValueMappingDraft,
    StandardValueProposal,
    StandardValueProposalDraft,
    get_semantic_alignment_service,
)
from src.semantic_layer.models import Metric
from src.security.desensitization.detection import redact_sensitive_text
from src.shared.schemas.responses import error_detail


router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/semantic/alignment",
    tags=["semantic-alignment"],
)

def _get_service() -> SemanticAlignmentService:
    return get_semantic_alignment_service()


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
    for mapping in redacted.suggested_mappings:
        mapping.source_value = redact_sensitive_text(mapping.source_value)
        mapping.standard_value = redact_sensitive_text(mapping.standard_value)
    for evidence in redacted.evidence:
        evidence.excerpt = (
            redact_sensitive_text(evidence.excerpt) if evidence.excerpt else None
        )
        evidence.representative_questions = [
            redact_sensitive_text(item) for item in evidence.representative_questions
        ]
        evidence.sample_values = [
            redact_sensitive_text(item) for item in evidence.sample_values
        ]
        evidence.observations = [
            redact_sensitive_text(item) for item in evidence.observations
        ]
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


@router.get("/proposals", response_model=list[SemanticProposal])
def list_semantic_proposals(
    principal: SemanticReviewPrincipalDependency,
    proposal_type: ProposalType | None = None,
    status: ProposalStatus | None = None,
) -> list[SemanticProposal]:
    del principal
    return [
        _redact_proposal(proposal)
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
    return _redact_proposal(proposal)


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
