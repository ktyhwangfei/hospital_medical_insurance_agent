from typing import Any

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """单轮对话记录"""
    role: str                       # "human" | "ai"
    message: str
    intent: str | None = None      # BusinessAction
    object: str | None = None      # BusinessObject
    cited_memory_ids: list[str] = Field(default_factory=list)


class RuntimeContext(BaseModel):
    # === 保留现有字段（请求级上下文）===
    request_id: str
    workflow_id: str
    user_id: str
    role: str
    message: str
    patient_id: str | None = None
    encounter_id: str | None = None
    intent: str
    intent_confidence: float
    intent_entities: dict[str, Any] = Field(default_factory=dict)
    intent_citations: list[str] = Field(default_factory=list)
    requested_at: str
    mentioned_skill_ids: list[str] = Field(default_factory=list)

    # === 新增：跨轮会话状态（从 BusinessSession 合并）===
    session_id: str | None = None           # 新增：跨轮会话标识
    current_topic: str | None = None        # 新增：当前话题
    current_settlement_id: str | None = None  # 新增：当前结算
    active_memory_ids: list[str] = Field(default_factory=list)  # 新增：活跃记忆
    conversation_turns: list[Turn] = Field(default_factory=list)  # 新增：对话轮次

    # === 新增：Runtime 增强注入（由 Memory/Composer 填充）===
    enriched_memories: list[dict[str, Any]] | None = None  # 增强后的记忆
    llm_context: dict[str, Any] | None = None              # 组装后的 LLM Context
    reasoning_state: dict[str, Any] | None = None          # 推理状态
