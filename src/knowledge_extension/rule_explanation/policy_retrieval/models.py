from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field
from dataclasses import dataclass, field


class PolicyNode(BaseModel):
    node_id: str
    parent_id: str | None = None
    policy_id: str | None = None
    policy_title: str | None = None
    level: int | None = None
    path_text: str | None = None
    current_text: str
    full_context_text: str | None = None
    chunk_type: str | None = None
    keywords: list[str] = Field(default_factory=list)
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding_text: str | None = None


class PolicyFact(BaseModel):
    fact_id: str
    source_node_id: str | None = None
    policy_id: str | None = None
    policy_title: str | None = None

    fact_type: Literal[
        "deductible", "payment_ratio", "cap", "formula", "condition", "inclusion", "exclusion", "limit"
    ] | str

    subject: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    value: Any | None = None
    value_map: dict[str, Any] | None = None
    formula: dict[str, Any] | None = None
    evidence_text: str = ""

    derived: bool = False
    inferred: bool = False
    derivation_basis: str | None = None
    uncertainty_reason: str | None = None

    keywords: list[str] = Field(default_factory=list)
    dimensions: dict[str, Any] = Field(default_factory=dict)
    knowledge_group_id: str | None = None
    knowledge_group_type: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    embedding_text: str | None = None

    # Milvus 标量冗余字段
    population: str = "unknown"
    service_type: str = "unknown"
    insurance_type: str = "unknown"
    hospital_level: str = "unknown"
    admission_order: str = "unknown"
    amount: float | None = None
    ratio: float | None = None
    unit: str = "unknown"


@dataclass
class SearchQuery:
    question: str
    intent: str = "qa"
    target_object: str | None = None
    target_value: float | None = None
    fact_types: list[str] = field(default_factory=list)
    population: str | None = None
    service_type: str | None = None
    hospital_level: str | None = None
    admission_order: str | None = None
    need_formula: bool = False
    need_calculation_explanation: bool = False
    top_k: int = 10


@dataclass
class SearchHit:
    collection: str
    id: str
    score: float | None
    entity: dict[str, Any]
    rerank_score: float | None = None
    rerank_debug: list[str] = field(default_factory=list)


@dataclass
class PickedEvidence:
    nodes: list[SearchHit]
    facts: list[SearchHit]
    search_query: SearchQuery
    warnings: list[str] = field(default_factory=list)

