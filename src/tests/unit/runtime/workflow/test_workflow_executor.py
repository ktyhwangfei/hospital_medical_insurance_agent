import os

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest
from pydantic import BaseModel

from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolStatus,
    ToolVersion,
)
from src.domain.workflow.models import (
    DecisionNode,
    DomainNode,
    MissingEvidenceRule,
    OutputNode,
    WorkflowDefinition,
    WorkflowExecutionStatus,
    WorkflowStep,
)
from src.runtime.tool_registry.service import ToolRegistryService
from src.runtime.workflow.executor import DomainHandler, WorkflowExecutor


class _DoubleInput(BaseModel):
    amount: int


class _DoubleOutput(BaseModel):
    doubled: int


def _tool_version(tool_id: str) -> ToolVersion:
    return ToolVersion(
        version_id=f"tv-{tool_id}",
        tool_id=tool_id,
        semantic_version="1.0.0",
        definition=ToolDefinition(
            tool_id=tool_id,
            name=tool_id,
            description=tool_id,
            contract_kind=ToolContractKind.FUNCTION,
            target_ref="src.runtime.policy_qa.settlement_data_provider.create_settlement_data_provider",
        ),
        status=ToolStatus.MATERIALIZED,
    )


def _definition(**overrides) -> WorkflowDefinition:
    defaults = dict(
        workflow_id="wf_demo",
        name="示例 Workflow",
        description="用于测试的示例 Workflow",
        intent_keywords=["退费"],
        missing_evidence_rules=[
            MissingEvidenceRule(field_name="settlement_id", clarify_message="请提供结算单号")
        ],
        steps=[WorkflowStep(step_id="s1", tool_id="tool_a")],
    )
    defaults.update(overrides)
    return WorkflowDefinition(**defaults)


@pytest.mark.asyncio
async def test_execute_returns_clarify_when_missing_evidence() -> None:
    registry = ToolRegistryService()
    executor = WorkflowExecutor(registry)

    result = await executor.execute(_definition(), context={"settlement_id": None})

    assert result.status == WorkflowExecutionStatus.CLARIFY
    assert result.clarify_message == "请提供结算单号"


@pytest.mark.asyncio
async def test_execute_completes_when_all_steps_bound() -> None:
    registry = ToolRegistryService()
    registry.register(_tool_version("tool_a"), implementation=lambda **kwargs: {"ok": True})
    executor = WorkflowExecutor(registry)

    result = await executor.execute(
        _definition(missing_evidence_rules=[]), context={"settlement_id": "S001"}
    )

    assert result.status == WorkflowExecutionStatus.COMPLETE
    assert result.step_results[0].status.value == "completed"


@pytest.mark.asyncio
async def test_execute_degrades_to_unavailable_when_step_unbound() -> None:
    registry = ToolRegistryService()
    executor = WorkflowExecutor(registry)

    result = await executor.execute(
        _definition(missing_evidence_rules=[]), context={"settlement_id": "S001"}
    )

    assert result.status == WorkflowExecutionStatus.UNAVAILABLE
    assert result.step_results[0].status.value == "unavailable"
    assert result.uncertainties


@pytest.mark.asyncio
async def test_execute_chains_step_outputs_via_input_mapping() -> None:
    registry = ToolRegistryService()
    registry.register(
        _tool_version("tool_fetch"),
        implementation=lambda settlement_id: {"settlement_id": settlement_id, "amount": 100},
    )

    async def _consume(settlement_fact: dict) -> dict:
        return {"doubled": settlement_fact["amount"] * 2}

    registry.register(_tool_version("tool_consume"), implementation=_consume)
    executor = WorkflowExecutor(registry)

    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            WorkflowStep(step_id="fetch", tool_id="tool_fetch"),
            WorkflowStep(
                step_id="consume",
                tool_id="tool_consume",
                input_mapping={"settlement_fact": "fetch"},
            ),
        ],
    )
    result = await executor.execute(definition, context={"settlement_id": "S001"})

    assert result.status == WorkflowExecutionStatus.COMPLETE
    assert result.step_results[1].output["doubled"] == 200


