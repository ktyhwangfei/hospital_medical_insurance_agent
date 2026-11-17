"""筛查规则管理 API — issue #86 规则管理（管理入口）。

前缀 /api/v1/medical-insurance-ai-agent/rule-management；全部端点走签名
JWT 的 rule_management:read / rule_management:write 权限（与
question-library / data-governance 同模式）。

与运营问数入口严格分离：这里负责上传、分类、候选规则、批准/修改/关闭、
执行批次与两本名单；问数侧只读结果表（ai_screen_*）作答。

服务通过 Depends(get_screening_rule_service) 注入——API 测试 override
该依赖即可注入内存存储与 fake 执行数据面（项目既有陷阱：直接调用工厂
不响应 override）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Callable, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.data_platform.storage.screening_rules.factory import (
    get_screening_rule_storage,
)
from src.domain.screening_rules.models import (
    FindingType,
    NoApprovedRulesError,
    RuleClass,
    RuleNotApprovedError,
    RuleStatus,
    ScreeningFindingNotFoundError,
    ScreeningRuleNotFoundError,
    ScreeningRunNotFoundError,
    VerifyStatus,
)
from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
from src.runtime.screening_rules.service import ScreeningRuleService
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/rule-management",
    tags=["rule-management"],
)
T = TypeVar("T")


def _default_fee_line_loader():
    """生产执行数据面：bjyb 的 dbo.o_Trade × dbo.o_FeeItem。"""
    from src.runtime.screening_rules.fee_line_loader import load_fee_lines

    return load_fee_lines


def _default_context_loader():
    """生产就诊上下文：dbo.o_Trade 的 P_Birthday/P_Sex + dbo.o_Diagnose。"""
    from src.runtime.screening_rules.fee_line_loader import load_settlement_contexts

    return load_settlement_contexts


def get_screening_rule_service() -> ScreeningRuleService:
    """依赖注入 seam：API 测试 override 此函数注入内存存储与 fake loader。"""
    return ScreeningRuleService(
        get_screening_rule_storage(),
        fee_line_loader=_default_fee_line_loader(),
        context_loader=_default_context_loader(),
    )


def _require_permission(permission: str, authorization: str | None) -> DataGovernancePrincipal:
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


def require_rule_management_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> DataGovernancePrincipal:
    return _require_permission("rule_management:read", authorization)


def require_rule_management_write(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> DataGovernancePrincipal:
    return _require_permission("rule_management:write", authorization)


ReadPrincipal = Annotated[DataGovernancePrincipal, Depends(require_rule_management_read)]
WritePrincipal = Annotated[DataGovernancePrincipal, Depends(require_rule_management_write)]
Service = Annotated[ScreeningRuleService, Depends(get_screening_rule_service)]


def _call(action: Callable[[], T]) -> T:
    try:
        return action()
    except ScreeningRuleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("RULE_NOT_FOUND", str(exc)),
        ) from exc
    except ScreeningRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("RUN_NOT_FOUND", str(exc)),
        ) from exc
    except ScreeningFindingNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("FINDING_NOT_FOUND", str(exc)),
        ) from exc
    except RuleNotApprovedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("RULE_NOT_APPROVED", str(exc)),
        ) from exc
    except NoApprovedRulesError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("NO_APPROVED_RULES", str(exc)),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail("RULE_INVALID", str(exc)),
        ) from exc


# ── 请求/响应 DTO ──


class UploadChecklistRequest(BaseModel):
    source_doc: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1)


class ChecklistItemResponse(BaseModel):
    item_ref: str
    clause: str
    rule_class: str
    mapping_gap: str | None
    candidate_rule_id: str | None


class UploadChecklistResponse(BaseModel):
    source_doc: str
    items: list[ChecklistItemResponse]
    candidate_rule_ids: list[str]


class RuleResponse(BaseModel):
    rule_id: str
    source_doc: str
    source_clause: str
    title: str
    condition_text: str
    rule_class: str
    mapping_gap: str | None
    status: str
    source_item_ref: str | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    approved_by: str | None


class UpdateRuleRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    condition_text: str | None = Field(default=None, min_length=1)
    mapping_gap: str | None = None


class CreateRuleRequest(BaseModel):
    """手工录入规则（两库知识点等非「重复收取」句式条款）。"""

    source_doc: str = Field(min_length=1, max_length=300)
    source_clause: str = Field(min_length=1)  # 必填：原条款
    title: str = Field(min_length=1, max_length=300)
    condition_text: str = Field(min_length=1)
    rule_class: RuleClass
    condition_spec: dict[str, Any] | None = None
    mapping_gap: str | None = None
    source_item_ref: str | None = None


class StartRunRequest(BaseModel):
    time_range_start: datetime
    time_range_end: datetime
    rule_ids: list[str] | None = None  # 缺省 = 全部已批准的可执行规则


class RunResponse(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    time_range_start: datetime
    time_range_end: datetime
    error_message: str | None
    created_by: str
    rule_ids: list[str] = []
    finding_counts: dict[str, int] = {}


class FindingResponse(BaseModel):
    finding_id: str
    run_id: str
    rule_id: str
    settlement_key: str
    fee_line_id: str | None
    item_code: str | None
    item_name: str | None
    amount: float | None
    finding_type: str
    primary_finding_id: str
    evidence_clause: str
    evidence_facts: dict[str, Any]
    verify_status: str
    created_at: datetime


class VerifyFindingRequest(BaseModel):
    verify_status: VerifyStatus


def _rule_response(rule) -> RuleResponse:
    return RuleResponse(
        rule_id=rule.rule_id,
        source_doc=rule.source_doc,
        source_clause=rule.source_clause,
        title=rule.title,
        condition_text=rule.condition_text,
        rule_class=rule.rule_class.value,
        mapping_gap=rule.mapping_gap,
        status=rule.status.value,
        source_item_ref=rule.source_item_ref,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        approved_at=rule.approved_at,
        approved_by=rule.approved_by,
    )


def _run_response(service: ScreeningRuleService, run) -> RunResponse:
    _, rule_ids, finding_counts = service.get_run(run.run_id)
    return RunResponse(
        run_id=run.run_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status.value,
        time_range_start=run.time_range_start,
        time_range_end=run.time_range_end,
        error_message=run.error_message,
        created_by=run.created_by,
        rule_ids=rule_ids,
        finding_counts=finding_counts,
    )


def _finding_response(finding) -> FindingResponse:
    return FindingResponse(**finding.model_dump(mode="json"))


# ── 上传与分类 ──


@router.post("/checklists", response_model=UploadChecklistResponse, status_code=status.HTTP_201_CREATED)
def upload_checklist(
    payload: UploadChecklistRequest,
    service: Service,
    _principal: WritePrincipal,
) -> UploadChecklistResponse:
    """上传政策/问题清单：逐条分类，可执行条目生成带原条款的候选规则。"""
    items, rules = _call(
        lambda: service.upload_checklist(
            source_doc=payload.source_doc, content=payload.content
        )
    )
    return UploadChecklistResponse(
        source_doc=payload.source_doc,
        items=[
            ChecklistItemResponse(
                item_ref=item.item_ref,
                clause=item.clause,
                rule_class=item.rule_class.value,
                mapping_gap=item.mapping_gap,
                candidate_rule_id=item.candidate_rule_id,
            )
            for item in items
        ],
        candidate_rule_ids=[rule.rule_id for rule in rules],
    )


# ── 规则生命周期 ──


@router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: CreateRuleRequest,
    service: Service,
    _principal: WritePrincipal,
) -> RuleResponse:
    """手工录入规则（两库知识点等非「重复收取」句式条款），一律以候选落库。"""
    rule = _call(
        lambda: service.create_rule(
            source_doc=payload.source_doc,
            source_clause=payload.source_clause,
            title=payload.title,
            condition_text=payload.condition_text,
            rule_class=payload.rule_class,
            condition_spec=payload.condition_spec,
            mapping_gap=payload.mapping_gap,
            source_item_ref=payload.source_item_ref,
        )
    )
    return _rule_response(rule)


@router.get("/rules", response_model=list[RuleResponse])
def list_rules(
    service: Service,
    _principal: ReadPrincipal,
    rule_class: RuleClass | None = Query(default=None),
    rule_status: RuleStatus | None = Query(default=None, alias="status"),
) -> list[RuleResponse]:
    rules = _call(lambda: service.list_rules(rule_class=rule_class, status=rule_status))
    return [_rule_response(rule) for rule in rules]


@router.get("/rules/{rule_id}", response_model=RuleResponse)
def get_rule(rule_id: str, service: Service, _principal: ReadPrincipal) -> RuleResponse:
    return _rule_response(_call(lambda: service.get_rule(rule_id)))


@router.patch("/rules/{rule_id}", response_model=RuleResponse)
def update_rule(
    rule_id: str,
    payload: UpdateRuleRequest,
    service: Service,
    _principal: WritePrincipal,
) -> RuleResponse:
    rule = _call(
        lambda: service.update_rule(
            rule_id,
            title=payload.title,
            condition_text=payload.condition_text,
            mapping_gap=payload.mapping_gap,
        )
    )
    return _rule_response(rule)


@router.post("/rules/{rule_id}/approve", response_model=RuleResponse)
def approve_rule(rule_id: str, service: Service, principal: WritePrincipal) -> RuleResponse:
    """批准规则：批准前不得跑数（批准门禁）。"""
    rule = _call(lambda: service.approve_rule(rule_id, approved_by=principal.user_id))
    return _rule_response(rule)


@router.post("/rules/{rule_id}/disable", response_model=RuleResponse)
def disable_rule(rule_id: str, service: Service, _principal: WritePrincipal) -> RuleResponse:
    """关闭规则：不再进入后续执行批次。"""
    return _rule_response(_call(lambda: service.disable_rule(rule_id)))


# ── 执行批次 ──


@router.post("/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def start_run(
    payload: StartRunRequest,
    service: Service,
    principal: WritePrincipal,
) -> RunResponse:
    """对已批准规则执行跑数；未批准规则整批拒绝，结果表不出现新命中。"""
    run = _call(
        lambda: service.start_run(
            time_range_start=payload.time_range_start,
            time_range_end=payload.time_range_end,
            created_by=principal.user_id,
            rule_ids=payload.rule_ids,
        )
    )
    return _run_response(service, run)


@router.get("/runs", response_model=list[RunResponse])
def list_runs(
    service: Service,
    _principal: ReadPrincipal,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[RunResponse]:
    runs = _call(lambda: service.list_runs(limit=limit))
    return [_run_response(service, run) for run in runs]


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, service: Service, _principal: ReadPrincipal) -> RunResponse:
    run, _, _ = _call(lambda: service.get_run(run_id))
    return _run_response(service, run)


# ── 两本名单与核实 ──


@router.get("/findings", response_model=list[FindingResponse])
def list_findings(
    service: Service,
    _principal: ReadPrincipal,
    run_id: str | None = Query(default=None),
    rule_id: str | None = Query(default=None),
    finding_type: FindingType | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[FindingResponse]:
    """疑点名单：finding_type=mismatch「明显对不上」/ insufficient_material「材料不足」。"""
    findings = _call(
        lambda: service.list_findings(
            run_id=run_id, rule_id=rule_id, finding_type=finding_type, limit=limit
        )
    )
    return [_finding_response(finding) for finding in findings]


@router.post("/findings/{finding_id}/verify", response_model=FindingResponse)
def verify_finding(
    finding_id: str,
    payload: VerifyFindingRequest,
    service: Service,
    _principal: WritePrincipal,
) -> FindingResponse:
    """医保办核实结论（跟/不跟/材料不足）记在疑点上。"""
    finding = _call(lambda: service.verify_finding(finding_id, payload.verify_status))
    return _finding_response(finding)
