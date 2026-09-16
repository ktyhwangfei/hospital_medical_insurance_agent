"""WorkflowExecutor：静态 Workflow 定义的薄解释器。

不做动态规划、不引入通用 Graph 框架；只按 WorkflowDefinition.steps 顺序
执行 Tool、代码侧白名单领域处理器和输出投影，节点失败即降级为 unavailable，
不重试、不回退到自由生成，遵循"来源可追溯、不编造"硬约束。

步骤间数据流：通过 WorkflowStep.input_mapping 声明式引用上游输出；
上游步骤 unavailable 时，依赖它的下游步骤同样降级为 unavailable（fail-closed）。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from src.domain.workflow.models import (
    DecisionNode,
    DomainNode,
    OutputNode,
    ToolNode,
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
    WorkflowStepResult,
    WorkflowStepStatus,
)
from src.runtime.tool_registry.service import ToolInvocationError, ToolRegistryService

_CONTEXT_REF_PREFIX = "context."


class DomainContractError(Exception):
    """领域节点输入或输出未通过强类型契约校验。"""


class DomainExecutionError(Exception):
    """领域节点实现执行失败；公开结果不携带原始异常。"""


@dataclass(frozen=True)
class DomainHandler:
    """领域处理器白名单条目：实现与 Pydantic 输入输出契约绑定。"""

    input_model: type[BaseModel]
    output_model: type[BaseModel]
    implementation: Callable[..., Any]

    async def invoke(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self.input_model.model_validate(kwargs)
        except ValidationError as exc:
            raise DomainContractError("输入不符合契约") from exc

        try:
            result = self.implementation(**payload.model_dump())
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise DomainExecutionError("领域节点执行失败") from exc
        try:
            return self.output_model.model_validate(result).model_dump()
        except ValidationError as exc:
            raise DomainContractError("输出不符合契约") from exc


class _MissingInput:
    """引用解析失败的哨兵值，区分"值为 None"与"引用不存在"。"""


def _resolve_input_ref(
    ref: str,
    context: dict[str, Any],
    step_outputs: dict[str, dict],
) -> Any | type[_MissingInput]:
    """解析 input_mapping 引用表达式：context.<字段> / <step_id> / <step_id>.<键>。"""
    if ref.startswith(_CONTEXT_REF_PREFIX):
        key = ref[len(_CONTEXT_REF_PREFIX):]
        if key in context:
            return context[key]
        return _MissingInput

    head, _, tail = ref.partition(".")
    output = step_outputs.get(head)
    if output is None:
        return _MissingInput
    if not tail:
        return output
    if tail in output:
        return output[tail]
    return _MissingInput


class WorkflowExecutor:
    def __init__(
        self,
        tool_registry: ToolRegistryService,
        *,
        domain_handlers: dict[tuple[str, str], DomainHandler] | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._domain_handlers = domain_handlers or {}

    async def execute(
        self,
        definition: WorkflowDefinition,
        *,
        context: dict[str, Any],
    ) -> WorkflowExecutionResult:
        for rule in definition.missing_evidence_rules:
            if not context.get(rule.field_name):
                return WorkflowExecutionResult(
                    workflow_id=definition.workflow_id,
                    status=WorkflowExecutionStatus.CLARIFY,
                    clarify_message=rule.clarify_message,
                )

        step_results: list[WorkflowStepResult] = []
        step_outputs: dict[str, dict] = {}
        uncertainties: list[str] = []
        step_indexes = {step.step_id: index for index, step in enumerate(definition.steps)}
        step_index = 0
        while step_index < len(definition.steps):
            step = definition.steps[step_index]
            if isinstance(step, DecisionNode):
                value = _resolve_input_ref(step.condition_ref, context, step_outputs)
                if value is _MissingInput:
                    message = (
                        f"步骤 {step.step_id}（decision）依赖的上游输入缺失："
                        f"{step.condition_ref}，无法执行"
                    )
                    uncertainties.append(message)
                    step_results.append(
                        WorkflowStepResult(
                            step_id=step.step_id,
                            node_type=step.node_type,
                            status=WorkflowStepStatus.UNAVAILABLE,
                            uncertainty=message,
                        )
                    )
                    break
                matched = value == step.expected_value
                selected_step_id = (
                    step.match_step_id if matched else step.default_step_id
                )
                step_outputs[step.step_id] = {
                    "matched": matched,
                    "selected_step_id": selected_step_id,
                }
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        status=WorkflowStepStatus.COMPLETED,
                        output=step_outputs[step.step_id],
                        selected_step_id=selected_step_id,
                    )
                )
                step_index = step_indexes[selected_step_id]
                continue
            if isinstance(step, OutputNode):
                value = _resolve_input_ref(step.source_ref, context, step_outputs)
                if value is _MissingInput:
                    message = (
                        f"步骤 {step.step_id}（output）依赖的上游输入缺失："
                        f"{step.source_ref}，无法执行"
                    )
                    uncertainties.append(message)
                    step_results.append(
                        WorkflowStepResult(
                            step_id=step.step_id,
                            node_type=step.node_type,
                            status=WorkflowStepStatus.UNAVAILABLE,
                            uncertainty=message,
                        )
                    )
                    break
                output_dict = value if isinstance(value, dict) else {"value": value}
                step_outputs[step.step_id] = output_dict
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        status=WorkflowStepStatus.COMPLETED,
                        output=output_dict,
                    )
                )
                break

            if step.input_mapping:
                kwargs: dict[str, Any] = {}
                missing_refs: list[str] = []
                for arg_name, ref in step.input_mapping.items():
                    value = _resolve_input_ref(ref, context, step_outputs)
                    if value is _MissingInput:
                        missing_refs.append(ref)
                    else:
                        kwargs[arg_name] = value
                if missing_refs:
                    node_ref = (
                        step.tool_id
                        if isinstance(step, ToolNode)
                        else f"{step.handler_id}:{step.handler_version}"
                    )
                    message = (
                        f"步骤 {step.step_id}（{node_ref}）依赖的上游输入缺失："
                        f"{', '.join(missing_refs)}，无法执行"
                    )
                    uncertainties.append(message)
                    step_results.append(
                        WorkflowStepResult(
                            step_id=step.step_id,
                            node_type=step.node_type,
                            tool_id=step.tool_id if isinstance(step, ToolNode) else None,
                            handler_id=step.handler_id if isinstance(step, DomainNode) else None,
                            handler_version=(
                                step.handler_version if isinstance(step, DomainNode) else None
                            ),
                            status=WorkflowStepStatus.UNAVAILABLE,
                            uncertainty=message,
                        )
                    )
                    step_index += 1
                    continue
            else:
                kwargs = dict(context)

            try:
                if isinstance(step, ToolNode):
                    output = await self._tool_registry.invoke(step.tool_id, **kwargs)
                else:
                    handler = self._domain_handlers.get(
                        (step.handler_id, step.handler_version)
                    )
                    if handler is None:
                        raise ToolInvocationError(
                            f"领域节点 {step.handler_id}:{step.handler_version} 未绑定实现"
                        )
                    output = await handler.invoke(kwargs)
                output_dict = output if isinstance(output, dict) else {"value": output}
                step_outputs[step.step_id] = output_dict
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        tool_id=step.tool_id if isinstance(step, ToolNode) else None,
                        handler_id=step.handler_id if isinstance(step, DomainNode) else None,
                        handler_version=(
                            step.handler_version if isinstance(step, DomainNode) else None
                        ),
                        status=WorkflowStepStatus.COMPLETED,
                        output=output_dict,
                    )
                )
            except DomainContractError as exc:
                node_ref = f"{step.handler_id}:{step.handler_version}"
                message = f"步骤 {step.step_id}（{node_ref}）领域节点契约校验失败：{exc}"
                uncertainties.append(message)
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        handler_id=step.handler_id,
                        handler_version=step.handler_version,
                        status=WorkflowStepStatus.UNAVAILABLE,
                        uncertainty=message,
                    )
                )
            except DomainExecutionError as exc:
                node_ref = f"{step.handler_id}:{step.handler_version}"
                message = f"步骤 {step.step_id}（{node_ref}）{exc}"
                uncertainties.append(message)
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        handler_id=step.handler_id,
                        handler_version=step.handler_version,
                        status=WorkflowStepStatus.UNAVAILABLE,
                        uncertainty=message,
                    )
                )
            except ToolInvocationError as exc:
                node_ref = (
                    step.tool_id
                    if isinstance(step, ToolNode)
                    else f"{step.handler_id}:{step.handler_version}"
                )
                message = f"步骤 {step.step_id}（{node_ref}）暂无可用实现：{exc}"
                uncertainties.append(message)
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        tool_id=step.tool_id if isinstance(step, ToolNode) else None,
                        handler_id=step.handler_id if isinstance(step, DomainNode) else None,
                        handler_version=(
                            step.handler_version if isinstance(step, DomainNode) else None
                        ),
                        status=WorkflowStepStatus.UNAVAILABLE,
                        uncertainty=message,
                    )
                )
            except Exception as exc:
                # fail-closed 兜底（2026-09-15 SSE 静默断流修复）：工具/领域节点内部
                # 未预期异常（如语义规划失败）不得穿透崩掉 SSE 流；降级 unavailable
                node_ref = (
                    step.tool_id
                    if isinstance(step, ToolNode)
                    else f"{step.handler_id}:{step.handler_version}"
                )
                message = f"步骤 {step.step_id}（{node_ref}）执行失败：{exc}"
                uncertainties.append(message)
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        node_type=step.node_type,
                        tool_id=step.tool_id if isinstance(step, ToolNode) else None,
                        handler_id=step.handler_id if isinstance(step, DomainNode) else None,
                        handler_version=(
                            step.handler_version if isinstance(step, DomainNode) else None
                        ),
                        status=WorkflowStepStatus.UNAVAILABLE,
                        uncertainty=message,
                    )
                )
            step_index += 1

        overall_status = (
            WorkflowExecutionStatus.UNAVAILABLE
            if uncertainties
            else WorkflowExecutionStatus.COMPLETE
        )
        return WorkflowExecutionResult(
            workflow_id=definition.workflow_id,
            status=overall_status,
            step_results=step_results,
            uncertainties=uncertainties,
        )
