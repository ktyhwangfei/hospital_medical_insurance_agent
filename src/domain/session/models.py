"""会话领域模型"""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict


class Session(BaseModel):
    """用户会话（按 user_id 分组，一个用户可以有多个会话）"""

    model_config = ConfigDict(frozen=False)

    session_id: str
    user_id: str
    role: str = ""
    created_at: str = ""
    last_active: str = ""


def create_session(
    session_id: str,
    user_id: str,
    role: str = "",
    created_at: str | None = None,
    last_active: str | None = None,
) -> Session:
    now = datetime.now(timezone.utc).isoformat()
    return Session(
        session_id=session_id,
        user_id=user_id,
        role=role,
        created_at=created_at or now,
        last_active=last_active or now,
    )
