from fastapi.testclient import TestClient


def build_client() -> TestClient:
    from src.runtime.api.app import create_app

    return TestClient(create_app())
