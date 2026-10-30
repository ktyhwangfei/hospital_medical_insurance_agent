import os

from fastapi.testclient import TestClient

# 测试默认不调用模型；需要模型行为的用例自行 monkeypatch.setenv('FEE_EXPLANATION_MODE', ...)。
os.environ.setdefault("FEE_EXPLANATION_MODE", "deterministic")


def build_client() -> TestClient:
    from src.runtime.api.app import create_app

    return TestClient(create_app())
