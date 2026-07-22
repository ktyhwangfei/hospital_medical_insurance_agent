"""基础设施事件上下文 — 通过 contextvars 跨调用栈传递 session/workflow 上下文。

用法：
    from src.runtime.infra_event.context import set_infra_context

    # 在 API 入口设置上下文
    set_infra_context(session_id="sess-xxx", workflow_id="wf-xxx")

    # 在基础设施层读取
    from src.runtime.infra_event.context import infra_context
    ctx = infra_context.get()
    print(ctx.session_id)  # "sess-xxx"
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@dataclass
class InfraContext:
    """跨调用栈传递的请求上下文"""

    session_id: str = ""
    workflow_id: str = ""
    user_id: str = ""
    role: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# contextvars 变量（线程安全 + async 安全）
_infra_ctx: contextvars.ContextVar[InfraContext] = contextvars.ContextVar(
    "infra_context", default=InfraContext()
)


def infra_context() -> InfraContext:
    """获取当前请求的 infra 上下文"""
    return _infra_ctx.get()


def set_infra_context(
    session_id: str = "",
    workflow_id: str = "",
    user_id: str = "",
    role: str = "",
    **extra: Any,
) -> None:
    """设置当前请求的 infra 上下文（通常在 API 入口调用）"""
    ctx = InfraContext(
        session_id=session_id,
        workflow_id=workflow_id,
        user_id=user_id,
        role=role,
        extra=dict(extra),
    )
    _infra_ctx.set(ctx)
