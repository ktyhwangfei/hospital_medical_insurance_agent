"""
网关审计中间件 — 自动记录所有 API 请求审计日志 (v3.0)

基于 Starlette BaseHTTPMiddleware，在请求前后采集元数据并写入 audit_logs 表。
同时负责会话管理（sessions 表写入）和 X-Session-Id 响应头注入。

提取字段:
    user_id, session_id, role, request_path, request_method,
    request_summary (JSONB), response_status, response_summary (JSONB),
    client_ip, user_agent, duration_ms

排除路径 (无审计): /health, /version, /metrics
排除路径 (无会话): 上述 + /model-test
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# 不需要审计的路径（健康检查、版本信息、Prometheus 指标）
EXCLUDED_AUDIT_PATHS: frozenset[str] = frozenset({"/health", "/version", "/metrics"})

# 不需要会话管理的路径（加上测试端点）
EXCLUDED_SESSION_PATHS: frozenset[str] = frozenset({"/health", "/version", "/metrics", "/model-test"})


class GatewayAuditMiddleware(BaseHTTPMiddleware):
    """网关审计中间件

    自动记录所有 API 请求到 audit_logs 表，并管理 sessions 表。
    请求处理步骤:
      1. 提取请求元数据（user_id, session_id, role, client_ip, user_agent）
      2. 生成/延续会话（sessions 表 upsert）
      3. 转发请求并计时
      4. 构建响应摘要
      5. 写入审计日志（audit_logs 表）
      6. 注入 X-Session-Id 响应头
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._db_client: Any = None
        self._audit_log: Any = None

    # ── lazy 资源初始化 ──────────────────────────────────────────────

    def _get_client(self) -> Any:
        """懒加载 PostgreSQL 客户端。"""
        if self._db_client is None:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient

            self._db_client = PostgreSQLClient(DATABASE_URL)
        return self._db_client

    def _get_audit_log(self) -> Any:
        """懒加载审计日志实例（自动选择 PostgreSQL/内存实现）。"""
        if self._audit_log is None:
            from src.security.audit import create_audit_log

            self._audit_log = create_audit_log()
        return self._audit_log

    # ── 核心 dispatch ────────────────────────────────────────────────

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:  # type: ignore[override]
        path = request.url.path
        method = request.method

        # 跳过排除路径
        if path in EXCLUDED_AUDIT_PATHS:
            return await call_next(request)

        # Step 1: 提取请求元数据
        session_id = request.headers.get("X-Session-Id", str(uuid.uuid4()))
        user_id = request.headers.get("X-User-Id", "")
        role = request.headers.get("X-Role", "")
        client_ip = request.client.host if request.client else ""
        user_agent = request.headers.get("user-agent", "")

        # 构建脱敏的请求摘要（不记录请求体内容）
        try:
            body_size = int(request.headers.get("content-length", 0))
        except (ValueError, TypeError):
            body_size = 0
        request_summary: dict[str, Any] = {
            "path": path,
            "query_params": dict(request.query_params),
            "body_size": body_size,
        }

        # Step 2: 会话管理（异步写入，不阻塞请求链路）
        if path not in EXCLUDED_SESSION_PATHS:
            asyncio.create_task(self._write_session(session_id, user_id, role))

        # Step 3: 转发请求并计时
        start_time = time.monotonic()
        try:
            response = await call_next(request)
        except BaseException as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            # 异常情况下仍记录审计
            asyncio.create_task(
                self._write_audit(
                    event_type="request",
                    user_id=user_id,
                    session_id=session_id,
                    role=role,
                    request_path=path,
                    request_method=method,
                    request_summary=request_summary,
                    response_status=500,
                    response_summary={"error": str(exc)[:200]},
                    client_ip=client_ip,
                    user_agent=user_agent,
                    duration_ms=duration_ms,
                )
            )
            raise

        # Step 4: 构建响应摘要
        duration_ms = int((time.monotonic() - start_time) * 1000)
        response_summary: dict[str, Any] = {
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
        }

        # Step 5: 写入审计日志（异步，不阻塞响应返回）
        asyncio.create_task(
            self._write_audit(
                event_type="request",
                user_id=user_id,
                session_id=session_id,
                role=role,
                request_path=path,
                request_method=method,
                request_summary=request_summary,
                response_status=response.status_code,
                response_summary=response_summary,
                client_ip=client_ip,
                user_agent=user_agent,
                duration_ms=duration_ms,
            )
        )

        # Step 6: 注入 X-Session-Id 响应头
        response.headers["X-Session-Id"] = session_id
        return response

    # ── 异步辅助方法（通过 to_thread 运行同步 DB 操作） ─────────────

    async def _write_session(self, session_id: str, user_id: str, role: str) -> None:
        """异步写入/更新 sessions 表。"""
        try:
            client = self._get_client()
            await asyncio.to_thread(
                client.execute,
                """INSERT INTO sessions (session_id, user_id, role)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (session_id) DO UPDATE SET last_active = CURRENT_TIMESTAMP""",
                (session_id, user_id, role),
            )
        except Exception:
            logger.debug("Session write skipped (DB unavailable)", exc_info=True)

    async def _write_audit(self, **kwargs: Any) -> None:
        """异步写入 audit_logs 表。"""
        try:
            audit_log = self._get_audit_log()
            await asyncio.to_thread(lambda: audit_log.record(**kwargs))
        except Exception:
            logger.debug("Audit log write skipped (DB unavailable)", exc_info=True)
