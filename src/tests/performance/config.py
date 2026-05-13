"""
Performance baseline configuration for Locust-based stress tests.

Defines target RPS, response time thresholds, error rate tolerances,
and load generation parameters matching AGENTS.md specifications.
"""

API_PREFIX = "/api/v1/medical-insurance-ai-agent"

TARGET_RPS = {
    "business": 10,
    "knowledge": 30,
    "model": 30,
    "skill": 30,
    "mcp": 30,
}

RESPONSE_TIME_THRESHOLDS = {
    "health": {"p50": 50, "p95": 100, "p99": 200},
    "readonly": {"p50": 100, "p95": 300, "p99": 500},
    "crud": {"p50": 150, "p95": 500, "p99": 1000},
    "chat": {"p50": 500, "p95": 2000, "p99": 5000},
    "stream": {"p50": 1000, "p95": 3000, "p99": 8000},
}

ERROR_RATE_TOLERANCE = {
    "health": 0.0,
    "readonly": 0.01,
    "crud": 0.02,
    "chat": 0.05,
    "stream": 0.05,
}

LOAD_CONFIG = {
    "users": 50,
    "spawn_rate": 5,
    "run_time": 60,
}
