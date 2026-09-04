"""Policy QA 答案验证 trace 捕获与存储（MVU-3）。

SSE 生成路径在回答完成后把内部证据血缘组装为 ``KnowledgeAnswerVerificationInput``
信封并按 ``qa_turn_id`` 存储；``POST /policy-qa/answers/{qa_turn_id}/verification``
薄路由据此调用 Knowledge 上下文的 ``KnowledgeAnswerVerifier`` 做事后验证。

设计约束（见 docs/steering/政策知识治理-需求迭代记录.md Issue 20）：
- Runtime 仅做 trace 捕获/存储与 thin API，**不改 SSE 公开契约**；
- trace 存储为易失运行时状态（内存实现）；PG 持久化留作后续增量；
- 无 trace 但 task 闭环存在时降级为公开-only 验证（degraded），
  完全不存在的 qa_turn_id 返回 None 由路由层映射 404，绝不泄露内部细节。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from src.knowledge_extension.rule_explanation.answer_verification.models import (
    AnswerCitation,
    AnswerEvidenceRef,
    KnowledgeAnswerVerificationInput,
    KnowledgeAnswerVerificationResult,
    QueryPlanItem,
    RuleKnowledgePort,
)
from src.knowledge_extension.rule_explanation.answer_verification.verifier import (
    KnowledgeAnswerVerifier,
    source_text_hash,
)
from src.runtime.task_closure.service import get_task

logger = logging.getLogger(__name__)


class AnswerVerificationTraceStore(Protocol):
    """答案验证 trace 存储端口：按 qa_turn_id 存取内部验证信封。"""

    def save(self, envelope: KnowledgeAnswerVerificationInput) -> None: ...
    def get(self, qa_turn_id: str) -> KnowledgeAnswerVerificationInput | None: ...


class InMemoryAnswerVerificationTraceStore:
    """内存 trace 存储（线程安全）。进程重启即失效，属易失运行时状态。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._envelopes: dict[str, KnowledgeAnswerVerificationInput] = {}

    def save(self, envelope: KnowledgeAnswerVerificationInput) -> None:
        with self._lock:
            self._envelopes[envelope.qa_turn_id] = envelope

    def get(self, qa_turn_id: str) -> KnowledgeAnswerVerificationInput | None:
        with self._lock:
            return self._envelopes.get(qa_turn_id)


_store_singleton: InMemoryAnswerVerificationTraceStore | None = None
_store_lock = threading.Lock()


def get_answer_verification_trace_store() -> AnswerVerificationTraceStore:
    """trace 存储单例工厂（测试经路由层依赖覆盖注入隔离实例）。"""
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = InMemoryAnswerVerificationTraceStore()
    return _store_singleton


def reset_answer_verification_trace_store() -> None:
    """清空单例（仅测试使用）。"""
    global _store_singleton
    with _store_lock:
        _store_singleton = None


def _evidence_to_ref(evidence: Any) -> AnswerEvidenceRef:
    """把检索证据（StructuredPolicyEvidence，鸭子类型）映射为内部证据引用。"""
    source_text = str(getattr(evidence, "source_text", "") or "")
    return AnswerEvidenceRef(
        evidence_id=str(getattr(evidence, "evidence_id", "") or ""),
        rule_id=str(getattr(evidence, "rule_id", "") or ""),
        rule_instance_key=str(getattr(evidence, "rule_instance_key", "") or ""),
        policy_id=str(getattr(evidence, "policy_id", "") or ""),
        clause_id=str(getattr(evidence, "clause_id", "") or ""),
        query_name=str(getattr(evidence, "query_name", "") or ""),
        source_text=source_text,
        source_text_hash=source_text_hash(source_text) if source_text else "",
        rule_value=str(getattr(evidence, "rule_value", "") or ""),
        payment_ratio=str(getattr(evidence, "payment_ratio", "") or ""),
        amount_band=str(getattr(evidence, "amount_band", "") or ""),
        psn_type=str(getattr(evidence, "psn_type", "") or ""),
    )


