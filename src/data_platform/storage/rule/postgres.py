"""
PostgreSQL 规则解释存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

RULE_TABLE = """
CREATE TABLE IF NOT EXISTS rule_explanations (
    rule_id VARCHAR(128) PRIMARY KEY,
    rule_name VARCHAR(256) NOT NULL,
    category VARCHAR(64),
    scenario VARCHAR(64),
    rule_content TEXT,
    explanation TEXT,
    applicable_roles JSONB DEFAULT '[]',
    risk_level VARCHAR(32) DEFAULT 'LOW',
    effective_date DATE,
    enabled BOOLEAN DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rules_category ON rule_explanations(category);
CREATE INDEX IF NOT EXISTS idx_rules_scenario ON rule_explanations(scenario);
"""


class PostgresRuleStorage:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._client.execute(RULE_TABLE)
                logger.info("PostgreSQL rule storage initialized")
            except Exception as e:
                logger.error(f"Failed to initialize rule storage: {e}")
                raise
        return self._client

    def save_rule(self, rule: dict[str, Any]) -> None:
        client = self._get_client()
        sql = """
            INSERT INTO rule_explanations (rule_id, rule_name, category, scenario, rule_content, explanation, applicable_roles, risk_level, effective_date, enabled, metadata, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (rule_id) DO UPDATE SET
                rule_name=EXCLUDED.rule_name, category=EXCLUDED.category, scenario=EXCLUDED.scenario,
                rule_content=EXCLUDED.rule_content, explanation=EXCLUDED.explanation,
                applicable_roles=EXCLUDED.applicable_roles, risk_level=EXCLUDED.risk_level,
                effective_date=EXCLUDED.effective_date, enabled=EXCLUDED.enabled,
                metadata=EXCLUDED.metadata, updated_at=CURRENT_TIMESTAMP
        """
        client.execute(sql, (
            rule['rule_id'], rule['rule_name'], rule.get('category'), rule.get('scenario'),
            rule.get('rule_content'), rule.get('explanation'),
            json.dumps(rule.get('applicable_roles', [])),
            rule.get('risk_level', 'LOW'), rule.get('effective_date'),
            rule.get('enabled', True), json.dumps(rule.get('metadata', {})),
        ))

    def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        client = self._get_client()
        rows = client.execute("SELECT * FROM rule_explanations WHERE rule_id = %s", (rule_id,))
        return rows[0] if rows else None

    def list_rules(self, scenario: str | None = None) -> list[dict[str, Any]]:
        client = self._get_client()
        if scenario:
            return client.execute("SELECT * FROM rule_explanations WHERE scenario=%s AND enabled=true ORDER BY rule_id", (scenario,))
        return client.execute("SELECT * FROM rule_explanations WHERE enabled=true ORDER BY rule_id")

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            logger.error(f"Rule storage health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}
