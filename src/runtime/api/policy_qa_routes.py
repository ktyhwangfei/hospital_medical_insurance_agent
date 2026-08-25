"""
医保政策问答RAG系统 - SSE流式API端点

端点: POST /api/v1/medical-insurance-ai-agent/policy-qa/stream
      GET  /api/v1/medical-insurance-ai-agent/policy-qa/history
"""

from __future__ import annotations

import json
import logging
import math
import re
import time as _time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated, Any

import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.runtime.policy_qa.explanation_mode import (
    ExplanationMode,
    detect_explanation_mode,
    fee_item_label,
)
from src.runtime.policy_qa.models import PolicyQARequest
from src.runtime.policy_qa.public_contract import (
    PolicyCitation,
    PolicyQAPublicResult,
    VerificationSummary,
)
from src.runtime.policy_qa.runtime_bridge import get_runtime_bridge
from src.runtime.policy_qa.settlement_data_provider import (
    SettlementDataUnavailableError,
    SettlementNotFoundError,
    create_settlement_data_provider,
)
from src.runtime.policy_qa.structured_policy_retriever import (
    PolicyRetrievalUnavailableError,
    retrieve_policy_evidence,
)
from src.config.production import MILVUS_HOST, MILVUS_PORT
from src.skill_infra.skill_router import route_question, get_assembler, get_skill_manifest
from src.runtime.policy_qa.persistence import (
    ensure_session_and_workflow,
    record_qa_task,
    record_step_task,
    finalize_workflow,
)
from src.runtime.infra_event.context import set_infra_context
from src.shared.schemas.responses import error_detail
from src.data_platform.storage.skill.regression_factory import (
    get_skill_regression_storage,
)
from src.data_platform.storage.skill.regression_ports import (
    SkillRegressionConflictError,
    SkillRegressionNotFoundError,
)
from src.domain.skill.regression_models import SkillFeedbackReasonCode
from src.runtime.api.skill_schemas import (
    EvalCasePoolFromHistoryRequest,
    EvalCasePoolFromHistoryResponse,
    EvalCasePoolItemResponse,
    EvalCasePoolListResponse,
    HistoryMiningOutcomeResponse,
    PolicyQAFeedbackRequest,
    PolicyQAFeedbackResponse,
)
from src.runtime.skill_management.regression_mining_service import (
    QASourceReader,
    QATurnNotAccessibleError,
    QATurnSource,
    RegressionMiningService,
    RegressionPrincipal,
    SensitiveFeedbackRejectedError,
)
from src.runtime.task_closure.service import get_task

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_POLICY_QA_ATTEMPTS = 2

def _sse_event(event_type: str, data: dict | str) -> str:
    """格式化SSE事件
    v2: 包含 public_message / detail / dual-view
    """
    if isinstance(data, dict):
        data_str = json.dumps(data, ensure_ascii=False)
    else:
        data_str = data
    return f'event: {event_type}\ndata: {data_str}\n\n'


def _resolve_tenant_id(request: PolicyQARequest) -> str:
    """从请求上下文解析租户 ID。

    当前未接入生产认证；后续由认证上下文提供，这里提供稳定默认值，
    供案例池去重与所有权校验使用。
    """
    return getattr(request, "tenant_id", None) or "default"


class TaskBackedQASourceReader(QASourceReader):
    """按 qa_turn_id 从 task 闭包读取脱敏前来源快照。"""

    def get_qa_turn(self, qa_turn_id: str) -> QATurnSource | None:
        if not qa_turn_id.startswith("qat_"):
            return None
        task = get_task(qa_turn_id)
        if task is None:
            return None
        input_data = task.get("input_data") or {}
        output_data = task.get("output_data") or {}
        return QATurnSource(
            qa_turn_id=qa_turn_id,
            user_id=str(input_data.get("user_id") or ""),
            tenant_id=str(input_data.get("tenant_id") or ""),
            question=str(input_data.get("question_excerpt") or ""),
            answer=str(output_data.get("answer_excerpt") or ""),
            selected_skill_id=output_data.get("selected_skill_id"),
        )


def get_policy_qa_feedback_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> RegressionPrincipal:
    """反馈调用方身份来自认证上下文（非查询参数）。"""
    from src.gateway.auth import authenticator

    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail=error_detail("AUTHENTICATION_REQUIRED", "反馈需要登录凭证"),
        )
    auth_result = authenticator.validate_token(authorization)
    if not auth_result.is_success or not auth_result.user_id.strip():
        raise HTTPException(
            status_code=401,
            detail=error_detail("INVALID_AUTHENTICATION", auth_result.error_message),
        )
    tenant_id = str(auth_result.metadata.get("tenant_id") or "default")
    return RegressionPrincipal(
        user_id=auth_result.user_id.strip(),
        tenant_id=tenant_id,
        roles=tuple(auth_result.roles),
    )


PolicyQAFeedbackPrincipalDependency = Annotated[
    RegressionPrincipal, Depends(get_policy_qa_feedback_principal)
]


def get_policy_qa_regression_mining_service() -> RegressionMiningService:
    return RegressionMiningService(
        storage=get_skill_regression_storage(),
        qa_source_reader=TaskBackedQASourceReader(),
    )


PolicyQARegressionMiningDependency = Annotated[
    RegressionMiningService, Depends(get_policy_qa_regression_mining_service)
]


# ── 防泄漏：禁止返回前端的字段 ────────────────────────────────────
_FORBIDDEN_KEYS = frozenset({
    "reasoning", "reasoning_content", "chain_of_thought", "thought",
    "scratchpad", "debug", "internal", "prompt", "messages",
    "raw_response", "tool_calls", "agent_trace",
})


