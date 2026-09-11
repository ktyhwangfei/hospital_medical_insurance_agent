"""健康运营 API — issue #45 P0（问题库 + 手动巡检）+ #50（详情与生命周期）
+ #53（L1 白名单自动修复与强制验证）+ #54（L2 人工确认修复流）。

前缀 /api/v1/medical-insurance-ai-agent/ops；鉴权走签名 JWT 的
ops:read / ops:write 权限（与 data-governance 同模式）。

服务通过 Depends(get_ops_service) 注入——API 测试 override 该依赖
即可注入内存存储（项目既有陷阱：直接调用工厂不响应 override）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.data_platform.storage.ops.ops_factory import get_ops_finding_storage
from src.domain.ops.models import (
    DiagnosisUnavailableError,
    FindingRevisionConflictError,
    InspectionInProgressError,
    InvalidFindingTransitionError,
    ManualTaskNotFoundError,
    OpsAssetType,
    OpsDiagnosisResult,
    OpsFindingDetail,
    OpsFindingNotFoundError,
    OpsFindingPage,
    OpsFindingStatus,
    OpsInspectionSummary,
    OpsManualResult,
    OpsSeverity,
    RemediationNotAllowedError,
    RemediationRiskLevel,
)
from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
from src.runtime.ops.diagnosis import OpsDiagnosisService
from src.runtime.ops.scheduler import OpsInspectionScheduler
from src.runtime.ops.service import OpsHealthService, OpsInspectionResult, OpsRemediationResult
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/ops",
    tags=["ops-health"],
)


def get_ops_service() -> OpsHealthService:
    """依赖注入 seam：API 测试 override 此函数注入内存存储与假读取面。"""
    # 巡检读取面复用治理控制面服务（lru_cache 单例，密钥缺失时端点 503）
    from src.runtime.api.data_governance_routes import get_data_governance_service

    return OpsHealthService(get_ops_finding_storage(), get_data_governance_service)


def get_ops_diagnosis_service() -> OpsDiagnosisService:
    """诊断服务依赖注入 seam（#51）：与 /ops 共享问题库存储进程级单例。"""

    def gateway_factory():
        from src.model_service.gateway import ModelGateway

        return ModelGateway()

    return OpsDiagnosisService(get_ops_finding_storage(), gateway_factory)


def get_ops_inspection_scheduler() -> OpsInspectionScheduler:
    """巡检调度器依赖注入 seam（#52）：与 /ops 共享问题库存储进程级单例。"""
    # 巡检读取面复用治理控制面服务（lru_cache 单例，密钥缺失时端点 503）
    from src.runtime.api.data_governance_routes import get_data_governance_service

    storage = get_ops_finding_storage()
    health = OpsHealthService(storage, get_data_governance_service)
    return OpsInspectionScheduler(storage, health)


def _require_permission(permission: str, authorization: str | None):
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success or not auth.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_INVALID", auth.error_message or "登录凭据无效"),
        )
    permitted = authenticator.check_permission(auth, permission)
    if not permitted.is_success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("AUTH_FORBIDDEN", "权限不足"),
        )
    return DataGovernancePrincipal(
        user_id=auth.user_id,
        roles=auth.roles,
        permissions=auth.permissions,
    )


def require_ops_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    return _require_permission("ops:read", authorization)


def require_ops_write(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    return _require_permission("ops:write", authorization)


@router.post(
    "/inspections",
    response_model=OpsInspectionResult,
)
def run_inspection(
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    scheduler: OpsInspectionScheduler = Depends(get_ops_inspection_scheduler),
) -> OpsInspectionResult:
    """手动触发一次巡检（#52 起写 ops_inspections 运行留痕）。

    全部检查器只读取数，问题按 fingerprint 去重落库；已有巡检执行中
    （手动或定时）→ 409 INSPECTION_IN_PROGRESS。
    """
    try:
        return scheduler.run_manual(actor=principal.user_id)
    except InspectionInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("INSPECTION_IN_PROGRESS", str(exc)),
        ) from exc


