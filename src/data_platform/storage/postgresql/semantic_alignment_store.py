"""语义指标多来源绑定和值域草稿的 PostgreSQL 存储。"""
from __future__ import annotations

from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.knowledge_extension.rule_explanation.semantic_alignment import (
    MetricSourceBinding,
    SourceValueMapping,
    StandardValueProposal,
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
"""


def _without_none_created_at(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if result.get("created_at") is None:
        result.pop("created_at", None)
    return result


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
