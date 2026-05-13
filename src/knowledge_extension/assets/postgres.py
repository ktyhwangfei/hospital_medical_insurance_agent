"""
PostgreSQL 知识资产存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

KNOWLEDGE_ASSETS_TABLE = """
CREATE TABLE IF NOT EXISTS knowledge_assets (
    asset_id VARCHAR(128) PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    asset_type VARCHAR(64) NOT NULL,
    source VARCHAR(256),
    version VARCHAR(32),
    status VARCHAR(32) NOT NULL DEFAULT 'published',
    summary TEXT,
    index_status VARCHAR(32) DEFAULT 'pending',
    visibility JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    imported_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_assets_type ON knowledge_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_status ON knowledge_assets(status);
"""

KNOWLEDGE_CHUNKS_TABLE = """
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id VARCHAR(128) PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    section VARCHAR(256),
    title VARCHAR(512),
    text TEXT NOT NULL,
    summary TEXT,
    asset_type VARCHAR(64),
    asset_version VARCHAR(32),
    tags JSONB DEFAULT '[]',
    scenario_tags JSONB DEFAULT '[]',
    embedding VECTOR(768),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chunks_asset ON knowledge_chunks(asset_id);
CREATE INDEX IF NOT EXISTS idx_chunks_scenario ON knowledge_chunks USING GIN (scenario_tags);
"""


class PostgresKnowledgeAssetStore:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._ensure_schema()
            except Exception as e:
                logger.error(f"Failed to initialize knowledge asset store: {e}")
                raise
        return self._client

    def _ensure_schema(self) -> None:
        try:
            self._client.execute(KNOWLEDGE_ASSETS_TABLE)
            self._client.execute(KNOWLEDGE_CHUNKS_TABLE)
        except Exception as e:
            logger.error(f"Failed to ensure knowledge asset schema: {e}")
            raise

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "backend": "postgresql", "error": str(e)}
