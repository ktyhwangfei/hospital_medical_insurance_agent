import os

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest

from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolStatus,
    ToolVersion,
)
from src.domain.workflow.models import (
    MissingEvidenceRule,
    WorkflowDefinition,
    WorkflowExecutionStatus,
    WorkflowStep,
)
from src.runtime.tool_registry.service import ToolRegistryService
from src.runtime.workflow.executor import WorkflowExecutor


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