def _sanitize(obj: dict) -> dict:
    """递归删除禁止字段，将内部数据写入日志"""
    result = {}
    for key, value in obj.items():
        key_lower = key.lower()
        if any(forbidden in key_lower for forbidden in _FORBIDDEN_KEYS):
            # 内部数据写入日志，不返回前端
            logger.debug(f'[SANITIZE] 已过滤字段: {key}')
            continue
        if isinstance(value, dict):
            result[key] = _sanitize(value)
        elif isinstance(value, list):
            result[key] = [
                _sanitize(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


_PUBLIC_CONTEXT_FIELDS = frozenset({
    "person_type",
    "insurance_type",
    "service_type",
    "hospital_level",
    "deductible",
    "yearly_cycle_count",
    "basic_pooling_payment",
    "basic_pooling_self_pay",
    "large_amount_payment",
    "large_amount_self_pay",
    "personal_total_pay",
    "total_amount",
})
_PUBLIC_CALCULATION_FIELDS = frozenset({
    "step_name", "description", "label", "formula", "result", "calculation", "note",
})
_PUBLIC_DEFINITION_FIELDS = frozenset({"name", "plain_text", "includes", "excludes"})
_PUBLIC_AMOUNT_FIELDS = frozenset({
    "deductible",
    "basic_pooling_payment",
    "basic_pooling_self_pay",
    "large_amount_payment",
    "large_amount_self_pay",
    "personal_total_pay",
    "total_amount",
})
_INTERNAL_TABLE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])yb_[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_SEMANTIC_OBJECT_FIELD_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:zydyxx|zyfdxx|zyjyxx|djxx)\."
    r"[A-Za-z0-9_]+(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_INTERNAL_BARE_IDENTIFIERS = frozenset({
    # settlement_field_mapping 与 assembler._FACT_FIELD_MAP 的原始字段。
    "bcqfje",
    "bcybnje",
    "bctcje",
    "bczfje",
    "bdtczf",
    "bdtczfje",
    "bddegwyzf",
    "bddegwyzfje",
    "bddezf",
    "bddezfje",
    "bdgryf",
    "debxbxje",
    "dezfje",
    "grzfje",
    "fund_type",
    "per_type",
    "yllb",
    "rylb",
    # 标准化字段；deductible 是合法医保术语，刻意保留为公开自然语言。
    "medical_insurance_inner_amount",
    "basic_pooling_payment",
    "basic_pooling_self_pay",
    "large_amount_payment",
    "large_amount_self_pay",
    "personal_total_pay",
    "person_type",
    "insurance_type",
    "service_type",
    "hospital_level",
    # 内部查询与追踪字段。
    "sql_profile",
    "tables_queried",
    "query_trace",
    "raw_sql",
})
_INTERNAL_IDENTIFIER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(
        re.escape(identifier)
        for identifier in sorted(_INTERNAL_BARE_IDENTIFIERS, key=len, reverse=True)
    )
    + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_SQL_STATEMENT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"select(?![A-Za-z0-9_])[\s\S]{0,500}?\s+from(?![A-Za-z0-9_])|"
    r"select(?![A-Za-z0-9_])\s+(?:"
    r"@@[A-Za-z_][A-Za-z0-9_]*|"
    r"\(?\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
    r"(?:\s*[+*/%-]\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+))*\s*\)?"
    r")(?![A-Za-z0-9_])|"
    r"insert(?![A-Za-z0-9_])\s+(?:into(?![A-Za-z0-9_])\s+)?"
    r"[A-Za-z_][A-Za-z0-9_.]*(?:\s*\([^)]{0,500}\))?\s+"
    r"values(?![A-Za-z0-9_])\s*\(|"
    r"update(?![A-Za-z0-9_])\s+[A-Za-z_][A-Za-z0-9_.]*\s+set(?![A-Za-z0-9_])|"
    r"delete(?![A-Za-z0-9_])\s+from(?![A-Za-z0-9_])|"
    r"merge(?![A-Za-z0-9_])\s+into(?![A-Za-z0-9_])|"
    r"(?:create|drop|alter)(?![A-Za-z0-9_])\s+"
    r"(?:or(?![A-Za-z0-9_])\s+replace(?![A-Za-z0-9_])\s+)?"
    r"(?:table|schema|database|db|index|view|procedure|function|trigger)"
    r"(?![A-Za-z0-9_])|"
    r"truncate(?![A-Za-z0-9_])\s+"
    r"(?:table|schema|database|db|index|view)(?![A-Za-z0-9_])|"
    r"exec(?:ute)?(?![A-Za-z0-9_])\s+[A-Za-z_][A-Za-z0-9_.]*|"
    r"call(?![A-Za-z0-9_])\s+[A-Za-z_][A-Za-z0-9_.]*\s*\("
    r")",
    re.IGNORECASE,
)
_CREDENTIAL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:dsn|password|passwd|pwd|token|api[_-]?key|secret|"
    r"connection[_-]?string)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_SENSITIVE_CONNECTION_URI_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:postgres(?:ql)?|redis(?:s)?|milvus|mysql|mssql)://"
    r"[^\s<>'\"]+",
    re.IGNORECASE,
)
_STORAGE_IMPLEMENTATION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:milvus|policy_rules|redis|postgresql|postgres|"
    r"sql[_ -]?server)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _SanitizedPublicText:
    text: str
    is_publicly_meaningful: bool


def _contains_internal_implementation(value: Any) -> bool:
    text = str(value or "")
    return any(
        pattern.search(text)
        for pattern in (
            _SQL_STATEMENT_PATTERN,
            _CREDENTIAL_PATTERN,
            _SENSITIVE_CONNECTION_URI_PATTERN,
            _STORAGE_IMPLEMENTATION_PATTERN,
            _INTERNAL_TABLE_PATTERN,
            _SEMANTIC_OBJECT_FIELD_PATTERN,
            _INTERNAL_IDENTIFIER_PATTERN,
        )
    )


def _sanitize_public_text(value: Any) -> _SanitizedPublicText:
    """清理公开文案，并区分安全占位与可支撑业务结论的内容。"""
    text = str(value or "").strip()
    if not text:
        return _SanitizedPublicText(text="", is_publicly_meaningful=False)
    if _CREDENTIAL_PATTERN.search(text) or _SENSITIVE_CONNECTION_URI_PATTERN.search(text):
        return _SanitizedPublicText(
            text="内部连接细节已隐藏。",
            is_publicly_meaningful=False,
        )
    if _STORAGE_IMPLEMENTATION_PATTERN.search(text):
        return _SanitizedPublicText(
            text="内部存储实现已隐藏。",
            is_publicly_meaningful=False,
        )
    if _SQL_STATEMENT_PATTERN.search(text):
        return _SanitizedPublicText(
            text="内部查询细节已隐藏。",
            is_publicly_meaningful=False,
        )
    meaningful_source = text
    for pattern in (
        _INTERNAL_TABLE_PATTERN,
        _SEMANTIC_OBJECT_FIELD_PATTERN,
        _INTERNAL_IDENTIFIER_PATTERN,
    ):
        meaningful_source = pattern.sub("", meaningful_source)
    text = _INTERNAL_TABLE_PATTERN.sub("结算数据字段", text)
    text = _SEMANTIC_OBJECT_FIELD_PATTERN.sub("结算数据字段", text)
    text = _INTERNAL_IDENTIFIER_PATTERN.sub("内部字段", text)
    text = re.sub(
        r"(?<![A-Za-z0-9_])Milvus\s+policy_rules(?![A-Za-z0-9_])",
        "政策知识库",
        text,
        flags=re.IGNORECASE,
    )
    is_meaningful = bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", meaningful_source))
    return _SanitizedPublicText(
        text=text,
        is_publicly_meaningful=is_meaningful,
    )


def _public_text(value: Any) -> str:
    """返回适合公开展示的安全文本。"""
    return _sanitize_public_text(value).text


def _answerability_from_completeness(
    completeness: dict | None,
    warnings: list[str] | None,
) -> tuple[bool, bool]:
    """只依据策略执行元数据判断是否可回答，避免把非空文案当作事实状态。"""
    completeness = completeness if isinstance(completeness, dict) else {}
    level = str(completeness.get("level") or "")
    has_real_data = completeness.get("has_real_data") is True
    safety_fallback = any(
        "未通过安全校验" in str(warning)
        for warning in warnings or []
    )
    can_answer = has_real_data and not safety_fallback
    partial_answer = can_answer and not level.startswith("full_policy")
    return can_answer, partial_answer


