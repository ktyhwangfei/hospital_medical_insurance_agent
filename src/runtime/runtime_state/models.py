from pydantic import BaseModel, Field


class ReasoningStep(BaseModel):
    """推理步骤 — 记录 Agent 的中间结论和推理链"""
    step_id: str
    claim: str                               # 中间结论/事实表述
    kind: str = "fact"                       # "fact" | "inference" | "hypothesis" | "verified"
    depends_on: list[str] = Field(default_factory=list)  # 依赖的 step_id
    confidence: float = 0.5
    citations: list[str] = Field(default_factory=list)    # 来源
    source_memory_ids: list[str] = Field(default_factory=list)  # 依赖的 memory_id


class Hypothesis(BaseModel):
    """假设 — 待验证的推理假设"""
    hypothesis_id: str
    statement: str
    status: str = "open"          # open | confirmed | rejected
    tested_by: list[str] = Field(default_factory=list)


class ReasoningState(BaseModel):
    """推理状态 — 会话级临时态，记录推理链、假设和中间结论"""
    session_id: str
    workflow_id: str | None = None
    chain: list[ReasoningStep] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class StepState(BaseModel):
    step_id: str
    status: str
    input_refs: list[str] = Field(default_factory=list)
    output_refs: list[str] = Field(default_factory=list)
    error: str | None = None
    audit_refs: list[str] = Field(default_factory=list)
    # 新增：推理链
    reasoning_chain: list[ReasoningStep] = Field(default_factory=list)


class WorkflowInstance(BaseModel):
    workflow_id: str
    scenario: str
    status: str
    current_step: str | None = None
    steps: list[StepState] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
    knowledge_events: list[dict] = Field(default_factory=list)
    knowledge_degradation_reasons: list[str] = Field(default_factory=list)
    session_id: str | None = None
    patient_id: str | None = None
    # 新增：推理状态
    reasoning_state: ReasoningState | None = None
