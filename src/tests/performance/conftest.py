"""
Pytest conftest for performance tests.

Provides a session-scoped fixture that verifies the backend API is reachable
before running any performance tests. Skips the entire suite if the backend
is not available, with a descriptive message.
"""

import pytest
import requests

from src.tests.performance.config import (
    API_PREFIX,
    LOAD_CONFIG,
    RESPONSE_TIME_THRESHOLDS,
    TARGET_RPS,
)


@pytest.fixture(scope="session")
def backend_health_check():
    """Verify that the backend API is reachable before running performance tests."""
    health_url = "http://127.0.0.1:8000/health"
    try:
        resp = requests.get(health_url, timeout=5)
        resp.raise_for_status()
    except requests.ConnectionError:
        pytest.skip(
            f"Backend not reachable at {health_url}. "
            "Start the server with: uvicorn src.runtime.api.app:create_app "
            "--host 127.0.0.1 --port 8000 --factory --reload"
        )
    except requests.Timeout:
        pytest.skip(
            f"Backend health check timed out at {health_url}. "
            "Ensure the server is running and accessible."
        )
    except requests.HTTPError as e:
        pytest.skip(
            f"Backend health check returned error: {e}. "
            "The server may be running but unhealthy."
        )

    print(f"\nBackend healthy: {resp.json()}")
    print(f"API Prefix: {API_PREFIX}")
    print(f"Target RPS: {TARGET_RPS}")
    print(f"Response Time Thresholds: {RESPONSE_TIME_THRESHOLDS}")
    print(f"Load Config: {LOAD_CONFIG}")
