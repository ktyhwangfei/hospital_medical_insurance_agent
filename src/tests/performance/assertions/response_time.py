"""
Response time assertion module.

Compares Locust statistics against AGENTS.md-defined response time
thresholds (P50, P95, P99) for each endpoint category.
"""

from typing import Dict, Tuple

THRESHOLDS: Dict[str, Dict[str, float]] = {
    "health": {"p50": 50, "p95": 100, "p99": 200},
    "readonly": {"p50": 100, "p95": 300, "p99": 500},
    "crud": {"p50": 150, "p95": 500, "p99": 1000},
    "chat": {"p50": 500, "p95": 2000, "p99": 5000},
    "stream": {"p50": 1000, "p95": 3000, "p99": 8000},
}


def check_response_time(
    endpoint_category: str, stats: dict
) -> Tuple[bool, str]:
    """
    Compare Locust stats against response time thresholds.

    Args:
        endpoint_category: One of 'health', 'readonly', 'crud', 'chat', 'stream'.
        stats: Dict-like Locust stats object with get_response_time_percentile().

    Returns:
        Tuple of (passed, detail_message).
    """
    if endpoint_category not in THRESHOLDS:
        return False, f"Unknown endpoint_category: {endpoint_category}"

    thresholds = THRESHOLDS[endpoint_category]
    failures = []

    for percentile_key, max_value in thresholds.items():
        percentile = int(percentile_key[1:])
        actual = stats.get_response_time_percentile(percentile / 100.0) if stats.num_requests > 0 else 0

        if actual > max_value:
            failures.append(
                f"  {percentile_key.upper()}: {actual:.2f}ms > threshold {max_value}ms"
            )

    if failures:
        detail = (
            f"FAIL [{endpoint_category}] response time thresholds exceeded:\n"
            + "\n".join(failures)
        )
        return False, detail

    return True, f"PASS [{endpoint_category}] all response time thresholds met"
