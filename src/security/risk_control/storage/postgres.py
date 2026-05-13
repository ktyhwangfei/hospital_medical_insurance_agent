"""
PostgreSQL 风控存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

RISK_CONTROL_TABLES = """
CREATE TABLE IF NOT EXISTS risk_control_rules (
    rule_id VARCHAR(128) PRIMARY KEY,
    rule_name VARCHAR(256) NOT NULL,
    action_pattern TEXT NOT NULL,
    risk_level VARCHAR(32) DEFAULT 'HIGH',
    block_reason TEXT,
    recommendation TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS risk_control_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(64) UNIQUE,
    event_type VARCHAR(64) NOT NULL DEFAULT 'risk_detected',
    rule_id VARCHAR(128),
    user_id VARCHAR(64),
    patient_id VARCHAR(64),
    encounter_id VARCHAR(64),
    role VARCHAR(32),
    action TEXT,
    risk_level VARCHAR(32) NOT NULL DEFAULT 'HIGH',
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    result VARCHAR(32),
    reason TEXT,
    message_preview TEXT,
    workflow_id VARCHAR(128),
    context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_risk_events_rule ON risk_control_events(rule_id);
CREATE INDEX IF NOT EXISTS idx_risk_events_created ON risk_control_events(created_at);
"""


class PostgresRiskControlStorage:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._client.execute(RISK_CONTROL_TABLES)
                logger.info("PostgreSQL risk control storage initialized")
            except Exception as e:
                logger.error(f"Failed to initialize risk control storage: {e}")
                raise
        return self._client

    def save_rule(self, rule: dict[str, Any]) -> None:
        client = self._get_client()
        sql = """
            INSERT INTO risk_control_rules (rule_id, rule_name, action_pattern, risk_level, block_reason, recommendation, enabled, metadata, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (rule_id) DO UPDATE SET
                rule_name=EXCLUDED.rule_name, action_pattern=EXCLUDED.action_pattern,
                risk_level=EXCLUDED.risk_level, block_reason=EXCLUDED.block_reason,
                recommendation=EXCLUDED.recommendation, enabled=EXCLUDED.enabled,
                metadata=EXCLUDED.metadata, updated_at=CURRENT_TIMESTAMP
        """
        client.execute(sql, (
            rule['rule_id'], rule['rule_name'], rule['action_pattern'],
            rule.get('risk_level', 'HIGH'), rule.get('block_reason'),
            rule.get('recommendation'), rule.get('enabled', True),
            json.dumps(rule.get('metadata', {})),
        ))

    def record_event(self, event: dict[str, Any]) -> None:
        client = self._get_client()
        sql = """
            INSERT INTO risk_control_events (rule_id, event_type, user_id, patient_id, encounter_id, action_pattern, risk_level, blocked, reason, result, workflow_id, context)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """
        client.execute(sql, (
            event.get('rule_id'), event.get('event_type', 'blocked'),
            event.get('user_id'), event.get('patient_id'), event.get('encounter_id'),
            event.get('action_pattern'), event.get('risk_level', 'HIGH'),
            event.get('blocked', True), event.get('reason'),
            event.get('result'), event.get('workflow_id'),
            json.dumps(event.get('context', {})),
        ))

    def list_rules(self) -> list[dict[str, Any]]:
        return self._get_client().execute("SELECT * FROM risk_control_rules WHERE enabled=true ORDER BY rule_id")

    def get_events(self, workflow_id: str) -> list[dict[str, Any]]:
        return self._get_client().execute("SELECT * FROM risk_control_events WHERE workflow_id=%s ORDER BY created_at DESC", (workflow_id,))

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
