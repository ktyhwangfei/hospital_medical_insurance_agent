"""Workflow 领域模型：声明式类型化节点编排，不引入通用 Graph/自由规划。

WorkflowExecutor 只是这些声明的一个"薄解释器"，不做动态规划。
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MissingEvidenceRule(BaseModel):
    """静态澄清触发规则：缺失指定字段时直接要求澄清，不进入 Tool 调用。"""

    model_config = ConfigDict(frozen=True)

    field_name: str
    clarify_message: str


class WorkflowNodeType(StrEnum):
    """首期支持的 Workflow 节点类型。"""

    TOOL = "tool"
    DOMAIN = "domain"
    DECISION = "decision"
    OUTPUT = "output"


class ToolNode(BaseModel):
    """Workflow 中的一个 Tool 调用节点。

    input_mapping 声明步骤间数据流：键 = 工具入参名，值 = 引用表达式：
    - "context.<字段名>"：取执行上下文字段（如 settlement_id）
    - "<step_id>"：取上游步骤完整输出 dict
    - "<step_id>.<输出键>"：取上游步骤输出的某个键
    未声明 input_mapping 的步骤沿用既有行为：整包接收执行上下文。
    """

    model_config = ConfigDict(frozen=True)

    node_type: Literal[WorkflowNodeType.TOOL] = WorkflowNodeType.TOOL
    step_id: str
    tool_id: str
    description: str = ""
    input_mapping: dict[str, str] = Field(default_factory=dict)


class DomainNode(BaseModel):
    """代码侧白名单登记的确定性医保业务节点。"""

    model_config = ConfigDict(frozen=True)

    node_type: Literal[WorkflowNodeType.DOMAIN] = WorkflowNodeType.DOMAIN
    step_id: str
    handler_id: str
    handler_version: str
    description: str = ""
    input_mapping: dict[str, str] = Field(default_factory=dict)


class DecisionNode(BaseModel):
    """按上游事实选择一个前向分支，不支持表达式、循环或动态目标。"""

    model_config = ConfigDict(frozen=True)

    node_type: Literal[WorkflowNodeType.DECISION] = WorkflowNodeType.DECISION
    step_id: str
    condition_ref: str
    expected_value: Any
    match_step_id: str
    default_step_id: str
    description: str = ""


class OutputNode(BaseModel):
    """把指定上游节点结果声明为 Workflow 最终输出。"""

    model_config = ConfigDict(frozen=True)

    node_type: Literal[WorkflowNodeType.OUTPUT] = WorkflowNodeType.OUTPUT
    step_id: str
    source_ref: str
    description: str = ""


# 保留既有名称，避免 Tool-only Workflow 和调用方一次性迁移。
WorkflowStep = ToolNode
WorkflowNode = Annotated[
    ToolNode | DomainNode | DecisionNode | OutputNode, Field(discriminator="node_type")
]


class WorkflowDefinition(BaseModel):
    """静态 Workflow 定义：意图关键词 + 缺失证据规则 + 节点序列。"""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    name: str
    description: str
    intent_keywords: list[str] = Field(min_length=1)
    missing_evidence_rules: list[MissingEvidenceRule] = Field(default_factory=list)
    steps: list[WorkflowNode] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_static_control_flow(self) -> "WorkflowDefinition":
        """发布前拒绝重复节点、未知目标和回跳，保持解释器有界。"""
        indexes = {step.step_id: index for index, step in enumerate(self.steps)}
        if len(indexes) != len(self.steps):
            raise ValueError("Workflow 节点 step_id 必须唯一")
        for index, step in enumerate(self.steps):
            if not isinstance(step, DecisionNode):
                continue
            for target in (step.match_step_id, step.default_step_id):
                target_index = indexes.get(target)
                if target_index is None:
                    raise ValueError(f"DecisionNode 目标节点不存在：{target}")
                if target_index <= index:
                    raise ValueError("DecisionNode 目标必须位于决策节点之后，禁止回跳")
        return self


class WorkflowStepStatus(StrEnum):
    """单个步骤的执行结果状态。"""

    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"


class WorkflowStepResult(BaseModel):
    """单个步骤的执行结果，携带来源可追溯所需的不确定性说明。"""

    model_config = ConfigDict(frozen=True)

    step_id: str
    node_type: WorkflowNodeType
    tool_id: str | None = None
    handler_id: str | None = None
    handler_version: str | None = None
    selected_step_id: str | None = None
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


class WorkflowConfigOverride(BaseModel):
    """Workflow 治理覆盖（关键词 / 启停），按院区维度存放。

    `hospital_code=""` 表示平台全局默认覆盖；院区行优先于全局行，
    全局行优先于代码内声明（definitions.py）。设计目标：院区个性化不再
    需要改代码重发版（一套产品多院复用）。
    """

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    hospital_code: str = ""
    enabled: bool = True
    # None = 继承平台默认关键词（区别于空列表 = 显式清空）
    intent_keywords: list[str] | None = None
    updated_by: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
