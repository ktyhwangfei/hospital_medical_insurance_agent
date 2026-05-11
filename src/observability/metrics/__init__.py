from __future__ import annotations

from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram, disable_created_metrics

    _PROMETHEUS_AVAILABLE = True
    disable_created_metrics()
except ImportError:
    _PROMETHEUS_AVAILABLE = False

# ── HTTP Metrics ─────────────────────────────────────────────────────────────────

http_requests_total: Any = None
http_request_duration_seconds: Any = None
active_requests: Any = None

# ── Business Metrics ─────────────────────────────────────────────────────────────

workflow_executions_total: Any = None
adapter_calls_total: Any = None

_METRICS_INITIALIZED = False


def setup_metrics() -> bool:
    """Define and register all Prometheus metrics.

    Returns:
        True if metrics were successfully initialized, False if prometheus_client
        is not installed.
    """
    global http_requests_total, http_request_duration_seconds, active_requests
    global workflow_executions_total, adapter_calls_total, _METRICS_INITIALIZED

    if not _PROMETHEUS_AVAILABLE:
        return False

    if _METRICS_INITIALIZED:
        return True

    http_requests_total = Counter(
        'http_requests_total',
        'Total number of HTTP requests',
        ['method', 'path', 'status'],
    )

    http_request_duration_seconds = Histogram(
        'http_request_duration_seconds',
        'HTTP request duration in seconds',
        ['method', 'path'],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    active_requests = Gauge(
        'active_requests',
        'Number of active HTTP requests',
    )

    workflow_executions_total = Counter(
        'workflow_executions_total',
        'Total number of workflow executions',
        ['scenario', 'status'],
    )

    adapter_calls_total = Counter(
        'adapter_calls_total',
        'Total number of adapter calls',
        ['adapter', 'operation', 'status'],
    )

    _METRICS_INITIALIZED = True
    return True
