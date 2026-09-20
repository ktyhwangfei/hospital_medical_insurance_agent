"""统一治理接口权限校验核心（Issue #75 S2）。

收敛原先散落于 tool_workflow / ops / question_library / data_governance /
ops_analytics / flow 六个路由文件的同构 `_require_permission` helper。

错误码契约保持 AUTH_REQUIRED / AUTH_INVALID / AUTH_FORBIDDEN 不变；
语义审核 / PDSC / Skill 治理等使用独立错误码契约（AUTHENTICATION_REQUIRED 族）
的域不在此收敛，其契约由前端按域处理。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, status

from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
from src.shared.schemas.responses import error_detail


@dataclass(frozen=True)
class PrincipalErrorCodes:
    """各域 401/403 错误码契约（默认 AUTH_* 族）。"""

    missing: str = "AUTH_REQUIRED"
    invalid: str = "AUTH_INVALID"
    forbidden: str = "AUTH_FORBIDDEN"


def resolve_principal(
    scope: str,
    authorization: str | None,
    codes: PrincipalErrorCodes | None = None,
) -> DataGovernancePrincipal:
    """验签 + scope 校验，失败抛 401/403；成功返回认证主体。

    行为与各路由原本地 helper 完全一致，仅此一份实现。
    """
    codes = codes or PrincipalErrorCodes()
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(codes.missing, "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success or not auth.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(codes.invalid, auth.error_message or "登录凭据无效"),
        )
    permitted = authenticator.check_permission(auth, scope)
    if not permitted.is_success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(codes.forbidden, "权限不足"),
        )
    return DataGovernancePrincipal(
        user_id=auth.user_id,
        roles=auth.roles,
        permissions=auth.permissions,
    )
