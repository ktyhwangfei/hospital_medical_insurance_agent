"""语义指标多来源绑定和值域草稿的 PostgreSQL 存储。"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.data_platform.storage.postgresql.semantic_registry_store import (
    SEMANTIC_REGISTRY_TRANSACTION_LOCK,
)
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    MetricSourceBinding,
    ProposalStatus,
    ProposalType,
    SemanticProposal,
    SourceValueMapping,
    StandardValueProposal,
    _landing_lock_keys,
    _landing_target_keys,
    _merge_semantic_proposals,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS semantic_metric_source_bindings (
    binding_id VARCHAR(64) PRIMARY KEY,
    metric_code VARCHAR(256) NOT NULL REFERENCES semantic_metrics(metric_code) ON DELETE CASCADE,
    source_type VARCHAR(32) NOT NULL,
    source_ref VARCHAR(512) NOT NULL,
    source_field VARCHAR(256) NOT NULL,
    source_version VARCHAR(128) NOT NULL,
    evidence TEXT NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    reviewed_by VARCHAR(128),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(metric_code, source_type, source_ref, source_field, source_version)
);
CREATE INDEX IF NOT EXISTS idx_semantic_source_binding_metric
    ON semantic_metric_source_bindings(metric_code);

CREATE TABLE IF NOT EXISTS semantic_source_value_mappings (
    mapping_id VARCHAR(64) PRIMARY KEY,
    metric_code VARCHAR(256) NOT NULL REFERENCES semantic_metrics(metric_code) ON DELETE CASCADE,
    domain_code VARCHAR(128) NOT NULL REFERENCES semantic_value_domains(domain_code) ON DELETE CASCADE,
    binding_id VARCHAR(64) NOT NULL REFERENCES semantic_metric_source_bindings(binding_id) ON DELETE CASCADE,
    source_value VARCHAR(512) NOT NULL,
    standard_value VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    reviewed_by VARCHAR(128),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(binding_id, source_value)
);
CREATE INDEX IF NOT EXISTS idx_semantic_source_value_metric
    ON semantic_source_value_mappings(metric_code);

CREATE TABLE IF NOT EXISTS semantic_standard_value_proposals (
    proposal_id VARCHAR(64) PRIMARY KEY,
    domain_code VARCHAR(128) NOT NULL REFERENCES semantic_value_domains(domain_code) ON DELETE CASCADE,
    standard_value VARCHAR(512) NOT NULL,
    evidence TEXT NOT NULL,
    source_ref VARCHAR(512) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    reviewed_by VARCHAR(128),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(domain_code, standard_value, source_ref)
);

CREATE TABLE IF NOT EXISTS semantic_proposals (
    proposal_id VARCHAR(64) PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL,
    proposal_type VARCHAR(32) NOT NULL,
    trigger_source VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'proposed',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    payload JSONB NOT NULL,
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    reviewed_by VARCHAR(128),
    reviewed_at TIMESTAMPTZ,
    review_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE semantic_proposals
    DROP CONSTRAINT IF EXISTS semantic_proposals_fingerprint_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_semantic_proposals_active_fingerprint
    ON semantic_proposals(fingerprint)
    WHERE status IN ('proposed', 'reviewing', 'accepted');
CREATE INDEX IF NOT EXISTS idx_semantic_proposals_status
    ON semantic_proposals(proposal_type, status, created_at);

CREATE TABLE IF NOT EXISTS semantic_proposal_landing_targets (
    target_key VARCHAR(512) PRIMARY KEY,
    proposal_id VARCHAR(64) NOT NULL REFERENCES semantic_proposals(proposal_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _without_none_created_at(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if result.get("created_at") is None:
        result.pop("created_at", None)
    return result


def _proposal_from_row(row: dict[str, Any]) -> SemanticProposal:
    payload = row.get("payload") or {}
    evidence = row.get("evidence") or []
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(evidence, str):
        evidence = json.loads(evidence)
    data = dict(payload)
    data.update({
        key: row[key] for key in (
            "proposal_id", "fingerprint", "proposal_type", "trigger_source",
            "status", "confidence", "occurrence_count", "reviewed_by",
            "reviewed_at", "review_note", "created_at", "updated_at",
        ) if row.get(key) is not None
    })
    data["evidence"] = evidence
    return SemanticProposal(**data)


class PostgresSemanticAlignmentStore:
    """SemanticAlignmentStore 的 PostgreSQL adapter。"""

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._database_url)
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    self._client.execute(statement)
        return self._client

    @contextmanager
    def registry_transaction(self, registry_store: object):
        """让提议与 registry 共用同一 PostgreSQL 连接和事务。"""
        client = self._get_client()
        with SEMANTIC_REGISTRY_TRANSACTION_LOCK:
            original_client = getattr(registry_store, "_client", None)
            setattr(registry_store, "_client", client)
            try:
                with client.transaction():
                    yield
            finally:
                setattr(registry_store, "_client", original_client)

    def lock_and_claim_landing_targets(self, proposal: SemanticProposal) -> None:
        """排序获取事务级锁，并由唯一声明保证一个目标只落地一个提议。"""
        client = self._get_client()
        keys = _landing_target_keys(proposal)
        for key in _landing_lock_keys(proposal):
            client.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (key,),
            )
        for key in keys:
            rows = client.execute(
                """INSERT INTO semantic_proposal_landing_targets (target_key, proposal_id)
                   VALUES (%s, %s)
                   ON CONFLICT (target_key) DO UPDATE SET target_key=EXCLUDED.target_key
                   RETURNING proposal_id""",
                (key, proposal.proposal_id),
            )
            if not rows or rows[0]["proposal_id"] != proposal.proposal_id:
                raise ValueError(f"落地目标已被其他提议占用: {key}")

    def save_binding(self, binding: MetricSourceBinding) -> MetricSourceBinding:
        self._get_client().execute(
            """INSERT INTO semantic_metric_source_bindings
               (binding_id, metric_code, source_type, source_ref, source_field,
                source_version, evidence, status, reviewed_by, reviewed_at, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (binding_id) DO UPDATE SET
                 evidence=EXCLUDED.evidence, status=EXCLUDED.status,
                 reviewed_by=EXCLUDED.reviewed_by, reviewed_at=EXCLUDED.reviewed_at""",
            (
                binding.binding_id,
                binding.metric_code,
                binding.source_type,
                binding.source_ref,
                binding.source_field,
                binding.source_version,
                binding.evidence,
                binding.status,
                binding.reviewed_by,
                binding.reviewed_at,
                binding.created_at,
            ),
        )
        return binding

    def get_binding(self, binding_id: str) -> MetricSourceBinding | None:
        rows = self._get_client().execute(
            "SELECT * FROM semantic_metric_source_bindings WHERE binding_id=%s",
            (binding_id,),
        )
        return MetricSourceBinding(**_without_none_created_at(rows[0])) if rows else None

    def list_bindings(self, metric_code: str) -> list[MetricSourceBinding]:
        rows = self._get_client().execute(
            "SELECT * FROM semantic_metric_source_bindings WHERE metric_code=%s ORDER BY created_at, binding_id",
            (metric_code,),
        )
        return [MetricSourceBinding(**_without_none_created_at(row)) for row in rows]

    def save_value_mapping(self, mapping: SourceValueMapping) -> SourceValueMapping:
        self._get_client().execute(
            """INSERT INTO semantic_source_value_mappings
               (mapping_id, metric_code, domain_code, binding_id, source_value,
                standard_value, status, reviewed_by, reviewed_at, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (mapping_id) DO UPDATE SET
                 standard_value=EXCLUDED.standard_value, status=EXCLUDED.status,
                 reviewed_by=EXCLUDED.reviewed_by, reviewed_at=EXCLUDED.reviewed_at""",
            (
                mapping.mapping_id,
                mapping.metric_code,
                mapping.domain_code,
                mapping.binding_id,
                mapping.source_value,
                mapping.standard_value,
                mapping.status,
                mapping.reviewed_by,
                mapping.reviewed_at,
                mapping.created_at,
            ),
        )
        return mapping

    def get_value_mapping(self, mapping_id: str) -> SourceValueMapping | None:
        rows = self._get_client().execute(
            "SELECT * FROM semantic_source_value_mappings WHERE mapping_id=%s",
            (mapping_id,),
        )
        return SourceValueMapping(**_without_none_created_at(rows[0])) if rows else None

    def save_standard_value_proposal(self, proposal: StandardValueProposal) -> StandardValueProposal:
        self._get_client().execute(
            """INSERT INTO semantic_standard_value_proposals
               (proposal_id, domain_code, standard_value, evidence, source_ref,
                status, reviewed_by, reviewed_at, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (proposal_id) DO UPDATE SET
                 evidence=EXCLUDED.evidence, status=EXCLUDED.status,
                 reviewed_by=EXCLUDED.reviewed_by, reviewed_at=EXCLUDED.reviewed_at""",
            (
                proposal.proposal_id,
                proposal.domain_code,
                proposal.standard_value,
                proposal.evidence,
                proposal.source_ref,
                proposal.status,
                proposal.reviewed_by,
                proposal.reviewed_at,
                proposal.created_at,
            ),
        )
        return proposal

    def get_standard_value_proposal(self, proposal_id: str) -> StandardValueProposal | None:
        rows = self._get_client().execute(
            "SELECT * FROM semantic_standard_value_proposals WHERE proposal_id=%s",
            (proposal_id,),
        )
        return StandardValueProposal(**_without_none_created_at(rows[0])) if rows else None

    def save_proposal(self, proposal: SemanticProposal) -> SemanticProposal:
        payload = proposal.model_dump(
            mode="json",
            exclude={
                "proposal_id", "fingerprint", "proposal_type", "trigger_source",
                "status", "confidence", "occurrence_count", "evidence",
                "reviewed_by", "reviewed_at", "review_note", "created_at", "updated_at",
            },
        )
        self._get_client().execute(
            """INSERT INTO semantic_proposals
               (proposal_id, fingerprint, proposal_type, trigger_source, status,
                confidence, occurrence_count, payload, evidence, reviewed_by,
                reviewed_at, review_note, created_at, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (fingerprint) WHERE status IN ('proposed', 'reviewing', 'accepted')
               DO UPDATE SET
                 status=EXCLUDED.status, confidence=EXCLUDED.confidence,
                 occurrence_count=EXCLUDED.occurrence_count, payload=EXCLUDED.payload,
                 evidence=EXCLUDED.evidence, reviewed_by=EXCLUDED.reviewed_by,
                 reviewed_at=EXCLUDED.reviewed_at, review_note=EXCLUDED.review_note,
                 updated_at=EXCLUDED.updated_at""",
            (
                proposal.proposal_id, proposal.fingerprint, proposal.proposal_type,
                proposal.trigger_source, proposal.status, proposal.confidence,
                proposal.occurrence_count,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(
                    [item.model_dump(mode="json") for item in proposal.evidence],
                    ensure_ascii=False,
                ),
                proposal.reviewed_by, proposal.reviewed_at, proposal.review_note,
                proposal.created_at, proposal.updated_at,
            ),
        )
        return proposal

    def merge_proposal(self, proposal: SemanticProposal) -> SemanticProposal:
        """按 fingerprint 串行合并；相同 source_ref 替换证据而非累加。"""
        client = self._get_client()
        with client.transaction():
            client.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (proposal.fingerprint,),
            )
            rows = client.execute(
                """SELECT * FROM semantic_proposals
                   WHERE fingerprint=%s AND status IN ('proposed', 'reviewing', 'accepted')
                   ORDER BY created_at DESC, proposal_id DESC LIMIT 1 FOR UPDATE""",
                (proposal.fingerprint,),
            )
            merged = (
                _merge_semantic_proposals(_proposal_from_row(rows[0]), proposal)
                if rows else proposal
            )
            self.save_proposal(merged)
            return merged

    def get_proposal(self, proposal_id: str) -> SemanticProposal | None:
        rows = self._get_client().execute(
            "SELECT * FROM semantic_proposals WHERE proposal_id=%s", (proposal_id,)
        )
        return _proposal_from_row(rows[0]) if rows else None

    def lock_proposal(self, proposal_id: str) -> SemanticProposal | None:
        rows = self._get_client().execute(
            "SELECT * FROM semantic_proposals WHERE proposal_id=%s FOR UPDATE",
            (proposal_id,),
        )
        return _proposal_from_row(rows[0]) if rows else None

    def compare_and_set_proposal(
        self, proposal: SemanticProposal, expected_status: ProposalStatus,
    ) -> SemanticProposal | None:
        rows = self._get_client().execute(
            """UPDATE semantic_proposals SET
                 status=%s, reviewed_by=%s, reviewed_at=%s, review_note=%s,
                 updated_at=%s
               WHERE proposal_id=%s AND status=%s
               RETURNING *""",
            (
                proposal.status, proposal.reviewed_by, proposal.reviewed_at,
                proposal.review_note, proposal.updated_at, proposal.proposal_id,
                expected_status,
            ),
        )
        return _proposal_from_row(rows[0]) if rows else None

    def get_proposal_by_fingerprint(self, fingerprint: str) -> SemanticProposal | None:
        rows = self._get_client().execute(
            """SELECT * FROM semantic_proposals
               WHERE fingerprint=%s AND status IN ('proposed', 'reviewing', 'accepted')
               ORDER BY created_at DESC, proposal_id DESC LIMIT 1""",
            (fingerprint,),
        )
        return _proposal_from_row(rows[0]) if rows else None

    def list_proposals(
        self, proposal_type: ProposalType | None = None,
        status: ProposalStatus | None = None,
    ) -> list[SemanticProposal]:
        clauses: list[str] = []
        params: list[object] = []
        if proposal_type is not None:
            clauses.append("proposal_type=%s")
            params.append(proposal_type)
        if status is not None:
            clauses.append("status=%s")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._get_client().execute(
            f"SELECT * FROM semantic_proposals{where} ORDER BY created_at, proposal_id",
            tuple(params),
        )
        return [_proposal_from_row(row) for row in rows]
