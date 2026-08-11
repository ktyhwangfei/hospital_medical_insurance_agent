"""政策规则编译器的类型化契约。"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


CompileStage = Literal[
    "INPUT_SNAPSHOT",
    "LLM_EXTRACTION",
    "CANONICALIZE",
    "COMPOSE",
    "RESOLVE",
    "DERIVE",
    "VALIDATE",
    "PUBLISH",
    "LEGACY_IMPORT",
]
CompileStatus = Literal["RUNNING", "PASS", "WARN", "REVIEW", "FAIL"]


class ValidationIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    issue_id: str
    severity: Literal["WARN", "REVIEW", "FAIL"]
    code: str
    stage: CompileStage
    fact_id: str | None = None
    rule_id: str | None = None
    message: str
    recommended_action: str


class PolicyExpression(BaseModel):
    model_config = ConfigDict(frozen=True)

    operator: Literal["ABSOLUTE", "MULTIPLY", "COMPLEMENT", "DIRECT_COPY"]
    reference: dict[str, Any] | None = None
    factor: Decimal | None = Field(default=None, gt=0, le=1)
    total: Decimal | None = Field(default=None, gt=0)


class PolicyFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    fact_id: str
    subject: str
    population: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    value: dict[str, Any] = Field(default_factory=dict)
    expression: PolicyExpression | None = None
    evidence: list[str] = Field(min_length=1)
    document_id: str | None = None
    unit_id: str | None = None
    extraction_id: str | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)


class CanonicalRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    subject: str
    population: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any]
    source_type: Literal["DIRECT", "DERIVED"] = "DIRECT"
    evidence: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    formula: PolicyExpression | None = None
    compiler_version: str = "1.0"
    rule_version: int = Field(default=1, ge=1)
    status: CompileStatus = "PASS"

    @field_validator("result", mode="before")
    @classmethod
    def normalize_result_ratio(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(value)
        if normalized.get("ratio") is not None:
            normalized["ratio"] = Decimal(str(normalized["ratio"]))
        return normalized

    @model_validator(mode="after")
    def validate_rule(self) -> "CanonicalRule":
        ratio = self.result.get("ratio")
        if ratio is not None:
            try:
                decimal_ratio = Decimal(str(ratio))
            except (InvalidOperation, ValueError) as exc:
                raise ValueError("ratio must be numeric") from exc
            if not Decimal("0") <= decimal_ratio <= Decimal("1"):
                raise ValueError("ratio must be between 0 and 1")
        if self.source_type == "DERIVED" and (not self.dependencies or self.formula is None):
            raise ValueError("derived rule requires dependencies and formula")
        return self


class CompileStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str
    run_id: str
    sequence_no: int = Field(ge=1)
    stage: CompileStage
    status: CompileStatus
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    issues: list[ValidationIssue] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    duration_ms: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class CompileRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    document_id: str
    unit_id: str
    extraction_id: str
    raw_input: dict[str, Any]
    llm_output: dict[str, Any]
    model_name: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    compiler_version: str = "1.0"
    status: CompileStatus = "RUNNING"
    metrics: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None


class CompilationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    rules: list[CanonicalRule] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    unresolved_relations: list[ValidationIssue] = Field(default_factory=list)
    steps: list[CompileStep] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    status: CompileStatus


class RulePublication(BaseModel):
    model_config = ConfigDict(frozen=True)

    release_id: str
    status: str = "published"
    published_at: datetime | None = None


class RuleTraceHistorySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    rule_version: int | None = None
    status: CompileStatus
    compiler_version: str
    started_at: datetime
    finished_at: datetime | None = None


class RuleCompilationTraceResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    rule: CanonicalRule | None = None
    run: CompileRun
    raw_input: dict[str, Any]
    llm_output: dict[str, Any]
    steps: list[CompileStep]
    issues: list[ValidationIssue] = Field(default_factory=list)
    publication: RulePublication | None = None
    history: list[RuleTraceHistorySummary] = Field(default_factory=list)
