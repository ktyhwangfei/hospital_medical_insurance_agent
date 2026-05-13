"""API 网关中间件模块

提供统一的请求处理、响应封装和处理时间记录等网关功能。
"""
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from src.gateway.access_log import access_logger
from src.gateway.auth import AuthResult, AuthStatus, authenticator
from src.gateway.channel import ChannelType, channel_detector
from src.gateway.rate_limiter import rate_limiter
from src.gateway.request_guard import request_guard
from src.gateway.tenant import tenant_manager

logger = logging.getLogger(__name__)


@dataclass
class GatewayRequest:
    """网关请求上下文

    携带网关处理过程中的所有上下文信息。
    """
    request_id: str = ""
    method: str = ""
    path: str = ""
    query_params: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    client_ip: str = ""
    user_agent: str = ""

    # 网关处理后填充
    channel: ChannelType = ChannelType.UNKNOWN
    auth_result: AuthResult | None = None
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class GatewayResponse:
    """网关响应

    统一封装的响应结构。
    """
    success: bool = True
    status_code: int = 200
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    request_id: str = ""
    duration_ms: float = 0.0


class ApiGatewayMiddleware:
    """API 网关中间件

    统一请求处理管道，包含：
    - 请求 ID 生成
    - 渠道识别
    - 认证鉴权
    - 租户解析
    - 限流检查
    - 请求安全校验
    - 响应封装
    - 接入日志记录
    """

    def __init__(self) -> None:
        self._request_count: int = 0

    async def process_request(self, request: GatewayRequest) -> GatewayResponse:
        """处理请求

        按顺序执行网关管道中的各个处理步骤。

        Args:
            request: 网关请求上下文

        Returns:
            网关响应
        """
        request.request_id = self._generate_request_id()
        request.start_time = time.monotonic()
        self._request_count += 1

        # 1. 渠道识别
        request.channel = channel_detector.detect(
            host=request.headers.get("host", ""),
            user_agent=request.user_agent,
            referer=request.headers.get("referer", ""),
            headers=request.headers,
            path=request.path,
        )
        logger.debug("Channel detected: %s for request %s", request.channel, request.request_id)

        # 2. 认证鉴权
        auth_header = request.headers.get("authorization", "")
        if authenticator.is_public_path(request.path):
            logger.debug("Public path, skip auth: %s", request.path)
        elif auth_header:
            request.auth_result = authenticator.validate_token(auth_header)
            if not request.auth_result.is_success:
                return self._error_response(
                    request=request,
                    status_code=401,
                    error_code=request.auth_result.status.value,
                    error_message=request.auth_result.error_message,
                )

            # 3. 租户上下文
            if request.auth_result.metadata:
                tenant_ctx = tenant_manager.resolve_from_token(
                    request.auth_result.metadata.get("payload", {}),
                )
                if tenant_ctx:
                    tenant_manager.set_current(tenant_ctx)
        else:
            logger.warning("No auth header for request %s", request.request_id)

        # 4. 限流检查
        rate_key = request.auth_result.user_id if request.auth_result else request.client_ip
        rate_result = rate_limiter.check(rate_key)
        if not rate_result.allowed:
            return self._error_response(
                request=request,
                status_code=429,
                error_code="rate_limited",
                error_message=f"请求过于频繁，请在 {rate_result.retry_after:.1f} 秒后重试",
            )

        # 返回成功响应（具体业务处理由上层继续）
        return GatewayResponse(
            success=True,
            status_code=200,
            request_id=request.request_id,
        )

    async def finalize_response(
        self,
        request: GatewayRequest,
        response: GatewayResponse,
        *,
        risk_level: str = "low",
        audit_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """完成响应处理（记录日志、清理上下文）

        Args:
            request: 网关请求上下文
            response: 网关响应
            risk_level: 风险等级
            audit_events: 审计事件
        """
        request.end_time = time.monotonic()
        duration_ms = (request.end_time - request.start_time) * 1000
        response.duration_ms = round(duration_ms, 2)

        # 记录接入日志
        access_logger.log(
            request_id=request.request_id,
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=request.client_ip,
            user_agent=request.user_agent,
            channel=request.channel.value,
            tenant_id=tenant_manager.get_current().tenant_id if tenant_manager.get_current() else "",
            user_id=request.auth_result.user_id if request.auth_result else "",
            query_params=request.query_params,
            request_body=request.body,
            response_body=response.data if response.data else None,
            error_code=response.error_code,
            risk_level=risk_level,
            audit_events=audit_events,
        )

        # 清理租户上下文
        tenant_manager.clear_current()

    def _error_response(
        self,
        request: GatewayRequest,
        status_code: int,
        error_code: str,
        error_message: str,
    ) -> GatewayResponse:
        """构造错误响应

        Args:
            request: 网关请求上下文
            status_code: HTTP 状态码
            error_code: 错误码
            error_message: 错误信息

        Returns:
            错误响应
        """
        return GatewayResponse(
            success=False,
            status_code=status_code,
            error_code=error_code,
            error_message=error_message,
            request_id=request.request_id,
        )

    @staticmethod
    def _generate_request_id() -> str:
        """生成请求唯一标识

        Returns:
            请求 ID（UUID 格式）
        """
        return str(uuid.uuid4())

    def reset(self) -> None:
        """重置中间件状态"""
        self._request_count = 0


class RequestAggregator:
    """请求聚合器

    将多个相关的请求聚合成一个批量请求，减少网络开销。
    适用于前端需要同时获取多个数据源的场景。
    """

    def __init__(self) -> None:
        self._batches: dict[str, list[dict[str, Any]]] = {}

    def add_request(self, batch_id: str, request: dict[str, Any]) -> str:
        """添加请求到聚合批次

        Args:
            batch_id: 批次 ID
            request: 请求描述（包含 method, path, params 等）

        Returns:
            请求在批次中的索引
        """
        if batch_id not in self._batches:
            self._batches[batch_id] = []
        self._batches[batch_id].append(request)
        return str(len(self._batches[batch_id]) - 1)

    async def execute_batch(
        self,
        batch_id: str,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """执行一个聚合批次的请求

        Args:
            batch_id: 批次 ID
            handler: 单个请求的处理函数

        Returns:
            所有请求的响应列表
        """
        batch = self._batches.pop(batch_id, [])
        if not batch:
            logger.warning("Empty batch: %s", batch_id)
            return []

        import asyncio
        results = await asyncio.gather(
            *[handler(req) for req in batch],
            return_exceptions=True,
        )

        # 将异常转换为错误响应
        final_results: list[dict[str, Any]] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Batch request %s[%d] failed: %s", batch_id, i, result)
                final_results.append({
                    "index": i,
                    "success": False,
                    "error": str(result),
                })
            else:
                final_results.append({
                    "index": i,
                    "success": True,
                    "data": result,
                })

        return final_results

    def reset(self) -> None:
        """重置聚合器"""
        self._batches.clear()


__all__ = [
    "GatewayRequest",
    "GatewayResponse",
    "ApiGatewayMiddleware",
    "RequestAggregator",
]
