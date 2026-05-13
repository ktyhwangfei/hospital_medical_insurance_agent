import fnmatch
import logging
import time
from collections.abc import Callable
from uuid import uuid4

from src.adapters.base.models import AdapterCallStatus
from src.adapters.ports import BillingPort, HisPort, InsuranceInterfacePort
from src.domain.skill.models import Skill, SkillStep
from src.runtime.api.schemas import AgentResponse
from src.runtime.context.models import RuntimeContext
from src.runtime.task_closure.service import create_task as _create_task
from src.runtime.task_closure.service import save_task as _save_task
from src.security.risk_control.service import build_human_confirmation_response
from src.knowledge_extension.knowledge.factory import create_knowledge_store

logger = logging.getLogger(__name__)

# Known tool_id → capability_ref mapping (tools table removed, ref kept inline)
_TOOL_CAPABILITY_REFS: dict[str, str] = {
    "query_transaction": "insurance_interface.query_transaction",
    "query_insurance_status": "insurance_interface.query_status",
    "query_billing_status": "billing.query_billing_status",
    "query_orders": "his.query_orders",
    "retrieve_error_code": "knowledge.error_code",
    "retrieve_rule_explanation": "knowledge.rule_explanation",
    "build_result": "settlement_exception.build_result",
    "build_risk_list": "pre_discharge_qc.build_risk_list",
    "create_tasks": "task_closure.create_tasks",
    "match_mcp_capability": "mcp.match_capability",
    "invoke_mcp_tool": "mcp.invoke_tool",
    "detect_high_risk_action": "risk_control.detect",
    "create_human_confirmation": "task_closure.human_confirmation",
    "query_pre_audit": "pre_audit.query_audit_result",
    "query_drg_dip": "drg_dip.query_group_result",
    "query_medical_record": "medical_record.query_homepage",
}

# Known tool_id → risk_level mapping (high-risk tools)
_TOOL_RISK_LEVELS: dict[str, str] = {
    "create_tasks": "medium",
    "invoke_mcp_tool": "medium",
    "detect_high_risk_action": "high",
    "create_human_confirmation": "high",
}

# Known tool_id → metadata mapping
_TOOL_METADATA: dict[str, dict] = {}


def _get_capability_ref(tool_id: str) -> str:
    return _TOOL_CAPABILITY_REFS.get(tool_id, f"adapter.{tool_id}")


def _get_tool_risk_level(tool_id: str) -> str:
    return _TOOL_RISK_LEVELS.get(tool_id, "low")


def _tool_requires_confirmation(tool_id: str) -> bool:
    return _TOOL_METADATA.get(tool_id, {}).get("has_external_side_effects", False)