def _build_public_result(
    *,
    answer: str,
    can_answer: bool,
    partial_answer: bool,
    policy_status: str,
    policy_evidence: list[dict],
    calculation_steps: list[dict],
    definition: dict | None,
    warnings: list[str],
    case_context: dict | None,
    is_overview: bool = False,
) -> PolicyQAPublicResult:
    """用字段白名单把内部执行结果重建为唯一公开回答契约。"""
    safe_context = None
    if isinstance(case_context, dict):
        safe_context = {}
        for key, value in case_context.items():
            if key not in _PUBLIC_CONTEXT_FIELDS:
                continue
            if isinstance(value, str):
                safe_context[key] = _public_text(value)
            elif value is None or isinstance(value, (int, float, bool)):
                safe_context[key] = value
        safe_context = safe_context or None

    safe_steps: list[dict[str, str]] = []
    calculation_content_fields = frozenset({
        "description", "formula", "result", "calculation", "note",
    })
    for step in calculation_steps or []:
        if not isinstance(step, dict):
            continue
        safe_step: dict[str, str] = {}
        has_meaningful_content = False
        for key, value in step.items():
            if key not in _PUBLIC_CALCULATION_FIELDS or value is None:
                continue
            sanitized = _sanitize_public_text(value)
            safe_step[key] = sanitized.text
            if key in calculation_content_fields and sanitized.is_publicly_meaningful:
                has_meaningful_content = True
        if safe_step and has_meaningful_content:
            safe_steps.append(safe_step)

    safe_definition = None
    if isinstance(definition, dict):
        safe_definition = {}
        for key, value in definition.items():
            if key not in _PUBLIC_DEFINITION_FIELDS:
                continue
            if isinstance(value, str):
                safe_definition[key] = _public_text(value)
            elif isinstance(value, list):
                safe_definition[key] = [_public_text(item) for item in value if isinstance(item, str)]
        safe_definition = safe_definition or None

    safe_evidence: list[dict[str, str | float | None]] = []
    citations: list[PolicyCitation] = []
    seen_citations: set[tuple[str, str]] = set()
    for evidence in policy_evidence or []:
        if not isinstance(evidence, dict):
            continue
        raw_excerpt = (
            evidence.get("excerpt")
            or evidence.get("clause")
            or evidence.get("clause_text")
            or evidence.get("evidence_text")
            or evidence.get("source_text")
        )
        raw_title = evidence.get("title") or evidence.get("policy_title") or "政策依据"
        if (
            _contains_internal_implementation(raw_excerpt)
            or _contains_internal_implementation(raw_title)
        ):
            continue
        excerpt = _public_text(raw_excerpt)
        if not excerpt:
            continue
        title = _public_text(raw_title)
        citation_key = (title, excerpt)
        if citation_key in seen_citations:
            continue
        score = evidence.get("score")
        try:
            public_score = float(score) if score is not None and not isinstance(score, bool) else None
        except (TypeError, ValueError):
            public_score = None
        if public_score is not None and not math.isfinite(public_score):
            public_score = None
        safe_evidence.append({"title": title, "excerpt": excerpt, "score": public_score})
        citations.append(PolicyCitation(title=title, excerpt=excerpt))
        seen_citations.add(citation_key)

    answer_text = _sanitize_public_text(answer)
    safe_answer = answer_text.text
    has_meaningful_answer = answer_text.is_publicly_meaningful
    has_real_amount = bool(safe_context) and any(
        key in safe_context
        and isinstance(safe_context[key], (int, float))
        and not isinstance(safe_context[key], bool)
        for key in _PUBLIC_AMOUNT_FIELDS
    )
    calculation_checked = bool(safe_steps)
    policy_count = len(safe_evidence)
    if is_overview and has_meaningful_answer and can_answer and has_real_amount:
        answer_status = "complete"
    elif (
        has_meaningful_answer
        and can_answer
        and has_real_amount
        and calculation_checked
        and policy_status == "full_policy_matched"
        and policy_count > 0
    ):
        answer_status = "complete"
    elif has_meaningful_answer and (partial_answer or (can_answer and has_real_amount)):
        answer_status = "partial"
    else:
        answer_status = "unavailable"
        safe_answer = safe_answer or "当前信息不足，无法可靠回答该问题。"

    uncertainties: list[str] = []
    if not has_meaningful_answer:
        uncertainties.append("公开回答未包含可核验的业务内容。")
    if is_overview:
        uncertainties.append("费用总览不涉及单项政策匹配或单项计算过程核验。")
    elif not citations:
        uncertainties.append("未检索到可展示的政策依据。")
    if answer_status == "partial":
        uncertainties.append("政策依据不完整，当前回答仅供核对真实结算金额。")
    elif answer_status == "unavailable":
        uncertainties.append("现有结算数据和政策依据不足以形成可靠结论。")

    verification_messages = {
        "complete": (
            "真实结算金额已完成核对；费用总览不涉及单项政策或计算过程核验。"
            if is_overview
            else "结算金额、计算过程和政策依据已完成核对。"
        ),
        "partial": "已核对结算金额，但政策依据或计算过程仍不完整。",
        "unavailable": "现有信息不足，未形成可靠核对结论。",
    }
    return PolicyQAPublicResult(
        answer=safe_answer,
        answer_status=answer_status,
        case_context=safe_context,
        calculation_steps=safe_steps,
        definition=safe_definition,
        warnings=[_public_text(item) for item in warnings or [] if str(item or "").strip()],
        policy_evidence=safe_evidence,
        citations=citations,
        uncertainties=uncertainties,
        verification_summary=VerificationSummary(
            settlement_checked=has_real_amount,
            calculation_checked=calculation_checked,
            policy_count=policy_count,
            message=verification_messages[answer_status],
        ),
    )


