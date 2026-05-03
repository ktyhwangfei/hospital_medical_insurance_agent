from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def build_client() -> TestClient:
    return TestClient(create_app())
