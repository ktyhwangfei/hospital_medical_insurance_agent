"""BusinessMemory 数据模型

定义业务记忆的实体、枚举和快照结构。
遵循 DDD 战术分类：BusinessMemory 为 Entity（有唯一标识 memory_id）。
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryType(StrEnum):
    """记忆类型 — 对应语义层业务对象"""

    PATIENT = "patient"           # 患者信息
    VISIT = "visit"               # 就诊记录
    SETTLEMENT = "settlement"     # 结算记录
    POLICY = "policy"             # 政策规则
    RULE = "rule"                 # 业务规则
    DRUG = "drug"                 # 药品信息
    DISEASE = "disease"           # 疾病诊断
    INDICATOR = "indicator"       # 业务指标
    CONVERSATION = "conversation" # 对话摘要


class ExpirePolicy(StrEnum):
    """记忆过期策略"""

    SESSION = "session"     # 会话结束即失效
    TOPIC = "topic"         # 话题切换即失效
    STICKY = "sticky"       # 跨话题保留（如政策/规则）
    TIME = "time"           # 时间过期（如 30 分钟无活动）


class BusinessMemory(BaseModel):
    """业务记忆 — 会话级缓存与索引

    不复制领域对象全部数据，仅保存：
    1. 指向领域对象的引用（ref_id + type）
    2. 当前推理所需的关键字段快照（object_snapshot）
    3. 元数据（重要性、置信度、过期策略、关联）

    领域真相权威来源是语义层与外部系统（经 adapters/ 防腐层）。
    """

    memory_id: str
    session_id: str
    type: MemoryType
    ref_id: str | None = None              # 领域对象标识，如 settlement_id
    object_snapshot: dict[str, Any] = Field(default_factory=dict)  # 关键字段快照
    importance: float = 0.5                # 0~1，供 Composer 排序
    confidence: float = 0.5                # 0~1
    expire_policy: ExpirePolicy = ExpirePolicy.TOPIC
    relations: list[str] = Field(default_factory=list)  # 关联 memory_id
    version: int = 1                       # 快照版本，用于刷新检测
    last_used_at: str
    created_at: str