async def _policy_qa_stream(
    request: PolicyQARequest,
) -> AsyncGenerator[str, None]:
    """
    政策问答SSE流式处理

    Args:
        request: 政策问答请求

    Yields:
        SSE事件字符串
    """
    print(f'[POLICY-QA] 开始处理请求: question={request.question[:30]}..., settlement_id={request.settlement_id}', flush=True)

    # 服务端在请求开始时生成一次稳定的 qa_turn_id，贯穿 persistence、result、done 与异常 done
    qa_turn_id = f"qat_{uuid.uuid4().hex}"

    # ── 持久化：创建 session + workflow（失败不影响流式响应）──
    start_time = _time.time()
    user_id = request.user_id or "demo"
    role = request.role or "cashier"
    session_id = request.session_id or f"sess-{id(request)}"
    workflow_id = f"wf-{id(request)}"
    tenant_id = _resolve_tenant_id(request)
    try:
        session_id, workflow_id = ensure_session_and_workflow(
            session_id=session_id,
            user_id=user_id,
            role=role,
            question=request.question,
            settlement_id=request.settlement_id,
        )
        logger.info(f"[PERSIST] 持久化完成: session_id={session_id}, workflow_id={workflow_id}")
    except Exception as e:
        logger.warning(f"Session/workflow creation failed (non-blocking): {e}")

    # 设置基础设施事件上下文（供 ModelGateway/McpTransport/SQLDataFetcher 使用）
    set_infra_context(
        session_id=session_id,
        workflow_id=workflow_id,
        user_id=user_id,
        role=role,
    )

    # ── Runtime 增强：上下文规划（Memory/Planner/Reasoning，失败降级不阻塞）──
    runtime_bridge = get_runtime_bridge()
    context_need = runtime_bridge.prepare_turn(
        session_id=session_id,
        question=request.question,
        settlement_id=request.settlement_id,
        user_id=user_id,
        role=role,
    )
    if context_need:
        yield _sse_event("context_need", _sanitize(context_need))

    # 累积结果用于 task 记录
    accumulated_steps: list[dict] = []
    attempt_count = 1
    halt_reason = "non_retryable_error"
    last_retryable_failure: str | None = None
    
    try:
        # ── Skill 驱动：结算数据 provider（真实 SQL）+ 模型网关（来源标注）──
        # 旧编排器（PolicyQAOrchestrator）已退役：政策检索/计算/回答统一走 skill 策略引擎。
        provider = create_settlement_data_provider()
        # 处理请求并 yield SSE 事件（Skill 驱动：五步流程）
        public_steps: list[dict] = []          # 累积公开步骤
        result_answer = ""                     # 最终公开回答
        result_policy_evidence: list[dict] = [] # 最终结果：政策依据（RAG）
        import asyncio

        # v2 trace result tracking
        trace_run_id: str = workflow_id
        trace_can_answer: bool = False
        trace_partial_answer: bool = False

        _loop = asyncio.get_event_loop()

        async def _yield_step(
            step_name: str,
            status: str,
            public_message: str = "",
        ) -> AsyncGenerator[str, None]:
            """发送公开步骤事件；内部执行轨迹仅保留在服务端。"""
            step_evt: dict[str, Any] = {"step": step_name, "status": status}
            if public_message:
                step_evt["public_message"] = public_message
            public_steps.append(step_evt)
            accumulated_steps.append(step_evt)
            yield _sse_event("step", _sanitize(step_evt))
            await asyncio.sleep(0)

        # ═══ Step 1: intent_detection（统一解释模式识别，C 方案）═══
        # overview（费用构成总览）/ single_item（单项），消除「默认 pooling_self_pay」有毒默认
        _explanation_mode, _detected_fee_item = detect_explanation_mode(request.question or "")
        _is_overview = _explanation_mode == ExplanationMode.OVERVIEW
        target_fee_item = _detected_fee_item or "pooling_self_pay"
        async for _ev in _yield_step("intent_detection", "running", "识别问题意图…"):
            yield _ev
        _intent_label = "费用构成总览" if _is_overview else f"{fee_item_label(target_fee_item)}费用解释"
        async for _ev in _yield_step("intent_detection", "done", f"识别为「{_intent_label}」"):
            yield _ev

        # ═══ Step 2: skill_routing（SkillRouter 路由到技能）═══
        skill_id = route_question(request.question) or "settlement_explain_skill"
        assembler = get_assembler(skill_id)
        if assembler is None:
            raise RuntimeError(f"Skill '{skill_id}' 未加载")
        async for _ev in _yield_step("skill_routing", "running", "匹配技能…"):
            yield _ev
        async for _ev in _yield_step("skill_routing", "done", "已匹配费用解释技能"):
            yield _ev

        # ═══ Step 3: settlement_query（真实结算数据）═══
        async for _ev in _yield_step("settlement_query", "running", "查询真实结算数据…"):
            yield _ev
        while True:
            try:
                settlement_context = await provider.get_settlement_context(
                    request.settlement_id
                )
                break
            except SettlementDataUnavailableError:
                failure_class = "settlement_data_unavailable"
                if attempt_count >= MAX_POLICY_QA_ATTEMPTS:
                    halt_reason = (
                        "stalled"
                        if last_retryable_failure == failure_class
                        else "max_attempts"
                    )
                    raise
                last_retryable_failure = failure_class
                attempt_count += 1
                async for _ev in _yield_step(
                    "recovery", "done", "结算数据源暂时不可用，正在重试…"
                ):
                    yield _ev
        for _evt_type, _evt_payload in runtime_bridge.record_step(
            session_id=session_id,
            step="settlement_query",
            detail={
                "settlement_id": request.settlement_id,
                "total_fee": settlement_context.total_amount,
                "deductible": settlement_context.deductible,
                "basic_pooling_self_pay": settlement_context.basic_pooling_self_pay,
            },
            settlement_id=request.settlement_id,
        ):
            if _evt_type == "memory_update":
                yield _sse_event(_evt_type, _sanitize(_evt_payload))
                await asyncio.sleep(0)
        async for _ev in _yield_step("settlement_query", "done", "结算数据获取完成"):
            yield _ev

        # ═══ Step 4: policy_rule_search（skill 查询计划 + 结构化检索）═══
        async for _ev in _yield_step("policy_rule_search", "running", "检索政策规则…"):
            yield _ev
        policy_evidence: list[dict] = []
        policy_status = "no_policy_matched"
        # overview 模式是纯数据总览，不依赖单项政策规则；仅 single_item 检索单项政策
        if not _is_overview:
            _normalized_ctx: dict[str, Any] = {
                "settlement_id": settlement_context.settlement_id,
                "insu_type": _normalize_insu_type(settlement_context.insurance_type or "城镇职工"),
                "med_type": _normalize_med_type(settlement_context.service_type or "普通住院"),
                "hosp_lv": settlement_context.hospital_level or "三级医院",
                "psn_type": settlement_context.person_type or "退休人员",
                "target_field": assembler._get_fee_field(target_fee_item),
                "target_amount": assembler._get_fee_amount(settlement_context, target_fee_item),
            }
            _custom_queries = assembler.build_policy_queries(target_fee_item)
            while True:
                try:
                    _retrieval_result = await _loop.run_in_executor(
                        None,
                        lambda: retrieve_policy_evidence(
                            settlement_context=_normalized_ctx,
                            host=MILVUS_HOST,
                            port=str(MILVUS_PORT),
                            custom_queries=_custom_queries,
                        ),
                    )
                    break
                except PolicyRetrievalUnavailableError:
                    failure_class = "policy_retrieval_unavailable"
                    if attempt_count >= MAX_POLICY_QA_ATTEMPTS:
                        halt_reason = (
                            "stalled"
                            if last_retryable_failure == failure_class
                            else "max_attempts"
                        )
                        raise
                    last_retryable_failure = failure_class
                    attempt_count += 1
                    async for _ev in _yield_step(
                        "recovery", "done", "政策数据源暂时不可用，正在重试…"
                    ):
                        yield _ev
            for _ev in _retrieval_result.selected_evidence:
                policy_evidence.append({
                    "title": _ev.source_text[:80] + "..." if len(_ev.source_text) > 80 else _ev.source_text,
                    "clause": _ev.source_text,
                    "evidence_text": _ev.source_text,
                    "matched_reason": _ev.applied_reason or f"匹配规则类型: {_ev.rule_type}",
                    "rule_type": _ev.rule_type,
                    "score": _ev.score,
                    "source_text": _ev.source_text,
                    "payment_ratio": _ev.payment_ratio,
                    "amount_band": _ev.amount_band,
                    "rule_value": _ev.rule_value,
                })
            if not _retrieval_result.missing_required_rules and len(policy_evidence) >= 2:
                policy_status = "full_policy_matched"
            elif len(policy_evidence) > 0:
                policy_status = "partial_policy_matched"
            for _evt_type, _evt_payload in runtime_bridge.record_step(
                session_id=session_id,
                step="policy_rule_search",
                detail={"rules_count": len(policy_evidence), "policy_filters": []},
            ):
                if _evt_type == "memory_update":
                    yield _sse_event(_evt_type, _sanitize(_evt_payload))
                    await asyncio.sleep(0)
        async for _ev in _yield_step(
            "policy_rule_search", "done",
            f"检索到 {len(policy_evidence)} 条政策规则" if policy_evidence else "未检索到匹配的政策规则",
        ):
            yield _ev

        # ═══ Step 5: skill_execution（skill 策略引擎执行 / overview 总览生成）═══
        _exec_msg = "生成费用构成总览…" if _is_overview else "生成费用解释…"
        async for _ev in _yield_step("skill_execution", "running", _exec_msg):
            yield _ev
        # overview → 费用构成总表（纯数据，不检索单项政策）；single_item → assembler 单项解释
        overview_payload: dict | None = None
        result_answer = ""
        _single_skill_result = None
        if _is_overview:
            overview_payload = await _loop.run_in_executor(
                None,
                lambda: _build_overview_payload(settlement_context, request.question, skill_id, assembler),
            )
            result_answer = overview_payload["answer"]
        else:
            _single_skill_result = await _loop.run_in_executor(
                None,
                lambda: assembler.execute(
                    settlement_context=settlement_context,
                    policy_evidence=policy_evidence,
                    policy_status=policy_status,
                    target_fee_item=target_fee_item,
                ),
            )
            result_answer = _single_skill_result.answer or ""
        for _evt_type, _evt_payload in runtime_bridge.record_step(
            session_id=session_id, step="answer_assembly", detail={},
        ):
            if _evt_type == "memory_update":
                yield _sse_event(_evt_type, _sanitize(_evt_payload))
                await asyncio.sleep(0)
        _exec_done_msg = "费用构成总览生成完成" if _is_overview else "费用解释生成完成"
        async for _ev in _yield_step("skill_execution", "done", _exec_done_msg):
            yield _ev

        # ── 结果捕获（供 result 事件组装）──
        result_policy_evidence = policy_evidence
        trace_can_answer = bool(result_answer)
        trace_partial_answer = False

        # single_item 的结构化计算依据（overview 模式留空）——此前被丢弃，
        # 导致前端只拿到文本，无法展示「为什么这么多」的算账过程。
        _calc_steps: list[dict] = []
        _definition: dict | None = None
        _warnings: list[str] = []
        _case_context: dict | None = None
        if _single_skill_result is not None:
            policy_status = _single_skill_result.policy_status or policy_status
            trace_can_answer, trace_partial_answer = _answerability_from_completeness(
                _single_skill_result.explanation_completeness,
                _single_skill_result.warnings,
            )
            _trace = _single_skill_result.calculation_trace or {}
            _calc_steps = _trace.get("steps", []) if isinstance(_trace, dict) else []
            _definition = _single_skill_result.definition or None
            _warnings = _single_skill_result.warnings or []
            _case_context = {
                "person_type": getattr(settlement_context, "person_type", None),
                "insurance_type": getattr(settlement_context, "insurance_type", None),
                "service_type": getattr(settlement_context, "service_type", None),
                "hospital_level": getattr(settlement_context, "hospital_level", None),
                "deductible": getattr(settlement_context, "deductible", None),
                "basic_pooling_payment": getattr(settlement_context, "basic_pooling_payment", None),
                "basic_pooling_self_pay": getattr(settlement_context, "basic_pooling_self_pay", None),
                "large_amount_payment": getattr(settlement_context, "large_amount_payment", None),
                "large_amount_self_pay": getattr(settlement_context, "large_amount_self_pay", None),
                "personal_total_pay": getattr(settlement_context, "personal_total_pay", None),
            }
        elif overview_payload is not None:
            trace_can_answer = True
            trace_partial_answer = False
            _trace = overview_payload.get("calculation_trace") or {}
            _calc_steps = _trace.get("steps", []) if isinstance(_trace, dict) else []
            _definition = overview_payload.get("definition") or None
            _warnings = overview_payload.get("warnings") or []
            _case_context = overview_payload.get("case_context") or None

        # ── 所有步骤完成：发送合并结果 ──
        logger.info(f'[POLICY-QA] 处理完成，发送 result 事件（共 {len(public_steps)} 个步骤）')

        public_result = _build_public_result(
            answer=result_answer,
            can_answer=trace_can_answer,
            partial_answer=trace_partial_answer,
            policy_status=policy_status,
            policy_evidence=result_policy_evidence,
            calculation_steps=_calc_steps,
            definition=_definition,
            warnings=_warnings,
            case_context=_case_context,
            is_overview=_is_overview,
        )
        halt_reason = "verified"
        async for _ev in _yield_step(
            "verification",
            "done",
            public_result.verification_summary.message,
        ):
            yield _ev
        # Runtime 仍在服务端维护推理链与对话记忆，但不把内部推理快照并入公开结果。
        runtime_bridge.finalize_turn(
            session_id=session_id, question=request.question,
        )
        yield _sse_event("result", {"qa_turn_id": qa_turn_id, "result": public_result.model_dump(mode="json")})

        # ── 持久化：记录 task 并完成 workflow ──
        duration_ms = int((_time.time() - start_time) * 1000)
        try:
            record_qa_task(
                qa_turn_id=qa_turn_id,
                workflow_id=workflow_id,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
                question=request.question,
                settlement_id=request.settlement_id,
                status="completed",
                output={
                    "answer_excerpt": public_result.answer[:500],
                    "answer_status": public_result.answer_status,
                    "evidence_count": len(public_result.policy_evidence),
                    "internal_run_id": trace_run_id,
                    "selected_skill_id": skill_id,
                    "question_excerpt": (request.question or "")[:500],
                    "attempt_count": attempt_count,
                    "halt_reason": halt_reason,
                },
                duration_ms=duration_ms,
            )
            finalize_workflow(workflow_id, "completed", accumulated_steps or public_steps)
        except Exception as e:
            logger.warning(f"Failed to persist QA result: {e}")

        yield _sse_event(
            "done",
            {
                "qa_turn_id": qa_turn_id,
                "answer_status": public_result.answer_status,
                "success": True,
                "attempt_count": attempt_count,
                "halt_reason": halt_reason,
            },
        )

    except Exception as e:
        if halt_reason not in {"max_attempts", "stalled"}:
            halt_reason = "non_retryable_error"
        print(f'[POLICY-QA] 处理异常: {e}', flush=True)
        logger.exception("Policy QA stream failed")

        # ── 持久化：记录失败 ──
        try:
            duration_ms = int((_time.time() - start_time) * 1000)
            record_qa_task(
                qa_turn_id=qa_turn_id,
                workflow_id=workflow_id,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
                question=request.question,
                settlement_id=request.settlement_id,
                status="failed",
                output={
                    "attempt_count": attempt_count,
                    "halt_reason": halt_reason,
                },
                error_message=str(e),
                duration_ms=duration_ms,
            )
            finalize_workflow(workflow_id, "failed", accumulated_steps)
        except Exception as pe:
            logger.warning(f"Failed to persist error state: {pe}")

        error_code = "POLICY_QA_FAILED"
        yield _sse_event(
            "error",
            {
                "qa_turn_id": qa_turn_id,
                "error_code": error_code,
                "attempt_count": attempt_count,
                "halt_reason": halt_reason,
                "message": "政策问答处理失败，请稍后重试或联系医保办。",
            },
        )
        yield _sse_event(
            "done",
            {
                "qa_turn_id": qa_turn_id,
                "answer_status": "unavailable",
                "success": False,
                "error_code": error_code,
                "attempt_count": attempt_count,
                "halt_reason": halt_reason,
            },
        )


