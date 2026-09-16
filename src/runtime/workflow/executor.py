"""WorkflowExecutor：静态 Workflow 定义的薄解释器。

不做动态规划、不引入通用 Graph 框架；只按 WorkflowDefinition.steps 顺序
调用 ToolRegistryService，Tool 调用失败即降级为该步骤 unavailable，
不重试、不回退到自由生成，遵循"来源可追溯、不编造"硬约束。

步骤间数据流：通过 WorkflowStep.input_mapping 声明式引用上游输出；
上游步骤 unavailable 时，依赖它的下游步骤同样降级为 unavailable（fail-closed）。
"""

from __future__ import annotations

from typing import Any

from src.domain.workflow.models import (
    WorkflowDefinition,
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
    WorkflowStepResult,
    WorkflowStepStatus,
)
from src.runtime.tool_registry.service import ToolInvocationError, ToolRegistryService

_CONTEXT_REF_PREFIX = "context."


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
    def __init__(self, tool_registry: ToolRegistryService) -> None:
        self._tool_registry = tool_registry

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
        for step in definition.steps:
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
                    message = (
                        f"步骤 {step.step_id}（{step.tool_id}）依赖的上游输入缺失："
                        f"{', '.join(missing_refs)}，无法执行"
                    )
                    uncertainties.append(message)
                    step_results.append(
                        WorkflowStepResult(
                            step_id=step.step_id,
                            tool_id=step.tool_id,
                            status=WorkflowStepStatus.UNAVAILABLE,
                            uncertainty=message,
                        )
                    )
                    continue
            else:
                kwargs = dict(context)

            try:
                output = await self._tool_registry.invoke(step.tool_id, **kwargs)
                output_dict = output if isinstance(output, dict) else {"value": output}
                step_outputs[step.step_id] = output_dict
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        tool_id=step.tool_id,
                        status=WorkflowStepStatus.COMPLETED,
                        output=output_dict,
                    )
                )
            except ToolInvocationError as exc:
                message = f"步骤 {step.step_id}（{step.tool_id}）暂无可用数据源：{exc}"
                uncertainties.append(message)
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        tool_id=step.tool_id,
                        status=WorkflowStepStatus.UNAVAILABLE,
                        uncertainty=message,
                    )
                )
            except Exception as exc:
                # fail-closed 兜底：工具内部领域异常（如语义规划失败）不得穿透
                # 崩掉 SSE 流；该步骤降级 unavailable 并如实记录不确定性
                message = f"步骤 {step.step_id}（{step.tool_id}）执行失败：{exc}"
                uncertainties.append(message)
                step_results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        tool_id=step.tool_id,
                        status=WorkflowStepStatus.UNAVAILABLE,
                        uncertainty=message,
                    )
                )

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