class SkillExecutionEngine:
    def __init__(
        self,
        insurance_adapter: InsuranceInterfacePort | None = None,
        his_adapter: HisPort | None = None,
        billing_adapter: BillingPort | None = None,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        """初始化技能执行引擎。

        Args:
            insurance_adapter: 医保接口适配器
            his_adapter: HIS 系统适配器
            billing_adapter: 收费系统适配器
            on_event: 流式事件回调，格式为 (event_type, payload) -> None
                      用于在技能步骤执行过程中发出 tool_call/tool_result/error 事件
        """
        self._insurance_adapter = insurance_adapter
        self._his_adapter = his_adapter
        self._billing_adapter = billing_adapter
        self._knowledge_store = create_knowledge_store()
        self._on_event = on_event

    def execute_skill(self, skill: Skill, context: RuntimeContext) -> AgentResponse:
        self._verify_allowed_tools(skill)
        return self._execute_sequential(skill, context)

    def _execute_sequential(self, skill: Skill, context: RuntimeContext) -> AgentResponse:
        accumulated: dict[str, dict] = {}
        steps_completed: list[str] = []
        for step in skill.steps:
            capability_ref = _get_capability_ref(step.tool_id)
            risk_level = _get_tool_risk_level(step.tool_id)
            if risk_level == "high" or _tool_requires_confirmation(step.tool_id):
                blocked = [capability_ref]
                return build_human_confirmation_response(blocked)

            # 生成 call_id 用于关联前后事件
            call_id = uuid4().hex[:8]

            # 发出 tool_call 事件（步骤执行前）
            if self._on_event:
                self._on_event('stream:tool_call', {
                    'call_id': call_id,
                    'tool_name': step.tool_id,
                    'params': step.params or {},
                    'step_id': step.step_id,
                    'capability_ref': capability_ref,
                })

            # 记录步骤执行任务（非阻塞）
            task_id = f"task-exec-{uuid4().hex[:8]}"
            task_start = time.time()
            try:
                _create_task(
                    task_id, "skill_execution", f"技能步骤: {step.step_id}",
                    context.role or "system", context.workflow_id,
                    executor_type="skill",
                    input_data={"step_id": step.step_id, "capability_ref": capability_ref, "tool_id": step.tool_id},
                    status="running",
                )
            except Exception as e:
                logger.warning(f"创建步骤任务记录失败 (非阻断): {e}")

            # 执行步骤（带错误捕获，用于发出 error 事件）
            try:
                result = self._execute_step_by_ref(capability_ref, step, context, accumulated)
            except Exception as e:
                if self._on_event:
                    self._on_event('stream:error', {
                        'step_id': step.step_id,
                        'error': str(e),
                        'tool_id': step.tool_id,
                    })
                raise

            # 发出 tool_result 事件（步骤执行成功后）
            if self._on_event:
                duration_ms = int((time.time() - task_start) * 1000)
                self._on_event('stream:tool_result', {
                    'call_id': call_id,
                    'result': result.get('output', result),
                    'duration_ms': duration_ms,
                    'step_id': step.step_id,
                })

            # 更新步骤执行任务
            try:
                task = _create_task(
                    task_id, "skill_execution", f"技能步骤: {step.step_id}",
                    context.role or "system", context.workflow_id,
                    executor_type="skill",
                    input_data={"step_id": step.step_id, "capability_ref": capability_ref, "tool_id": step.tool_id},
                    output_data={"result": result},
                    duration_ms=(time.time() - task_start) * 1000,
                    status="completed",
                )
                _save_task(task)
            except Exception as e:
                logger.warning(f"更新步骤任务记录失败 (非阻断): {e}")

            accumulated[step.step_id] = result
            steps_completed.append(step.step_id)
        return self._build_response(skill, context, steps_completed, accumulated)

    def _execute_step_by_ref(self, ref: str, step: SkillStep, context: RuntimeContext, accumulated: dict) -> dict:
        if ref.startswith("insurance_interface."):
            return self._call_insurance_adapter(ref, context, step)
        elif ref.startswith("knowledge."):
            return self._call_knowledge_service(ref, context, step, accumulated)
        elif ref.startswith("his."):
            return self._call_his_adapter(ref, context, step)
        elif ref.startswith("billing."):
            return self._call_billing_adapter(ref, context, step)
        return {"status": "completed", "tool_id": step.tool_id, "output": {}}

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
            except Exception as e:
                logger.error(f"Insurance adapter error: {e}")
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
        # 从数据库查询错误码知识
        if error_code:
            try:
                entry = self._knowledge_store.get_error_code(error_code)
                if entry:
                    return {"status": "completed", "tool_id": step.tool_id, "output": entry}
            except Exception as e:
                logger.error(f"Knowledge store error: {e}")

        return {"status": "completed", "tool_id": step.tool_id, "output": {"error_code": error_code} if error_code else {}}

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
            except Exception as e:
                logger.error(f"HIS adapter error: {e}")
            return {"status": "completed", "tool_id": step.tool_id, "output": {"patient_id": context.patient_id or "", "name": "unknown"}}
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
            except Exception as e:
                logger.error(f"Billing adapter error: {e}")
            return {"status": "completed", "tool_id": step.tool_id, "output": {"upload_status": "not_found"}}
        return {"status": "completed", "tool_id": step.tool_id, "output": {}}

    def _verify_allowed_tools(self, skill: Skill) -> None:
        if not skill.allowed_tools:
            return
        for step in skill.steps:
            if not any(fnmatch.fnmatch(step.tool_id, pattern) for pattern in skill.allowed_tools):
                raise ValueError(f"技能 {skill.skill_id} 不允许使用工具: {step.tool_id}")

    def _build_response(self, skill: Skill, context: RuntimeContext, steps_completed: list[str], accumulated: dict) -> AgentResponse:
        return AgentResponse(
            scenario=skill.skill_id,
            status="completed",
            result={"skill_name": skill.name, "steps_completed": steps_completed, "outputs": accumulated},
            citations=[],
            tasks=[],
            audit={"workflow_id": context.workflow_id, "skill_id": skill.skill_id, "steps": [s.step_id for s in skill.steps]},
        )