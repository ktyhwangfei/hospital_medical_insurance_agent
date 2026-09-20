"""门户认证 API（Issue #75）：登录 / 续期 / 登出 / 当前主体。

全部 fail-closed：AUTH_JWT_SECRET 缺失时签发抛错（绝不回退假数据）。
依赖注入 seam：get_portal_auth_service 供测试 override 注入内存存储。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.gateway.auth import authenticator
from src.gateway.auth.token_issuer import ACCESS_TOKEN_TTL_SECONDS
from src.runtime.portal_auth.service import PortalAuthError, PortalAuthService
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent",
    tags=["portal-auth"],
)

# 进程内懒加载单例；种子初始化仅执行一次
_service: PortalAuthService | None = None


def get_portal_auth_service() -> PortalAuthService:
    """依赖注入 seam：测试 override 此函数注入内存存储 + 预置账号。"""
    global _service
    if _service is None:
        from src.data_platform.storage.portal_account import get_portal_account_store

        _service = PortalAuthService(get_portal_account_store())
        _service.seed_from_env()
    return _service


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = ACCESS_TOKEN_TTL_SECONDS


class MeResponse(BaseModel):
    user_id: str
    roles: list[str]
    permissions: list[str]
    exp: int


def _require_valid_token(authorization: str | None) -> None:
    """校验 Authorization 持有效未过期 JWT，失败抛 401。返回 token 供拉黑。"""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success:
        code = "EXPIRED_TOKEN" if auth.status.value == "expired_token" else "AUTH_INVALID"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(code, auth.error_message or "登录凭据无效"),
        )


def _rate_limit_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}|{username}"


@router.post("/auth/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    service: PortalAuthService = Depends(get_portal_auth_service),
) -> TokenResponse:
    """账号密码登录，签发 access token（2h）。"""
    try:
        account = service.authenticate(
            payload.username, payload.password, _rate_limit_key(request, payload.username)
        )
        return TokenResponse(access_token=service.issue_token(account))
    except PortalAuthError as exc:
        status_code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if exc.code == "RATE_LIMITED"
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(
            status_code=status_code,
            detail=error_detail(exc.code, exc.message),
        ) from exc
    except RuntimeError as exc:
        # fail-closed：签发配置缺失，端点显式不可用（绝不回退假数据）
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail("AUTH_SIGNING_UNAVAILABLE", str(exc)),
        ) from exc


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh(
    authorization: str | None = Header(default=None, alias="Authorization"),
    service: PortalAuthService = Depends(get_portal_auth_service),
) -> TokenResponse:
    """持未过期 token 滑动续签；超 12h 绝对上限 → 401 强制重登（不静默降级）。"""
    try:
        return TokenResponse(access_token=service.refresh(authorization or ""))
    except PortalAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail(exc.code, exc.message),
        ) from exc


@router.post("/auth/logout")
def logout(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, str]:
    """登出：token 加入进程内黑名单。"""
    _require_valid_token(authorization)
    authenticator.invalidate_token(authorization or "")
    return {"status": "ok"}


@router.get("/auth/me", response_model=MeResponse)
def me(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> MeResponse:
    """返回当前 token 主体，供前端 AuthProvider 初始化。"""
    _require_valid_token(authorization)
    auth = authenticator.validate_signed_token(authorization or "")
    exp = auth.metadata.get("payload", {}).get("exp", 0)
    return MeResponse(
        user_id=auth.user_id,
        roles=auth.roles,
        permissions=auth.permissions,
        exp=exp if isinstance(exp, int) else 0,
    )
