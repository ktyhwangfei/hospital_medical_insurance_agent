"""治理操作审计（Issue #75 S4）— actor + action + target_ref 显式留痕。

网关中间件的请求级审计只记录 X-User-Id 头，拿不到 JWT 主体；
本模块在治理写端点显式调用，操作人取自认证主体（与 flow 发布先例对齐）。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def record_governance_action(
    *,
    user_id: str,
    roles: list[str],
    action: str,
    target_ref: str,
    request_path: str | None = None,
) -> None:
    """记录一次治理写操作；审计写入失败只告警，不阻断业务。

    Args:
        user_id: 操作人（认证主体 sub，禁止自报）
        roles: 主体角色列表
        action: 操作标识，如 workflow.config.update / flow.publish / question.review
        target_ref: 操作对象，如 workflow_id=wf_refund_verification
        request_path: 触发请求的 API 路径（可选）
    """
    try:
        from src.security.audit import audit_log

        audit_log.record_event(
            event_type="governance_action",
            user_id=user_id,
            role=",".join(roles),
            action=action,
            target_ref=target_ref,
            request_path=request_path,
        )
    except Exception:
        logger.warning("治理审计写入失败（不阻断业务）", exc_info=True)
