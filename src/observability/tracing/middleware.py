from __future__ import annotations

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

try:
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


class TracingMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that creates OpenTelemetry spans for each request.

    Records method, path, status code, and duration on each span.
    Exceptions are recorded in the span before re-raising.
    Gracefully no-ops if OpenTelemetry is not installed.
    """

    def __init__(self, app: ASGIApp, tracer: Any | None = None) -> None:
        super().__init__(app)
        self._tracer = tracer

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not _OTEL_AVAILABLE or self._tracer is None:
            return await call_next(request)

        span_name = f'{request.method} {request.url.path}'
        with self._tracer.start_as_current_span(span_name, kind=SpanKind.SERVER) as span:
            span.set_attribute('http.method', request.method)
            span.set_attribute('http.url', str(request.url))
            span.set_attribute('http.path', request.url.path)
            if request.query_params:
                span.set_attribute('http.query_params', str(request.query_params))

            start = time.time()
            try:
                response = await call_next(request)
                elapsed = time.time() - start
                span.set_attribute('http.status_code', response.status_code)
                span.set_attribute('http.duration_ms', int(elapsed * 1000))
                return response
            except Exception as exc:
                span.set_attribute('http.status_code', 500)
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise
