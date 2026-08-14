import os

# T1/T2 测试默认使用内存存储，避免收集期连接外部数据库。
os.environ.setdefault("USE_MEMORY_STORAGE", "1")

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def build_client() -> TestClient:
    return TestClient(create_app())
