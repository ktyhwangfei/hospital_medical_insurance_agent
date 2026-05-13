"""
Error rate assertion module.

Validates that actual error rates during performance tests do not
exceed the AGENTS.md-defined tolerances for each endpoint category.
"""

from typing import Tuple

ERROR_RATE_TOLERANCE = {
    "health": 0.0,
    "readonly": 0.01,
    "crud": 0.02,
    "chat": 0.05,
    "stream": 0.05,
}


def check_error_rate(endpoint_category: str, stats) -> Tuple[bool, str]:
    """
    Compare actual error rate against the allowed tolerance.

    Args:
        endpoint_category: One of 'health', 'readonly', 'crud', 'chat', 'stream'.
        stats: Dict-like Locust stats object with num_requests and num_failures.

    Returns:
        Tuple of (passed, detail_message).
    """
    if endpoint_category not in ERROR_RATE_TOLERANCE:
        return False, f"Unknown endpoint_category: {endpoint_category}"

    tolerance = ERROR_RATE_TOLERANCE[endpoint_category]
    total = stats.num_requests

    if total == 0:
        return True, f"PASS [{endpoint_category}] no requests made (0 errors)"

    actual_rate = stats.num_failures / total

    if actual_rate > tolerance:
        return (
            False,
            f"FAIL [{endpoint_category}] error rate {actual_rate:.4f} "
            f"exceeds tolerance {tolerance} "
            f"({stats.num_failures}/{total} failures)",
        )

    return (
        True,
        f"PASS [{endpoint_category}] error rate {actual_rate:.4f} "
        f"within tolerance {tolerance} "
        f"({stats.num_failures}/{total} failures)",
    )
