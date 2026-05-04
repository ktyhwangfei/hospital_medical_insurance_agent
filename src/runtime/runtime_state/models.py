from pydantic import BaseModel, Field


class StepState(BaseModel):
    step_id: str
    status: str
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    error: str | None = None
    audit_refs: list[str] = Field(default_factory=list)


class WorkflowInstance(BaseModel):
    workflow_id: str
    scenario: str
    status: str
    current_step: str | None = None
    steps: list[StepState] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
    knowledge_events: list[dict] = Field(default_factory=list)
    knowledge_degradation_reasons: list[str] = Field(default_factory=list)
