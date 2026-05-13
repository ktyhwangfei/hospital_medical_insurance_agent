"""
PostgreSQL 申诉模板存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

APPEAL_TEMPLATES_TABLE = """
CREATE TABLE IF NOT EXISTS appeal_templates (
    template_id VARCHAR(128) PRIMARY KEY,
    template_name VARCHAR(256) NOT NULL,
    template_type VARCHAR(64),
    denial_reason_pattern VARCHAR(256),
    content TEXT NOT NULL,
    required_evidence JSONB DEFAULT '[]',
    applicable_scenarios JSONB DEFAULT '[]',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_appeal_templates_type ON appeal_templates(template_type);
"""

SEED_APPEAL_TEMPLATES = [
    {
        "template_id": "at-001",
        "template_name": "费用上传异常申诉模板",
        "template_type": "appeal",
        "denial_reason_pattern": "费用上传",
        "content": "申诉事由：因费用上传异常导致结算失败。\n处理经过：已核对费用明细，补传缺失数据。\n申诉依据：根据医保结算管理办法...\n请求：撤销拒付决定，重新结算。",
        "required_evidence": ["费用明细清单", "上传日志截图"],
        "applicable_scenarios": ["settlement_exception"],
    },
]


class PostgresAppealTemplateStore:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
            except Exception as e:
                logger.error(f"Failed to initialize appeal template store: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(APPEAL_TEMPLATES_TABLE)
            self._seed_data()
        except Exception as e:
            logger.error(f"Failed to ensure appeal template schema: {e}")
            raise

    def _seed_data(self) -> None:
        try:
            client = self._get_client()
            for item in SEED_APPEAL_TEMPLATES:
                sql = """
                    INSERT INTO appeal_templates (template_id, template_name, template_type, denial_reason_pattern, content, required_evidence, applicable_scenarios)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (template_id) DO UPDATE SET template_name = EXCLUDED.template_name, content = EXCLUDED.content
                """
                client.execute(sql, (
                    item["template_id"], item["template_name"], item["template_type"],
                    item["denial_reason_pattern"], item["content"],
                    json.dumps(item["required_evidence"]), json.dumps(item["applicable_scenarios"])
                ))
        except Exception as e:
            logger.error(f"Failed to seed appeal templates: {e}")
            raise

    def list_templates(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        """返回申诉模板列表，默认只返回启用的模板。"""
        try:
            client = self._get_client()
            sql = "SELECT * FROM appeal_templates"
            params: tuple = ()
            if enabled_only:
                sql += " WHERE enabled = %s"
                params = (True,)
            sql += " ORDER BY template_id"
            return client.execute(sql, params)
        except Exception as e:
            logger.error(f"Failed to list appeal templates: {e}")
            return []

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}
