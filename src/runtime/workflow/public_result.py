"""映射 WorkflowExecutionResult → PolicyQAPublicResult（对外契约不变）。"""

from __future__ import annotations

from src.domain.workflow.models import (
    WorkflowExecutionResult,
    WorkflowExecutionStatus,
)
from src.runtime.policy_qa.public_contract import (
    PolicyCitation,
    PolicyEvidence,
    PolicyQAPublicResult,
    VerificationSummary,
)


def _completed_outputs(result: WorkflowExecutionResult) -> dict[str, dict]:
    outputs = {
        step.step_id: step.output
        for step in result.step_results
        if step.status.value == "completed"
    }
    final_outputs = {
        step.step_id: step.output
        for step in result.step_results
        if step.node_type.value == "output" and step.status.value == "completed"
    }
    return final_outputs or outputs


def _collect_evidence(outputs: dict[str, dict]) -> list[dict]:
    for output in outputs.values():
        if isinstance(output.get("evidence"), list) and output.get("evidence_count") is not None:
            return output["evidence"]
    return []


def _collect_conclusion(outputs: dict[str, dict]) -> str | None:
    for output in outputs.values():
        if isinstance(output.get("conclusion"), str) and output["conclusion"]:
            return output["conclusion"]
    return None


def _collect_uncertainties(outputs: dict[str, dict]) -> list[str]:
    """汇总输出节点/末端步骤的缺失证据与不确定性声明（低保缺失、规则未接入等）。"""
    items: list[str] = []
    for output in outputs.values():
        for missing in output.get("missing_evidence", []):
            message = f"缺少{missing}，相关结论存在不确定性"
            if message not in items:
                items.append(message)
        for item in output.get("uncertainties", []):
            if item not in items:
                items.append(item)
    return items


def build_workflow_public_result(result: WorkflowExecutionResult) -> PolicyQAPublicResult:
    if result.status == WorkflowExecutionStatus.CLARIFY:
        return PolicyQAPublicResult(
            answer=result.clarify_message or "请补充信息后再继续。",
            answer_status="unavailable",
            uncertainties=[],
            verification_summary=VerificationSummary(
                settlement_checked=False,
                calculation_checked=False,
                policy_count=0,
                message="缺少必要信息，已要求澄清",
            ),
        )

    settlement_checked = any(
        bool(step.tool_id)
        and step.tool_id.startswith("tool_get_settlement")
        and step.status.value == "completed"
        for step in result.step_results
    )
    if result.status == WorkflowExecutionStatus.UNAVAILABLE:
        return PolicyQAPublicResult(
            answer="当前问题涉及的部分信息暂无可用数据源，无法给出确定结论。",
            answer_status="unavailable",
            uncertainties=result.uncertainties,
            verification_summary=VerificationSummary(
                settlement_checked=settlement_checked,
                calculation_checked=False,
                policy_count=0,
                message="工作流执行中存在无数据源的步骤，已如实告知不确定性",
            ),
        )

    outputs = _completed_outputs(result)
    evidence_items = _collect_evidence(outputs)
    conclusion = _collect_conclusion(outputs)
    uncertainties = list(result.uncertainties)
    uncertainties.extend(
        item for item in _collect_uncertainties(outputs) if item not in uncertainties
    )
    compare_outputs = [output for output in outputs.values() if "comparisons" in output]
    all_match = all(output.get("all_match") for output in compare_outputs) if compare_outputs else None
    calculation_checked = bool(compare_outputs)

    if all_match is False:
        answer_status = "partial"
        message = "工作流已完成，但对比存在差异或政策证据不足，结论按不确定性如实标注"
    else:
        answer_status = "complete"
        message = "工作流各步骤均已核实"

    return PolicyQAPublicResult(
        answer=conclusion or "已完成核对，未发现异常。",
        answer_status=answer_status,
        uncertainties=uncertainties,
        policy_evidence=[
            PolicyEvidence(
                title=(ev.get("rule_id") or "政策规则") if isinstance(ev, dict) else "政策规则",
                excerpt=(ev.get("source_text") or "") if isinstance(ev, dict) else "",
                score=(ev.get("score") if isinstance(ev, dict) else None),
            )
            for ev in evidence_items
        ],
        citations=[
            PolicyCitation(
                title=(ev.get("rule_id") or "政策规则") if isinstance(ev, dict) else "政策规则",
                excerpt=(ev.get("source_text") or "") if isinstance(ev, dict) else "",
            )
            for ev in evidence_items
        ],
        verification_summary=VerificationSummary(
            settlement_checked=settlement_checked,
            calculation_checked=calculation_checked,
            policy_count=len(evidence_items),
            message=message,
        ),
    )
