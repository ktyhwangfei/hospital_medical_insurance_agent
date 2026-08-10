"""验证 /health 真实反映数据源就绪状态（区分"进程存活"与"服务就绪"）。

背景：后端连不上 PostgreSQL 时会回退内存存储，但进程仍存活。此前 /health 恒返回
200，导致 ws.ps1 / start-servers.ps1 把"内存残废态"误报为健康。现在 /health 依据
factory.DATA_SOURCE_READY 判定：未连通真实数据源时返回 503。
"""
import os

os.environ["USE_MEMORY_STORAGE"] = "1"

from unittest.mock import patch

from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.data_platform.data_access import factory


def test_health_503_when_data_source_not_ready():
    # 回退内存时 DATA_SOURCE_READY 保持 False，/health 应回 503，让启动脚本判定未就绪。
    with patch("psycopg.connect", side_effect=Exception("no pg")):
        client = TestClient(create_app())

    assert factory.DATA_SOURCE_READY is False
    response = client.get("/health")
    assert response.status_code == 503


def test_health_200_when_data_source_ready(monkeypatch):
    # 真实 PostgreSQL 连通并播种成功后 DATA_SOURCE_READY=True，/health 回 200。
    with patch("psycopg.connect", side_effect=Exception("no pg")):
        client = TestClient(create_app())
    monkeypatch.setattr(factory, "DATA_SOURCE_READY", True)

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
