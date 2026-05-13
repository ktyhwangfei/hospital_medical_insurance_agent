"""
PostgreSQL 风控事件存储

⚠️ 已废弃 (DEPRECATED) — 此文件是 event_store 的早期实现，已被
src/security/risk_control/storage/postgres.py（PostgresRiskControlStorage）取代。
两者均通过 PostgreSQLClient 操作相同的 risk_control_rules / risk_control_events 表，
但 storage/postgres.py 提供了更完整的方法集（save_rule / list_rules / record_event / get_events / health）。

当前 active code 不再 import 本模块，保留仅作参考。
"""
import json
import logging
from datetime import UTC, datetime
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

RISK_CONTROL_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS risk_control_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) NOT NULL UNIQUE,
    event_type VARCHAR(64) NOT NULL,
    user_id VARCHAR(64),
    patient_id VARCHAR(64),
    encounter_id VARCHAR(64),
    action VARCHAR(128),
    risk_level VARCHAR(32) NOT NULL,
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_risk_events_user ON risk_control_events(user_id);
CREATE INDEX IF NOT EXISTS idx_risk_events_patient ON risk_control_events(patient_id);
CREATE INDEX IF NOT EXISTS idx_risk_events_created ON risk_control_events(created_at);
"""

# 种子数据
SEED_RISK_RULES = [
    {
        "rule_id": "rcr-001",
        "rule_name": "正式结算拦截",
        "action_pattern": "正式结算",
        "risk_level": "HIGH",
        "description": "正式结算为高风险动作，需人工确认",
    },
    {
        "rule_id": "rcr-002",
        "rule_name": "退费拦截",
        "action_pattern": "退费",
        "risk_level": "HIGH",
        "description": "退费为高风险动作，需人工确认",
    },
    {
        "rule_id": "rcr-003",
        "rule_name": "冲正拦截",
        "action_pattern": "冲正",
        "risk_level": "HIGH",
        "description": "冲正为高风险动作，需人工确认",
    },
]

RISK_CONTROL_RULES_TABLE = """
CREATE TABLE IF NOT EXISTS risk_control_rules (
    rule_id VARCHAR(64) PRIMARY KEY,
    rule_name VARCHAR(128) NOT NULL,
    action_pattern VARCHAR(256) NOT NULL,
    risk_level VARCHAR(32) NOT NULL DEFAULT 'HIGH',
    description TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class PostgresRiskEventStore:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
                logger.info("PostgreSQL risk event store initialized")
            except Exception as e:
                logger.error(f"Failed to initialize risk event store: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(RISK_CONTROL_EVENTS_TABLE)
            self._client.execute(RISK_CONTROL_RULES_TABLE)
            self._seed_rules()
        except Exception as e:
            logger.error(f"Failed to ensure risk control schema: {e}")
            raise

    def _seed_rules(self) -> None:
        try:
            client = self._get_client()
            for rule in SEED_RISK_RULES:
                sql = """
                    INSERT INTO risk_control_rules (rule_id, rule_name, action_pattern, risk_level, description)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (rule_id) DO UPDATE SET
                        rule_name = EXCLUDED.rule_name,
                        action_pattern = EXCLUDED.action_pattern,
                        risk_level = EXCLUDED.risk_level,
                        description = EXCLUDED.description
                """
                client.execute(sql, (rule["rule_id"], rule["rule_name"], rule["action_pattern"], rule["risk_level"], rule["description"]))
            logger.info("Risk control rules seeded")
        except Exception as e:
            logger.error(f"Failed to seed risk rules: {e}")
            raise

    def record_event(self, event_id: str, event_type: str, risk_level: str, blocked: bool = False, **kwargs) -> dict:
        try:
            client = self._get_client()
            now = datetime.now(UTC).isoformat()
            sql = """
                INSERT INTO risk_control_events (event_id, event_type, user_id, patient_id, encounter_id, action, risk_level, blocked, reason, context)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            client.execute(sql, (
                event_id, event_type,
                kwargs.get("user_id"), kwargs.get("patient_id"), kwargs.get("encounter_id"),
                kwargs.get("action"), risk_level, blocked,
                kwargs.get("reason"), json.dumps(kwargs.get("context", {}))
            ))
            return {"event_id": event_id, "recorded": True}
        except Exception as e:
            logger.error(f"Failed to record event {event_id}: {e}")
            return {"event_id": event_id, "recorded": False, "error": str(e)}

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}
