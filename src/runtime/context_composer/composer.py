"""Context Composer — 上下文编排器

从 Memory 中挑选最有价值的信息并排序，组织为 LLM Context。
负责 Token 预算管理和摘要策略。
"""

import logging
from typing import Any

from src.runtime.context_composer.budget import TokenBudget
from src.runtime.context_composer.models import LLMContext, MemoryBrief
from src.runtime.memory.models import BusinessMemory

logger = logging.getLogger(__name__)


class ContextComposer:
    """上下文编排器

    职责：
    1. 从 Memory 中挑选最有价值的信息
    2. 按 importance + recency 排序
    3. Token 预算管理：超出时摘要（summarize）而非截断（truncate）
    4. 输出结构化的 LLMContext

    策略：
    - 高优先级记忆（importance > 0.7）全量放入
    - 中优先级记忆（0.3 < importance <= 0.7）放入摘要
    - 低优先级记忆（importance <= 0.3）丢弃
    - 保留 token_budget 的 10% 给 reasoning chain
    """

    def __init__(self, token_budget: int | None = None, model_gateway=None):
        self._budget = TokenBudget(token_budget)
        self._model_gateway = model_gateway  # 可选：用于模型摘要

    def compose(
        self,
        memories: list[BusinessMemory],
        reasoning_chain: list[str] | None = None,
        session_summary: str = "",
    ) -> LLMContext:
        """编排 LLM 上下文。

        Args:
            memories: 当前会话的所有记忆
            reasoning_chain: 已有的推理链（来自 ReasoningState）
            session_summary: 会话摘要

        Returns:
            结构化的 LLMContext
        """
        budget = self._budget.allocate()
        reasoning_chain = reasoning_chain or []

        # 1. 按 importance + recency 排序
        sorted_memories = sorted(
            memories,
            key=lambda m: (m.importance, m.last_used_at),
            reverse=True,
        )

        # 2. 分类记忆
        high_priority = [m for m in sorted_memories if m.importance > 0.7]
        medium_priority = [m for m in sorted_memories if 0.3 < m.importance <= 0.7]
        low_priority = [m for m in sorted_memories if m.importance <= 0.3]

        # 3. 处理高优先级记忆（全量放入）
        selected: list[MemoryBrief] = []
        total_tokens = 0

        for memory in high_priority:
            summary = self._summarize_memory(memory, full=True)
            tokens = self._budget.estimate_tokens(summary)
            selected.append(MemoryBrief(
                memory_id=memory.memory_id,
                type=memory.type.value,
                summary=summary,
                importance=memory.importance,
            ))
            total_tokens += tokens

        # 4. 处理中优先级记忆（摘要放入）
        for memory in medium_priority:
            summary = self._summarize_memory(memory, full=False)
            tokens = self._budget.estimate_tokens(summary)

            # 检查预算
            if total_tokens + tokens > budget["current_entity"] + budget["related_entities"]:
                # 尝试进一步压缩摘要
                summary = self._compress_summary(summary)
                tokens = self._budget.estimate_tokens(summary)
                if total_tokens + tokens > budget["current_entity"] + budget["related_entities"]:
                    continue  # 仍然超预算，跳过

            selected.append(MemoryBrief(
                memory_id=memory.memory_id,
                type=memory.type.value,
                summary=summary,
                importance=memory.importance,
            ))
            total_tokens += tokens

        # 5. 低优先级记忆：仅记录数量，不放入详情
        if low_priority:
            logger.debug(f"Skipped {len(low_priority)} low-priority memories")

        # 6. 计算推理链 token
        reasoning_tokens = sum(
            self._budget.estimate_tokens(step) for step in reasoning_chain
        )
        if reasoning_tokens > budget["reasoning_chain"]:
            # 推理链过长，保留最近 3 步
            reasoning_chain = reasoning_chain[-3:]

        # 7. 组装 LLMContext
        llm_context = LLMContext(
            session_summary=session_summary,
            selected_memories=selected,
            reasoning_so_far=reasoning_chain,
            token_budget_used=total_tokens + reasoning_tokens,
            token_budget_total=self._budget.total,
        )

        logger.info(
            f"Composed LLMContext: {len(selected)} memories "
            f"({len(high_priority)} high + {len(medium_priority)} medium + {len(low_priority)} low), "
            f"{len(reasoning_chain)} reasoning steps, "
            f"tokens {llm_context.token_budget_used}/{llm_context.token_budget_total}"
        )
        return llm_context

    def _summarize_memory(self, memory: BusinessMemory, full: bool = False) -> str:
        """将记忆转换为自然语言摘要。

        Args:
            memory: 业务记忆
            full: 是否生成完整摘要（高优先级记忆用）
        """
        parts = [f"[{memory.type.value}]"]
        if memory.ref_id:
            parts.append(f"ref={memory.ref_id}")

        if full:
            # 全量：取快照中的所有字段
            snapshot_items = list(memory.object_snapshot.items())
        else:
            # 摘要：仅取前 3 个关键字段
            snapshot_items = list(memory.object_snapshot.items())[:3]

        for k, v in snapshot_items:
            parts.append(f"{k}={v}")

        return " ".join(parts)

    def _compress_summary(self, summary: str) -> str:
        """压缩摘要到更短的长度。

        优先保留类型和 ref_id，丢弃详细字段。
        如果配置了 model_gateway，可调用模型生成更流畅的摘要。
        """
        # 如果摘要已经很短，直接返回
        if len(summary) <= 100:
            return summary

        # 尝试提取关键信息
        parts = summary.split()
        if len(parts) <= 2:
            return summary

        # 保留类型和 ref，丢弃其他字段
        compressed = [parts[0]]  # [type]
        for part in parts[1:]:
            if part.startswith("ref="):
                compressed.append(part)
                break

        result = " ".join(compressed)
        if len(result) < len(summary):
            return result + " ..."
        return summary[:100] + " ..."
