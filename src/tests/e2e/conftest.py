"""E2E test fixtures — verify all services are reachable before running frontend tests."""

import pytest
import requests

API_PREFIX = "/api/v1/medical-insurance-ai-agent"
BACKEND_URL = "http://127.0.0.1:8000"
PORTAL_URL = "http://127.0.0.1:3000"
ADMIN_URL = "http://127.0.0.1:3001"
EMBED_URL = "http://127.0.0.1:3002"

STARTUP_COMMANDS = (
    "# Startup commands:\n"
    "uvicorn src.runtime.api.app:create_app --host 127.0.0.1 --port 8000 --factory\n"
    "cd src/apps/portal && npm run dev\n"
    "cd src/apps/admin  && npm run dev\n"
    "cd src/apps/embed  && npm run dev"
)


def _check_service(url: str, name: str) -> bool:
    try:
        resp = requests.get(url, timeout=5)
        return resp.status_code < 500
    except requests.RequestException:
        return False


@pytest.fixture(scope="session")
def backend_health() -> str:
    """Verify backend is reachable. Skips all e2e tests if unavailable."""
    if not _check_service(f"{BACKEND_URL}/health", "backend"):
        pytest.skip(
            f"Backend at {BACKEND_URL} is not reachable.\n{STARTUP_COMMANDS}"
        )
    return BACKEND_URL


@pytest.fixture(scope="session")
def portal_health() -> str:
    if not _check_service(PORTAL_URL, "portal"):
        pytest.skip(
            f"Portal at {PORTAL_URL} is not reachable.\n{STARTUP_COMMANDS}"
        )
    return PORTAL_URL


@pytest.fixture(scope="session")
def admin_health() -> str:
    if not _check_service(ADMIN_URL, "admin"):
        pytest.skip(
            f"Admin at {ADMIN_URL} is not reachable.\n{STARTUP_COMMANDS}"
        )
    return ADMIN_URL


@pytest.fixture(scope="session")
def embed_health() -> str:
    if not _check_service(EMBED_URL, "embed"):
        pytest.skip(
            f"Embed at {EMBED_URL} is not reachable.\n{STARTUP_COMMANDS}"
        )
    return EMBED_URL


@pytest.fixture(scope="session")
def all_services(backend_health, portal_health, admin_health, embed_health):
    """Fixture that requires all four services to be reachable."""
    return {
        "backend": backend_health,
        "portal": portal_health,
        "admin": admin_health,
        "embed": embed_health,
    }
