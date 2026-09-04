"""Policy QA API 输入模型。"""

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass
class PolicyQARequest:
    """政策问答请求；结算单是业务上下文，宽泛政策问题可省略。"""

    question: str
    settlement_id: str | None = None
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
