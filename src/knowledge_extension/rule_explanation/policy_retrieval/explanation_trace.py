from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExplanationStep:
    step: int
    description: str
    formula: str | None = None
    value: Any | None = None
    source_fact_ids: list[str] = field(default_factory=list)
    source_node_ids: list[str] = field(default_factory=list)


@dataclass
class ExplanationTrace:
    trace_id: str
    question: str
    intent: str
    target_object: str | None = None
    target_value: Any | None = None
    used_fact_ids: list[str] = field(default_factory=list)
    used_node_ids: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    calculation_steps: list[ExplanationStep] = field(default_factory=list)
    evidence_texts: list[str] = field(default_factory=list)
    confidence: float = 0.0
    final_explanation: str = ""
