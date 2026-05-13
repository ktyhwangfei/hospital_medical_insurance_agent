"""
PostgreSQL 提示词模板存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

PROMPT_TEMPLATES_TABLE = """
CREATE TABLE IF NOT EXISTS prompt_templates (
    template_id VARCHAR(128) PRIMARY KEY,
    template_name VARCHAR(256) NOT NULL,
    template_type VARCHAR(64) NOT NULL,
    scenario VARCHAR(64),
    role VARCHAR(64),
    system_prompt TEXT,
    user_prompt_template TEXT,
    variables JSONB DEFAULT '[]',
    output_format JSONB DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_prompts_scenario ON prompt_templates(scenario);
CREATE INDEX IF NOT EXISTS idx_prompts_role ON prompt_templates(role);
"""

SEED_PROMPT_TEMPLATES = [
    {
        "template_id": "pt-001",
        "template_name": "意图识别提示词",
        "template_type": "system",
        "scenario": "intent_detection",
        "role": "system",
        "system_prompt": "你是一个医保智能导办助手，负责识别用户的医保业务意图。",
        "variables": ["user_message", "patient_context"],
        "output_format": {"intent": "string", "confidence": "float", "entities": "dict"},
    },
    {
        "template_id": "pt-002",
        "template_name": "结算异常导办提示词",
        "template_type": "scenario",
        "scenario": "settlement_exception_guidance",
        "role": "cashier",
        "system_prompt": "你是一个医保结算异常导办专家，帮助收费员处理结算异常。",
        "variables": ["error_code", "patient_info", "knowledge"],
        "output_format": {"recommendation": "string", "responsible_role": "string", "steps": "list"},
    },
]


class PostgresPromptTemplateStore:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
            except Exception as e:
                logger.error(f"Failed to initialize prompt template store: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(PROMPT_TEMPLATES_TABLE)
            self._seed_data()
        except Exception as e:
            logger.error(f"Failed to ensure prompt template schema: {e}")
            raise

    def _seed_data(self) -> None:
        try:
            client = self._get_client()
            for item in SEED_PROMPT_TEMPLATES:
                sql = """
                    INSERT INTO prompt_templates (template_id, template_name, template_type, scenario, role, system_prompt, variables, output_format)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (template_id) DO UPDATE SET template_name = EXCLUDED.template_name, system_prompt = EXCLUDED.system_prompt
                """
                client.execute(sql, (
                    item["template_id"], item["template_name"], item["template_type"],
                    item["scenario"], item["role"], item["system_prompt"],
                    json.dumps(item["variables"]), json.dumps(item["output_format"])
                ))
        except Exception as e:
            logger.error(f"Failed to seed prompt templates: {e}")
            raise

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}