@router.post("/stream")
async def policy_qa_stream(request: PolicyQARequest) -> StreamingResponse:
    """
    政策问答SSE流式端点

    Args:
        request: 政策问答请求

    Returns:
        StreamingResponse: SSE流式响应
    """
    # 验证请求
    if not request.question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    if not request.settlement_id:
        raise HTTPException(status_code=400, detail="结算ID不能为空")

    # 返回SSE流式响应
    return StreamingResponse(
        _policy_qa_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/test")
async def policy_qa_test(request: PolicyQARequest) -> dict:
    """
    政策问答测试端点 (非流式)

    Args:
        request: 政策问答请求

    Returns:
        dict: 测试结果
    """
    # 验证请求
    if not request.question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    if not request.settlement_id:
        raise HTTPException(status_code=400, detail="结算ID不能为空")

    # 返回测试结果
    return {
        "status": "ok",
        "message": "政策问答测试端点",
        "request": {
            "question": request.question,
            "settlement_id": request.settlement_id,
            "session_id": request.session_id,
        },
    }


# ── 调试端点：结构化政策规则检索 ──────────────────────────────────

@router.get("/debug/structured-policy-search")
async def debug_structured_policy_search(
    settlement_id: str,
    target_field: str = "统筹自付",
) -> dict:
    """
    调试端点：展示结构化政策规则检索的完整过程。

    返回：
    - settlement_context: 真实结算数据上下文
    - normalized_policy_context: 标准化后的政策查询上下文
    - planned_queries: 规划的各组查询
    - structured_hits: 各组查询的命中结果
    - vector_fallback_hits: 向量兜底结果（当前未使用）
    - selected_policy_evidence: 最终选中的政策证据
    - missing_required_rules: 缺失的必需规则
    - dedupe_info: 去重信息
    """
    if not settlement_id:
        raise HTTPException(status_code=400, detail="settlement_id is required")

    try:
        provider = create_settlement_data_provider()
        context = await provider.get_settlement_context(settlement_id)

        # 构建标准化上下文
        normalized_ctx = {
            "settlement_id": context.settlement_id,
            "insu_type": _normalize_insu_type(context.insurance_type or "城镇职工"),
            "med_type": _normalize_med_type(context.service_type or "普通住院"),
            "hosp_lv": context.hospital_level or "三级医院",
            "psn_type": context.person_type or "退休人员",
            "target_field": target_field,
            "target_amount": context.basic_pooling_self_pay,
        }

        # 执行结构化检索
        retrieval_result = retrieve_policy_evidence(
            settlement_context=normalized_ctx,
            host=MILVUS_HOST,
            port=str(MILVUS_PORT),
        )

        # 序列化 selected_evidence
        selected_evidence = []
        for ev in retrieval_result.selected_evidence:
            selected_evidence.append({
                "evidence_id": ev.evidence_id,
                "source": ev.source,
                "query_name": ev.query_name,
                "policy_id": ev.policy_id,
                "clause_id": ev.clause_id,
                "rule_type": ev.rule_type,
                "insu_type": ev.insu_type,
                "med_type": ev.med_type,
                "hosp_lv": ev.hosp_lv,
                "psn_type": ev.psn_type,
                "source_text": ev.source_text,
                "rule_value": ev.rule_value,
                "payment_ratio": ev.payment_ratio,
                "amount_band": ev.amount_band,
                "rule_id": ev.rule_id,
                "rule_instance_key": ev.rule_instance_key,
                "applied_reason": ev.applied_reason,
                "score": ev.score,
            })

        return {
            "settlement_context": {
                "settlement_id": context.settlement_id,
                "insurance_type": context.insurance_type,
                "service_type": context.service_type,
                "hospital_level": context.hospital_level,
                "person_type": context.person_type,
                "basic_pooling_self_pay": context.basic_pooling_self_pay,
                "deductible": context.deductible,
                "yearly_cycle_count": context.yearly_cycle_count,
                "tables_queried": context.tables_queried,
                "query_profile": context.query_profile,
            },
            "normalized_policy_context": normalized_ctx,
            "planned_queries": retrieval_result.planned_queries,
            "structured_hits": retrieval_result.query_results,
            "vector_fallback_hits": [],
            "selected_policy_evidence": selected_evidence,
            "missing_required_rules": retrieval_result.missing_required_rules,
            "dedupe_info": retrieval_result.dedupe_info,
        }

    except SettlementNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Debug structured policy search failed")
        raise HTTPException(status_code=503, detail=f'检索失败: {str(e)}')


# ── 解释生成辅助函数（从结算上下文构建双视角文本和计算链路）──

# ★ Milvus 字段标准化映射
# SQL CASE WHEN 返回的简称 vs Milvus 存储的全称
_INSURANCE_TYPE_EXPAND: dict[str, str] = {
    "城镇职工": "城镇职工基本医疗保险",
    "城乡居民": "城乡居民基本医疗保险",
    "工伤保险": "工伤保险",
    "离休统筹": "离休统筹",
    "公疗医照": "公疗医照",
}
_MEDICAL_TYPE_PREFIX: dict[str, str] = {
    "普通门诊": "门诊-普通门诊",
    "急诊": "门诊-急诊",
    "普通住院": "住院-普通住院",
    "单病种住院": "住院-单病种住院",
    "日间手术": "住院-日间手术",
    "生育住院": "住院-生育住院",
    "生育门诊": "门诊-生育门诊",
    "家庭病床": "住院-家庭病床",
    "药店购药": "药店购药",
}


def _normalize_insu_type(raw: str) -> str:
    """将 SQL 返回的险种简称映射到 Milvus 存储的全称。"""
    for short, full in _INSURANCE_TYPE_EXPAND.items():
        if short in raw:
            return full
    return raw


def _normalize_med_type(raw: str) -> str:
    """将 SQL 返回的医疗类别映射到 Milvus 存储格式 '住院-普通住院'。"""
    if raw in _MEDICAL_TYPE_PREFIX:
        return _MEDICAL_TYPE_PREFIX[raw]
    if raw.startswith("住院-") or raw.startswith("门诊-"):
        return raw
    return f'住院-{raw}'


# ── 解释生成 ──────────────────────────────────────────────────

def _fmt_money(value) -> str:
    """安全格式化金额：null/0/空 → '未获取'，否则千分位两位小数。"""
    if value is None or value == '' or (isinstance(value, (int, float)) and value == 0):
        return '未获取'
    try:
        return f'{float(value):,.2f}'
    except (ValueError, TypeError):
        return '未获取'


def _fmt_label(value, label: str) -> str:
    """格式化带标签的值，如 format_label(650, '元') → '650.00 元'，空值 → '未获取'。"""
    v = _fmt_money(value)
    if v == '未获取':
        return f'{label}：未获取'
    return f'{label} {v} 元'


def _clean_policy_excerpt(text: str) -> str:
    """清洗政策原文：移除 JSON 块（如 {"ratio": 0.85}）和多余空白，只保留可读文本。"""
    import re
    # 移除 JSON 块，如 {"ratio": 0.85} 或 {"expression": "...", "multiplier": 0.6}
    cleaned = re.sub(r'\n?\{[^}]*\}[\s\S]*$', '', text).strip()
    # 移除连续空行
    cleaned = re.sub(r'\n{2,}', '\n', cleaned)
    # 移除行首多余空白
    cleaned = '\n'.join(line.strip() for line in cleaned.split('\n') if line.strip())
    return cleaned

# ── 以下函数已迁移到 src/skills/benefit_pooling_self_pay/assembler.py ──
# _build_patient_answer, _build_office_answer, _extract_segment_ratios,
# _build_ratio_explanation, _build_explanation_completeness,
# _build_calculation_trace, _build_warnings
# 产品层不再包含统筹自付专属解释逻辑。


def _assemble_display_payload(context: Any, skill_id: str, assembler: Any) -> dict:
    """从 SettlementContext + skill manifest 组装前端展示数据。

    抽取自 _process_single_settlement，供 single-item 与 overview 两种模式复用，
    消除双端点的展示组装重复（C 方案：统一双端点）。

    Returns:
        {"profile": dict, "output_groups": list, "display_config": dict}
    """
    manifest = get_skill_manifest(skill_id) or {}
    display_config = manifest.get("display", {})

    profile: dict[str, Any] = {}
    if "profile" in display_config:
        profile["title"] = display_config["profile"].get("title", "")
        profile["items"] = []
        for item in display_config["profile"].get("items", []):
            field = item.get("field", "")
            # field 为 SQL 列名（如 zyjyxx.rylb），需映射到 SettlementContext 属性名
            attr = assembler._FACT_FIELD_MAP.get(field, field)
            value = getattr(context, attr, "") or ""
            profile["items"].append({
                "label": item.get("label", field),
                "field": field,
                "value": value,
            })

    output_groups: list[dict[str, Any]] = []
    for group_def in display_config.get("output", []):
        group_entry: dict[str, Any] = {"group": group_def.get("group", ""), "items": []}
        for item_def in group_def.get("items", []):
            field = item_def.get("field", "")
            # field 为 SQL 列名（如 zyfdxx.bdtczf），需映射到 SettlementContext 属性名
            attr = assembler._FACT_FIELD_MAP.get(field, field)
            value = getattr(context, attr, 0) or 0
            entry: dict[str, Any] = {
                "label": item_def.get("label", field),
                "field": field,
                "value": value,
            }
            if "format" in item_def:
                entry["format"] = item_def["format"]
            if "hint" in item_def:
                entry["hint"] = item_def["hint"]
            if "highlight" in item_def:
                entry["highlight"] = item_def["highlight"]
            group_entry["items"].append(entry)
        output_groups.append(group_entry)

    return {"profile": profile, "output_groups": output_groups, "display_config": display_config}


def _build_overview_payload(context: Any, question: str, skill_id: str, assembler: Any) -> dict:
    """overview 模式：从真实结算数据组装「费用构成总览」。

    不依赖政策检索（总览是纯数据展示，避免无依据的逐段复算）；
    直接复用 skill manifest 的 display 配置生成 profile/output_groups，
    与 SettlementExplanationData 契约兼容，前端可用同一组件渲染。

    Returns:
        兼容 _process_single_settlement 返回结构的 dict，关键字段：
        - answer: 总览文本（自然语言汇总 + 结构化字段）
        - case_context / profile / output_groups: 结构化构成数据
        - target_fee_item="overview" / target_field="total_amount"
    """
    display = _assemble_display_payload(context, skill_id, assembler)

    total = _fmt_money(context.total_amount)
    pooling_payment = _fmt_money(context.basic_pooling_payment)
    large_payment = _fmt_money(context.large_amount_payment)
    deductible = _fmt_money(context.deductible)
    pooling_self_pay = _fmt_money(context.basic_pooling_self_pay)
    large_self_pay = _fmt_money(context.large_amount_self_pay)
    personal_total = _fmt_money(context.personal_total_pay)

    answer = (
        f"本次住院总费用 {total} 元。\n\n"
        f"【医保支付】统筹基金支付 {pooling_payment} 元，大额基金支付 {large_payment} 元。\n"
        f"【个人承担】起付线 {deductible} 元、统筹自付 {pooling_self_pay} 元、"
        f"大额自付 {large_self_pay} 元，个人总支付合计 {personal_total} 元。\n\n"
        f"如需了解某一项的详细计算，可以直接追问"
        f"（例如「统筹自付为什么是 {pooling_self_pay} 元」）。\n\n"
        f"本回答基于真实结算数据，仅供参考，不作为报销或结算依据。"
    )

    return {
        "question": question or "查询住院费用构成",
        "answer_type": "benefit_calculation_explanation",
        "target_fee_item": "overview",
        "target_field": "total_amount",
        "target_amount": context.total_amount,
        "data_source": "REAL_DB",
        "mock_used": False,
        "query_trace": {
            "settlement_id": context.settlement_id,
            "tables": context.tables_queried,
            "sql_profile": context.query_profile,
        },
        "definition": {
            "name": "住院费用构成",
            "plain_text": "本次住院结算的费用构成总览，包含医保支付与个人承担各部分金额。",
            "excludes": [],
        },
        "case_context": {
            "person_type": context.person_type,
            "insurance_type": context.insurance_type,
            "service_type": context.service_type,
            "hospital_level": context.hospital_level,
            "deductible": context.deductible,
            "yearly_cycle_count": getattr(context, "yearly_cycle_count", 0),
            "basic_pooling_payment": context.basic_pooling_payment,
            "basic_pooling_self_pay": context.basic_pooling_self_pay,
            "large_amount_payment": context.large_amount_payment,
            "large_amount_self_pay": context.large_amount_self_pay,
            "personal_total_pay": context.personal_total_pay,
        },
        "policy_evidence": [],
        "policy_status": "no_policy_matched",
        "policy_warning": "费用构成总览不依赖单项政策规则；如需单项计算过程，请针对该单项提问。",
        "calculation_trace": {"method": "汇总真实结算字段", "steps": []},
        "answer": answer,
        "ratio_explanation": {},
        "explanation_completeness": {
            "level": "real_data_only",
            "message": "总览基于真实结算字段汇总。",
            "has_real_data": True,
        },
        "can_answer": True,
        "partial_answer": False,
        "is_overview": True,
        "warnings": [
            "本结果来自真实数据库查询。",
            "如需某一项的详细政策计算过程，请针对该单项提问。",
        ],
        "mode": "single",
        "profile": display["profile"],
        "output_groups": display["output_groups"],
        "display_config": display["display_config"],
    }


async def _process_single_settlement(settlement_id: str, question: str = "") -> dict:
    """提取单个结算单的完整处理流程，返回结果字典。

    同时用于单结算单模式和对比模式，保持两种模式的输出一致性。

    Returns:
        与 get_settlement_explanation 单结算单模式完全相同的返回结构

    Raises:
        HTTPException: settlement_id 不存在、skill 未匹配等
        SettlementNotFoundError: 结算数据在数据库中不存在
    """
    provider = create_settlement_data_provider()
    context = await provider.get_settlement_context(settlement_id)

    # ★ Skill 驱动架构：通过 SkillRouter 路由到对应 skill
    skill_id = route_question(question or "统筹自付")
    if skill_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"问题 '{question}' 未匹配到解释技能",
        )

    # 加载 skill assembler（通过动态加载器）
    assembler = get_assembler(skill_id)
    if assembler is None:
        raise HTTPException(status_code=500, detail=f"Skill '{skill_id}' not loaded")

    # ★ 统一解释模式识别（C 方案）：overview（费用构成总览）/ single_item（单项）
    #    消除原先「未命中关键词 → 默认 pooling_self_pay」的有毒默认。
    mode, detected_fee_item = detect_explanation_mode(question or "")
    if mode == ExplanationMode.OVERVIEW:
        # 总览模式：直接返回费用构成总表，不检索单项政策、不走 assembler 单项解释
        return _build_overview_payload(context, question, skill_id, assembler)
    target_fee_item = detected_fee_item or "pooling_self_pay"

    # ★ 结构化政策规则检索（使用 skill 定义的查询计划）
    policy_evidence: list[dict] = []
    policy_status = "no_policy_matched"
    try:
        # 构建标准化上下文 → 映射 SettlementContext 字段到 Milvus 字段名
        normalized_ctx: dict[str, Any] = {
            "settlement_id": context.settlement_id,
            "insu_type": _normalize_insu_type(context.insurance_type or "城镇职工"),
            "med_type": _normalize_med_type(context.service_type or "普通住院"),
            "hosp_lv": context.hospital_level or "三级医院",
            "psn_type": context.person_type or "退休人员",
            "target_field": assembler._get_fee_field(target_fee_item),
            "target_amount": assembler._get_fee_amount(context, target_fee_item),
        }
        logger.info(f'[settlement-explanation] Structured retrieval with: {normalized_ctx}')

        # 使用 skill 配置的查询计划（根据 target_fee_item 选择对应 Strategy）
        custom_queries = assembler.build_policy_queries(target_fee_item)

        retrieval_result = retrieve_policy_evidence(
            settlement_context=normalized_ctx,
            host=MILVUS_HOST,
            port=str(MILVUS_PORT),
            custom_queries=custom_queries,
        )

        # 组装 policy_evidence
        for ev in retrieval_result.selected_evidence:
            policy_evidence.append({
                "policy_title": ev.source_text[:80] + "..." if len(ev.source_text) > 80 else ev.source_text,
                "clause_text": ev.source_text,
                "source_text": ev.source_text,
                "rule_tags": [
                    ev.rule_type,
                    ev.insu_type,
                    ev.med_type,
                    ev.hosp_lv,
                    ev.psn_type,
                ],
                "matched_query": ev.query_name,
                "score": ev.score,
                "applied_reason": ev.applied_reason,
                "rule_id": ev.rule_id,
                "rule_type": ev.rule_type,
                "payment_ratio": ev.payment_ratio,
                "amount_band": ev.amount_band,
                "rule_value": ev.rule_value,
                "psn_type": ev.psn_type,
                "insu_type": ev.insu_type,
                "med_type": ev.med_type,
                "hosp_lv": ev.hosp_lv,
            })

        # 判断匹配状态（基于检索结果，不依赖硬编码解析逻辑）
        if not retrieval_result.missing_required_rules and len(policy_evidence) >= 2:
            policy_status = "full_policy_matched"
        elif len(policy_evidence) > 0:
            policy_status = "partial_policy_matched"

        logger.info(
            f'[settlement-explanation] Policy retrieval: {len(policy_evidence)} evidence, '
            f'status={policy_status}, missing={retrieval_result.missing_required_rules}, '
            f'dedup={retrieval_result.dedupe_info}'
        )

    except Exception as e:
        logger.exception(f'[settlement-explanation] Structured retrieval failed: {e}')
        policy_status = "no_policy_matched"

    # ★ Skill 驱动：通过 assembler 生成所有解释输出（统一处理所有费用类型）
    # A-重：语义层数据路径（开关 USE_SEMANTIC_LAYER_PATH=1 启用）
    # 把 SettlementContext 经 BusinessFactsBuilder（已发布版本锁定）转为 facts，
    # 再走 execute_via_registry；默认关闭，沿用 SQL 直连路径。
    import os
    if os.environ.get("USE_SEMANTIC_LAYER_PATH") == "1":
        from src.semantic_layer.settlement_bridge import build_settlement_facts
        facts = build_settlement_facts(context)
        skill_result = assembler.execute_via_registry(
            facts, question, target_fee_item=target_fee_item,
            policy_evidence=policy_evidence, policy_status=policy_status,
        )
    else:
        skill_result = assembler.execute(
            settlement_context=context,
            policy_evidence=policy_evidence,
            policy_status=policy_status,
            target_fee_item=target_fee_item,
        )

    # ★ 复用共享展示组装（C 方案：消除双端点重复）
    _display = _assemble_display_payload(context, skill_id, assembler)
    profile = _display["profile"]
    output_groups = _display["output_groups"]
    display_config = _display["display_config"]

    can_answer, partial_answer = _answerability_from_completeness(
        skill_result.explanation_completeness,
        skill_result.warnings,
    )
    return {
        "question": question or f'{assembler._get_fee_label(target_fee_item)}为什么是{_fmt_money(assembler._get_fee_amount(context, target_fee_item))}？',
        "answer_type": "benefit_calculation_explanation",
        "target_fee_item": target_fee_item,
        "target_field": assembler._get_fee_field(target_fee_item),
        "target_amount": assembler._get_fee_amount(context, target_fee_item),
        "data_source": "REAL_DB",
        "mock_used": False,
        "query_trace": {
            "settlement_id": context.settlement_id,
            "tables": context.tables_queried,
            "sql_profile": context.query_profile,
        },
        "definition": skill_result.definition,
        "case_context": {
            "person_type": context.person_type,
            "insurance_type": context.insurance_type,
            "service_type": context.service_type,
            "hospital_level": context.hospital_level,
            "deductible": context.deductible,
            "yearly_cycle_count": context.yearly_cycle_count,
            "basic_pooling_payment": context.basic_pooling_payment,
            "basic_pooling_self_pay": context.basic_pooling_self_pay,
            "large_amount_payment": context.large_amount_payment,
            "large_amount_self_pay": context.large_amount_self_pay,
            "personal_total_pay": context.personal_total_pay,
        },
        "policy_evidence": policy_evidence,
        "policy_status": skill_result.policy_status,
        "policy_warning": skill_result.policy_status_message,
        "calculation_trace": skill_result.calculation_trace,
        "answer": skill_result.answer,
        "ratio_explanation": skill_result.ratio_explanation,
        "explanation_completeness": skill_result.explanation_completeness,
        "can_answer": can_answer,
        "partial_answer": partial_answer,
        "is_overview": False,
        "warnings": skill_result.warnings,
        "mode": "single",
        "profile": profile,
        "output_groups": output_groups,
        "display_config": display_config,
    }


def _public_result_from_internal_payload(payload: dict) -> PolicyQAPublicResult:
    """把 settlement explanation 内部载荷收敛为公开契约。"""
    trace = payload.get("calculation_trace") or {}
    steps = trace.get("steps", []) if isinstance(trace, dict) else []
    answer = str(payload.get("answer") or "")
    if "can_answer" in payload or "partial_answer" in payload:
        can_answer = payload.get("can_answer") is True
        partial_answer = payload.get("partial_answer") is True
    else:
        can_answer, partial_answer = _answerability_from_completeness(
            payload.get("explanation_completeness"),
            payload.get("warnings"),
        )
    return _build_public_result(
        answer=answer,
        can_answer=can_answer,
        partial_answer=partial_answer,
        policy_status=str(payload.get("policy_status") or "no_policy_matched"),
        policy_evidence=payload.get("policy_evidence") or [],
        calculation_steps=steps,
        definition=payload.get("definition"),
        warnings=payload.get("warnings") or [],
        case_context=payload.get("case_context"),
        is_overview=payload.get("is_overview") is True,
    )


@router.get("/settlement-explanation", response_model=PolicyQAPublicResult)
async def get_settlement_explanation(
    settlement_id: str,
    question: str = "",
    compare_with: str = "",
) -> PolicyQAPublicResult:
    """
    GET settlement explanation from REAL DATABASE.

    Query real SQL Server for settlement context using the existing
    settlement_context SQL.  Never uses mock data — errors propagate clearly.

    When `compare_with` is provided, returns one consolidated public answer.

    Args:
        settlement_id: 登记号 from the settlement system (required)
        question: optional user question for additional context
        compare_with: 对比结算单号 — when provided, returns comparison mode

    Returns:
        PolicyQAPublicResult: 单一回答、公开证据和核验摘要。

    Raises:
        HTTPException 400: missing settlement_id or compare_with equals settlement_id
        HTTPException 404: settlement_id / compare_with not found in DB
        HTTPException 503: DB connection/query failure
    """
    if not settlement_id:
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                "POLICY_QA_INVALID_REQUEST",
                "settlement_id 不能为空。",
                {"operation": "settlement_explanation"},
            ),
        )

    if compare_with and compare_with == settlement_id:
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                "POLICY_QA_INVALID_COMPARISON",
                "对比结算单号不能与主结算单号相同。",
                {"operation": "settlement_explanation"},
            ),
        )

    try:
        # ── Single settlement mode (original behavior) ──
        if not compare_with:
            internal_payload = await _process_single_settlement(settlement_id, question)
            return _public_result_from_internal_payload(internal_payload)

        # ── Comparison mode ──
        primary = await _process_single_settlement(settlement_id, question)
        secondary = await _process_single_settlement(compare_with, question)
        primary_answer = str(primary.get("answer") or "")
        secondary_answer = str(secondary.get("answer") or "")
        policy_statuses = {primary.get("policy_status"), secondary.get("policy_status")}
        if policy_statuses == {"full_policy_matched"}:
            combined_policy_status = "full_policy_matched"
        elif policy_statuses.intersection({"full_policy_matched", "partial_policy_matched"}):
            combined_policy_status = "partial_policy_matched"
        else:
            combined_policy_status = "no_policy_matched"
        combined = {
            "answer": f"主结算：{primary_answer}\n\n对比结算：{secondary_answer}",
            "policy_status": combined_policy_status,
            "policy_evidence": (primary.get("policy_evidence") or [])
            + (secondary.get("policy_evidence") or []),
            "calculation_trace": primary.get("calculation_trace") or {},
            "definition": primary.get("definition"),
            "case_context": primary.get("case_context"),
            "warnings": (primary.get("warnings") or [])
            + (secondary.get("warnings") or [])
            + ["对比结果已合并为单一公开回答。"],
            "can_answer": primary.get("can_answer") is True
            and secondary.get("can_answer") is True,
            "partial_answer": primary.get("partial_answer") is True
            or secondary.get("partial_answer") is True,
            "is_overview": primary.get("is_overview") is True
            and secondary.get("is_overview") is True,
        }
        return _public_result_from_internal_payload(combined)

    except SettlementNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "POLICY_QA_SETTLEMENT_NOT_FOUND",
                "未找到对应的结算记录。",
                {"operation": "settlement_explanation"},
            ),
        )
    except RuntimeError:
        # Raised when DATA_SOURCE_MODE != "real_db"
        logger.exception("Settlement explanation runtime failure")
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "POLICY_QA_UNAVAILABLE",
                "政策问答服务暂时不可用，请稍后重试。",
                {"operation": "settlement_explanation"},
            ),
        )
    except Exception:
        logger.exception("Settlement explanation query failed")
        raise HTTPException(
            status_code=503,
            detail=error_detail(
                "POLICY_QA_UNAVAILABLE",
                "政策问答服务暂时不可用，请稍后重试。",
                {"operation": "settlement_explanation"},
            ),
        )