def build_verification_envelope(
    *,
    qa_turn_id: str,
    question: str,
    public_result: Any,
    retrieval_result: Any | None,
    calculation_trace: dict[str, Any] | None,
    scenario: str,
    context: dict[str, Any] | None,
) -> KnowledgeAnswerVerificationInput:
    """从 SSE 流局部状态组装内部验证信封（服务端专用，不回显）。

    Args:
        qa_turn_id: 服务端生成的稳定问答轮次 ID
        question: 用户问题
        public_result: PolicyQAPublicResult（公开回答快照，取 answer/status/citations）
        retrieval_result: StructuredRetrievalResult 或 None（overview 模式无政策检索）
        calculation_trace: 内部计算轨迹（SkillResult.calculation_trace）
        scenario: 支持场景标记（如 pooling_self_pay）；空 = 未声明
        context: 归一化结算上下文快照
    """
    internal_evidence: list[AnswerEvidenceRef] = []
    planned_queries: list[QueryPlanItem] = []
    missing_required_rules: list[str] = []
    if retrieval_result is not None:
        internal_evidence = [
            _evidence_to_ref(evidence)
            for evidence in (getattr(retrieval_result, "selected_evidence", None) or [])
        ]
        query_results = getattr(retrieval_result, "query_results", None) or {}
        for planned in (getattr(retrieval_result, "planned_queries", None) or []):
            query_name = str(planned.get("query_name") or "")
            if not query_name:
                continue
            planned_queries.append(QueryPlanItem(
                query_name=query_name,
                required=bool(planned.get("required", True)),
                hit_count=len(query_results.get(query_name) or []),
            ))
        missing_required_rules = [
            str(item) for item in (getattr(retrieval_result, "missing_required_rules", None) or [])
        ]

    answer_status = str(getattr(public_result, "answer_status", "") or "unavailable")
    if answer_status not in ("complete", "partial", "unavailable"):
        answer_status = "unavailable"

    return KnowledgeAnswerVerificationInput(
        qa_turn_id=qa_turn_id,
        question=question or "",
        answer=str(getattr(public_result, "answer", "") or ""),
        answer_status=answer_status,  # type: ignore[arg-type]  # 上面已收敛到三个字面量
        citations=[
            AnswerCitation(title=str(citation.title or ""), excerpt=str(citation.excerpt or ""))
            for citation in (getattr(public_result, "citations", None) or [])
        ],
        internal_evidence=internal_evidence,
        context=dict(context or {}),
        scenario=scenario or "",
        planned_queries=planned_queries,
        missing_required_rules=missing_required_rules,
        calculation_trace=calculation_trace if isinstance(calculation_trace, dict) else None,
    )


class QAVerificationOutcome(BaseModel):
    """薄路由的验证结果响应契约。"""

    model_config = ConfigDict(frozen=True)

    verification: KnowledgeAnswerVerificationResult
    trace_available: bool
    degraded: bool


def _build_degraded_envelope(qa_turn_id: str, task: dict[str, Any]) -> KnowledgeAnswerVerificationInput:
    """无 trace 时从 task 闭环的公开快照构建降级信封（公开-only 验证）。"""
    input_data = task.get("input_data") or {}
    output_data = task.get("output_data") or {}
    answer_status = str(output_data.get("answer_status") or "unavailable")
    if answer_status not in ("complete", "partial", "unavailable"):
        answer_status = "unavailable"
    return KnowledgeAnswerVerificationInput(
        qa_turn_id=qa_turn_id,
        question=str(input_data.get("question_excerpt") or ""),
        answer=str(output_data.get("answer_excerpt") or ""),
        answer_status=answer_status,  # type: ignore[arg-type]
    )


def verify_qa_turn(
    qa_turn_id: str,
    *,
    store: AnswerVerificationTraceStore,
    port: RuleKnowledgePort | None,
) -> QAVerificationOutcome | None:
    """按 qa_turn_id 验证一次 Policy QA 回答。

    Returns:
        None 表示 qa_turn_id 完全不存在（伪造/过期），路由层映射 404；
        有 trace → 完整内部验证；无 trace 但 task 存在 → 公开-only 降级验证。
    """
    verifier = KnowledgeAnswerVerifier(port)
    envelope = store.get(qa_turn_id)
    if envelope is not None:
        return QAVerificationOutcome(
            verification=_verify_fail_closed(verifier, envelope),
            trace_available=True,
            degraded=False,
        )
    task = get_task(qa_turn_id)
    if task is None:
        return None
    degraded_envelope = _build_degraded_envelope(qa_turn_id, task)
    return QAVerificationOutcome(
        verification=_verify_fail_closed(verifier, degraded_envelope),
        trace_available=False,
        degraded=True,
    )


def _verify_fail_closed(
    verifier: KnowledgeAnswerVerifier,
    envelope: KnowledgeAnswerVerificationInput,
) -> KnowledgeAnswerVerificationResult:
    """知识源中途故障时降级为无知识源验证（blocked_by_evaluator），绝不 500/伪通过。"""
    try:
        return verifier.verify(envelope)
    except Exception as exc:  # Milvus 等知识源异常 → fail-closed
        logger.warning(f"[ANSWER-VERIFY] knowledge source failed, fail-closed: {exc}")
        return KnowledgeAnswerVerifier(None).verify(envelope)
