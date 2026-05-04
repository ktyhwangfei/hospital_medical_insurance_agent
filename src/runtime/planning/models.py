from enum import Enum

from pydantic import BaseModel, Field


class StepType(str, Enum):
    ADAPTER_CALL = "adapter_call"
    KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
    RESULT_BUILDING = "result_building"
    TASK_CREATION = "task_creation"
    HUMAN_CONFIRMATION = "human_confirmation"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PlanStep(BaseModel):
    step_id: str
    step_type: StepType
    capability: str
    depends_on: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_human_confirmation: bool = False


class ExecutionPlan(BaseModel):
    workflow_id: str
    scenario: str
    goal: str
    steps: list[PlanStep]
    output_requirements: list[str] = Field(default_factory=list)
