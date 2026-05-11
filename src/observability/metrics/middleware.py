from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match
from starlette.types import ASGIApp

try:
    from prometheus_client import generate_latest, REGISTRY

    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

from src.observability.metrics import (
    _METRICS_INITIALIZED,
    active_requests,
    http_request_duration_seconds,
    http_requests_total,
    setup_metrics,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that tracks HTTP request metrics for Prometheus.

    Records:
      - http_requests_total (counter by method, path, status)
      - http_request_duration_seconds (histogram by method, path)
      - active_requests (gauge)

    Exposes a /metrics endpoint for Prometheus scraping.
    Gracefully no-ops if prometheus_client is not installed.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        if _PROMETHEUS_AVAILABLE and not _METRICS_INITIALIZED:
            setup_metrics()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Handle /metrics endpoint for Prometheus scraping
        if request.url.path == '/metrics' and _PROMETHEUS_AVAILABLE:
            from starlette.responses import PlainTextResponse

            return PlainTextResponse(generate_latest(REGISTRY), media_type='text/plain')

        if not _PROMETHEUS_AVAILABLE or not _METRICS_INITIALIZED:
            return await call_next(request)

        # Resolve route path pattern for grouping
        path = self._resolve_route_path(request)

        active_requests.inc()
        start = time.time()

        try:
            response = await call_next(request)
            return response
        finally:
            elapsed = time.time() - start
            status_code = response.status_code if 'response' in dir() else 500
            # `response` may not be bound if call_next raised
            http_requests_total.labels(method=request.method, path=path, status=status_code).inc()
            http_request_duration_seconds.labels(method=request.method, path=path).observe(elapsed)
            active_requests.dec()

    @staticmethod
    def _resolve_route_path(request: Request) -> str:
        """Resolve the request path to the route pattern (e.g. /api/v1/.../{param})."""
        for route in request.app.routes:
            match, _ = route.matches(request)
            if match == Match.FULL:
                if hasattr(route, 'path'):
                    return route.path
        return request.url.path
