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
skill_ai_generation_total: Any = None
skill_ai_generation_success_total: Any = None
skill_ai_generation_rejected_total: Any = None
skill_ai_output_parse_failure_total: Any = None
skill_ai_unsafe_code_total: Any = None
skill_ai_manual_accept_total: Any = None

_METRICS_INITIALIZED = False


def setup_metrics() -> bool:
    """Define and register all Prometheus metrics.

    Returns:
        True if metrics were successfully initialized, False if prometheus_client
        is not installed.
    """
    global http_requests_total, http_request_duration_seconds, active_requests
    global workflow_executions_total, adapter_calls_total, _METRICS_INITIALIZED
    global skill_ai_generation_total, skill_ai_generation_success_total
    global skill_ai_generation_rejected_total, skill_ai_output_parse_failure_total
    global skill_ai_unsafe_code_total, skill_ai_manual_accept_total

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

    skill_ai_generation_total = Counter(
        'skill_ai_generation_total',
        'Total number of Skill AI generation attempts',
        ['scene', 'status'],
    )
    skill_ai_generation_success_total = Counter(
        'skill_ai_generation_success_total',
        'Total number of successful Skill AI generations',
        ['scene', 'status'],
    )
    skill_ai_generation_rejected_total = Counter(
        'skill_ai_generation_rejected_total',
        'Total number of rejected Skill AI generations',
        ['scene', 'reason_code'],
    )
    skill_ai_output_parse_failure_total = Counter(
        'skill_ai_output_parse_failure_total',
        'Total number of invalid Skill AI output payloads',
        ['scene', 'reason_code'],
    )
    skill_ai_unsafe_code_total = Counter(
        'skill_ai_unsafe_code_total',
        'Total number of unsafe Skill AI code rejections',
        ['scene', 'reason_code'],
    )
    skill_ai_manual_accept_total = Counter(
        'skill_ai_manual_accept_total',
        'Total number of manually accepted Skill AI proposals',
        ['scene', 'status'],
    )

    _METRICS_INITIALIZED = True
    return True


_SKILL_AI_SCENE = 'skill_authoring'
_SKILL_AI_REASON_CODES = frozenset(
    {
        'evidence_unavailable',
        'input_invalid',
        'metric_not_found',
        'metric_not_published',
        'model_error',
        'output_invalid',
        'output_parse_failure',
        'revision_conflict',
        'unsafe_code',
    }
)


def _increment(counter: Any, **labels: str) -> None:
    if counter is not None:
        counter.labels(**labels).inc()


def record_skill_ai_generation_started() -> None:
    _increment(
        skill_ai_generation_total,
        scene=_SKILL_AI_SCENE,
        status='started',
    )


def record_skill_ai_generation_success() -> None:
    _increment(
        skill_ai_generation_success_total,
        scene=_SKILL_AI_SCENE,
        status='success',
    )


def record_skill_ai_generation_rejected(reason_code: str) -> None:
    safe_reason = reason_code if reason_code in _SKILL_AI_REASON_CODES else 'other'
    labels = {'scene': _SKILL_AI_SCENE, 'reason_code': safe_reason}
    _increment(skill_ai_generation_rejected_total, **labels)
    if safe_reason == 'output_parse_failure':
        _increment(skill_ai_output_parse_failure_total, **labels)
    elif safe_reason == 'unsafe_code':
        _increment(skill_ai_unsafe_code_total, **labels)


def record_skill_ai_manual_accept() -> None:
    _increment(
        skill_ai_manual_accept_total,
        scene=_SKILL_AI_SCENE,
        status='accepted',
    )
