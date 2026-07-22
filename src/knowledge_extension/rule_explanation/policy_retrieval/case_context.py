from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawBusinessContext:
    case_id: str | None = None
    person_id: str | None = None
    settlement_id: str | None = None
    visit_id: str | None = None

    raw_person_type: str | None = None
    raw_insurance_type: str | None = None
    raw_service_type: str | None = None

    raw_hospital_level: str | None = None
    raw_hospital_name: str | None = None

    raw_admission_count: int | None = None
    raw_settlement_year: int | None = None

    raw_target_amount: float | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)

    # ★ SQL 可观测性：携带查询元数据
    query_sql: str = ""
    query_params: dict[str, Any] = field(default_factory=dict)
    query_duration_ms: float = 0.0
    query_result_columns: list[str] = field(default_factory=list)


@dataclass
class SemanticMappingResult:
    field: str
    raw_value: Any
    normalized_value: str | None
    confidence: float
    mapping_source: str
    warning: str | None = None


@dataclass
class CaseContext:
    case_id: str | None = None
    person_id: str | None = None
    settlement_id: str | None = None
    visit_id: str | None = None

    population: str | None = None
    insurance_type: str | None = None
    service_type: str | None = None
    hospital_level: str | None = None
    admission_order: str | None = None
    settlement_year: int | None = None

    target_amount: float | None = None
    target_object: str | None = None

    mapping_logs: list[SemanticMappingResult] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    raw_context: RawBusinessContext | None = None
