from __future__ import annotations

from dataclasses import dataclass, field

from .query_understanding import understand_query


@dataclass
class ContextRequirement:
    target_object: str | None = None
    target_value: float | None = None
    required_fields: list[str] = field(default_factory=list)


def analyze_context_requirement(question: str) -> ContextRequirement:
    sq = understand_query(question)

    required: list[str] = []

    if sq.target_object == "deductible":
        required = [
            "population",
            "insurance_type",
            "service_type",
            "hospital_level",
            "admission_order",
            "settlement_year",
        ]

    elif sq.target_object == "payment_ratio":
        required = [
            "population",
            "insurance_type",
            "service_type",
            "hospital_level",
        ]

    elif sq.target_object == "cap":
        required = [
            "population",
            "insurance_type",
            "service_type",
            "settlement_year",
        ]

    return ContextRequirement(
        target_object=sq.target_object,
        target_value=sq.target_value,
        required_fields=required,
    )
