"""政策知识管线元数据存储（PG）。

政策业务数据（事实/规则）入 Milvus，PG 只存产品/任务类元数据。
本 store 管理三张表：

- ``policy_schema_update_task``: 重新结构化任务（schema 演化的异步载体）
- ``policy_golden_sample``: 质量门禁黄金样本集（已审核规则抽样 + 人工锁定）
- ``policy_datasource``: 数据源注册表（多源：SQL Server ×N + Milvus ×1）

[来源: docs/steering/政策知识管线设计.md §3.4]
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.postgresql.semantic_registry_store import (
    SEMANTIC_REGISTRY_TRANSACTION_LOCK,
)

_SCHEMA = """
-- 重新结构化任务（加/改/删指标后，批量更新 policy_rules 的异步任务）
CREATE TABLE IF NOT EXISTS policy_schema_update_task (
    task_id VARCHAR(64) PRIMARY KEY,
    metric_code VARCHAR(256) NOT NULL,
    change_type VARCHAR(32) NOT NULL,            -- add | modify | remove
    strategy VARCHAR(32) NOT NULL,               -- incremental | full | soft_delete
    status VARCHAR(32) NOT NULL DEFAULT 'pending', -- pending | running | done | failed
    progress INTEGER NOT NULL DEFAULT 0,          -- 0-100
    total INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    golden_score JSONB DEFAULT '{}',              -- 质量门禁得分 {filling_rate, compliance_rate, consistency}
    schema_version INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_schema_task_status ON policy_schema_update_task(status);
CREATE INDEX IF NOT EXISTS idx_schema_task_metric ON policy_schema_update_task(metric_code);

-- 黄金样本集（质量门禁基准 + 提取回归测试集；从已审核规则抽样人工锁定）
CREATE TABLE IF NOT EXISTS policy_golden_sample (
    sample_id VARCHAR(64) PRIMARY KEY,
    fact_id VARCHAR(64) NOT NULL,                 -- 关联 Milvus policy_facts
    metric_code VARCHAR(256) NOT NULL,            -- 关联语义层指标
    expected_value TEXT,                           -- 人工锁定的期望值
    locked_by VARCHAR(64),
    locked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_golden_metric ON policy_golden_sample(metric_code);

-- 数据源注册表（多源：语义层取数与发现的统一数据源抽象）
CREATE TABLE IF NOT EXISTS policy_datasource (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    type VARCHAR(32) NOT NULL,                    -- sqlserver | milvus
    connection_config JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PolicyMetaStore:
    """政策知识管线元数据 CRUD。"""

    def __init__(self, database_url: Optional[str] = None) -> None:
        self._client = PostgreSQLClient(database_url)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._client.execute(_SCHEMA)

    @contextmanager
    def registry_transaction(self, registry_store: object):
        """让 schema 更新任务与语义指标共用同一 PostgreSQL 事务。"""
        with SEMANTIC_REGISTRY_TRANSACTION_LOCK:
            original_client = getattr(registry_store, "_client", None)
            setattr(registry_store, "_client", self._client)
            try:
                with self._client.transaction():
                    yield
            finally:
                setattr(registry_store, "_client", original_client)

    # ════════════════════ schema_update_task ════════════════════

    def create_task(
        self,
        metric_code: str,
        change_type: str,
        strategy: str,
        golden_score: Optional[dict] = None,
        schema_version: int = 1,
    ) -> dict[str, Any]:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        self._client.execute(
            """INSERT INTO policy_schema_update_task
               (task_id, metric_code, change_type, strategy, golden_score, schema_version)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (task_id, metric_code, change_type, strategy,
             json.dumps(golden_score or {}, ensure_ascii=False), schema_version),
        )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        rows = self._client.execute(
            "SELECT * FROM policy_schema_update_task WHERE task_id = %s", (task_id,)
        )
        return self._task_row(rows[0]) if rows else None

    def list_tasks(
        self, status: str = "", metric_code: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        conditions, params = [], []
        if status:
            conditions.append("status = %s"); params.append(status)
        if metric_code:
            conditions.append("metric_code = %s"); params.append(metric_code)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = self._client.execute(
            f"SELECT * FROM policy_schema_update_task {where} ORDER BY created_at DESC LIMIT %s",
            tuple(params),
        )
        return [self._task_row(r) for r in rows]

    def update_task_progress(
        self, task_id: str, processed: int, total: int, status: str = ""
    ) -> None:
        progress = int(processed * 100 / total) if total else 0
        sets = ["processed = %s", "total = %s", "progress = %s", "updated_at = %s"]
        params: list[Any] = [processed, total, progress, _now()]
        if status:
            sets.append("status = %s"); params.append(status)
            if status in ("done", "failed"):
                sets.append("finished_at = %s"); params.append(_now())
        params.append(task_id)
        self._client.execute(
            f"UPDATE policy_schema_update_task SET {', '.join(sets)} WHERE task_id = %s",
            tuple(params),
        )

    def fail_task(self, task_id: str, error: str) -> None:
        self._client.execute(
            """UPDATE policy_schema_update_task
               SET status = 'failed', error = %s, finished_at = %s, updated_at = %s
               WHERE task_id = %s""",
            (error[:2000], _now(), _now(), task_id),
        )

    @staticmethod
    def _task_row(row: dict) -> dict[str, Any]:
        gs = row.get("golden_score")
        if isinstance(gs, str):
            try:
                gs = json.loads(gs)
            except (json.JSONDecodeError, TypeError):
                gs = {}
        return {
            "task_id": row["task_id"],
            "metric_code": row["metric_code"],
            "change_type": row["change_type"],
            "strategy": row["strategy"],
            "status": row["status"],
            "progress": row.get("progress", 0),
            "total": row.get("total", 0),
            "processed": row.get("processed", 0),
            "golden_score": gs or {},
            "schema_version": row.get("schema_version", 1),
            "error": row.get("error"),
            "created_at": str(row["created_at"]) if row.get("created_at") else "",
            "finished_at": str(row["finished_at"]) if row.get("finished_at") else "",
        }

    # ════════════════════ golden_sample ════════════════════

    def add_golden_sample(
        self, fact_id: str, metric_code: str, expected_value: str, locked_by: str = ""
    ) -> dict[str, Any]:
        sample_id = f"gs_{uuid.uuid4().hex[:12]}"
        self._client.execute(
            """INSERT INTO policy_golden_sample
               (sample_id, fact_id, metric_code, expected_value, locked_by, locked_at)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (sample_id, fact_id, metric_code, expected_value, locked_by, _now()),
        )
        return self.get_golden_sample(sample_id)

    def list_golden_samples(self, metric_code: str = "") -> list[dict[str, Any]]:
        if metric_code:
            rows = self._client.execute(
                "SELECT * FROM policy_golden_sample WHERE metric_code = %s ORDER BY created_at",
                (metric_code,),
            )
        else:
            rows = self._client.execute(
                "SELECT * FROM policy_golden_sample ORDER BY created_at"
            )
        return [self._gs_row(r) for r in rows]

    def get_golden_sample(self, sample_id: str) -> Optional[dict[str, Any]]:
        rows = self._client.execute(
            "SELECT * FROM policy_golden_sample WHERE sample_id = %s", (sample_id,)
        )
        return self._gs_row(rows[0]) if rows else None

    def delete_golden_sample(self, sample_id: str) -> bool:
        rows = self._client.execute(
            "DELETE FROM policy_golden_sample WHERE sample_id = %s RETURNING sample_id",
            (sample_id,),
        )
        return len(rows) > 0

    @staticmethod
    def _gs_row(row: dict) -> dict[str, Any]:
        return {
            "sample_id": row["sample_id"],
            "fact_id": row["fact_id"],
            "metric_code": row["metric_code"],
            "expected_value": row.get("expected_value"),
            "locked_by": row.get("locked_by"),
            "locked_at": str(row["locked_at"]) if row.get("locked_at") else "",
        }

    # ════════════════════ datasource ════════════════════

    def register_datasource(
        self, name: str, ds_type: str, connection_config: dict, ds_id: str = ""
    ) -> dict[str, Any]:
        ds_id = ds_id or f"ds_{uuid.uuid4().hex[:12]}"
        self._client.execute(
            """INSERT INTO policy_datasource (id, name, type, connection_config)
               VALUES (%s, %s, %s, %s)""",
            (ds_id, name, ds_type, json.dumps(connection_config, ensure_ascii=False)),
        )
        return self.get_datasource(ds_id)

    def list_datasources(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE enabled = TRUE" if enabled_only else ""
        rows = self._client.execute(
            f"SELECT * FROM policy_datasource {where} ORDER BY created_at"
        )
        return [self._ds_row(r) for r in rows]

    def get_datasource(self, ds_id: str) -> Optional[dict[str, Any]]:
        rows = self._client.execute(
            "SELECT * FROM policy_datasource WHERE id = %s", (ds_id,)
        )
        return self._ds_row(rows[0]) if rows else None

    def toggle_datasource(self, ds_id: str, enabled: bool) -> None:
        self._client.execute(
            "UPDATE policy_datasource SET enabled = %s, updated_at = %s WHERE id = %s",
            (enabled, _now(), ds_id),
        )

    @staticmethod
    def _ds_row(row: dict) -> dict[str, Any]:
        cc = row.get("connection_config")
        if isinstance(cc, str):
            try:
                cc = json.loads(cc)
            except (json.JSONDecodeError, TypeError):
                cc = {}
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "connection_config": cc or {},
            "enabled": row.get("enabled", True),
            "created_at": str(row["created_at"]) if row.get("created_at") else "",
        }
