"""
PostgreSQL 规则解释存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

RULE_EXPLANATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS rule_explanations (
    rule_id VARCHAR(128) PRIMARY KEY,
    rule_name VARCHAR(256) NOT NULL,
    rule_category VARCHAR(64),
    source VARCHAR(128),
    description TEXT,
    explanation TEXT,
    applicable_scenarios JSONB DEFAULT '[]',
    references JSONB DEFAULT '[]',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rules_category ON rule_explanations(rule_category);
"""

SEED_RULE_EXPLANATIONS = [
    {
        "rule_id": "re-001",
        "rule_name": "费用上传完整性规则",
        "rule_category": "费用上传",
        "source": "医保结算规范",
        "description": "费用明细必须全部上传才能进行结算",
        "explanation": "根据医保结算规范，所有费用明细项目需在结算前完成上传。若存在未上传项目，结算状态将标记为失败，需补传后重新预结算。",
        "applicable_scenarios": ["settlement_exception"],
        "references": ["医保结算管理办法 第12条"],
    },
]


class PostgresRuleExplanationStore:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
            except Exception as e:
                logger.error(f"Failed to initialize rule explanation store: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(RULE_EXPLANATIONS_TABLE)
            self._seed_data()
        except Exception as e:
            logger.error(f"Failed to ensure rule explanations schema: {e}")
            raise

    def _seed_data(self) -> None:
        try:
            client = self._get_client()
            for item in SEED_RULE_EXPLANATIONS:
                sql = """
                    INSERT INTO rule_explanations (rule_id, rule_name, rule_category, source, description, explanation, applicable_scenarios, references)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (rule_id) DO UPDATE SET
                        rule_name = EXCLUDED.rule_name, rule_category = EXCLUDED.rule_category,
                        description = EXCLUDED.description, explanation = EXCLUDED.explanation
                """
                client.execute(sql, (
                    item["rule_id"], item["rule_name"], item["rule_category"], item["source"],
                    item["description"], item["explanation"],
                    json.dumps(item["applicable_scenarios"]), json.dumps(item["references"])
                ))
        except Exception as e:
            logger.error(f"Failed to seed rule explanations: {e}")
            raise

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}
