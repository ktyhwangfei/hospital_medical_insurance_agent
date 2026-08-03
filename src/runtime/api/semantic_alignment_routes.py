"""结构化数据与政策知识统一指标/值域对齐 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.knowledge_extension.rule_explanation.semantic_alignment import (
    CreateMetricDraft,
    MetricSourceBinding,
    MetricSourceBindingDraft,
    SemanticAlignmentService,
    SourceValueMapping,
    SourceValueMappingDraft,
    StandardValueProposal,
    StandardValueProposalDraft,
    get_semantic_alignment_service,
)
from src.semantic_layer.models import Metric
from src.shared.schemas.responses import error_detail


router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/semantic/alignment",
    tags=["semantic-alignment"],
)

def _get_service() -> SemanticAlignmentService:
    return get_semantic_alignment_service()


def _bad_request(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail=error_detail("SEMANTIC_ALIGNMENT_INVALID", str(exc), {}),
    )


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


@router.post("/bindings", response_model=MetricSourceBinding, status_code=201)
def bind_existing_metric(request: MetricSourceBindingDraft) -> MetricSourceBinding:
    try:
        return _get_service().bind_existing_metric(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/bindings/batch", response_model=list[BatchBindingResult])
def bind_existing_metrics_batch(request: BatchBindingRequest) -> list[BatchBindingResult]:
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
def publish_binding(binding_id: str, request: ReviewRequest) -> MetricSourceBinding:
    try:
        return _get_service().approve_binding(binding_id, request.reviewed_by)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/metrics", response_model=Metric, status_code=201)
def create_metric_draft(request: CreateMetricDraft) -> Metric:
    try:
        return _get_service().create_metric_draft(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/value-mappings", response_model=SourceValueMapping, status_code=201)
def propose_value_mapping(request: SourceValueMappingDraft) -> SourceValueMapping:
    try:
        return _get_service().propose_value_mapping(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/value-mappings/{mapping_id}/publish", response_model=SourceValueMapping)
def publish_value_mapping(mapping_id: str, request: ReviewRequest) -> SourceValueMapping:
    try:
        return _get_service().approve_value_mapping(mapping_id, request.reviewed_by)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/standard-values", response_model=StandardValueProposal, status_code=201)
def propose_standard_value(request: StandardValueProposalDraft) -> StandardValueProposal:
    try:
        return _get_service().propose_standard_value(request)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/standard-values/{proposal_id}/publish", response_model=StandardValueProposal)
def publish_standard_value(proposal_id: str, request: ReviewRequest) -> StandardValueProposal:
    try:
        return _get_service().approve_standard_value(proposal_id, request.reviewed_by)
    except ValueError as exc:
        raise _bad_request(exc) from exc
