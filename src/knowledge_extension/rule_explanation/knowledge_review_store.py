"""政策知识「评审」状态的持久化存储。

工作台中栏每组结构化知识需要人工评审（通过 / 驳回），评审通过的知识才能进入
第三栏做指标与值域标化。评审结果必须落库（需求：三栏所有操作结果保存到数据库），
不能只留在内存——否则刷新页面后评审结论丢失，无法形成可追溯的知识治理记录。

存储按 `doc_id + knowledge_id` 唯一约束，同一条知识的评审以最新一次为准（upsert）。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal, Protocol

from pydantic import BaseModel, Field

ReviewStatus = Literal["pending", "approved", "rejected"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stable_review_id(doc_id: str, knowledge_id: str) -> str:
    """同一 doc+knowledge 的评审记录使用稳定 id，便于 upsert 幂等。"""
    digest = hashlib.sha256(f"{doc_id}|{knowledge_id}".encode("utf-8")).hexdigest()[:16]
    return f"kr_{digest}"


class KnowledgeReview(BaseModel):
    """一条政策知识的评审结论（来源可追溯）。"""

    review_id: str
    doc_id: str
    unit_id: str
    knowledge_id: str
    extraction_id: str | None = None
    status: ReviewStatus
    reviewed_by: str
    reviewed_at: datetime = Field(default_factory=_now)
    note: str | None = None
    created_at: datetime = Field(default_factory=_now)


class KnowledgeReviewStore(Protocol):
    def save(self, review: KnowledgeReview) -> KnowledgeReview: ...
    def get(self, doc_id: str, knowledge_id: str) -> KnowledgeReview | None: ...
    def list_for_document(self, doc_id: str) -> list[KnowledgeReview]: ...


class InMemoryKnowledgeReviewStore:
    """测试与本地回退（USE_MEMORY_STORAGE=1）使用。"""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], KnowledgeReview] = {}

    def save(self, review: KnowledgeReview) -> KnowledgeReview:
        key = (review.doc_id, review.knowledge_id)
        self._items[key] = review.model_copy(deep=True)
        return self._items[key].model_copy(deep=True)

    def get(self, doc_id: str, knowledge_id: str) -> KnowledgeReview | None:
        item = self._items.get((doc_id, knowledge_id))
        return item.model_copy(deep=True) if item else None

    def list_for_document(self, doc_id: str) -> list[KnowledgeReview]:
        return [
            item.model_copy(deep=True)
            for (key_doc, _), item in self._items.items()
            if key_doc == doc_id
        ]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS policy_knowledge_reviews (
    review_id VARCHAR(64) PRIMARY KEY,
    doc_id VARCHAR(128) NOT NULL,
    unit_id VARCHAR(128) NOT NULL,
    knowledge_id VARCHAR(128) NOT NULL,
    extraction_id VARCHAR(128),
    status VARCHAR(32) NOT NULL,
    reviewed_by VARCHAR(128) NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(doc_id, knowledge_id)
);
CREATE INDEX IF NOT EXISTS idx_policy_knowledge_review_doc
    ON policy_knowledge_reviews(doc_id);
"""


class PostgresKnowledgeReviewStore:
    """KnowledgeReviewStore 的 PostgreSQL adapter，懒建表。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url
        self._client: "object | None" = None

    def _get_client(self):
        if self._client is None:
            from src.config.production import DATABASE_URL
            from src.data_platform.storage.postgresql.client import PostgreSQLClient

            self._client = PostgreSQLClient(self._database_url or DATABASE_URL)
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    self._client.execute(statement)
        return self._client

    def save(self, review: KnowledgeReview) -> KnowledgeReview:
        self._get_client().execute(
            """INSERT INTO policy_knowledge_reviews
               (review_id, doc_id, unit_id, knowledge_id, extraction_id,
                status, reviewed_by, reviewed_at, note, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (doc_id, knowledge_id) DO UPDATE SET
                 status=EXCLUDED.status, reviewed_by=EXCLUDED.reviewed_by,
                 reviewed_at=EXCLUDED.reviewed_at, note=EXCLUDED.note""",
            (
                review.review_id,
                review.doc_id,
                review.unit_id,
                review.knowledge_id,
                review.extraction_id,
                review.status,
                review.reviewed_by,
                review.reviewed_at,
                review.note,
                review.created_at,
            ),
        )
        return review

    def get(self, doc_id: str, knowledge_id: str) -> KnowledgeReview | None:
        rows = self._get_client().execute(
            "SELECT * FROM policy_knowledge_reviews WHERE doc_id=%s AND knowledge_id=%s",
            (doc_id, knowledge_id),
        )
        return self._row(rows[0]) if rows else None

    def list_for_document(self, doc_id: str) -> list[KnowledgeReview]:
        rows = self._get_client().execute(
            "SELECT * FROM policy_knowledge_reviews WHERE doc_id=%s ORDER BY reviewed_at, review_id",
            (doc_id,),
        )
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: dict) -> KnowledgeReview:
        result = dict(row)
        # TIMESTAMPTZ 列已带回时区信息，保持原样
        return KnowledgeReview(**result)
