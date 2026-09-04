"""
政策知识管线 PostgreSQL 存储

三张表：policy_documents / policy_extractions / policy_rule_lineage
"""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient

logger = logging.getLogger(__name__)

DOCUMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS policy_documents (
    doc_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    category VARCHAR(64),
    publish_date VARCHAR(32),
    abolition_date VARCHAR(32),
    validity VARCHAR(32) DEFAULT 'unknown',
    document_date VARCHAR(32),
    effective_date VARCHAR(32),
    issuing_agency VARCHAR(256),
    document_number VARCHAR(128),
    file_source VARCHAR(128),
    policy_region VARCHAR(64),
    policy_level VARCHAR(32),
    source_type VARCHAR(32) NOT NULL DEFAULT 'manual',
    source_url TEXT,
    content_text TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    content_size INTEGER DEFAULT 0,
    attachments JSONB DEFAULT '[]',
    crawl_status VARCHAR(32),
    crawl_time TIMESTAMPTZ,
    status VARCHAR(32) NOT NULL DEFAULT 'raw',
    coverage_ratio FLOAT DEFAULT 0,
    coverage_detail JSONB DEFAULT '{}',
    extraction_run_token VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_docs_status ON policy_documents(status);
CREATE INDEX IF NOT EXISTS idx_docs_hash ON policy_documents(content_hash);
"""

# 增量迁移：为已有表补充新增列（逐条执行，容错）
DOCUMENTS_MIGRATION = """
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS category VARCHAR(64);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS publish_date VARCHAR(32);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS abolition_date VARCHAR(32);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS validity VARCHAR(32) DEFAULT 'unknown';
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS document_date VARCHAR(32);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS effective_date VARCHAR(32);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS issuing_agency VARCHAR(256);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS document_number VARCHAR(128);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS file_source VARCHAR(128);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS policy_region VARCHAR(64);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS policy_level VARCHAR(32);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS content_size INTEGER DEFAULT 0;
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS attachments JSONB DEFAULT '[]';
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS crawl_status VARCHAR(32);
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS crawl_time TIMESTAMPTZ;
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS coverage_ratio FLOAT DEFAULT 0;
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS coverage_detail JSONB DEFAULT '{}';
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS dup_state JSONB DEFAULT '{}';
ALTER TABLE policy_documents ADD COLUMN IF NOT EXISTS extraction_run_token VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_docs_category ON policy_documents(category);
CREATE INDEX IF NOT EXISTS idx_docs_region ON policy_documents(policy_region);
"""

EXTRACTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS policy_extractions (
    extraction_id VARCHAR(64) PRIMARY KEY,
    doc_id VARCHAR(64) NOT NULL REFERENCES policy_documents(doc_id) ON DELETE CASCADE,
    unit_id VARCHAR(64),
    source_text TEXT NOT NULL,
    source_text_hash VARCHAR(64) NOT NULL,
    extracted_fields JSONB NOT NULL DEFAULT '{}',
    confidence FLOAT DEFAULT 0.0,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    reviewed_by VARCHAR(64),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_ext_doc_id ON policy_extractions(doc_id);
CREATE INDEX IF NOT EXISTS idx_ext_unit_id ON policy_extractions(unit_id);
CREATE INDEX IF NOT EXISTS idx_ext_status ON policy_extractions(status);
CREATE INDEX IF NOT EXISTS idx_ext_hash ON policy_extractions(source_text_hash);
-- 单元去重兑底：同文档同单元同原文至多一行活跃（NULL 归一；跨单元同文不约束）
-- [来源: docs/superpowers/specs/2026-08-25-extraction-unit-dedup-design.md §4.2]
CREATE UNIQUE INDEX IF NOT EXISTS uq_ext_active_doc_unit_text
    ON policy_extractions (doc_id, COALESCE(unit_id, ''), source_text_hash)
    WHERE status <> 'archived';
"""

EXTRACTIONS_MIGRATION = """
ALTER TABLE policy_extractions ADD COLUMN IF NOT EXISTS unit_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_ext_unit_id ON policy_extractions(unit_id);
ALTER TABLE policy_extractions ADD COLUMN IF NOT EXISTS last_override JSONB;
"""

LINEAGE_TABLE = """
CREATE TABLE IF NOT EXISTS policy_rule_lineage (
    lineage_id VARCHAR(64) PRIMARY KEY,
    rule_id VARCHAR(128) NOT NULL,
    extraction_id VARCHAR(64) REFERENCES policy_extractions(extraction_id) ON DELETE SET NULL,
    doc_id VARCHAR(64) NOT NULL REFERENCES policy_documents(doc_id) ON DELETE CASCADE,
    compile_run_id VARCHAR(64),
    rule_version INTEGER,
    canonical_rule JSONB,
    release_id VARCHAR(64),
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lineage_rule ON policy_rule_lineage(rule_id);
CREATE INDEX IF NOT EXISTS idx_lineage_doc ON policy_rule_lineage(doc_id);
CREATE INDEX IF NOT EXISTS idx_lineage_ext ON policy_rule_lineage(extraction_id);
"""

LINEAGE_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_lineage_rule_compile_run
    ON policy_rule_lineage(rule_id, compile_run_id)
"""

LINEAGE_MIGRATION = """
ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS compile_run_id VARCHAR(64);
ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS rule_version INTEGER;
ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS canonical_rule JSONB;
ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS release_id VARCHAR(64);
ALTER TABLE policy_rule_lineage ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_lineage_rule_version ON policy_rule_lineage(rule_id, rule_version);
CREATE INDEX IF NOT EXISTS idx_lineage_compile_run ON policy_rule_lineage(compile_run_id);
CREATE INDEX IF NOT EXISTS idx_lineage_release ON policy_rule_lineage(release_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lineage_rule_compile_run
    ON policy_rule_lineage(rule_id, compile_run_id);
"""


class PipelineStore:
    """政策知识管线存储（PostgreSQL）"""

    def __init__(self, database_url: str | None = None):
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    @staticmethod
    def _json_field(val: Any) -> Any:
        """安全解析 JSON 字段。"""
        if val is None:
            return {}
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return {}
        return val

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            self._ensure_schema()
        return self._client

    def _ensure_schema(self) -> None:
        client = self._get_client()
        for ddl in [DOCUMENTS_TABLE, EXTRACTIONS_TABLE, LINEAGE_TABLE]:
            client.execute(ddl)
        # 迁移：逐条 ALTER，表不存在时跳过
        for stmt in DOCUMENTS_MIGRATION.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    client.execute(stmt)
                except Exception:
                    pass  # 表不存在时静默跳过
        for stmt in EXTRACTIONS_MIGRATION.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    client.execute(stmt)
                except Exception:
                    pass
        for stmt in LINEAGE_MIGRATION.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    client.execute(stmt)
                except Exception:
                    pass
        # 唯一索引是候选/发布血缘并发安全的前提，迁移后必须成功建立。
        client.execute(LINEAGE_UNIQUE_INDEX)

    # ── Policy Documents ──────────────────────────────────────────

    def list_document_ids(self) -> list[str]:
        """廉价枚举文档 id（不构建 _unit_stats 详情），供只读批次扫描使用。"""
        client = self._get_client()
        rows = client.execute(
            "SELECT doc_id FROM policy_documents ORDER BY created_at DESC"
        )
        return [str(row["doc_id"]) for row in rows if row.get("doc_id")]

    def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str = "",
        keyword: str = "",
    ) -> dict[str, Any]:
        client = self._get_client()
        conditions = []
        params: list[Any] = []
        if status:
            conditions.append("d.status = %s")
            params.append(status)
        if keyword.strip():
            conditions.append("d.title ILIKE %s")
            params.append(f"%{keyword.strip()}%")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = (page - 1) * page_size

        count_row = client.execute(f"SELECT COUNT(*) as cnt FROM policy_documents d {where}", tuple(params))
        total = count_row[0]["cnt"] if count_row else 0

        rows = client.execute(
            f"SELECT d.* FROM policy_documents d {where} ORDER BY d.created_at DESC",
            tuple(params),
        )
        # 待处理数与前端 stats.draft 口径一致：以「去重后的叶子单元」为计数单位。
        # 之前用 SQL 子查询统计 draft 提取记录条数，会把「source_text 匹配不到叶子」
        # 的孤儿记录算进去，导致列表显示「待处理 N」但选中后前端按单元算=0（显示已完成）。
        items: list[dict[str, Any]] = []
        for r in rows:
            doc = self._doc_row(r)
            stats = self._unit_stats(doc)
            doc["unit_total"] = stats["total"]
            doc["unit_audited"] = stats["audited"]
            doc["pending_count"] = stats["pending"]
            items.append(doc)
        offset = (page - 1) * page_size
        # 待处理多的优先（保留原排序语义），Python 层排序后分页
        items.sort(key=lambda x: (-x["pending_count"], x.get("created_at", "")))
        paged = items[offset:offset + page_size]
        return {"items": paged, "total": total, "page": page, "page_size": page_size}

    def _unit_stats(self, doc: dict[str, Any]) -> dict[str, int]:
        """按去重叶子单元统计：总数 / 审核通过 / 待处理。

        - total：parse_kept_leaves 得到的去重叶子数（= 文档单元总数）。
        - audited：叶子状态聚合为 reviewed 或 published 的数量（“审核通过”）。
        - pending：与原 stats.draft 口径一致 = draft 叶子
          + 无提取记录且未经 unit_audit 审核的去重叶子。

        孤儿 draft 记录（source_text 匹配不到叶子）不计入。
        [来源: 排障 doc_466953309ccf/doc_ebea08e4d59d 孤儿记录导致待处理数虚高]
        """
        doc_id = doc["doc_id"]
        try:
            from src.knowledge_extension.rule_explanation.policy_struct.leaf_match import (
                parse_kept_leaves,
                match_leaves,
            )
            _root, _by_id, _all_leaves, kept = parse_kept_leaves(
                doc.get("content_text", ""), doc.get("title", "")
            )
        except Exception:
            logger.exception("parse_kept_leaves failed for doc %s", doc_id)
            return {"total": 0, "audited": 0, "pending": 0}
        if not kept:
            return {"total": 0, "audited": 0, "pending": 0}
        rows = self._get_client().execute(
            """SELECT source_text, extracted_fields, status FROM policy_extractions
               WHERE doc_id = %s AND status <> 'archived'""",
            (doc_id,),
        )
        # 每个 kept 叶子关联的提取状态列表（复刻前端 leafStatus 聚合）
        kept_status: dict[str, list[str]] = {lf.node_id: [] for lf in kept}
        for r in rows:
            fields = r.get("extracted_fields") or {}
            if isinstance(fields, str):
                try:
                    fields = json.loads(fields)
                except (json.JSONDecodeError, TypeError):
                    fields = {}
            fact = fields.get("fact_text") if isinstance(fields, dict) else ""
            src = (fact or r.get("source_text") or "").strip()
            for lid in match_leaves(src, kept):
                if lid in kept_status:
                    kept_status[lid].append(r["status"])

        def leaf_status(statuses: list[str]) -> str:
            if not statuses:
                return "pending"
            if any(s == "rejected" for s in statuses):
                return "rejected"
            if all(s == "published" for s in statuses):
                return "published"
            if all(s in ("reviewed", "published") for s in statuses):
                return "reviewed"
            return "draft"

        dup_state = doc.get("dup_state") or {}
        unit_audit = dup_state.get("unit_audit", {}) or {}
        audited_cnt = sum(
            1 for st in kept_status.values() if leaf_status(st) in ("reviewed", "published")
        )
        draft_cnt = sum(1 for st in kept_status.values() if leaf_status(st) == "draft")
        no_ext_pending = sum(
            1 for lid, st in kept_status.items() if not st and lid not in unit_audit
        )
        return {
            "total": len(kept),
            "audited": audited_cnt,
            "pending": draft_cnt + no_ext_pending,
        }

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        rows = self._get_client().execute(
            "SELECT * FROM policy_documents WHERE doc_id = %s", (doc_id,)
        )
        return self._doc_row(rows[0]) if rows else None

    def save_dup_state(self, doc_id: str, state: dict[str, Any]) -> bool:
        """保存重复处理状态（需求1：持久化，重启不丢失）"""
        client = self._get_client()
        client.execute(
            "UPDATE policy_documents SET dup_state = %s, updated_at = CURRENT_TIMESTAMP WHERE doc_id = %s",
            (json.dumps(state, ensure_ascii=False), doc_id),
        )
        return True

    def create_document(self, data: dict[str, Any]) -> dict[str, Any]:
        import hashlib

        client = self._get_client()
        doc_id = data.get("doc_id") or f"doc_{uuid.uuid4().hex[:12]}"
        title = data["title"]
        content_text = data.get("content_text", "")
        content_hash = hashlib.sha256(content_text.encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc)

        def _s(k: str) -> str:
            return str(data.get(k, "")).strip()

        attachments = data.get("attachments", [])
        if isinstance(attachments, list):
            attachments = json.dumps(attachments)

        fields = {
            "title": title,
            "category": _s("category"),
            "publish_date": _s("publish_date"),
            "abolition_date": _s("abolition_date"),
            "validity": _s("validity") or "unknown",
            "document_date": _s("document_date"),
            "effective_date": _s("effective_date"),
            "issuing_agency": _s("issuing_agency"),
            "document_number": _s("document_number"),
            "file_source": _s("file_source"),
            "policy_region": _s("policy_region"),
            "policy_level": _s("policy_level"),
            "source_type": _s("source_type") or "manual",
            "source_url": _s("source_url"),
            "content_text": content_text,
            "content_hash": content_hash,
            "content_size": len(content_text),
            "attachments": attachments,
            "crawl_status": _s("crawl_status") or None,
            "crawl_time": data.get("crawl_time") or None,
            "status": "raw",
            "created_at": now,
            "updated_at": now,
        }

        cols = ", ".join(fields.keys())
        placeholders = ", ".join(["%s"] * len(fields))
        vals = list(fields.values())
        update_cols = ", ".join(f"{k}=EXCLUDED.{k}" for k in fields if k not in ("doc_id", "status", "created_at", "updated_at")) + ", updated_at=EXCLUDED.updated_at"

        client.execute(
            f"INSERT INTO policy_documents (doc_id, {cols}) VALUES (%s, {placeholders}) ON CONFLICT (doc_id) DO UPDATE SET {update_cols}",
            (doc_id, *vals),
        )
        return self.get_document(doc_id) or {}

    def update_document(self, doc_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        import hashlib

        existing = self.get_document(doc_id)
        if not existing:
            return None
        client = self._get_client()

        def _g(k: str, default: str = "") -> str:
            return str(data.get(k, existing.get(k, default))).strip()

        content_text = _g("content_text", existing.get("content_text", ""))
        content_hash = hashlib.sha256(content_text.encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc)

        attachments = data.get("attachments", existing.get("attachments", []))
        if isinstance(attachments, list):
            attachments = json.dumps(attachments)

        settable = [
            "title", "category", "publish_date", "abolition_date", "validity",
            "document_date", "effective_date", "issuing_agency", "document_number",
            "file_source", "policy_region", "policy_level", "source_type", "source_url",
        ]
        set_clauses = ", ".join(f"{k}=%s" for k in settable)
        set_clauses += ", content_text=%s, content_hash=%s, content_size=%s, attachments=%s, status=%s, coverage_ratio=%s, coverage_detail=%s, updated_at=%s"

        vals: list[Any] = [_g(k) for k in settable]
        vals.extend([
            content_text, content_hash, len(content_text), attachments,
            data.get("status", existing["status"]),
            data.get("coverage_ratio", existing.get("coverage_ratio", 0)),
            json.dumps(data.get("coverage_detail", existing.get("coverage_detail", {}))),
            now, doc_id,
        ])

        client.execute(
            f"UPDATE policy_documents SET {set_clauses} WHERE doc_id=%s",
            tuple(vals),
        )
        return self.get_document(doc_id)

    def claim_extraction_run(self, doc_id: str, run_token: str) -> bool:
        """原子声明最新全文提取代次；LLM 调用期间不持有数据库事务。"""
        client = self._get_client()
        with client.transaction():
            client.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"policy-extraction-run:{doc_id}",),
            )
            rows = client.execute(
                """UPDATE policy_documents
                   SET extraction_run_token=%s, status='processing', updated_at=%s
                   WHERE doc_id=%s RETURNING doc_id""",
                (run_token, datetime.now(timezone.utc), doc_id),
            )
        return bool(rows)

    @contextmanager
    def commit_extraction_run(
        self, doc_id: str, run_token: str
    ) -> Iterator[bool]:
        """锁住文档提交窗口，阻止新代次穿过 proposal intake 与状态提交。"""
        client = self._get_client()
        with client.transaction():
            client.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"policy-extraction-run:{doc_id}",),
            )
            current = client.execute(
                """SELECT 1 FROM policy_documents
                   WHERE doc_id=%s AND extraction_run_token=%s FOR UPDATE""",
                (doc_id, run_token),
            )
            yield bool(current)

    def is_extraction_run_current(self, doc_id: str, run_token: str) -> bool:
        rows = self._get_client().execute(
            """SELECT 1 FROM policy_documents
               WHERE doc_id=%s AND extraction_run_token=%s""",
            (doc_id, run_token),
        )
        return bool(rows)

    def finish_extraction_run(
        self, doc_id: str, run_token: str, data: dict[str, Any]
    ) -> bool:
        """仅当前代次可提交文档状态与覆盖率。"""
        coverage_detail = (
            json.dumps(data["coverage_detail"])
            if "coverage_detail" in data else None
        )
        rows = self._get_client().execute(
            """UPDATE policy_documents SET
                 status=%s,
                 coverage_ratio=COALESCE(%s, coverage_ratio),
                 coverage_detail=COALESCE(%s::jsonb, coverage_detail),
                 updated_at=%s
               WHERE doc_id=%s AND extraction_run_token=%s
               RETURNING doc_id""",
            (
                data["status"], data.get("coverage_ratio"), coverage_detail,
                datetime.now(timezone.utc), doc_id, run_token,
            ),
        )
        return bool(rows)

    def delete_document(self, doc_id: str) -> bool:
        rows = self._get_client().execute(
            "DELETE FROM policy_documents WHERE doc_id = %s RETURNING doc_id", (doc_id,)
        )
        return len(rows) > 0

    def _doc_row(self, row: dict) -> dict:
        attachments = row.get("attachments")
        if isinstance(attachments, str):
            try:
                attachments = json.loads(attachments)
            except (json.JSONDecodeError, TypeError):
                attachments = []
        return {
            "doc_id": row["doc_id"],
            "title": row["title"],
            "category": row.get("category", ""),
            "publish_date": row.get("publish_date", ""),
            "abolition_date": row.get("abolition_date", ""),
            "validity": row.get("validity", "unknown"),
            "document_date": row.get("document_date", ""),
            "effective_date": row.get("effective_date", ""),
            "issuing_agency": row.get("issuing_agency", ""),
            "document_number": row.get("document_number", ""),
            "file_source": row.get("file_source", ""),
            "policy_region": row.get("policy_region", ""),
            "policy_level": row.get("policy_level", ""),
            "source_type": row["source_type"],
            "source_url": row.get("source_url", ""),
            "content_text": row.get("content_text", ""),
            "content_hash": row.get("content_hash", ""),
            "content_size": row.get("content_size", 0),
            "attachments": attachments,
            "crawl_status": row.get("crawl_status", ""),
            "crawl_time": str(row["crawl_time"]) if row.get("crawl_time") else "",
            "status": row["status"],
            "coverage_ratio": float(row.get("coverage_ratio", 0)),
            "coverage_detail": self._json_field(row.get("coverage_detail")),
            "extraction_run_token": row.get("extraction_run_token", ""),
            "dup_state": self._json_field(row.get("dup_state")),
            "pending_count": int(row.get("pending_count", 0)) if row.get("pending_count") is not None else 0,
            "created_at": str(row["created_at"]) if row.get("created_at") else "",
            "updated_at": str(row.get("updated_at")) if row.get("updated_at") else "",
        }

    # ── Policy Extractions ────────────────────────────────────────

    def list_extractions(
        self,
        page: int = 1,
        page_size: int = 20,
        doc_id: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        client = self._get_client()
        conditions = []
        params: list[Any] = []
        if doc_id:
            # 限定表别名 e，避免与 JOIN 后的 d.doc_id 列歧义（原 bug：HTTP 500）
            conditions.append("e.doc_id = %s")
            params.append(doc_id)
        if status:
            conditions.append("e.status = %s")
            params.append(status)
        else:
            conditions.append("e.status <> 'archived'")
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        offset = (page - 1) * page_size

        count_row = client.execute(f"SELECT COUNT(*) as cnt FROM policy_extractions e {where}", tuple(params))
        total = count_row[0]["cnt"] if count_row else 0

        rows = client.execute(
            f"SELECT e.*, d.title as doc_title FROM policy_extractions e LEFT JOIN policy_documents d ON e.doc_id = d.doc_id {where} ORDER BY e.created_at DESC LIMIT %s OFFSET %s",
            tuple(params) + (page_size, offset),
        )
        items = [self._ext_row(r) for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get_extraction(self, extraction_id: str) -> dict[str, Any] | None:
        rows = self._get_client().execute(
            """SELECT e.*, d.title as doc_title FROM policy_extractions e
               LEFT JOIN policy_documents d ON e.doc_id = d.doc_id
               WHERE e.extraction_id = %s""",
            (extraction_id,),
        )
        return self._ext_row(rows[0]) if rows else None

    def _find_active_duplicate(
        self, client: PostgreSQLClient, doc_id: str, unit_id: str | None,
        source_text_hash: str,
    ) -> str | None:
        """查活跃查重目标：unit 精确命中 > NULL 行承接（漂移）；跨单元同文不命中。

        SELECT 过滤 archived：归档行不可被复活（设计 §4.1）。
        """
        rows = client.execute(
            """SELECT extraction_id FROM policy_extractions
               WHERE doc_id=%s AND source_text_hash=%s AND status <> 'archived'
                 AND (unit_id = %s OR unit_id IS NULL OR %s::varchar IS NULL)
               ORDER BY (unit_id = %s) DESC
               LIMIT 1""",
            (doc_id, source_text_hash, unit_id, unit_id, unit_id),
        )
        return str(rows[0]["extraction_id"]) if rows else None

    def batch_create_extractions(self, items: list[dict[str, Any]]) -> int:
        """批量创建提取结果，按 doc_id + source_text_hash 去重（NULL 承接漂移，见 _find_active_duplicate）"""
        import hashlib

        client = self._get_client()
        count = 0
        now = datetime.now(timezone.utc)
        for item in items:
            extraction_id = item.get("extraction_id") or f"ext_{uuid.uuid4().hex[:12]}"
            doc_id = item["doc_id"]
            unit_id = item.get("unit_id") or None
            source_text = item.get("source_text", "")
            source_text_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]
            extracted_fields = item.get("extracted_fields", {})
            confidence = item.get("confidence", 0.0)

            # 去重：滤 archived；unit 精确命中 > NULL 承接；跨单元同文不命中（合法）
            existing_id = self._find_active_duplicate(client, doc_id, unit_id, source_text_hash)
            if existing_id:
                item["extraction_id"] = existing_id
                client.execute(
                    """UPDATE policy_extractions SET
                         unit_id=COALESCE(%s, unit_id), source_text=%s, source_text_hash=%s,
                         extracted_fields=%s, confidence=%s, status='draft',
                         reviewed_by=NULL, reviewed_at=NULL, updated_at=%s
                       WHERE extraction_id=%s""",
                    (
                        unit_id, source_text, source_text_hash,
                        json.dumps(extracted_fields), confidence, now, existing_id,
                    ),
                )
                continue

            client.execute(
                """INSERT INTO policy_extractions (extraction_id, doc_id, unit_id, source_text, source_text_hash, extracted_fields, confidence, status, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)""",
                (extraction_id, doc_id, unit_id, source_text, source_text_hash, json.dumps(extracted_fields), confidence, now, now),
            )
            count += 1
        return count

    def reconcile_extractions(
        self, doc_id: str, items: list[dict[str, Any]], run_token: str | None = None
    ) -> int | None:
        """单事务写入本轮全文提取并归档差集，保留历史证据外键。"""
        import hashlib

        if any(item.get("doc_id") != doc_id for item in items):
            raise ValueError("reconcile_extractions 仅接受同一 doc_id 的记录")
        client = self._get_client()
        current_ids: list[str] = []
        now = datetime.now(timezone.utc)
        with client.transaction():
            client.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"policy-extractions:{doc_id}",),
            )
            if run_token:
                current = client.execute(
                    """SELECT 1 FROM policy_documents
                       WHERE doc_id=%s AND extraction_run_token=%s FOR UPDATE""",
                    (doc_id, run_token),
                )
                if not current:
                    return None
            for item in items:
                extraction_id = str(item["extraction_id"])
                unit_id = item.get("unit_id") or None
                source_text = str(item.get("source_text") or "")
                source_text_hash = hashlib.sha256(source_text.encode()).hexdigest()[:16]
                # 与 batch_create 同一查重语义：滤 archived，NULL 承接漂移（设计 §4.1）
                dup = self._find_active_duplicate(client, doc_id, unit_id, source_text_hash)
                if dup:
                    extraction_id = dup
                    item["extraction_id"] = extraction_id
                current_ids.append(extraction_id)
                client.execute(
                    """INSERT INTO policy_extractions
                       (extraction_id, doc_id, unit_id, source_text, source_text_hash,
                        extracted_fields, confidence, status, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, 'draft', %s, %s)
                       ON CONFLICT (extraction_id) DO UPDATE SET
                         unit_id=COALESCE(EXCLUDED.unit_id, policy_extractions.unit_id),
                         source_text=EXCLUDED.source_text,
                         source_text_hash=EXCLUDED.source_text_hash,
                         extracted_fields=EXCLUDED.extracted_fields,
                         confidence=EXCLUDED.confidence, status='draft',
                         reviewed_by=NULL, reviewed_at=NULL, updated_at=EXCLUDED.updated_at""",
                    (
                        extraction_id, doc_id, unit_id, source_text, source_text_hash,
                        json.dumps(item.get("extracted_fields", {})),
                        item.get("confidence", 0.0), now, now,
                    ),
                )
            if current_ids:
                client.execute(
                    """UPDATE policy_extractions SET status='archived', updated_at=%s
                       WHERE doc_id=%s AND status <> 'archived'
                         AND NOT (extraction_id = ANY(%s))""",
                    (now, doc_id, current_ids),
                )
            else:
                client.execute(
                    """UPDATE policy_extractions SET status='archived', updated_at=%s
                       WHERE doc_id=%s AND status <> 'archived'""",
                    (now, doc_id),
                )
        return len(items)

    def update_extraction(self, extraction_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_extraction(extraction_id)
        if not existing:
            return None
        client = self._get_client()
        now = datetime.now(timezone.utc)
        fields = data.get("extracted_fields")
        status = data.get("status", existing["status"])
        confidence = data.get("confidence", existing["confidence"])
        reviewed_by = data.get("reviewed_by")
        last_override = data.get("last_override")
        unit_id = data.get("unit_id")

        if fields is not None:
            client.execute(
                "UPDATE policy_extractions SET extracted_fields=%s, status=%s, confidence=%s, reviewed_by=%s, reviewed_at=%s, updated_at=%s WHERE extraction_id=%s",
                (json.dumps(fields), status, confidence, reviewed_by, now if status in ("reviewed", "rejected") else None, now, extraction_id),
            )
        else:
            client.execute(
                "UPDATE policy_extractions SET status=%s, confidence=%s, reviewed_by=%s, reviewed_at=%s, updated_at=%s WHERE extraction_id=%s",
                (status, confidence, reviewed_by, now if status in ("reviewed", "rejected") else None, now, extraction_id),
            )
        # 归属修复（迭代 19）：回填 unit_id（匹配修复后的正文叶子）
        if unit_id is not None and unit_id != existing.get("unit_id"):
            client.execute(
                "UPDATE policy_extractions SET unit_id=%s, updated_at=%s WHERE extraction_id=%s",
                (unit_id or None, now, extraction_id),
            )
        # 审计字段 last_override（迭代 18）：单独更新，与上面互不影响
        if last_override is not None:
            client.execute(
                "UPDATE policy_extractions SET last_override=%s WHERE extraction_id=%s",
                (json.dumps(last_override), extraction_id),
            )
        return self.get_extraction(extraction_id)

    def delete_extraction(self, extraction_id: str) -> bool:
        rows = self._get_client().execute(
            "DELETE FROM policy_extractions WHERE extraction_id = %s RETURNING extraction_id", (extraction_id,)
        )
        return len(rows) > 0

    def _ext_row(self, row: dict) -> dict:
        fields = row.get("extracted_fields", {})
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except (json.JSONDecodeError, TypeError):
                fields = {}
        return {
            "extraction_id": row["extraction_id"],
            "doc_id": row["doc_id"],
            "unit_id": row.get("unit_id", "") or "",
            "doc_title": row.get("doc_title", ""),
            "source_text": row.get("source_text", ""),
            "source_text_hash": row.get("source_text_hash", ""),
            "extracted_fields": fields,
            "confidence": float(row.get("confidence", 0)),
            "status": row["status"],
            "reviewed_by": row.get("reviewed_by", ""),
            "reviewed_at": str(row["reviewed_at"]) if row.get("reviewed_at") else "",
            "last_override": self._json_field(row.get("last_override")) if row.get("last_override") else None,
            "created_at": str(row["created_at"]) if row.get("created_at") else "",
            "updated_at": str(row.get("updated_at")) if row.get("updated_at") else "",
        }

    # ── Lineage ───────────────────────────────────────────────────

    def create_lineage(self, rule_id: str, extraction_id: str, doc_id: str) -> dict:
        client = self._get_client()
        lineage_id = f"lin_{uuid.uuid4().hex[:12]}"
        client.execute(
            "INSERT INTO policy_rule_lineage (lineage_id, rule_id, extraction_id, doc_id) VALUES (%s, %s, %s, %s)",
            (lineage_id, rule_id, extraction_id, doc_id),
        )
        return {"lineage_id": lineage_id, "rule_id": rule_id, "extraction_id": extraction_id, "doc_id": doc_id}

    def get_lineages_by_rule(self, rule_id: str) -> list[dict]:
        rows = self._get_client().execute(
            """SELECT l.*, d.title as doc_title FROM policy_rule_lineage l
               LEFT JOIN policy_documents d ON l.doc_id = d.doc_id
               WHERE l.rule_id = %s""",
            (rule_id,),
        )
        return [{"lineage_id": r["lineage_id"], "rule_id": r["rule_id"], "extraction_id": r["extraction_id"], "doc_id": r["doc_id"], "doc_title": r.get("doc_title", "")} for r in rows]

    def get_lineages_by_doc(self, doc_id: str) -> list[dict]:
        rows = self._get_client().execute(
            "SELECT * FROM policy_rule_lineage WHERE doc_id = %s", (doc_id,)
        )
        return [{"lineage_id": r["lineage_id"], "rule_id": r["rule_id"], "extraction_id": r["extraction_id"], "doc_id": r["doc_id"]} for r in rows]

    def get_rules_by_doc(self, doc_id: str) -> list[str]:
        rows = self._get_client().execute(
            "SELECT DISTINCT rule_id FROM policy_rule_lineage WHERE doc_id = %s", (doc_id,)
        )
        return [r["rule_id"] for r in rows]

    # ── Summary ───────────────────────────────────────────────────

    def get_summary(self) -> dict[str, Any]:
        client = self._get_client()
        docs = client.execute("SELECT COUNT(*) as cnt, COUNT(CASE WHEN status='raw' THEN 1 END) as raw_cnt FROM policy_documents")
        exts = client.execute("SELECT COUNT(*) as cnt, COUNT(CASE WHEN status='draft' THEN 1 END) as draft_cnt, COUNT(CASE WHEN status='reviewed' THEN 1 END) as reviewed_cnt, COUNT(CASE WHEN status='published' THEN 1 END) as published_cnt FROM policy_extractions WHERE status <> 'archived'")
        document_items = self.list_documents(page=1, page_size=1000).get("items", [])
        return {
            "documents_count": docs[0]["cnt"] if docs else 0,
            "documents_raw": docs[0]["raw_cnt"] if docs else 0,
            "extractions_count": exts[0]["cnt"] if exts else 0,
            "extractions_draft": exts[0]["draft_cnt"] if exts else 0,
            "extractions_reviewed": exts[0]["reviewed_cnt"] if exts else 0,
            "extractions_published": exts[0]["published_cnt"] if exts else 0,
            "units_count": sum(int(item.get("unit_total") or 0) for item in document_items),
            "units_audited": sum(int(item.get("unit_audited") or 0) for item in document_items),
            "units_pending": sum(int(item.get("pending_count") or 0) for item in document_items),
        }
