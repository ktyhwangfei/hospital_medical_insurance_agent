"""门诊运营分析 API — issue #40 P3 受控问数与运营指导。

前缀 /api/v1/medical-insurance-ai-agent/ops-analytics；鉴权走签名 JWT 的
ops:read 权限（与 /ops 健康运营同模式）。

服务通过 Depends(get_ops_analytics_service) 注入——API 测试 override 该依赖
即可注入假读取面（项目既有陷阱：直接调用工厂不响应 override）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from src.gateway.auth import authenticator
from src.runtime.api.data_governance_schemas import DataGovernancePrincipal
from src.runtime.ops_analytics.service import OpsAnalyticsService
from src.shared.schemas.responses import error_detail

router = APIRouter(
    prefix="/api/v1/medical-insurance-ai-agent/ops-analytics",
    tags=["ops-analytics"],
)


def get_ops_analytics_service() -> OpsAnalyticsService:
    """依赖注入 seam：默认连 PostgreSQLClient 读取面 + 模型网关。"""
    from src.data_platform.storage.postgresql.client import PostgreSQLClient
    from src.model_service.gateway import ModelGateway

    return OpsAnalyticsService(PostgreSQLClient(), ModelGateway())


def _require_ops_read(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> DataGovernancePrincipal:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_REQUIRED", "缺少 Authorization 凭据"),
        )
    auth = authenticator.validate_signed_token(authorization)
    if not auth.is_success or not auth.user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("AUTH_INVALID", auth.error_message or "登录凭据无效"),
        )
    permitted = authenticator.check_permission(auth, "ops:read")
    if not permitted.is_success:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail("AUTH_FORBIDDEN", "权限不足"),
        )
    return DataGovernancePrincipal(
        user_id=auth.user_id, roles=auth.roles, permissions=auth.permissions,
    )


@router.get("/overview")
def ops_overview(
    _principal=Depends(_require_ops_read),
    service: OpsAnalyticsService = Depends(get_ops_analytics_service),
):
    """六指标总览：四卡 complete（口径句 v4）+ 人次/次均 unavailable。"""
    return service.overview().model_dump()


@router.get("/trend")
def ops_trend(
    months: int = Query(default=12, ge=1, le=36),
    _principal=Depends(_require_ops_read),
    service: OpsAnalyticsService = Depends(get_ops_analytics_service),
):
    """月度趋势（就诊时间维度，口径句 v4 范围）。"""
    return {"points": [p.model_dump() for p in service.trend(months)]}


@router.get("/breakdown")
def ops_breakdown(
    dimension: str = Query(description="fund_type|cure_type|settle_state|department"),
    top_n: int = Query(default=10, ge=1, le=50),
    _principal=Depends(_require_ops_read),
    service: OpsAnalyticsService = Depends(get_ops_analytics_service),
):
    """维度拆分：五维度中的三个可用维度；科室返回 unavailable + 原因。"""
    allowed = {"fund_type", "cure_type", "settle_state", "department"}
    if dimension not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                "OPS_DIMENSION_INVALID",
                f"维度必须是 {sorted(allowed)} 之一",
            ),
        )
    return service.breakdown(dimension, top_n=top_n).model_dump()  # type: ignore[arg-type]


@router.get("/drill")
def ops_drill(
    dimension: str | None = Query(default=None),
    value: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _principal=Depends(_require_ops_read),
    service: OpsAnalyticsService = Depends(get_ops_analytics_service),
):
    """行级下钻：就诊明细（T_TradeNo 粒度），行携带 data_batch_id 指标批次。"""
    allowed = {None, "fund_type", "cure_type", "settle_state"}
    if dimension not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                "OPS_DIMENSION_INVALID",
                "下钻维度必须是 fund_type|cure_type|settle_state 或留空",
            ),
        )
    return service.drill(
        dimension=dimension,  # type: ignore[arg-type]
        value=value, date_from=date_from, date_to=date_to,
        limit=limit, offset=offset,
    ).model_dump()


@router.get("/weekly-report")
def ops_weekly_report(
    week_start: str | None = Query(default=None, description="ISO 周一 YYYY-MM-DD"),
    _principal=Depends(_require_ops_read),
    service: OpsAnalyticsService = Depends(get_ops_analytics_service),
):
    """周报：四指标环比 + 每条结论引用指标批次 + AI 运营摘要（可降级）。"""
    try:
        return service.weekly_report(week_start).model_dump()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                "WEEK_START_INVALID", "week_start 必须是 YYYY-MM-DD 格式的周一日期"
            ),
        ) from None