@pytest.mark.asyncio
async def test_execute_resolves_output_key_reference() -> None:
    registry = ToolRegistryService()
    registry.register(
        _tool_version("tool_fetch"),
        implementation=lambda settlement_id: {"amount": 50},
    )
    registry.register(
        _tool_version("tool_consume"),
        implementation=lambda amount: {"received": amount},
    )
    executor = WorkflowExecutor(registry)

    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            WorkflowStep(step_id="fetch", tool_id="tool_fetch"),
            WorkflowStep(
                step_id="consume",
                tool_id="tool_consume",
                input_mapping={"amount": "fetch.amount"},
            ),
        ],
    )
    result = await executor.execute(definition, context={"settlement_id": "S001"})

    assert result.status == WorkflowExecutionStatus.COMPLETE
    assert result.step_results[1].output["received"] == 50


@pytest.mark.asyncio
async def test_execute_degrades_downstream_when_upstream_unbound() -> None:
    """上游 unavailable 时，依赖它的下游步骤应 fail-closed 同步降级。"""
    registry = ToolRegistryService()
    registry.register(
        _tool_version("tool_consume"),
        implementation=lambda settlement_fact: {"never": True},
    )
    executor = WorkflowExecutor(registry)

    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            WorkflowStep(step_id="fetch", tool_id="tool_fetch"),
            WorkflowStep(
                step_id="consume",
                tool_id="tool_consume",
                input_mapping={"settlement_fact": "fetch"},
            ),
        ],
    )
    result = await executor.execute(definition, context={"settlement_id": "S001"})

    assert result.status == WorkflowExecutionStatus.UNAVAILABLE
    statuses = {step.step_id: step.status.value for step in result.step_results}
    assert statuses["fetch"] == "unavailable"
    assert statuses["consume"] == "unavailable"
    assert any("fetch" in message for message in result.uncertainties)
    assert all(step.output == {} for step in result.step_results)


@pytest.mark.asyncio
async def test_execute_supports_context_field_reference() -> None:
    registry = ToolRegistryService()
    registry.register(
        _tool_version("tool_consume"),
        implementation=lambda settlement_id: {"echo": settlement_id},
    )
    executor = WorkflowExecutor(registry)

    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            WorkflowStep(
                step_id="consume",
                tool_id="tool_consume",
                input_mapping={"settlement_id": "context.settlement_id"},
            ),
        ],
    )
    result = await executor.execute(definition, context={"settlement_id": "S009"})

    assert result.status == WorkflowExecutionStatus.COMPLETE
    assert result.step_results[0].output["echo"] == "S009"


@pytest.mark.asyncio
async def test_execute_domain_error_inside_tool_degrades_step_not_crash() -> None:
    """缺陷回归（2026-09-15 SSE 静默断流）：Tool 内部抛领域异常（如
    SemanticQueryPlanningError）曾被穿透，导致 SSE 生成器崩溃、前端静默断流。
    正确语义：fail-closed——该步骤降级 unavailable + uncertainty，绝不穿透。"""
    registry = ToolRegistryService()

    def _boom(**_kwargs):
        raise ValueError("锚点字段未在已发布模型登记为 identifier")

    registry.register(_tool_version("tool_boom"), implementation=_boom)
    executor = WorkflowExecutor(registry)

    definition = _definition(
        missing_evidence_rules=[],
        steps=[WorkflowStep(step_id="s1", tool_id="tool_boom")],
    )
    result = await executor.execute(definition, context={"settlement_id": "S001"})

    assert result.status == WorkflowExecutionStatus.UNAVAILABLE
    assert result.step_results[0].status.value == "unavailable"
    assert any("锚点字段" in message for message in result.uncertainties)
@pytest.mark.asyncio
async def test_execute_supports_tool_domain_and_output_nodes() -> None:
    registry = ToolRegistryService()
    registry.register(
        _tool_version("tool_fetch"),
        implementation=lambda settlement_id: {"amount": 50},
    )
    executor = WorkflowExecutor(
        registry,
        domain_handlers={
            ("double_amount", "1.0.0"): DomainHandler(
                input_model=_DoubleInput,
                output_model=_DoubleOutput,
                implementation=lambda amount: {"doubled": amount * 2},
            )
        },
    )
    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            WorkflowStep(step_id="fetch", tool_id="tool_fetch"),
            DomainNode(
                step_id="calculate",
                handler_id="double_amount",
                handler_version="1.0.0",
                input_mapping={"amount": "fetch.amount"},
            ),
            OutputNode(step_id="result", source_ref="calculate"),
        ],
    )

    result = await executor.execute(definition, context={"settlement_id": "S001"})

    assert result.status == WorkflowExecutionStatus.COMPLETE
    assert [step.node_type for step in result.step_results] == [
        "tool",
        "domain",
        "output",
    ]
    assert result.step_results[-1].output == {"doubled": 100}


