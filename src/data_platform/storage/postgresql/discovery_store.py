"""Discovery 数据持久化存储（PostgreSQL）。

替代 semantic_routes.py 中的内存字典，确保服务重启后数据不丢失。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

_DISCOVERY_SCHEMA = """
-- 扫描任务：记录每次扫描的配置、状态和结果
CREATE TABLE IF NOT EXISTS discovery_scan_tasks (
    task_id VARCHAR(64) PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    source_config JSONB DEFAULT '{}'::jsonb,
    sample_limit INTEGER DEFAULT 10000,
    result_data JSONB,
    tables_count INTEGER DEFAULT 0,
    fields_count INTEGER DEFAULT 0,
    mapped_fields INTEGER DEFAULT 0,
    unmapped_fields INTEGER DEFAULT 0,
    new_found INTEGER DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_discovery_tasks_status ON discovery_scan_tasks(status);
CREATE INDEX IF NOT EXISTS idx_discovery_tasks_started ON discovery_scan_tasks(started_at DESC);

-- 字段中文释义（Excel 导入）
CREATE TABLE IF NOT EXISTS discovery_field_descriptions (
    id SERIAL PRIMARY KEY,
    lookup_key VARCHAR(256) UNIQUE NOT NULL,
    table_name VARCHAR(256) NOT NULL,
    field_name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL,
    is_primary_key BOOLEAN DEFAULT FALSE,
    remark TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_discovery_descriptions_key ON discovery_field_descriptions(lookup_key);

-- 表级检查点：记录每张表的列结构哈希和缓存结果，支持增量扫描
CREATE TABLE IF NOT EXISTS discovery_table_checkpoints (
    table_name VARCHAR(256) NOT NULL,
    schema_name VARCHAR(128) NOT NULL DEFAULT 'dbo',
    column_hash VARCHAR(64) NOT NULL,
    total_rows INTEGER DEFAULT 0,
    fields_count INTEGER DEFAULT 0,
    last_scanned_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    result_snapshot JSONB,
    error_message TEXT,
    PRIMARY KEY (table_name, schema_name)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryStore:
    """Discovery 数据 PostgreSQL 持久化存储。"""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            self._ensure_schema()
            logger.info("DiscoveryStore: PostgreSQL 初始化完成")
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(_DISCOVERY_SCHEMA)
            # 兼容旧表：new_found 列可能不存在（旧版 DDL 无此列）
            try:
                self._client.execute(
                    "ALTER TABLE discovery_scan_tasks ADD COLUMN IF NOT EXISTS new_found INTEGER DEFAULT 0"
                )
            except Exception:
                # IF NOT EXISTS 可能在旧版 PG 上不支持，回退到 DO 块
                try:
                    self._client.execute(
                        """DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'discovery_scan_tasks' AND column_name = 'new_found'
                            ) THEN
                                ALTER TABLE discovery_scan_tasks ADD COLUMN new_found INTEGER DEFAULT 0;
                            END IF;
                        END $$;"""
                    )
                except Exception:
                    pass  # 两次尝试都失败则忽略，UPDATE 时用 try/except 兜底
            logger.debug("DiscoveryStore: 表结构已确认")
        except Exception as e:
            logger.error("DiscoveryStore: 建表失败 — %s", e)
            raise

    # ── 扫描任务 ──────────────────────────────────────────────────

    def create_task(self, task_id: str, source_config: dict, sample_limit: int) -> None:
        client = self._get_client()
        client.execute(
            """INSERT INTO discovery_scan_tasks
               (task_id, status, source_config, sample_limit, started_at)
               VALUES (%s, 'pending', %s, %s, %s)""",
            (task_id, json.dumps(source_config, ensure_ascii=False), sample_limit, _now()),
        )

    def update_task_result(self, task_id: str, result: dict, tables_count: int,
                           fields_count: int, mapped_fields: int, unmapped_fields: int,
                           new_found: int = 0) -> None:
        client = self._get_client()
        try:
            client.execute(
                """UPDATE discovery_scan_tasks
                   SET status = 'completed',
                       result_data = %s,
                       tables_count = %s,
                       fields_count = %s,
                       mapped_fields = %s,
                       unmapped_fields = %s,
                       new_found = %s,
                       completed_at = %s
                   WHERE task_id = %s""",
                (
                    json.dumps(result, ensure_ascii=False, default=str),
                    tables_count, fields_count, mapped_fields, unmapped_fields,
                    new_found,
                    _now(), task_id,
                ),
            )
        except Exception:
            # 兼容：如果 new_found 列不存在则回退
            client.execute(
                """UPDATE discovery_scan_tasks
                   SET status = 'completed',
                       result_data = %s,
                       tables_count = %s,
                       fields_count = %s,
                       mapped_fields = %s,
                       unmapped_fields = %s,
                       completed_at = %s
                   WHERE task_id = %s""",
                (
                    json.dumps(result, ensure_ascii=False, default=str),
                    tables_count, fields_count, mapped_fields, unmapped_fields,
                    _now(), task_id,
                ),
            )
        logger.info("DiscoveryStore: task %s 结果已持久化 (%d 表, %d 字段, %d 新增)",
                    task_id, tables_count, fields_count, new_found)

    def update_task_error(self, task_id: str, error_message: str) -> None:
        client = self._get_client()
        client.execute(
            """UPDATE discovery_scan_tasks
               SET status = 'failed', error_message = %s, completed_at = %s
               WHERE task_id = %s""",
            (error_message, _now(), task_id),
        )

    def get_task(self, task_id: str) -> dict | None:
        client = self._get_client()
        rows = client.execute(
            "SELECT * FROM discovery_scan_tasks WHERE task_id = %s", (task_id,)
        )
        return rows[0] if rows else None

    def get_latest_completed_result(self) -> dict | None:
        """获取最近一次成功扫描的完整结果数据。"""
        client = self._get_client()
        rows = client.execute(
            """SELECT * FROM discovery_scan_tasks
               WHERE status = 'completed' AND result_data IS NOT NULL
               ORDER BY completed_at DESC LIMIT 1"""
        )
        if not rows:
            return None
        row = rows[0]
        result = row.get("result_data")
        if isinstance(result, str):
            result = json.loads(result)
        return result

    def get_latest_result(self) -> dict | None:
        """获取最近一次成功扫描的原始字段数据（兼容旧接口）。"""
        return self.get_latest_completed_result()

    # ── 扫描历史 ──────────────────────────────────────────────────

    def get_scan_history(self, limit: int = 20) -> list[dict]:
        client = self._get_client()
        rows = client.execute(
            """SELECT task_id as scan_id, started_at, completed_at,
                      status, tables_count as tables_scanned,
                      unmapped_fields as unmapped_found,
                      COALESCE(new_found, unmapped_fields) as new_found
               FROM discovery_scan_tasks
               WHERE status IN ('completed', 'failed')
               ORDER BY started_at DESC LIMIT %s""",
            (limit,),
        )
        history: list[dict] = []
        for row in rows:
            started = row.get("started_at")
            completed = row.get("completed_at")
            duration = None
            if started and completed:
                if hasattr(started, "isoformat"):
                    started_str = started.isoformat()
                else:
                    started_str = str(started)
                if hasattr(completed, "isoformat"):
                    completed_str = completed.isoformat()
                else:
                    completed_str = str(completed)
                try:
                    s_dt = datetime.fromisoformat(started_str.replace("Z", "+00:00"))
                    c_dt = datetime.fromisoformat(completed_str.replace("Z", "+00:00"))
                    duration = (c_dt - s_dt).total_seconds()
                except Exception:
                    pass

            history.append({
                "scan_id": row["scan_id"],
                "started_at": started.isoformat() if hasattr(started, "isoformat") else str(started) if started else None,
                "duration_seconds": duration,
                "status": row["status"],
                "tables_scanned": row.get("tables_scanned", 0),
                "unmapped_found": row.get("unmapped_found", 0),
                "new_found": row.get("new_found", 0),
            })
        return history

    # ── 字段中文释义（Excel 导入） ────────────────────────────────

    def save_field_description(self, table_name: str, field_name: str,
                               description: str, is_primary_key: bool = False,
                               remark: str | None = None) -> None:
        client = self._get_client()
        lookup_key = f"{table_name}:{field_name}".lower()
        client.execute(
            """INSERT INTO discovery_field_descriptions
               (lookup_key, table_name, field_name, description, is_primary_key, remark)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (lookup_key) DO UPDATE SET
                   table_name = EXCLUDED.table_name,
                   field_name = EXCLUDED.field_name,
                   description = EXCLUDED.description,
                   is_primary_key = EXCLUDED.is_primary_key,
                   remark = EXCLUDED.remark""",
            (lookup_key, table_name, field_name, description, is_primary_key, remark),
        )

    def get_field_description(self, table_name: str, field_name: str) -> dict | None:
        """获取单个字段的描述信息。返回 {description, is_primary_key, remark} 或 None。"""
        client = self._get_client()
        lookup_key = f"{table_name}:{field_name}".lower()
        rows = client.execute(
            "SELECT * FROM discovery_field_descriptions WHERE lookup_key = %s",
            (lookup_key,),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "description": r.get("description"),
            "is_primary_key": r.get("is_primary_key", False),
            "remark": r.get("remark"),
        }

    def get_field_descriptions_count(self) -> int:
        client = self._get_client()
        rows = client.execute("SELECT COUNT(*) as cnt FROM discovery_field_descriptions")
        return rows[0]["cnt"] if rows else 0

    def get_scanned_table_names(self) -> set[str]:
        """从最近一次扫描结果中提取已扫描的表名集合。"""
        result = self.get_latest_completed_result()
        if not result:
            return set()
        tables = result.get("tables", [])
        if isinstance(tables, list):
            return set(tables)
        return set()

    def get_previously_scanned_fields(self, exclude_task_id: str | None = None) -> set[str]:
        """获取历史扫描中已出现过的「表名:字段名」集合（排除当前任务）。

        用于判断当前扫描中哪些字段是真正的新增字段。
        """
        client = self._get_client()
        if exclude_task_id:
            rows = client.execute(
                """SELECT result_data FROM discovery_scan_tasks
                   WHERE status = 'completed' AND result_data IS NOT NULL AND task_id != %s
                   ORDER BY completed_at DESC""",
                (exclude_task_id,),
            )
        else:
            rows = client.execute(
                """SELECT result_data FROM discovery_scan_tasks
                   WHERE status = 'completed' AND result_data IS NOT NULL
                   ORDER BY completed_at DESC"""
            )
        seen: set[str] = set()
        for row in rows:
            result = row.get("result_data")
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except Exception:
                    continue
            if not result:
                continue
            for f in result.get("fields", []):
                key = f"{f.get('table_name', '')}:{f.get('field_name', '')}".lower()
                if key:
                    seen.add(key)
        logger.info("DiscoveryStore: get_previously_scanned_fields → %d 个历史字段（排除 %s）",
                    len(seen), exclude_task_id or "无")
        return seen

    # ── 表级检查点（增量扫描） ──────────────────────────────────

    def get_table_checkpoint(self, table_name: str, schema_name: str = "dbo") -> dict | None:
        """获取单表的检查点信息。返回 None 表示该表从未被扫描过。"""
        client = self._get_client()
        rows = client.execute(
            """SELECT * FROM discovery_table_checkpoints
               WHERE table_name = %s AND schema_name = %s""",
            (table_name, schema_name),
        )
        if not rows:
            return None
        r = rows[0]
        snap = r.get("result_snapshot")
        if isinstance(snap, str):
            try:
                snap = json.loads(snap)
            except Exception:
                snap = None
        return {
            "table_name": r["table_name"],
            "schema_name": r.get("schema_name", "dbo"),
            "column_hash": r["column_hash"],
            "total_rows": r.get("total_rows", 0),
            "fields_count": r.get("fields_count", 0),
            "result_snapshot": snap,
        }

    def save_table_checkpoint(self, table_name: str, schema_name: str,
                              column_hash: str, total_rows: int,
                              fields_count: int, result_snapshot: dict,
                              error_message: str | None = None) -> None:
        """保存/更新单表的检查点（UPSERT）。"""
        client = self._get_client()
        client.execute(
            """INSERT INTO discovery_table_checkpoints
               (table_name, schema_name, column_hash, total_rows, fields_count, result_snapshot, error_message, last_scanned_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
               ON CONFLICT (table_name, schema_name) DO UPDATE SET
                   column_hash = EXCLUDED.column_hash,
                   total_rows = EXCLUDED.total_rows,
                   fields_count = EXCLUDED.fields_count,
                   result_snapshot = EXCLUDED.result_snapshot,
                   error_message = EXCLUDED.error_message,
                   last_scanned_at = CURRENT_TIMESTAMP""",
            (
                table_name, schema_name, column_hash, total_rows, fields_count,
                json.dumps(result_snapshot, ensure_ascii=False, default=str),
                error_message,
            ),
        )
