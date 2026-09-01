"""PDSC 语义发现簇与政策适用关系的 PostgreSQL 存储。"""
from __future__ import annotations

import json
from typing import Any

from src.config.production import DATABASE_URL
from src.data_platform.storage.postgresql.client import PostgreSQLClient
from src.knowledge_extension.rule_explanation.pdsc import (
    ClusterActivation,
    ClusterStatus,
    PolicyApplicabilityRelation,
    SemanticDiscoveryCluster,
)

# DDL 双写原则：新增列必须 CREATE + ALTER 双写，旧库不重建也能补列。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS pdsc_clusters (
    cluster_id VARCHAR(64) PRIMARY KEY,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pdsc_clusters_status ON pdsc_clusters(status);

CREATE TABLE IF NOT EXISTS pdsc_policy_applicability_relations (
    relation_id VARCHAR(64) PRIMARY KEY,
    policy_metric_code VARCHAR(256) NOT NULL,
    business_metric_code VARCHAR(256) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    revision INTEGER NOT NULL DEFAULT 1,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pdsc_relations_business_metric
    ON pdsc_policy_applicability_relations(business_metric_code);

CREATE TABLE IF NOT EXISTS pdsc_activations (
    activation_id VARCHAR(64) PRIMARY KEY,
    cluster_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'running',
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pdsc_activations_cluster ON pdsc_activations(cluster_id);
"""


class PostgresPdscStore:
    def __init__(self, database_url: str | None = None) -> None:
        self._url = database_url or DATABASE_URL
        self._client: PostgreSQLClient | None = None

    def _get_client(self) -> PostgreSQLClient:
        if self._client is None:
            self._client = PostgreSQLClient(self._url)
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    self._client.execute(statement)
        return self._client

    # ── 簇 ──

    def save_cluster(self, cluster: SemanticDiscoveryCluster) -> SemanticDiscoveryCluster:
        client = self._get_client()
        payload = json.dumps(cluster.model_dump(mode="json"), ensure_ascii=False)
        client.execute(
            """
            INSERT INTO pdsc_clusters (cluster_id, status, payload, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (cluster_id) DO UPDATE SET
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = EXCLUDED.updated_at
            """,
            (cluster.cluster_id, cluster.status.value, payload,
             cluster.created_at, cluster.updated_at),
        )
        return cluster

    def get_cluster(self, cluster_id: str) -> SemanticDiscoveryCluster | None:
        rows = self._get_client().execute(
            "SELECT payload FROM pdsc_clusters WHERE cluster_id = %s", (cluster_id,),
        )
        return SemanticDiscoveryCluster.model_validate(rows[0]["payload"]) if rows else None

    def list_clusters(
        self, statuses: list[ClusterStatus] | None = None,
    ) -> list[SemanticDiscoveryCluster]:
        params: list[Any] = []
        where = ""
        if statuses:
            where = "WHERE status = ANY(%s)"
            params.append([s.value for s in statuses])
        rows = self._get_client().execute(
            f"SELECT payload FROM pdsc_clusters {where} ORDER BY updated_at DESC", tuple(params),
        )
        return [SemanticDiscoveryCluster.model_validate(r["payload"]) for r in rows]

    # ── 适用关系 ──

    def save_relation(self, relation: PolicyApplicabilityRelation) -> PolicyApplicabilityRelation:
        client = self._get_client()
        payload = json.dumps(relation.model_dump(mode="json"), ensure_ascii=False)
        client.execute(
            """
            INSERT INTO pdsc_policy_applicability_relations
                (relation_id, policy_metric_code, business_metric_code,
                 status, revision, payload, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (relation_id) DO UPDATE SET
                status = EXCLUDED.status,
                revision = EXCLUDED.revision,
                payload = EXCLUDED.payload,
                updated_at = EXCLUDED.updated_at
            """,
            (relation.relation_id, relation.policy_metric_code,
             relation.business_metric_code, relation.status, relation.revision,
             payload, relation.created_at, relation.updated_at),
        )
        return relation

    def get_relation(self, relation_id: str) -> PolicyApplicabilityRelation | None:
        rows = self._get_client().execute(
            "SELECT payload FROM pdsc_policy_applicability_relations WHERE relation_id = %s",
            (relation_id,),
        )
        return PolicyApplicabilityRelation.model_validate(rows[0]["payload"]) if rows else None

    def list_relations(self, business_metric_code: str | None = None) -> list[PolicyApplicabilityRelation]:
        params: tuple[Any, ...] = ()
        where = ""
        if business_metric_code:
            where = "WHERE business_metric_code = %s"
            params = (business_metric_code,)
        rows = self._get_client().execute(
            f"SELECT payload FROM pdsc_policy_applicability_relations {where}", params,
        )
        return [PolicyApplicabilityRelation.model_validate(r["payload"]) for r in rows]

    # ── 激活 ──

    def save_activation(self, activation: ClusterActivation) -> ClusterActivation:
        client = self._get_client()
        payload = json.dumps(activation.model_dump(mode="json"), ensure_ascii=False)
        client.execute(
            """
            INSERT INTO pdsc_activations (activation_id, cluster_id, status, payload, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (activation_id) DO UPDATE SET
                status = EXCLUDED.status,
                payload = EXCLUDED.payload,
                updated_at = EXCLUDED.updated_at
            """,
            (activation.activation_id, activation.cluster_id, activation.status.value,
             payload, activation.created_at, activation.updated_at),
        )
        return activation

    def get_activation(self, activation_id: str) -> ClusterActivation | None:
        rows = self._get_client().execute(
            "SELECT payload FROM pdsc_activations WHERE activation_id = %s", (activation_id,),
        )
        return ClusterActivation.model_validate(rows[0]["payload"]) if rows else None

    def list_activations(self, cluster_id: str | None = None) -> list[ClusterActivation]:
        params: tuple[Any, ...] = ()
        where = ""
        if cluster_id:
            where = "WHERE cluster_id = %s"
            params = (cluster_id,)
        rows = self._get_client().execute(
            f"SELECT payload FROM pdsc_activations {where} ORDER BY created_at DESC", params,
        )
        return [ClusterActivation.model_validate(r["payload"]) for r in rows]
