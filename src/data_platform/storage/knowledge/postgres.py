"""
PostgreSQL 知识资产和切片存储
"""
import json
import logging
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

KNOWLEDGE_TABLES = """
CREATE TABLE IF NOT EXISTS knowledge_assets (
    asset_id VARCHAR(128) PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    source VARCHAR(256),
    asset_type VARCHAR(64),
    version VARCHAR(32),
    status VARCHAR(32) DEFAULT 'draft',
    summary TEXT,
    visibility JSONB DEFAULT '{}',
    index_status VARCHAR(32),
    effective_date DATE,
    imported_at TIMESTAMP,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_assets_type ON knowledge_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_status ON knowledge_assets(status);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id VARCHAR(128) PRIMARY KEY,
    asset_id VARCHAR(128) NOT NULL,
    asset_type VARCHAR(64),
    title VARCHAR(512),
    section VARCHAR(256),
    text TEXT,
    summary TEXT,
    tags JSONB DEFAULT '[]',
    scenario_tags JSONB DEFAULT '[]',
    visibility JSONB DEFAULT '{}',
    locator VARCHAR(256),
    embedding_id VARCHAR(128),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chunks_asset ON knowledge_chunks(asset_id);
"""


class PostgresKnowledgeStorage:
    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            try:
                self._client = PostgreSQLClient(self._database_url)
                self._client.execute(KNOWLEDGE_TABLES)
                logger.info("PostgreSQL knowledge storage initialized")
            except Exception as e:
                logger.error(f"Failed to initialize knowledge storage: {e}")
                raise
        return self._client

    def save_asset(self, asset: dict[str, Any]) -> None:
        client = self._get_client()
        sql = """
            INSERT INTO knowledge_assets (asset_id, title, source, asset_type, version, status, summary, visibility, index_status, effective_date, imported_at, metadata, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
            ON CONFLICT (asset_id) DO UPDATE SET
                title=EXCLUDED.title, source=EXCLUDED.source, asset_type=EXCLUDED.asset_type,
                version=EXCLUDED.version, status=EXCLUDED.status, summary=EXCLUDED.summary,
                visibility=EXCLUDED.visibility, index_status=EXCLUDED.index_status,
                effective_date=EXCLUDED.effective_date, imported_at=EXCLUDED.imported_at,
                metadata=EXCLUDED.metadata, updated_at=CURRENT_TIMESTAMP
        """
        client.execute(sql, (
            asset['asset_id'], asset['title'], asset.get('source'), asset.get('asset_type'),
            asset.get('version'), asset.get('status', 'draft'), asset.get('summary'),
            json.dumps(asset.get('visibility', {})), asset.get('index_status'),
            asset.get('effective_date'), asset.get('imported_at'),
            json.dumps(asset.get('metadata', {})),
        ))

    def save_chunk(self, chunk: dict[str, Any]) -> None:
        client = self._get_client()
        sql = """
            INSERT INTO knowledge_chunks (chunk_id, asset_id, asset_type, title, section, text, summary, tags, scenario_tags, visibility, locator, embedding_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (chunk_id) DO UPDATE SET
                text=EXCLUDED.text, summary=EXCLUDED.summary, tags=EXCLUDED.tags,
                scenario_tags=EXCLUDED.scenario_tags, embedding_id=EXCLUDED.embedding_id
        """
        client.execute(sql, (
            chunk['chunk_id'], chunk['asset_id'], chunk.get('asset_type'), chunk.get('title'),
            chunk.get('section'), chunk.get('text'), chunk.get('summary'),
            json.dumps(chunk.get('tags', [])), json.dumps(chunk.get('scenario_tags', [])),
            json.dumps(chunk.get('visibility', {})), chunk.get('locator'), chunk.get('embedding_id'),
        ))

    def list_chunks(self, asset_id: str) -> list[dict[str, Any]]:
        return self._get_client().execute("SELECT * FROM knowledge_chunks WHERE asset_id=%s ORDER BY chunk_id", (asset_id,))

    def list_assets(self, asset_type: str | None = None) -> list[dict[str, Any]]:
        if asset_type:
            return self._get_client().execute("SELECT * FROM knowledge_assets WHERE asset_type=%s ORDER BY asset_id", (asset_type,))
        return self._get_client().execute("SELECT * FROM knowledge_assets ORDER BY asset_id")

    def health(self) -> dict[str, Any]:
        try:
            self._get_client().execute("SELECT 1")
            return {"status": "healthy", "backend": "postgresql"}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
