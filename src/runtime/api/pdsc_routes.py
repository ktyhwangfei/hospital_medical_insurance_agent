"""政策—数据语义协同发现（PDSC）API 路由。

一屏决策包数据源（设计 §9.1）：所有接口输出只描述机器观察与系统假设，
不使用「原始问题」措辞伪装人工结论（设计 §3）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from src.gateway.auth import AuthStatus, authenticator
from src.knowledge_extension.rule_explanation.pdsc import (
    ActivationPorts,
    ClusterActivation,
    ClusterStatus,
    DatabaseValueObservation,
    DecisionAction,
    PolicyApplicabilityRelation,
    PdscService,
    RelationValueMappingItem,
    SemanticDiscoveryCluster,
    SemanticRole,
    get_pdsc_service,
)
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    DiscoverySignal,
)
from src.security.desensitization.detection import redact_sensitive_text
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/semantic/pdsc",
    tags=["pdsc"],
)

logger = logging.getLogger(__name__)


def _get_service() -> PdscService:
    return get_pdsc_service()


@dataclass(frozen=True)
class PdscReviewPrincipal:
    user_id: str


def get_pdsc_review_principal(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> PdscReviewPrincipal:
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTHENTICATION_REQUIRED", "语义发现裁决需要登录凭证"),
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
    return PdscReviewPrincipal(user_id=auth_result.user_id.strip())


ReviewPrincipal = Annotated[PdscReviewPrincipal, Depends(get_pdsc_review_principal)]


def _error(exc: ValueError) -> HTTPException:
    message = str(exc)
    status_code = 409 if any(marker in message for marker in (
        "不能一键批准", "已裁决", "只有接受完整方案",
    )) else 404 if "不存在" in message else 400
    return HTTPException(
        status_code=status_code,
        detail=error_detail("PDSC_INVALID", message, {}),
    )


def _redact_cluster(cluster: SemanticDiscoveryCluster) -> SemanticDiscoveryCluster:
    redacted = cluster.model_copy(deep=True)
    for evidence in redacted.evidence:
        if evidence.excerpt:
            evidence.excerpt = redact_sensitive_text(evidence.excerpt)
    if redacted.cross_validation:
        for item in redacted.cross_validation.items:
            if item.excerpt:
                item.excerpt = redact_sensitive_text(item.excerpt)
    return redacted


class IntakeSignalRequest(BaseModel):
    signal: DiscoverySignal
    semantic_role: SemanticRole | None = None
    policy_values: list[str] | None = None


class RefreshRequest(BaseModel):
    database_values: list[DatabaseValueObservation] | None = None
    aliases: list[str] | None = None


class DecideRequest(BaseModel):
    action: DecisionAction
    reason: str | None = None


class AdjustRequest(BaseModel):
    reason: str
    business_metric_code: str | None = None
    policy_metric_code: str | None = None
    policy_values: list[str] | None = None


class MergeRequest(BaseModel):
    into_cluster_id: str
    reason: str


class BuildRelationRequest(BaseModel):
    value_mappings: list[RelationValueMappingItem] | None = None


class ResolveFiltersRequest(BaseModel):
    business_metric_code: str
    business_standard_value: str


class SplitRequest(BaseModel):
    source_refs: list[str]
    reason: str
    new_concept: str | None = None


class ScanReportItem(BaseModel):
    detector: str
    signals: int


class ScanReport(BaseModel):
    scanned_extractions: int
    intaked_clusters: int
    detectors: list[ScanReportItem]


class PolicyFilterOut(BaseModel):
    policy_metric_code: str
    policy_value: str


class BusinessMetricCandidateOut(BaseModel):
    """候选业务指标（点选绑定，取代手填编码）。"""

    metric_code: str
    name: str
    status: str
    source_object: str | None = None
    source_field: str | None = None
    value_domain: str | None = None
    value_overlap: list[str] = []
    match_reasons: list[str] = []


class BusinessFieldProfileOut(BaseModel):
    """业务字段库画像（非空率/distinct/样本值/释义）——摆事实上卡片。"""

    metric_code: str
    source_field: str | None = None
    table_name: str | None = None
    field_name: str | None = None
    non_null_rate: float | None = None
    distinct_count: int | None = None
    sample_values: list[str] = []
    has_description: bool = False
    last_updated: str | None = None


class DecisionPackageOut(BaseModel):
    """一屏语义治理决策包（设计 §9.1）。"""

    cluster: SemanticDiscoveryCluster
    recommended_policy_metric_code: str | None = None
    recommended_business_metric_code: str | None = None
    value_domain_extension_values: list[str] = []
    relation_draft: list[RelationValueMappingItem] = []
    affected_unit_ids: list[str] = []
    affected_rule_ids: list[str] = []
    affected_skill_usage: int = 0
    business_metric_candidates: list[BusinessMetricCandidateOut] = []
    business_field_profile: BusinessFieldProfileOut | None = None


@router.post("/signals", response_model=SemanticDiscoveryCluster, status_code=201)
def intake_signal(request: IntakeSignalRequest, principal: ReviewPrincipal) -> SemanticDiscoveryCluster:
    del principal
    try:
        return _redact_cluster(_get_service().intake_signal(
            request.signal,
            semantic_role=request.semantic_role,
            policy_values=request.policy_values,
        ))
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/scan", response_model=ScanReport)
def scan_signals(principal: ReviewPrincipal) -> ScanReport:
    """运行六类确定性检测器（§4.2），全部信号自动进入发现簇。"""
    del principal
    from src.knowledge_extension.rule_explanation.pipeline_store import PipelineStore

    store = PipelineStore()
    extractions: list[dict] = []
    page = 1
    while True:
        batch = store.list_extractions(page=page, page_size=200)
        items = batch.get("items", [])
        if not items:
            break
        extractions.extend(items)
        if page * 200 >= batch.get("total", 0):
            break
        page += 1
    db_fields: list[dict] = []
    try:
        db_fields = _get_discovery_fields()
    except Exception:
        logger.warning("PDSC 扫描：bjyb 字段画像不可用，跳过检测器 6", exc_info=True)
    report = _get_service().scan_and_intake(extractions, db_fields)
    return ScanReport(
        scanned_extractions=report["scanned_extractions"],
        intaked_clusters=report["intaked_clusters"],
        detectors=[ScanReportItem(detector=kind, signals=count)
                   for kind, count in report["detectors"].items()],
    )


@router.get("/clusters", response_model=list[SemanticDiscoveryCluster])
def list_clusters(
    principal: ReviewPrincipal,
    status: ClusterStatus | None = None,
) -> list[SemanticDiscoveryCluster]:
    del principal
    service = _get_service()
    items = service.list_clusters([status] if status else None)
    return [_redact_cluster(c) for c in items]


@router.get("/clusters/{cluster_id}", response_model=SemanticDiscoveryCluster)
def get_cluster(cluster_id: str, principal: ReviewPrincipal) -> SemanticDiscoveryCluster:
    del principal
    cluster = _get_service().get_cluster(cluster_id)
    if cluster is None:
        raise _error(ValueError(f"发现簇不存在: {cluster_id}"))
    return _redact_cluster(cluster)


@router.post("/clusters/{cluster_id}/refresh", response_model=SemanticDiscoveryCluster)
def refresh_cluster(
    cluster_id: str, request: RefreshRequest, principal: ReviewPrincipal,
) -> SemanticDiscoveryCluster:
    del principal
    try:
        return _redact_cluster(_get_service().refresh_cluster(
            cluster_id,
            database_values=request.database_values,
            aliases=request.aliases,
        ))
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/clusters/{cluster_id}/decide", response_model=SemanticDiscoveryCluster)
def decide_cluster(
    cluster_id: str, request: DecideRequest, principal: ReviewPrincipal,
) -> SemanticDiscoveryCluster:
    try:
        return _redact_cluster(_get_service().decide(
            cluster_id, request.action, principal.user_id, reason=request.reason,
        ))
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/clusters/{cluster_id}/adjust", response_model=SemanticDiscoveryCluster)
def adjust_cluster(
    cluster_id: str, request: AdjustRequest, principal: ReviewPrincipal,
) -> SemanticDiscoveryCluster:
    try:
        return _redact_cluster(_get_service().adjust_cluster(
            cluster_id, principal.user_id, reason=request.reason,
            business_metric_code=request.business_metric_code,
            policy_metric_code=request.policy_metric_code,
            policy_values=request.policy_values,
        ))
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/clusters/{source_cluster_id}/merge", response_model=SemanticDiscoveryCluster)
def merge_cluster(
    source_cluster_id: str, request: MergeRequest, principal: ReviewPrincipal,
) -> SemanticDiscoveryCluster:
    try:
        return _redact_cluster(_get_service().merge_clusters(
            source_cluster_id, request.into_cluster_id, principal.user_id, request.reason,
        ))
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/clusters/{cluster_id}/split", response_model=SemanticDiscoveryCluster)
def split_cluster(
    cluster_id: str, request: SplitRequest, principal: ReviewPrincipal,
) -> SemanticDiscoveryCluster:
    """人工拆分聚类歧义（§6.1/§9.2）：把指定证据移入新簇，返回拆分后的源簇。"""
    try:
        return _redact_cluster(_get_service().split_cluster(
            cluster_id, request.source_refs, principal.user_id, request.reason,
            new_concept=request.new_concept,
        ))
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/clusters/{cluster_id}/activate", response_model=ClusterActivation)
def activate_cluster(cluster_id: str, principal: ReviewPrincipal) -> ClusterActivation:
    """执行激活流水线（§11.2）：任一步失败不改变活动版本。

    激活依赖端口（重提取/编译/Skill 验证）默认用生产适配器；
    测试通过替换本模块 `_activation_ports` 注入内存桩。
    """
    try:
        return _get_service().execute_activation(
            cluster_id, principal.user_id, _activation_ports(),
        )
    except ValueError as exc:
        raise _error(exc) from exc


def _activation_ports() -> ActivationPorts | None:
    """默认 None = 服务内默认适配器；测试可 monkeypatch 本函数。"""
    return None


@router.get("/activations/{activation_id}", response_model=ClusterActivation)
def get_activation(activation_id: str, principal: ReviewPrincipal) -> ClusterActivation:
    del principal
    activation = _get_service().get_activation(activation_id)
    if activation is None:
        raise _error(ValueError(f"激活记录不存在: {activation_id}"))
    return activation


@router.get("/clusters/{cluster_id}/decision-package", response_model=DecisionPackageOut)
def build_decision_package(cluster_id: str, principal: ReviewPrincipal) -> DecisionPackageOut:
    del principal
    service = _get_service()
    cluster = service.get_cluster(cluster_id)
    if cluster is None:
        raise _error(ValueError(f"发现簇不存在: {cluster_id}"))
    # 决策包需要最新交叉验证与分数；未刷新时自动补一次
    if cluster.cross_validation is None or cluster.score is None:
        cluster = service.refresh_cluster(cluster_id)
    extension = cluster.cross_validation.extension_values if cluster.cross_validation else []
    business_code = cluster.business_metric_code
    candidates = service.suggest_business_metric_candidates(cluster)
    profile = service.get_business_field_profile(cluster, candidates)
    relation_draft: list[RelationValueMappingItem] = []
    skill_usage = service.get_business_metric_usage(business_code)
    unit_ids = sorted({e.unit_id for e in cluster.evidence if e.unit_id} | {
        item.unit_id for item in (cluster.cross_validation.items if cluster.cross_validation else [])
        if item.unit_id
    })
    rule_ids = sorted({rule for e in cluster.evidence for rule in e.rule_ids})
    return DecisionPackageOut(
        cluster=_redact_cluster(cluster),
        recommended_policy_metric_code=cluster.policy_metric_code,
        recommended_business_metric_code=business_code,
        value_domain_extension_values=extension,
        relation_draft=relation_draft,
        affected_unit_ids=unit_ids,
        affected_rule_ids=rule_ids,
        affected_skill_usage=skill_usage,
        business_metric_candidates=[
            BusinessMetricCandidateOut(**c) for c in candidates
        ],
        business_field_profile=(
            BusinessFieldProfileOut(**profile) if profile else None
        ),
    )


@router.post(
    "/clusters/{cluster_id}/relation",
    response_model=PolicyApplicabilityRelation, status_code=201,
)
def build_relation(
    cluster_id: str, request: BuildRelationRequest, principal: ReviewPrincipal,
) -> PolicyApplicabilityRelation:
    try:
        return _get_service().build_applicability_relation(
            cluster_id, principal.user_id, value_mappings=request.value_mappings,
        )
    except ValueError as exc:
        raise _error(exc) from exc


@router.get("/relations", response_model=list[PolicyApplicabilityRelation])
def list_relations(
    principal: ReviewPrincipal,
    business_metric_code: str | None = None,
) -> list[PolicyApplicabilityRelation]:
    del principal
    return _get_service().list_relations(business_metric_code)


@router.post("/relations/{relation_id}/publish", response_model=PolicyApplicabilityRelation)
def publish_relation(relation_id: str, principal: ReviewPrincipal) -> PolicyApplicabilityRelation:
    try:
        return _get_service().publish_relation(relation_id, principal.user_id)
    except ValueError as exc:
        raise _error(exc) from exc


@router.post("/resolve-policy-filters", response_model=list[PolicyFilterOut])
def resolve_policy_filters(request: ResolveFiltersRequest) -> list[PolicyFilterOut]:
    """Skill 运行时入口（设计 §10.3）：无需审核权限，供 Facts Builder 调用。"""
    service = _get_service()
    return [
        PolicyFilterOut(policy_metric_code=f.policy_metric_code, policy_value=f.policy_value)
        for f in service.resolve_policy_filters(
            request.business_metric_code, request.business_standard_value,
        )
    ]
