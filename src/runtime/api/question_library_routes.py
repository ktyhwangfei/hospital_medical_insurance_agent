"""可信问题库 API — issue #37。

前缀 /api/v1/medical-insurance-ai-agent/question-library；管理端点走签名
JWT 的 question_library:read / question_library:write 权限（与 ops 同模式），
试问 /match 与执行 /questions/{id}/execute 沿语义层只读先例开放（无写入性
副作用，事件留痕为追加元数据）。

服务通过 Depends(get_question_library_service) 注入——API 测试 override
该依赖即可注入内存存储（项目既有陷阱：直接调用工厂不响应 override）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.data_platform.storage.question_library.question_factory import (
    get_trusted_question_storage,
)
from src.domain.question_library.models import (
    ColdStartCandidate,
    InvalidQuestionTransitionError,
    QuestionLibraryStats,
    QuestionMatchEventOutcome,
    QuestionMatchEventPage,
    QuestionMatchOutcome,
    QuestionRevisionConflictError,
    QuestionRoleForbiddenError,
    QuestionSynonymConflictError,
    TrustedQuestionDraft,
    TrustedQuestionNotFoundError,
    TrustedQuestionPage,
    TrustedQuestionStatus,
)
from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
from src.runtime.question_library.service import QuestionLibraryService
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/question-library",
    tags=["question-library"],
)


def _default_plan_validator():
    """草稿期编译校验：绑定计划必须在当前已发布查询模型上可规划。"""
    from src.semantic_layer.query_planner import SemanticQuery, SemanticQueryPlanner
    from src.semantic_layer.registry import get_semantic_registry

    planner = SemanticQueryPlanner(get_semantic_registry())

    def validate(plan: dict[str, Any]) -> None:
        planner.plan(SemanticQuery.model_validate(plan))

    return validate


def _default_query_executor():
    """执行面：SemanticQueryService 确定性执行绑定计划（与结算问数同通道）。"""
    from src.semantic_layer.query_planner import SemanticQuery, SemanticQueryService
    from src.semantic_layer.registry import get_semantic_registry
    from src.runtime.discovery.semantic_source import get_semantic_data_source

    query_service = SemanticQueryService(
        get_semantic_registry(),
        get_semantic_data_source().open_connection,
    )

    def executor(plan: dict[str, Any]) -> dict[str, Any]:
        return query_service.execute(SemanticQuery.model_validate(plan)).model_dump()

    return executor


def _default_history_source():
    """冷启动数据面：tasks 表里 policy_qa 任务的原始问法（question_excerpt）。"""
    from src.config.production import DATABASE_URL
    from src.data_platform.storage.postgresql.client import PostgreSQLClient

    def read() -> list[tuple[str, str]]:
        client = PostgreSQLClient(DATABASE_URL)
        rows = client.execute(
            "SELECT input_data->>'question_excerpt' AS q, created_at AS c FROM tasks "
            "WHERE task_type = 'policy_qa' AND COALESCE(input_data->>'question_excerpt', '') <> '' "
            "ORDER BY created_at DESC LIMIT 2000",
        )
        return [(str(row["q"]), str(row["c"])) for row in rows]

    return read


def get_question_library_service() -> QuestionLibraryService:
    """依赖注入 seam：API 测试 override 此函数注入内存存储与 fake 执行面。"""
    return QuestionLibraryService(
        get_trusted_question_storage(),
        plan_validator=_default_plan_validator(),
        query_executor=_default_query_executor(),
        history_source=_default_history_source(),
    )


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


def require_question_library_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    return _require_permission("question_library:read", authorization)


def require_question_library_write(
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    return _require_permission("question_library:write", authorization)


class MatchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    roles: list[str] | None = Field(default=None, max_length=20)


class CreateDraftRequest(TrustedQuestionDraft):
    pass


class ReviewRequest(BaseModel):
    approve: bool
    reviewer: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=500)
    expected_revision: int = Field(ge=1)


class AddSynonymRequest(BaseModel):
    synonym: str = Field(min_length=1, max_length=500)
    expected_revision: int = Field(ge=1)


def _raise_question_error(exc: Exception) -> None:
    if isinstance(exc, TrustedQuestionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail("QUESTION_NOT_FOUND", str(exc)),
        )
    if isinstance(exc, QuestionRevisionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("QUESTION_REVISION_CONFLICT", str(exc)),
        )
    if isinstance(exc, InvalidQuestionTransitionError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("QUESTION_TRANSITION_INVALID", str(exc)),
        )
    if isinstance(exc, QuestionSynonymConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail("QUESTION_SYNONYM_CONFLICT", str(exc)),
        )
    if isinstance(exc, QuestionRoleForbiddenError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("QUESTION_ROLE_FORBIDDEN", str(exc)),
        )
    raise exc


@router.post("/match", response_model=QuestionMatchOutcome)
def match_question(
    request: MatchRequest,
    service: QuestionLibraryService = Depends(get_question_library_service),
) -> QuestionMatchOutcome:
    """试问：归一化命中→hit；其余一律 clarify（候选列表），不猜测执行。"""
    return service.match(request.question, roles=request.roles)


@router.get("/questions", response_model=TrustedQuestionPage)
def list_questions(
    status_filter: TrustedQuestionStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _principal: DataGovernancePrincipal = Depends(require_question_library_read),
    service: QuestionLibraryService = Depends(get_question_library_service),
) -> TrustedQuestionPage:
    return service.list_questions(status=status_filter, q=q, page=page, page_size=page_size)


@router.post("/questions", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_draft(
    request: CreateDraftRequest,
    principal: DataGovernancePrincipal = Depends(require_question_library_write),
    service: QuestionLibraryService = Depends(get_question_library_service),
):
    try:
        question = service.create_draft(request, actor=principal.user_id)
    except QuestionSynonymConflictError as exc:
        _raise_question_error(exc)
    except ValueError as exc:
        # 草稿元数据/绑定计划校验失败（含 planner 干跑拒绝）
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail("QUESTION_DRAFT_INVALID", str(exc)),
        )
    return {"question_id": question.question_id, "status": question.status.value}


@router.get("/questions/{question_id}", response_model=dict)
def get_question(
    question_id: str,
    _principal: DataGovernancePrincipal = Depends(require_question_library_read),
    service: QuestionLibraryService = Depends(get_question_library_service),
):
    try:
        return service.get_question(question_id).model_dump(mode="json")
    except TrustedQuestionNotFoundError as exc:
        _raise_question_error(exc)


@router.post("/questions/{question_id}/review", response_model=dict)
def review_question(
    question_id: str,
    request: ReviewRequest,
    principal: DataGovernancePrincipal = Depends(require_question_library_write),
    service: QuestionLibraryService = Depends(get_question_library_service),
):
    try:
        question = service.review(
            question_id,
            approve=request.approve,
            reviewer=request.reviewer,
            expected_revision=request.expected_revision,
        )
    except (TrustedQuestionNotFoundError, InvalidQuestionTransitionError, QuestionRevisionConflictError) as exc:
        _raise_question_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail("QUESTION_REVIEW_INVALID", str(exc)),
        )
    return {"question_id": question.question_id, "status": question.status.value, "version": question.version}


@router.post("/questions/{question_id}/archive", response_model=dict)
def archive_question(
    question_id: str,
    expected_revision: int = Query(ge=1),
    _principal: DataGovernancePrincipal = Depends(require_question_library_write),
    service: QuestionLibraryService = Depends(get_question_library_service),
):
    try:
        question = service.archive(question_id, expected_revision=expected_revision)
    except (TrustedQuestionNotFoundError, InvalidQuestionTransitionError, QuestionRevisionConflictError) as exc:
        _raise_question_error(exc)
    return {"question_id": question.question_id, "status": question.status.value}


@router.post("/questions/{question_id}/synonyms", response_model=dict)
def add_synonym(
    question_id: str,
    request: AddSynonymRequest,
    _principal: DataGovernancePrincipal = Depends(require_question_library_write),
    service: QuestionLibraryService = Depends(get_question_library_service),
):
    try:
        question = service.add_synonym(
            question_id,
            synonym=request.synonym,
            expected_revision=request.expected_revision,
        )
    except (
        TrustedQuestionNotFoundError,
        InvalidQuestionTransitionError,
        QuestionRevisionConflictError,
        QuestionSynonymConflictError,
    ) as exc:
        _raise_question_error(exc)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail("QUESTION_SYNONYM_INVALID", str(exc)),
        )
    return {"question_id": question.question_id, "synonyms": question.synonyms}


@router.post("/questions/{question_id}/execute", response_model=dict)
def execute_question(
    question_id: str,
    roles: list[str] | None = Query(default=None),
    service: QuestionLibraryService = Depends(get_question_library_service),
):
    """执行已发布问题的绑定查询计划（只读确定性查询，沿语义层只读先例开放）。"""
    try:
        return service.execute(question_id, roles=roles)
    except (TrustedQuestionNotFoundError, InvalidQuestionTransitionError, QuestionRoleForbiddenError) as exc:
        _raise_question_error(exc)


@router.get("/match-events", response_model=QuestionMatchEventPage)
def list_match_events(
    outcome: QuestionMatchEventOutcome | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _principal: DataGovernancePrincipal = Depends(require_question_library_read),
    service: QuestionLibraryService = Depends(get_question_library_service),
) -> QuestionMatchEventPage:
    return service.list_match_events(outcome=outcome, page=page, page_size=page_size)


@router.get("/stats", response_model=QuestionLibraryStats)
def get_stats(
    _principal: DataGovernancePrincipal = Depends(require_question_library_read),
    service: QuestionLibraryService = Depends(get_question_library_service),
) -> QuestionLibraryStats:
    return service.stats()


@router.get("/cold-start", response_model=list[ColdStartCandidate])
def cold_start(
    limit: int = Query(default=100, ge=1, le=100),
    _principal: DataGovernancePrincipal = Depends(require_question_library_read),
    service: QuestionLibraryService = Depends(get_question_library_service),
) -> list[ColdStartCandidate]:
    return service.cold_start(limit=limit)
