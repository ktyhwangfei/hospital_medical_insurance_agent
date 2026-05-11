import fnmatch

from src.adapters.base.models import AdapterCallStatus
from src.adapters.ports import BillingPort, HisPort, InsuranceInterfacePort
from src.domain.skill.models import Skill, SkillStep
from src.domain.tool.models import Tool
from src.data_platform.storage.tool.ports import ToolStorage
from src.runtime.api.schemas import AgentResponse
from src.runtime.context.models import RuntimeContext
from src.security.risk_control.service import build_human_confirmation_response
from src.knowledge_extension.mcp_registry.models import McpRiskLevel
from src.data_platform.data_access.in_memory import build_sample_store
from src.knowledge_extension.knowledge.in_memory import ERROR_CODE_KNOWLEDGE


class SkillExecutionEngine:
    def __init__(
        self,
        insurance_adapter: InsuranceInterfacePort | None = None,
        his_adapter: HisPort | None = None,
        billing_adapter: BillingPort | None = None,
    ) -> None:
        self._store = build_sample_store()
        self._insurance_adapter = insurance_adapter
        self._his_adapter = his_adapter
        self._billing_adapter = billing_adapter

    def execute_skill(self, skill: Skill, context: RuntimeContext, tool_storage: ToolStorage) -> AgentResponse:
        self._verify_allowed_tools(skill, tool_storage)
        return self._execute_sequential(skill, context, tool_storage)

    def _execute_sequential(self, skill: Skill, context: RuntimeContext, tool_storage: ToolStorage) -> AgentResponse:
        accumulated: dict[str, dict] = {}
        steps_completed: list[str] = []
        for step in skill.steps:
            tool = tool_storage.get_tool(step.tool_id)
            if tool is None:
                accumulated[step.step_id] = {"status": "skipped", "reason": f"tool not found: {step.tool_id}"}
                continue
            if tool.risk_level == McpRiskLevel.HIGH or self._tool_requires_confirmation(tool):
                blocked = [tool.capability_ref]
                return build_human_confirmation_response(blocked)
            result = self._execute_step(tool, step, context, accumulated)
            accumulated[step.step_id] = result
            steps_completed.append(step.step_id)
        return self._build_response(skill, context, steps_completed, accumulated)

    def _execute_step(self, tool: Tool, step: SkillStep, context: RuntimeContext, accumulated: dict) -> dict:
        ref = tool.capability_ref
        if ref.startswith("insurance_interface."):
            return self._call_insurance_adapter(ref, context, step)
        elif ref.startswith("knowledge."):
            return self._call_knowledge_service(ref, context, step, accumulated)
        elif ref.startswith("his."):
            return self._call_his_adapter(ref, context, step)
        elif ref.startswith("billing."):
            return self._call_billing_adapter(ref, context, step)
        return {"status": "completed", "tool_id": tool.tool_id, "output": {}}

    def _call_insurance_adapter(self, ref: str, context: RuntimeContext, step: SkillStep) -> dict:
        if self._insurance_adapter is not None:
            try:
                result = self._insurance_adapter.query_transaction(
                    context.patient_id or "", context.encounter_id or ""
                )
                if result.status == AdapterCallStatus.SUCCESS:
                    return {
                        "status": "completed",
                        "tool_id": step.tool_id,
                        "output": {
                            "settlement_status": result.data.get("settlement_status"),
                            "error_code": result.data.get("error_code"),
                        },
                    }
            except Exception:
                pass
            return {"status": "completed", "tool_id": step.tool_id, "output": {"settlement_status": "not_found"}}
        # Fallback to direct in-memory store access
        if context.patient_id and context.encounter_id:
            try:
                txn = self._store.get_insurance_transaction(context.patient_id, context.encounter_id)
                return {"status": "completed", "tool_id": step.tool_id, "output": {"settlement_status": txn.settlement_status, "error_code": txn.error_code}}
            except KeyError:
                return {"status": "completed", "tool_id": step.tool_id, "output": {"settlement_status": "not_found"}}
        return {"status": "completed", "tool_id": step.tool_id, "output": {}}

    def _call_knowledge_service(self, ref: str, context: RuntimeContext, step: SkillStep, accumulated: dict) -> dict:
        error_code = ""
        for dep_id in step.depends_on:
            prev = accumulated.get(dep_id, {})
            output = prev.get("output", {})
            if "error_code" in output:
                error_code = output["error_code"]
                break
        if not error_code:
            for step_result in accumulated.values():
                output = step_result.get("output", {})
                if "error_code" in output:
                    error_code = output["error_code"]
                    break
        if error_code and error_code in ERROR_CODE_KNOWLEDGE:
            entry = ERROR_CODE_KNOWLEDGE[error_code]
            return {"status": "completed", "tool_id": step.tool_id, "output": entry}
        return {"status": "completed", "tool_id": step.tool_id, "output": {}}

    def _call_his_adapter(self, ref: str, context: RuntimeContext, step: SkillStep) -> dict:
        if self._his_adapter is not None:
            try:
                result = self._his_adapter.query_orders(
                    context.patient_id or "", context.encounter_id or ""
                )
                if result.status == AdapterCallStatus.SUCCESS:
                    return {
                        "status": "completed",
                        "tool_id": step.tool_id,
                        "output": {
                            "patient_id": result.data.get("patient_id", context.patient_id),
                            "name": "unknown",
                        },
                    }
            except Exception:
                pass
            return {"status": "completed", "tool_id": step.tool_id, "output": {"patient_id": context.patient_id or "", "name": "unknown"}}
        # Fallback to direct in-memory store access
        if context.patient_id:
            try:
                patient = self._store.get_patient(context.patient_id)
                return {"status": "completed", "tool_id": step.tool_id, "output": {"patient_id": patient.patient_id, "name": patient.name}}
            except KeyError:
                return {"status": "completed", "tool_id": step.tool_id, "output": {"patient_id": context.patient_id, "name": "unknown"}}
        return {"status": "completed", "tool_id": step.tool_id, "output": {}}

    def _call_billing_adapter(self, ref: str, context: RuntimeContext, step: SkillStep) -> dict:
        if self._billing_adapter is not None:
            try:
                result = self._billing_adapter.query_billing_status(
                    context.patient_id or "", context.encounter_id or ""
                )
                if result.status == AdapterCallStatus.SUCCESS:
                    return {
                        "status": "completed",
                        "tool_id": step.tool_id,
                        "output": {
                            "upload_status": result.data.get("billing_status", "not_found"),
                            "settlement_status": result.data.get("settlement_status"),
                        },
                    }
            except Exception:
                pass
            return {"status": "completed", "tool_id": step.tool_id, "output": {"upload_status": "not_found"}}
        # Fallback to direct in-memory store access
        if context.patient_id and context.encounter_id:
            try:
                txn = self._store.get_insurance_transaction(context.patient_id, context.encounter_id)
                return {"status": "completed", "tool_id": step.tool_id, "output": {"upload_status": txn.upload_status, "settlement_status": txn.settlement_status}}
            except KeyError:
                return {"status": "completed", "tool_id": step.tool_id, "output": {"upload_status": "not_found"}}
        return {"status": "completed", "tool_id": step.tool_id, "output": {}}

    def _verify_allowed_tools(self, skill: Skill, tool_storage: ToolStorage) -> None:
        if not skill.allowed_tools:
            return
        for step in skill.steps:
            tool = tool_storage.get_tool(step.tool_id)
            if tool is None:
                continue
            if not any(fnmatch.fnmatch(tool.tool_id, pattern) for pattern in skill.allowed_tools):
                raise ValueError(f"技能 {skill.skill_id} 不允许使用工具: {tool.tool_id}")

    def _tool_requires_confirmation(self, tool: Tool) -> bool:
        return tool.metadata.get("has_external_side_effects", False)

    def _build_response(self, skill: Skill, context: RuntimeContext, steps_completed: list[str], accumulated: dict) -> AgentResponse:
        return AgentResponse(
            scenario=skill.skill_id,
            status="completed",
            result={"skill_name": skill.name, "steps_completed": steps_completed, "outputs": accumulated},
            citations=[],
            tasks=[],
            audit={"workflow_id": context.workflow_id, "skill_id": skill.skill_id, "steps": [s.step_id for s in skill.steps]},
        )