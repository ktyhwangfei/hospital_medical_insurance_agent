"""Runtime Workflow 混合节点完整业务流。"""

import os

os.environ["USE_MEMORY_STORAGE"] = "1"

import pytest

from src.domain.tool.models import (
    ToolContractKind,
    ToolDefinition,
    ToolStatus,
    ToolVersion,
)
from src.runtime.tool_registry.builtin_tools import TOOL_GET_SETTLEMENT_FACT
from src.runtime.tool_registry.knowledge_tools import TOOL_RETRIEVE_POLICY_EVIDENCE
from src.runtime.tool_registry.service import ToolRegistryService
from src.runtime.workflow.definitions import WF_OUTPATIENT_SETTLEMENT_EXPLAIN
from src.runtime.workflow.domain_nodes import DOMAIN_HANDLERS
from src.runtime.workflow.executor import WorkflowExecutor
from src.runtime.workflow.public_result import build_workflow_public_result


def _tool_version(tool_id: str) -> ToolVersion:
    return ToolVersion(
        version_id=f"tv-flow-{tool_id}",
        tool_id=tool_id,
        # 版本号回内宣 1.0.0：本测试使用独立内存存储（见下），不会与进程级
        # 单例中的内置工具版本冲突，也不会以 created_at 压过内置版本污染其他用例。
        semantic_version="1.0.0",
        definition=ToolDefinition(
            tool_id=tool_id,
            name=tool_id,
            description=tool_id,
            contract_kind=ToolContractKind.FUNCTION,
            target_ref="src.runtime.policy_qa.knowledge_lookup.retrieve_policy_evidence_for_fact",
        ),
        status=ToolStatus.MATERIALIZED,
    )


@pytest.mark.asyncio
async def test_settlement_workflow_runs_tool_domain_and_output_nodes() -> None:
    from src.data_platform.storage.tool.in_memory import InMemoryToolVersionStorage

    registry = ToolRegistryService(storage=InMemoryToolVersionStorage())
    registry.register(
        _tool_version(TOOL_GET_SETTLEMENT_FACT),
        implementation=lambda settlement_id: {
            "settlement_id": settlement_id,
            "medical_insurance_inner_amount": 10000.0,
            "basic_pooling_payment": 8500.0,
        },
    )
    registry.register(
        _tool_version(TOOL_RETRIEVE_POLICY_EVIDENCE),
        implementation=lambda settlement_fact: {
            "policy_status": "full_policy_matched",
            "evidence": [
                {
                    "rule_id": "R-FLOW-85",
                    "source_text": "三级医院城镇职工住院统筹支付比例为85%。",
                    "payment_ratio": "85%",
                }
            ],
            "evidence_count": 1,
            "missing_required_rules": [],
        },
    )
    executor = WorkflowExecutor(registry, domain_handlers=DOMAIN_HANDLERS)

    execution = await executor.execute(
        WF_OUTPATIENT_SETTLEMENT_EXPLAIN,
        context={"question": "帮我核对一下这张结算单对不对", "settlement_id": "S-FLOW-1"},
    )
    public_result = build_workflow_public_result(execution)

    assert [step.node_type.value for step in execution.step_results] == [
        "tool",
        "tool",
        "domain",
        "domain",
        "domain",
        "output",
    ]
    assert public_result.answer_status == "complete"
    assert public_result.verification_summary.calculation_checked is True
    assert [citation.title for citation in public_result.citations] == ["R-FLOW-85"]
