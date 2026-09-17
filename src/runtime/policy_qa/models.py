"""Policy QA API 输入模型。"""

from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class PolicyQAMode(StrEnum):
    """Policy QA 三态入口模式：政策问答 / 结算解释 / 运营问数。"""

    POLICY_CHAT = "policy_chat"
    SETTLEMENT_EXPLAIN = "settlement_explain"
    DATA_QUERY = "data_query"


@dataclass
class PolicyQARequest:
    """政策问答请求；结算单是业务上下文，宽泛政策问题可省略。

    settlement_ids：同药跨单对比（Q1 型）的多单号入口；
    id_card/visit_date：门诊 HIS 退费核对（Q2/Q4 型）的人员身份入口——
    仅在进程内用于查询过滤，不落轨迹/日志（脱敏硬约束）。
    """

    question: str
    mode: PolicyQAMode = PolicyQAMode.POLICY_CHAT
    settlement_id: str | None = None
    settlement_ids: list[str] = field(default_factory=list)
    id_card: str = ""
    visit_date: str = ""
    session_id: str | None = None
    user_id: str = ""
    role: str = ""


class SuspendSessionRequest(BaseModel):
    """挂起会话请求（Issue #30 §五）"""

    reason: str = Field(default="", max_length=500)


class EscalateSessionRequest(BaseModel):
    """升级医保办请求"""

    question: str = Field(min_length=1, max_length=2000)
    reason: str = Field(default="", max_length=500)
    qa_turn_id: str | None = Field(default=None, max_length=80)


class ResolveEscalationRequest(BaseModel):
    """医保办回复升级工单请求"""

    reply: str = Field(min_length=1, max_length=5000)
    resolved_by: str = Field(default="", max_length=64)
