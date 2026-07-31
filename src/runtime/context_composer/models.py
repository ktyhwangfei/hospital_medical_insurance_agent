"""Context Composer — 上下文编排器

从 Memory 中挑选最有价值的信息并排序，组织为 LLM Context。
负责 Token 预算管理和摘要策略。
"""

from pydantic import BaseModel, Field


class MemoryBrief(BaseModel):
    """记忆摘要 — 用于 LLM Context 的精简表示"""
    memory_id: str
    type: str
    summary: str
    importance: float


class LLMContext(BaseModel):
    """LLM 上下文 — 结构化对象，供 Prompt Template 消费"""
    session_summary: str = ""
    selected_memories: list[MemoryBrief] = Field(default_factory=list)
    reasoning_so_far: list[str] = Field(default_factory=list)   # 来自 Reasoning State
    token_budget_used: int = 0
    token_budget_total: int = 0
