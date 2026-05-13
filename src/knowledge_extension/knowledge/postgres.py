"""
PostgreSQL 错误码知识库
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

# 表结构
ERROR_CODE_TABLE = """
CREATE TABLE IF NOT EXISTS error_code_knowledge (
    error_code VARCHAR(64) PRIMARY KEY,
    description TEXT,
    exception_type VARCHAR(128),
    responsible_role VARCHAR(64),
    recommendation TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# 种子数据
SEED_ERROR_CODES = [
    {
        'error_code': 'E-UPLOAD-001',
        'description': '费用明细未全部上传',
        'exception_type': '费用上传异常',
        'responsible_role': '收费员',
        'recommendation': '请核对费用上传状态，补传失败明细后重新预结算。',
    },
]


class PostgresKnowledgeStore:
    """PostgreSQL 错误码知识库实现"""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
                logger.info("PostgreSQL knowledge store initialized")
            except Exception as e:
                logger.error(f"Failed to initialize PostgreSQL knowledge store: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(ERROR_CODE_TABLE)
            logger.debug("Error code table ensured")
        except Exception as e:
            logger.error(f"Failed to ensure error code table: {e}")
            raise

    def seed_data(self) -> None:
        """加载种子数据"""
        try:
            client = self._get_client()
            for item in SEED_ERROR_CODES:
                sql = """
                    INSERT INTO error_code_knowledge (error_code, description, exception_type, responsible_role, recommendation)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (error_code) DO UPDATE SET
                        description = EXCLUDED.description,
                        exception_type = EXCLUDED.exception_type,
                        responsible_role = EXCLUDED.responsible_role,
                        recommendation = EXCLUDED.recommendation
                """
                client.execute(sql, (
                    item['error_code'],
                    item['description'],
                    item['exception_type'],
                    item['responsible_role'],
                    item['recommendation'],
                ))
            logger.info("Error code seed data loaded")
        except Exception as e:
            logger.error(f"Failed to load error code seed data: {e}")
            raise

    def get_error_code(self, error_code: str) -> dict[str, Any] | None:
        """获取错误码信息"""
        try:
            client = self._get_client()
            sql = """
                SELECT error_code, description, exception_type, responsible_role, recommendation
                FROM error_code_knowledge
                WHERE error_code = %s
            """
            rows = client.execute(sql, (error_code,))
            if not rows:
                return None
            row = rows[0]
            return {
                'error_code': row['error_code'],
                'description': row['description'],
                'exception_type': row['exception_type'],
                'responsible_role': row['responsible_role'],
                'recommendation': row['recommendation'],
            }
        except Exception as e:
            logger.error(f"Failed to get error code {error_code}: {e}")
            raise

    def list_error_codes(self) -> list[dict[str, Any]]:
        """列出所有错误码"""
        try:
            client = self._get_client()
            sql = "SELECT error_code, description, exception_type, responsible_role, recommendation FROM error_code_knowledge ORDER BY error_code"
            rows = client.execute(sql)
            return [
                {
                    'error_code': row['error_code'],
                    'description': row['description'],
                    'exception_type': row['exception_type'],
                    'responsible_role': row['responsible_role'],
                    'recommendation': row['recommendation'],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to list error codes: {e}")
            raise

    def health(self) -> dict[str, Any]:
        try:
            client = self._get_client()
            client.execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}
