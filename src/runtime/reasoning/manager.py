"""Reasoning State Manager — 推理状态管理器

负责推理链的维护、假设管理和中间结论的持久化。
会话级临时态，不复用为知识。
"""

import logging
from typing import Any

from src.runtime.runtime_state.models import Hypothesis, ReasoningState, ReasoningStep

logger = logging.getLogger(__name__)


class ReasoningStateManager:
    """推理状态管理器

    职责：
    - 维护推理链（添加步骤、依赖关系）
    - 管理假设（创建、验证、拒绝）
    - 支持连续追问的推理复用
    """

    def __init__(self):
        self._states: dict[str, ReasoningState] = {}  # session_id -> ReasoningState

    def get_or_create(self, session_id: str, workflow_id: str | None = None) -> ReasoningState:
        """获取或创建会话的推理状态。"""
        if session_id not in self._states:
            self._states[session_id] = ReasoningState(
                session_id=session_id,
                workflow_id=workflow_id,
            )
        return self._states[session_id]

    def add_step(
        self,
        session_id: str,
        claim: str,
        kind: str = "fact",
        depends_on: list[str] | None = None,
        confidence: float = 0.5,
        citations: list[str] | None = None,
        source_memory_ids: list[str] | None = None,
    ) -> ReasoningStep:
        """添加推理步骤。

        Args:
            session_id: 会话 ID
            claim: 结论/事实表述
            kind: 步骤类型（fact/inference/hypothesis/verified）
            depends_on: 依赖的 step_id 列表
            confidence: 置信度
            citations: 来源引用
            source_memory_ids: 来源 memory_id 列表

        Returns:
            创建的 ReasoningStep
        """
        state = self._states.get(session_id)
        if state is None:
            state = self.get_or_create(session_id)

        step_id = f"step-{len(state.chain)}-{hash(claim) & 0xFFFFFF:06x}"
        step = ReasoningStep(
            step_id=step_id,
            claim=claim,
            kind=kind,
            depends_on=depends_on or [],
            confidence=confidence,
            citations=citations or [],
            source_memory_ids=source_memory_ids or [],
        )
        state.chain.append(step)
        logger.debug(f"Added reasoning step {step_id} to session {session_id}")
        return step

    def add_hypothesis(
        self,
        session_id: str,
        statement: str,
    ) -> Hypothesis:
        """添加假设。"""
        state = self._states.get(session_id)
        if state is None:
            state = self.get_or_create(session_id)

        hypothesis_id = f"hyp-{len(state.hypotheses)}-{hash(statement) & 0xFFFFFF:06x}"
        hypothesis = Hypothesis(
            hypothesis_id=hypothesis_id,
            statement=statement,
        )
        state.hypotheses.append(hypothesis)
        logger.debug(f"Added hypothesis {hypothesis_id} to session {session_id}")
        return hypothesis

    def confirm_hypothesis(self, session_id: str, hypothesis_id: str) -> bool:
        """确认假设为真。"""
        state = self._states.get(session_id)
        if not state:
            return False

        for h in state.hypotheses:
            if h.hypothesis_id == hypothesis_id:
                h.status = "confirmed"
                # 将假设转为已验证的推理步骤
                self.add_step(
                    session_id=session_id,
                    claim=h.statement,
                    kind="verified",
                    confidence=0.9,
                )
                logger.info(f"Hypothesis {hypothesis_id} confirmed")
                return True
        return False

    def reject_hypothesis(self, session_id: str, hypothesis_id: str) -> bool:
        """拒绝假设。"""
        state = self._states.get(session_id)
        if not state:
            return False

        for h in state.hypotheses:
            if h.hypothesis_id == hypothesis_id:
                h.status = "rejected"
                logger.info(f"Hypothesis {hypothesis_id} rejected")
                return True
        return False

    def get_chain(self, session_id: str) -> list[ReasoningStep]:
        """获取会话的完整推理链。"""
        state = self._states.get(session_id)
        return state.chain if state else []

    def get_chain_summary(self, session_id: str) -> list[str]:
        """获取推理链的文本摘要（用于 LLM Context）。"""
        chain = self.get_chain(session_id)
        return [f"[{s.kind}] {s.claim}" for s in chain]

    def get_open_hypotheses(self, session_id: str) -> list[Hypothesis]:
        """获取未解决的假设。"""
        state = self._states.get(session_id)
        if not state:
            return []
        return [h for h in state.hypotheses if h.status == "open"]

    def clear(self, session_id: str) -> None:
        """清除会话的推理状态。"""
        if session_id in self._states:
            del self._states[session_id]
            logger.info(f"Cleared reasoning state for session {session_id}")

    def build_reasoning_context(self, session_id: str) -> dict[str, Any]:
        """构建推理上下文（用于注入 RuntimeContext）。"""
        state = self._states.get(session_id)
        if not state:
            return {}

        return {
            "chain_summary": self.get_chain_summary(session_id),
            "open_hypotheses": [h.statement for h in self.get_open_hypotheses(session_id)],
            "total_steps": len(state.chain),
            "total_hypotheses": len(state.hypotheses),
        }
