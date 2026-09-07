"""Flow 视图部署适配器 — Phase 3。

PG 适配器经统一 PostgreSQLClient 防腐通道执行 CREATE OR REPLACE VIEW；
USE_MEMORY_STORAGE=1 时回退 Noop（仅记录，不触库），与存储工厂同一开关。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PostgresFlowViewDeployer:
    """把编译产物 DDL 部署到 PG 落地库（CREATE OR REPLACE 原子替换）。"""

    def __init__(self, client=None) -> None:
        # 延迟注入便于测试替身；生产由工厂默认构造 PostgreSQLClient
        self._client = client

    def deploy_view(self, view_sql: str) -> None:
        if self._client is None:
            from src.data_platform.storage.postgresql.client import PostgreSQLClient

            self._client = PostgreSQLClient()
        self._client.execute(view_sql)
        logger.info("flow view deployed: %.80s", view_sql.splitlines()[0])


class NoopFlowViewDeployer:
    """内存模式部署器：记录调用供断言，不触库（无 PG 契约可部署）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def deploy_view(self, view_sql: str) -> None:
        self.calls.append(view_sql)
