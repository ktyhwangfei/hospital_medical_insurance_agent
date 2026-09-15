"""Tool / Workflow 可视化只读服务：把 Registry/静态 Workflow 定义投影为展示模型。

镜像 catalog/skill workbench 的只读聚合模式：不新增存储，只读现有注册信息。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.domain.workflow.models import WorkflowDefinition
from src.runtime.tool_registry.factory import get_tool_registry
from src.runtime.tool_registry.service import ToolRegistryService
from src.runtime.workflow.definitions import ALL_WORKFLOWS


class ToolSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    name: str
    description: str
    contract_kind: str
    target_ref: str
    risk_level: str
    status: str
    semantic_version: str
    bound: bool
    tags: list[str]
    # 输入/输出字段契约：{字段名: {type/required/description}}，供 Portal 优先展示。
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    # 执行细节：SQL / Milvus expr / 核心公式等底层实现描述，治理页展示到底。
    execution_detail: str = ""


class ToolCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ToolSummary]


class WorkflowStepSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    tool_id: str
    description: str
    tool_bound: bool
    input_mapping: dict[str, str]


class MissingEvidenceRuleSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    clarify_message: str


class WorkflowSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    name: str
    description: str
    intent_keywords: list[str]
    missing_evidence_rules: list[MissingEvidenceRuleSummary]
    steps: list[WorkflowStepSummary]


class WorkflowCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WorkflowSummary]


def _tool_summary(registry: ToolRegistryService, tool_id: str) -> ToolSummary | None:
    version = registry.get_tool(tool_id)
    if version is None:
        return None
    definition = version.definition
    return ToolSummary(
        tool_id=definition.tool_id,
        name=definition.name,
        description=definition.description,
        contract_kind=definition.contract_kind.value,
        target_ref=definition.target_ref,
        risk_level=definition.risk_level.value,
        status=version.status.value,
        semantic_version=version.semantic_version,
        bound=registry.is_bound(tool_id),
        tags=list(definition.tags),
        input_schema=dict(definition.input_schema),
        output_schema=dict(definition.output_schema),
        execution_detail=definition.execution_detail,
    )


def build_tool_catalog() -> ToolCatalog:
    registry = get_tool_registry()
    items = [
        summary
        for tool_id in registry.list_registered_tool_ids()
        if (summary := _tool_summary(registry, tool_id)) is not None
    ]
    return ToolCatalog(items=items)


def _workflow_summary(
    registry: ToolRegistryService, definition: WorkflowDefinition
) -> WorkflowSummary:
    return WorkflowSummary(
        workflow_id=definition.workflow_id,
        name=definition.name,
        description=definition.description,
        intent_keywords=list(definition.intent_keywords),
        missing_evidence_rules=[
            MissingEvidenceRuleSummary(
                field_name=rule.field_name, clarify_message=rule.clarify_message
            )
            for rule in definition.missing_evidence_rules
        ],
        steps=[
            WorkflowStepSummary(
                step_id=step.step_id,
                tool_id=step.tool_id,
                description=step.description,
                tool_bound=registry.is_bound(step.tool_id),
                input_mapping=dict(step.input_mapping),
            )
            for step in definition.steps
        ],
    )


def build_workflow_catalog() -> WorkflowCatalog:
    registry = get_tool_registry()
    return WorkflowCatalog(
        items=[_workflow_summary(registry, definition) for definition in ALL_WORKFLOWS]
    )