# ── 问答历史端点 ──────────────────────────────────────────────

@router.get("/history")
async def get_qa_history(
    user_id: str | None = Query(None, description="按用户ID过滤（不传则返回全部）"),
    limit: int = Query(50, ge=1, le=500, description="每页条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
) -> dict:
    """
    获取政策问答历史记录（含全量 session、workflow、task 数据）。

    默认返回全部用户的记录。
    """
    from src.runtime.policy_qa.history_service import get_qa_history as _get_history
    try:
        return _get_history(user_id=user_id, limit=limit, offset=offset)
    except Exception as e:
        logger.exception("Failed to get QA history")
        raise HTTPException(status_code=500, detail=f"获取历史记录失败: {str(e)}")


@router.post("/feedback")
def submit_policy_qa_feedback(
    request: PolicyQAFeedbackRequest,
    principal: PolicyQAFeedbackPrincipalDependency,
    service: PolicyQARegressionMiningDependency,
) -> PolicyQAFeedbackResponse:
    """提交「回答有误」反馈。

    客户端只能提交 qa_turn_id + reason_code + comment；正文与路由由服务端按 ID 读取。
    """
    try:
        item = service.collect_feedback(
            principal=principal,
            qa_turn_id=request.qa_turn_id,
            reason_code=request.reason_code,
            comment=request.comment,
            idempotency_key=request.qa_turn_id,
        )
    except QATurnNotAccessibleError:
        # 统一返回 404，不泄露存在性
        raise HTTPException(
            status_code=404,
            detail=error_detail(
                "POLICY_QA_TURN_NOT_FOUND", "问答轮次不存在或无权访问"
            ),
        )
    except SensitiveFeedbackRejectedError:
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                "POLICY_QA_FEEDBACK_SENSITIVE", "反馈包含敏感信息，已拒绝"
            ),
        )
    return PolicyQAFeedbackResponse(
        pool_id=item.pool_id,
        status=item.status.value,
        error_dimension=item.error_dimension.value,
        source_selected_skill_id=item.source_selected_skill_id,
    )

