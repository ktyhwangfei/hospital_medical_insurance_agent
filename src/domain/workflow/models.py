"""Workflow 领域模型：声明式 Tool 编排，不引入通用 Graph/自由规划。

WorkflowExecutor 只是这些声明的一个"薄解释器"，不做动态规划。
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class MissingEvidenceRule(BaseModel):
    """静态澄清触发规则：缺失指定字段时直接要求澄清，不进入 Tool 调用。"""

    model_config = ConfigDict(frozen=True)

    field_name: str
    clarify_message: str


class WorkflowStep(BaseModel):
    """Workflow 中的一个 Tool 调用节点。

    input_mapping 声明步骤间数据流：键 = 工具入参名，值 = 引用表达式：
    - "context.<字段名>"：取执行上下文字段（如 settlement_id）
    - "<step_id>"：取上游步骤完整输出 dict
    - "<step_id>.<输出键>"：取上游步骤输出的某个键
    未声明 input_mapping 的步骤沿用既有行为：整包接收执行上下文。
    """

    model_config = ConfigDict(frozen=True)

    step_id: str
    tool_id: str
    description: str = ""
    input_mapping: dict[str, str] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    """静态 Workflow 定义：意图关键词 + 缺失证据规则 + Tool 调用序列。"""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    name: str
    description: str
    intent_keywords: list[str] = Field(min_length=1)
    missing_evidence_rules: list[MissingEvidenceRule] = Field(default_factory=list)
    steps: list[WorkflowStep] = Field(min_length=1)


class WorkflowStepStatus(StrEnum):
    """单个步骤的执行结果状态。"""

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class WorkflowStepResult(BaseModel):
    """单个步骤的执行结果，携带来源可追溯所需的不确定性说明。"""

    model_config = ConfigDict(frozen=True)

    step_id: str
    tool_id: str
    status: WorkflowStepStatus
    output: dict = Field(default_factory=dict)
    uncertainty: str | None = None


class WorkflowExecutionStatus(StrEnum):
    """Workflow 整体执行结果状态，与 PolicyQAPublicResult.answer_status 对齐。"""

    CLARIFY = "clarify"
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class WorkflowExecutionResult(BaseModel):
    """Workflow 一次执行的完整结果，供 public_result 映射为对外契约。"""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    status: WorkflowExecutionStatus
    step_results: list[WorkflowStepResult] = Field(default_factory=list)
    clarify_message: str | None = None
    uncertainties: list[str] = Field(default_factory=list)