@pytest.mark.asyncio
async def test_execute_fails_closed_for_unregistered_domain_handler() -> None:
    executor = WorkflowExecutor(ToolRegistryService())
    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            DomainNode(
                step_id="calculate",
                handler_id="unknown_handler",
                handler_version="9.9.9",
            )
        ],
    )

    result = await executor.execute(definition, context={"settlement_id": "S001"})

    assert result.status == WorkflowExecutionStatus.UNAVAILABLE
    assert result.step_results[0].handler_id == "unknown_handler"
    assert "未绑定实现" in result.uncertainties[0]


@pytest.mark.asyncio
async def test_execute_fails_closed_when_domain_output_breaks_contract() -> None:
    executor = WorkflowExecutor(
        ToolRegistryService(),
        domain_handlers={
            ("broken", "1.0.0"): DomainHandler(
                input_model=_DoubleInput,
                output_model=_DoubleOutput,
                implementation=lambda amount: {"unexpected": amount},
            )
        },
    )
    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            DomainNode(
                step_id="broken",
                handler_id="broken",
                handler_version="1.0.0",
                input_mapping={"amount": "context.amount"},
            )
        ],
    )

    result = await executor.execute(
        definition, context={"settlement_id": "S001", "amount": 10}
    )

    assert result.status == WorkflowExecutionStatus.UNAVAILABLE
    assert "输出不符合契约" in result.uncertainties[0]


@pytest.mark.asyncio
async def test_execute_fails_closed_when_domain_handler_raises() -> None:
    def _raise(_amount: int) -> dict:
        raise RuntimeError("sensitive implementation detail")

    executor = WorkflowExecutor(
        ToolRegistryService(),
        domain_handlers={
            ("broken", "1.0.0"): DomainHandler(
                input_model=_DoubleInput,
                output_model=_DoubleOutput,
                implementation=lambda amount: _raise(amount),
            )
        },
    )
    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            DomainNode(
                step_id="broken",
                handler_id="broken",
                handler_version="1.0.0",
                input_mapping={"amount": "context.amount"},
            )
        ],
    )

    result = await executor.execute(
        definition, context={"settlement_id": "S001", "amount": 10}
    )

    assert result.status == WorkflowExecutionStatus.UNAVAILABLE
    assert "领域节点执行失败" in result.uncertainties[0]
    assert "sensitive implementation detail" not in result.uncertainties[0]


@pytest.mark.asyncio
async def test_execute_decision_routes_to_the_selected_forward_node() -> None:
    registry = ToolRegistryService()
    registry.register(
        _tool_version("tool_fetch"),
        implementation=lambda **kwargs: {"match": {"result": "approved"}, "default": {"result": "manual_review"}},
    )
    executor = WorkflowExecutor(registry)
    definition = _definition(
        missing_evidence_rules=[],
        steps=[
            WorkflowStep(step_id="fetch", tool_id="tool_fetch"),
            DecisionNode(
                step_id="route",
                condition_ref="context.approved",
                expected_value=True,
                match_step_id="selected",
                default_step_id="default",
            ),
            OutputNode(step_id="default", source_ref="fetch.default"),
            OutputNode(step_id="selected", source_ref="fetch.match"),
        ],
    )

    result = await executor.execute(definition, context={"approved": True})

    assert [step.step_id for step in result.step_results] == ["fetch", "route", "selected"]
    assert result.step_results[1].selected_step_id == "selected"
    assert result.step_results[2].output == {"result": "approved"}

    default_result = await executor.execute(definition, context={"approved": False})

    assert [step.step_id for step in default_result.step_results] == ["fetch", "route", "default"]
    assert default_result.step_results[1].selected_step_id == "default"
    assert default_result.step_results[2].output == {"result": "manual_review"}


def test_workflow_definition_rejects_invalid_decision_targets() -> None:
    with pytest.raises(ValueError, match="目标节点不存在"):
        _definition(
            steps=[
                DecisionNode(
                    step_id="route",
                    condition_ref="context.approved",
                    expected_value=True,
                    match_step_id="missing",
                    default_step_id="later",
                ),
                WorkflowStep(step_id="later", tool_id="tool_a"),
            ]
        )

    with pytest.raises(ValueError, match="必须位于决策节点之后"):
        _definition(
            steps=[
                WorkflowStep(step_id="first", tool_id="tool_a"),
                DecisionNode(
                    step_id="route",
                    condition_ref="context.approved",
                    expected_value=True,
                    match_step_id="first",
                    default_step_id="missing",
                ),
            ]
        )