@router.get(
    "/inspection-summary",
    response_model=OpsInspectionSummary,
)
def get_inspection_summary(
    _principal=Depends(require_ops_read),
    scheduler: OpsInspectionScheduler = Depends(get_ops_inspection_scheduler),
) -> OpsInspectionSummary:
    """巡检摘要条数据（#52）：周期 + 下次巡检时间 + 最近一次巡检结果。"""
    return scheduler.get_summary()


@router.get(
    "/findings",
    response_model=OpsFindingPage,
)
def list_findings(
    status_filter: OpsFindingStatus | None = Query(default=None, alias="status"),
    severity: OpsSeverity | None = Query(default=None),
    asset_type: OpsAssetType | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _principal=Depends(require_ops_read),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingPage:
    """开放问题列表：severity / asset_type 过滤 + 分页，severity 与最近发现排序。"""
    return service.list_findings(
        status=status_filter,
        severity=severity,
        asset_type=asset_type,
        page=page,
        page_size=page_size,
    )


class IgnoreFindingRequest(BaseModel):
    """忽略原因（必填，写入事件留痕）。"""

    reason: str = Field(min_length=1, max_length=500)


class ManualHandoffRequest(BaseModel):
    """转人工处理备注（可选，写入任务与事件留痕）。"""

    note: str | None = Field(default=None, max_length=500)


class ManualCompleteRequest(BaseModel):
    """人工处理结果（必填，回填任务 output_data 供回链展示）。"""

    result_note: str = Field(min_length=1, max_length=500)


class RemediationActionInfo(BaseModel):
    """修复白名单条目（Portal 据此渲染「执行修复」入口）。"""

    action: str
    check_id: str
    risk_level: RemediationRiskLevel
    description: str


def _raise_lifecycle_error(exc: Exception) -> None:
    """生命周期异常 → HTTP 映射：404 不存在 / 409 非法流转、版本冲突或非白名单。"""
    if isinstance(exc, OpsFindingNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("FINDING_NOT_FOUND", str(exc)),
        ) from exc
    if isinstance(exc, ManualTaskNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("MANUAL_TASK_NOT_FOUND", str(exc)),
        ) from exc
    if isinstance(exc, InvalidFindingTransitionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("FINDING_TRANSITION_INVALID", str(exc)),
        ) from exc
    if isinstance(exc, FindingRevisionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("FINDING_REVISION_CONFLICT", str(exc)),
        ) from exc
    if isinstance(exc, RemediationNotAllowedError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("REMEDIATION_NOT_WHITELISTED", str(exc)),
        ) from exc
    raise exc


@router.get(
    "/findings/{finding_id}",
    response_model=OpsFindingDetail,
)
def get_finding(
    finding_id: str,
    _principal=Depends(require_ops_read),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingDetail:
    """单条问题详情：证据快照 + 生命周期事件时间线。"""
    try:
        return service.get_finding_detail(finding_id)
    except OpsFindingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("FINDING_NOT_FOUND", str(exc)),
        ) from exc


@router.post(
    "/findings/{finding_id}/ignore",
    response_model=OpsFindingDetail,
)
def ignore_finding(
    finding_id: str,
    request: IgnoreFindingRequest,
    expected_revision: int = Query(ge=1),
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingDetail:
    """忽略开放问题（open → ignored）：必填原因，乐观锁 expected_revision。"""
    try:
        return service.ignore_finding(
            finding_id,
            expected_revision=expected_revision,
            reason=request.reason,
            actor=principal.user_id,
        )
    except (OpsFindingNotFoundError, InvalidFindingTransitionError, FindingRevisionConflictError) as exc:
        _raise_lifecycle_error(exc)


@router.post(
    "/findings/{finding_id}/reopen",
    response_model=OpsFindingDetail,
)
def reopen_finding(
    finding_id: str,
    expected_revision: int = Query(ge=1),
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsFindingDetail:
    """重开已忽略/已解决问题（ignored|resolved → open）：乐观锁 expected_revision。"""
    try:
        return service.reopen_finding(
            finding_id,
            expected_revision=expected_revision,
            actor=principal.user_id,
        )
    except (OpsFindingNotFoundError, InvalidFindingTransitionError, FindingRevisionConflictError) as exc:
        _raise_lifecycle_error(exc)


@router.post(
    "/findings/{finding_id}/diagnose",
    response_model=OpsDiagnosisResult,
)
def diagnose_finding(
    finding_id: str,
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsDiagnosisService = Depends(get_ops_diagnosis_service),
) -> OpsDiagnosisResult:
    """对单条问题发起 LLM 智能诊断（#51）。

    无引用诊断落库 insufficient_evidence（不产生可执行建议）；
    模型未配置/输出不可解析 → 503，不落库不覆盖旧报告。
    """
    try:
        return service.diagnose_finding(finding_id, actor=principal.user_id)
    except OpsFindingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("FINDING_NOT_FOUND", str(exc)),
        ) from exc
    except DiagnosisUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("DIAGNOSIS_UNAVAILABLE", str(exc)),
        ) from exc


@router.get(
    "/remediation-actions",
    response_model=list[RemediationActionInfo],
)
def list_remediation_actions(
    _principal=Depends(require_ops_read),
    service: OpsHealthService = Depends(get_ops_service),
) -> list[RemediationActionInfo]:
    """当前 L1 修复白名单：检查项 → 允许自动执行的动作。"""
    return [
        RemediationActionInfo(
            action=spec.action_id,
            check_id=spec.check_id,
            risk_level=spec.risk_level,
            description=spec.description,
        )
        for spec in service.list_remediation_actions()
    ]


@router.post(
    "/findings/{finding_id}/remediate",
    response_model=OpsRemediationResult,
)
def remediate_finding(
    finding_id: str,
    expected_revision: int = Query(ge=1),
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsRemediationResult:
    """对开放问题执行白名单 L1 动作并强制验证（#53）。

    验证通过 → resolved；未通过 → 保持 open 并累计 occurrence；
    动作未发起 → 只落 failed 留痕。非白名单检查项 409。
    """
    try:
        return service.remediate_finding(
            finding_id,
            expected_revision=expected_revision,
            actor=principal.user_id,
        )
    except (
        OpsFindingNotFoundError,
        InvalidFindingTransitionError,
        FindingRevisionConflictError,
        RemediationNotAllowedError,
    ) as exc:
        _raise_lifecycle_error(exc)


@router.post(
    "/findings/{finding_id}/manual-handoff",
    response_model=OpsManualResult,
)
def request_manual_handling(
    finding_id: str,
    request: ManualHandoffRequest,
    expected_revision: int = Query(ge=1),
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsManualResult:
    """转人工处理（#54，open → waiting_human）。

    复用 task_closure 创建 waiting_human_confirmation 确认任务；跳转目标按
    资产类型映射（knowledge → 政策知识治理 / skill → 技能草稿 / 其余外部）。
    未完成确认前问题不得进入 resolved。
    """
    try:
        return service.request_manual_handling(
            finding_id,
            expected_revision=expected_revision,
            actor=principal.user_id,
            note=request.note,
        )
    except (
        OpsFindingNotFoundError,
        InvalidFindingTransitionError,
        FindingRevisionConflictError,
    ) as exc:
        _raise_lifecycle_error(exc)


@router.post(
    "/findings/{finding_id}/manual-complete",
    response_model=OpsManualResult,
)
def complete_manual_handling(
    finding_id: str,
    request: ManualCompleteRequest,
    expected_revision: int = Query(ge=1),
    principal: DataGovernancePrincipal = Depends(require_ops_write),
    service: OpsHealthService = Depends(get_ops_service),
) -> OpsManualResult:
    """人工处理完成（#54，waiting_human → 自动复检）。

    复检通过 → resolved；仍报 → 回 open 累计复现；检查器异常 → 回 open
    待下次巡检。处理结果回填任务 output_data 供 Portal 回链展示。
    """
    try:
        return service.complete_manual_handling(
            finding_id,
            expected_revision=expected_revision,
            actor=principal.user_id,
            result_note=request.result_note,
        )
    except (
        OpsFindingNotFoundError,
        ManualTaskNotFoundError,
        InvalidFindingTransitionError,
        FindingRevisionConflictError,
    ) as exc:
        _raise_lifecycle_error(exc)
