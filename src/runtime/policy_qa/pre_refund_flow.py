"""门诊部分项目预退费分析核心流程。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from skills.outpatient_pre_refund_analysis_skill.assembler import PreRefundSkillResult
from src.adapters.base.models import AdapterCallStatus
from src.adapters.billing.models import (
    PartialRefundItemRequest,
    PartialRefundPreview,
    PreSettlementErrorType,
)
from src.adapters.ports.billing import BillingPort
from src.runtime.api.schemas import AgentResponse
from src.runtime.policy_qa.models import PolicyQARequest
from src.security.risk_control.service import (
    build_human_confirmation_response,
    detect_blocked_actions,
)
from src.skill_infra.skill_router import get_assembler


PRE_REFUND_SKILL_ID = "outpatient_pre_refund_analysis_skill"
PREVIEW_TERMS = ("预退费", "退费分析", "退费试算", "分析退费")
EXECUTION_TERMS = ("确认退费", "执行退费", "办理退费", "立即退费", "马上退费", "冲正")


@dataclass(frozen=True)
class PreRefundFlowOutcome:
    state: Literal["completed", "unavailable", "waiting_human_confirmation"]
    skill_result: PreRefundSkillResult | None = None
    confirmation: AgentResponse | None = None
    attempt_count: int = 0
    recovery_count: int = 0
    halt_reason: str = ""
    message: str = ""


def refund_execution_actions(question: str) -> list[tuple[str, str]]:
    """只读分析词不触发拦截；显式退费执行词始终优先。"""
    question = question.strip()
    explicit = [term for term in EXECUTION_TERMS if term in question]
    if "立即执行" in question and ("退费" in question or "冲正" in question):
        explicit.append("立即执行退费")
    if explicit:
        return [(term, "pre_refund_explicit") for term in sorted(set(explicit))]
    detected = detect_blocked_actions(question)
    if any(term in question for term in PREVIEW_TERMS):
        return [(action, rule_id) for action, rule_id in detected if "退费" not in action]
    return detected


async def run_pre_refund_flow(
    request: PolicyQARequest,
    billing_adapter: BillingPort,
) -> PreRefundFlowOutcome:
    """执行门诊部分项目预退费分析，不执行实际退费。"""
    blocked_actions = refund_execution_actions(request.question)
    if blocked_actions:
        confirmation = build_human_confirmation_response(blocked_actions)
        return PreRefundFlowOutcome(
            state="waiting_human_confirmation",
            confirmation=confirmation,
            halt_reason="high_risk_action_requires_human_confirmation",
            message="实际退费或冲正必须由人工确认执行。",
        )

    request_items = request.pre_refund_items or []
    if not request_items:
        return PreRefundFlowOutcome(
            state="unavailable",
            halt_reason="pre_refund_items_missing",
            message="预退费分析缺少拟退费用明细。",
        )
    fee_detail_ids = [item.fee_detail_id for item in request_items]
    if len(set(fee_detail_ids)) != len(fee_detail_ids):
        return PreRefundFlowOutcome(
            state="unavailable",
            halt_reason="duplicate_fee_detail_id",
            message="拟退费用明细存在重复的 fee_detail_id。",
        )

    items = tuple(
        PartialRefundItemRequest(
            fee_detail_id=item.fee_detail_id,
            refund_quantity=item.refund_quantity,
        )
        for item in request_items
    )
    attempt_count = 0
    recovery_count = 0
    while attempt_count < 2:
        attempt_count += 1
        adapter_result = await asyncio.to_thread(
            billing_adapter.preview_partial_refund,
            request.settlement_id,
            items,
        )
        if adapter_result.status == AdapterCallStatus.FAILED:
            if (
                adapter_result.error_type == PreSettlementErrorType.UNAVAILABLE.value
                and attempt_count < 2
            ):
                recovery_count += 1
                continue
            return PreRefundFlowOutcome(
                state="unavailable",
                attempt_count=attempt_count,
                recovery_count=recovery_count,
                halt_reason=adapter_result.error_type or "pre_settlement_failed",
                message=adapter_result.message or "院端预结算不可用。",
            )

        preview = adapter_result.data.get("preview")
        if not isinstance(preview, PartialRefundPreview):
            return PreRefundFlowOutcome(
                state="unavailable",
                attempt_count=attempt_count,
                recovery_count=recovery_count,
                halt_reason="pre_settlement_response_invalid",
                message="院端预结算响应缺少有效的结构化结果。",
            )

        assembler = get_assembler(PRE_REFUND_SKILL_ID)
        if assembler is None:
            return PreRefundFlowOutcome(
                state="unavailable",
                attempt_count=attempt_count,
                recovery_count=recovery_count,
                halt_reason="pre_refund_skill_unavailable",
                message="门诊部分项目预退费分析 Skill 未加载。",
            )
        skill_result = assembler.execute(request.settlement_id, items, preview)
        if not skill_result.can_answer:
            return PreRefundFlowOutcome(
                state="unavailable",
                skill_result=skill_result,
                attempt_count=attempt_count,
                recovery_count=recovery_count,
                halt_reason="pre_settlement_verification_failed",
                message=(skill_result.warnings or ["院端预结算结果未通过校验。"])[0],
            )
        return PreRefundFlowOutcome(
            state="completed",
            skill_result=skill_result,
            attempt_count=attempt_count,
            recovery_count=recovery_count,
            halt_reason="official_pre_settlement_verified",
        )

    raise RuntimeError("unreachable")
