"""Policy QA API 输入模型。"""

from dataclasses import dataclass
@dataclass
class PolicyQARequest:
    """政策问答请求；结算单是必需业务上下文。"""

    question: str
    settlement_id: str
    session_id: str | None = None
    user_id: str = ""
    role: str = ""
