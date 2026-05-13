"""
Throughput assertion module.

Validates that actual requests per second during performance tests
meet the AGENTS.md-defined minimum RPS for each service domain.
"""

from typing import Tuple

MIN_RPS = {
    "business": 10,
    "knowledge": 30,
    "model": 30,
    "skill": 30,
    "mcp": 30,
}


def check_throughput(domain: str, stats) -> Tuple[bool, str]:
    """
    Compare actual RPS against the minimum required RPS.

    Args:
        domain: One of 'business', 'knowledge', 'model', 'skill', 'mcp'.
        stats: Dict-like Locust stats object with total_rps attribute.

    Returns:
        Tuple of (passed, detail_message).
    """
    if domain not in MIN_RPS:
        return False, f"Unknown domain: {domain}"

    min_rps = MIN_RPS[domain]
    actual_rps = getattr(stats, "total_rps", 0) or 0

    if actual_rps < min_rps:
        return (
            False,
            f"FAIL [{domain}] throughput {actual_rps:.2f} RPS "
            f"below minimum {min_rps} RPS",
        )

    return (
        True,
        f"PASS [{domain}] throughput {actual_rps:.2f} RPS "
        f"meets minimum {min_rps} RPS",
    )
