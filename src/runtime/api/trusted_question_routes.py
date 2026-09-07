"""可信问题库 API（Issue #37 Slice 3）。

前缀：/api/v1/medical-insurance-ai-agent/trusted-questions
审核流：draft → pending_review → active → retired（驳回回 draft），
状态机由领域层裁定，存储层乐观锁并发控制。
身份口径：沿用开发身份（created_by/reviewed_by 声明式字段），SSO 属 §10.1 外部依赖。
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.data_platform.storage.trusted_question.trusted_question_ports import (
    TrustedQuestionConflictError,
    TrustedQuestionNotFoundError,
    TrustedQuestionStorage,
)
from src.domain.trusted_qa.models import (
    TrustedQuestion,
    TrustedQuestionInvalidTransitionError,
    TrustedQuestionStatus,
    TrustedQuestionSynonym,
)
from src.runtime.trusted_qa.executor import (
    TrustedAnswerResult,
    execute_trusted_answer,
)
from src.runtime.trusted_qa.matcher import TrustedQuestionMatcher
from src.runtime.trusted_qa.models import (
    TrustedQuestionCandidate,
    TrustedQuestionMatchOutcome,
    TrustedQuestionMatchResult,
)
from src.semantic_layer.query_planner import SemanticQueryService
from src.shared.schemas.responses import error_detail

logger = logging.getLogger(__name__)

router = APIRouter(tags=["trusted-questions"])

# 匹配候选加载上限：active 可信问题全量参与匹配（v1 规模 50~100 条，500 足够）
_MATCH_LOAD_LIMIT = 500


def get_trusted_question_store() -> TrustedQuestionStorage:
    from src.data_platform.storage.trusted_question.trusted_question_factory import (
        get_trusted_question_storage,
    )

    return get_trusted_question_storage()


TrustedQuestionStoreDependency = Annotated[
    TrustedQuestionStorage, Depends(get_trusted_question_store)
]


def get_trusted_question_matcher() -> TrustedQuestionMatcher:
    return TrustedQuestionMatcher()


def get_semantic_query_service() -> SemanticQueryService:
    """语义查询执行通道：与 /semantic/query/test 共用连接注入（SQL Server 防腐层）。"""
    from src.runtime.api.semantic_routes import _get_semantic_query_runtime

    _, service = _get_semantic_query_runtime()
    return service


SemanticQueryServiceDependency = Annotated[
    SemanticQueryService, Depends(get_semantic_query_service)
]


TrustedQuestionMatcherDependency = Annotated[
    TrustedQuestionMatcher, Depends(get_trusted_question_matcher)
]


# ── 请求 / 响应模型 ─────────────────────────────────────────────


class TrustedQuestionCreateRequest(BaseModel):
    standard_question: str = Field(min_length=1)
    synonyms: list[str] = Field(default_factory=list)
    applicable_roles: list[str] = Field(default_factory=list)
    metric_codes: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    query_plan: dict[str, Any] | None = None
    allowed_drilldowns: list[str] = Field(default_factory=list)
    expected_result_traits: dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(default="", max_length=64)


class TrustedQuestionUpdateRequest(BaseModel):
    standard_question: str = Field(min_length=1)
    synonyms: list[str] = Field(default_factory=list)
    applicable_roles: list[str] = Field(default_factory=list)
    metric_codes: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    query_plan: dict[str, Any] | None = None
    allowed_drilldowns: list[str] = Field(default_factory=list)
    expected_result_traits: dict[str, Any] = Field(default_factory=dict)
    expected_version: int = Field(ge=1)


class TrustedQuestionTransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    operator: str = Field(default="", max_length=64)
    review_note: str | None = None


class TrustedQuestionSynonymAddRequest(BaseModel):
    expression: str = Field(min_length=1, max_length=512)
    added_by: str = Field(default="", max_length=64)
    expected_version: int = Field(ge=1)


class TrustedQuestionListResponse(BaseModel):
    items: list[TrustedQuestion]
    limit: int
    offset: int


class TrustedQuestionMatchRequest(BaseModel):
    question: str = Field(min_length=1)
    role: str | None = Field(default=None, max_length=64)


# ── 异常映射 ────────────────────────────────────────────────────


def _not_found(exc: TrustedQuestionNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=error_detail("TRUSTED_QUESTION_NOT_FOUND", str(exc)),
    )


def _conflict(exc: TrustedQuestionConflictError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=error_detail("TRUSTED_QUESTION_CONFLICT", str(exc)),
    )


def _invalid_transition(exc: TrustedQuestionInvalidTransitionError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=error_detail("TRUSTED_QUESTION_INVALID_TRANSITION", str(exc)),
    )


# ── 管理端点 ────────────────────────────────────────────────────


@router.get("/trusted-questions", response_model=TrustedQuestionListResponse)
def list_trusted_questions(
    store: TrustedQuestionStoreDependency,
    status_filter: TrustedQuestionStatus | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TrustedQuestionListResponse:
    items = store.list_questions(
        status=status_filter, keyword=keyword, limit=limit, offset=offset
    )
    return TrustedQuestionListResponse(items=items, limit=limit, offset=offset)


@router.post(
    "/trusted-questions",
    response_model=TrustedQuestion,
    status_code=status.HTTP_201_CREATED,
)
def create_trusted_question(
    request: TrustedQuestionCreateRequest,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    # 新建一律 draft 状态，必须经审核流才能 active
    question = TrustedQuestion(
        question_id=f"tq_{uuid4().hex[:12]}",
        standard_question=request.standard_question,
        synonyms=[
            TrustedQuestionSynonym(expression=e, added_by=request.created_by)
            for e in request.synonyms
        ],
        applicable_roles=request.applicable_roles,
        metric_codes=request.metric_codes,
        dimensions=request.dimensions,
        time_scope=request.time_scope,
        filters=request.filters,
        query_plan=request.query_plan,
        allowed_drilldowns=request.allowed_drilldowns,
        expected_result_traits=request.expected_result_traits,
        created_by=request.created_by,
    )
    try:
        return store.save_question(question)
    except TrustedQuestionConflictError as exc:
        raise _conflict(exc) from exc


@router.get("/trusted-questions/{question_id}", response_model=TrustedQuestion)
def get_trusted_question(
    question_id: str,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    question = store.get_question(question_id)
    if question is None:
        raise _not_found(TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}"))
    return question


@router.put("/trusted-questions/{question_id}", response_model=TrustedQuestion)
def update_trusted_question(
    question_id: str,
    request: TrustedQuestionUpdateRequest,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    current = store.get_question(question_id)
    if current is None:
        raise _not_found(TrustedQuestionNotFoundError(f"可信问题不存在: {question_id}"))
    updated = current.model_copy(
        update={
            "standard_question": request.standard_question,
            "synonyms": [
                TrustedQuestionSynonym(expression=e, added_by=current.created_by)
                for e in request.synonyms
            ],
            "applicable_roles": request.applicable_roles,
            "metric_codes": request.metric_codes,
            "dimensions": request.dimensions,
            "time_scope": request.time_scope,
            "filters": request.filters,
            "query_plan": request.query_plan,
            "allowed_drilldowns": request.allowed_drilldowns,
            "expected_result_traits": request.expected_result_traits,
            "version": request.expected_version + 1,
        },
        deep=True,
    )
    try:
        return store.update_question(updated, expected_version=request.expected_version)
    except TrustedQuestionNotFoundError as exc:
        raise _not_found(exc) from exc
    except TrustedQuestionInvalidTransitionError as exc:
        raise _invalid_transition(exc) from exc
    except TrustedQuestionConflictError as exc:
        raise _conflict(exc) from exc


@router.post(
    "/trusted-questions/{question_id}/submit-review", response_model=TrustedQuestion
)
def submit_trusted_question_review(
    question_id: str,
    request: TrustedQuestionTransitionRequest,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    return _transition(
        store,
        question_id,
        TrustedQuestionStatus.PENDING_REVIEW,
        request,
    )


@router.post("/trusted-questions/{question_id}/approve", response_model=TrustedQuestion)
def approve_trusted_question(
    question_id: str,
    request: TrustedQuestionTransitionRequest,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    if not request.operator.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("REVIEWER_REQUIRED", "审核通过必须声明审核人 operator"),
        )
    return _transition(store, question_id, TrustedQuestionStatus.ACTIVE, request)


@router.post("/trusted-questions/{question_id}/reject", response_model=TrustedQuestion)
def reject_trusted_question(
    question_id: str,
    request: TrustedQuestionTransitionRequest,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    if not (request.review_note or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail("REVIEW_NOTE_REQUIRED", "驳回必须填写 review_note"),
        )
    return _transition(store, question_id, TrustedQuestionStatus.DRAFT, request)


@router.post("/trusted-questions/{question_id}/retire", response_model=TrustedQuestion)
def retire_trusted_question(
    question_id: str,
    request: TrustedQuestionTransitionRequest,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    return _transition(store, question_id, TrustedQuestionStatus.RETIRED, request)


def _transition(
    store: TrustedQuestionStorage,
    question_id: str,
    to_status: TrustedQuestionStatus,
    request: TrustedQuestionTransitionRequest,
) -> TrustedQuestion:
    try:
        return store.transition_status(
            question_id,
            to_status,
            expected_version=request.expected_version,
            operator=request.operator,
            review_note=request.review_note,
        )
    except TrustedQuestionNotFoundError as exc:
        raise _not_found(exc) from exc
    except TrustedQuestionInvalidTransitionError as exc:
        raise _invalid_transition(exc) from exc
    except TrustedQuestionConflictError as exc:
        raise _conflict(exc) from exc


# ── 同义表达运营 ────────────────────────────────────────────────


@router.post(
    "/trusted-questions/{question_id}/synonyms", response_model=TrustedQuestion
)
def add_trusted_question_synonym(
    question_id: str,
    request: TrustedQuestionSynonymAddRequest,
    store: TrustedQuestionStoreDependency,
) -> TrustedQuestion:
    try:
        return store.add_synonym(
            question_id,
            TrustedQuestionSynonym(
                expression=request.expression, added_by=request.added_by
            ),
            expected_version=request.expected_version,
        )
    except TrustedQuestionNotFoundError as exc:
        raise _not_found(exc) from exc
    except TrustedQuestionConflictError as exc:
        raise _conflict(exc) from exc


@router.delete(
    "/trusted-questions/{question_id}/synonyms/{expression}",
    response_model=TrustedQuestion,
)
def remove_trusted_question_synonym(
    question_id: str,
    expression: str,
    store: TrustedQuestionStoreDependency,
    expected_version: int = Query(ge=1),
) -> TrustedQuestion:
    try:
        return store.remove_synonym(
            question_id, expression, expected_version=expected_version
        )
    except TrustedQuestionNotFoundError as exc:
        raise _not_found(exc) from exc
    except TrustedQuestionConflictError as exc:
        raise _conflict(exc) from exc


# ── 匹配端点 ────────────────────────────────────────────────────


@router.post("/trusted-questions/match", response_model=TrustedQuestionMatchResult)
def match_trusted_question(
    request: TrustedQuestionMatchRequest,
    store: TrustedQuestionStoreDependency,
    matcher: TrustedQuestionMatcherDependency,
) -> TrustedQuestionMatchResult:
    """可信问题优先匹配：不确定时返回候选列表，绝不猜测执行。"""
    # 仅 active 可信问题参与匹配；声明 role 时按适用角色过滤（空角色表=全员适用）
    active = store.list_questions(
        status=TrustedQuestionStatus.ACTIVE, limit=_MATCH_LOAD_LIMIT
    )
    if request.role:
        active = [
            q
            for q in active
            if not q.applicable_roles or request.role in q.applicable_roles
        ]
    return matcher.match(request.question, active)


# ── 命中执行闭环 ────────────────────────────────────────────────


class TrustedMatchAndExecuteResponse(BaseModel):
    """match + execute 组合响应。

    仅 matched 且携带查询计划快照时才执行；candidates/no_match
    绝不执行，交澄清或长尾受控语义生成。
    """

    outcome: TrustedQuestionMatchOutcome
    question: TrustedQuestion | None = None
    candidates: list[TrustedQuestionCandidate] = Field(default_factory=list)
    answer: TrustedAnswerResult | None = None


@router.post(
    "/trusted-questions/match-and-execute",
    response_model=TrustedMatchAndExecuteResponse,
)
def match_and_execute_trusted_question(
    request: TrustedQuestionMatchRequest,
    store: TrustedQuestionStoreDependency,
    matcher: TrustedQuestionMatcherDependency,
    service: SemanticQueryServiceDependency,
) -> TrustedMatchAndExecuteResponse:
    """可信问题优先命中 + 确定性执行闭环。

    验收口径：命中时结果必须来自 query_plan 快照回放且通过
    expected_result_traits 校验；匹配不确定时只返回候选，不猜测执行。
    """
    active = store.list_questions(
        status=TrustedQuestionStatus.ACTIVE, limit=_MATCH_LOAD_LIMIT
    )
    if request.role:
        active = [
            q
            for q in active
            if not q.applicable_roles or request.role in q.applicable_roles
        ]
    match_result = matcher.match(request.question, active)

    # 不确定或未命中：只回候选，绝不执行
    if match_result.outcome != TrustedQuestionMatchOutcome.MATCHED or (
        match_result.question is None
    ):
        return TrustedMatchAndExecuteResponse(
            outcome=match_result.outcome,
            question=match_result.question,
            candidates=match_result.candidates,
        )

    answer = execute_trusted_answer(match_result.question, service)
    return TrustedMatchAndExecuteResponse(
        outcome=match_result.outcome,
        question=match_result.question,
        answer=answer,
    )
