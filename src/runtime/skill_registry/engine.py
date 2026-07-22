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
from src.knowledge_extension.knowledge_stub import create_knowledge_store

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
    # 政策问答相关 tool
    "query_sql_settlement_data": "policy_qa.query_sql_data",
    "search_policy_rules": "policy_qa.search_rules",
    "calculate_fee_decomposition": "policy_qa.calculate_decomposition",
    "generate_policy_explanation": "policy_qa.generate_explanation",
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
        elif ref.startswith("policy_qa."):
            return self._call_policy_qa_service(ref, context, step, accumulated)
        return {"status": "completed", "tool_id": step.tool_id, "output": {}}

    def _call_policy_qa_service(self, ref: str, context: RuntimeContext, step: SkillStep, accumulated: dict) -> dict:
        """处理政策问答相关的 tool"""
        settlement_id = context.encounter_id or context.patient_id or ""
        
        if ref == "policy_qa.query_sql_data":
            # 查询 SQL 数据
            from src.runtime.policy_qa.sql_data_fetcher import SQLDataFetcher
            try:
                fetcher = SQLDataFetcher()
                import asyncio
                sql_result = asyncio.get_event_loop().run_until_complete(fetcher.fetch_all_tables(settlement_id))
                return {
                    "status": "completed",
                    "tool_id": step.tool_id,
                    "output": {
                        "treatment": sql_result.yb_zyfdxx,
                        "fee_details_count": len(sql_result.yb_zyfymx),
                        "annual": sql_result.yb_dyxxnd,
                        "admission": sql_result.yb_dyxxzy,
                        "patient": sql_result.yb_brdjxx,
                    },
                }
            except Exception as e:
                logger.error(f"Policy QA SQL query error: {e}")
                return {"status": "failed", "tool_id": step.tool_id, "output": {"error": str(e)}}
        
        elif ref == "policy_qa.search_rules":
            # 搜索政策规则
            from src.runtime.policy_qa.policy_rules_search import PolicyRulesSearchEngine
            from src.config.production import MILVUS_HOST, MILVUS_PORT
            try:
                engine = PolicyRulesSearchEngine(host=MILVUS_HOST, port=MILVUS_PORT, embedding_kind="hash")
                # 从 accumulated 中获取 SQL 结果用于过滤（已标准化）
                sql_output = accumulated.get("query_sql_data", {}).get("output", {})
                patient = sql_output.get("patient", {})
                insu_type = patient.get("fund_type", "")  # 已标准化
                psn_type = patient.get("PER_TYPE", "")  # 已标准化
                
                print(f"[SKILL] 搜索政策规则 (已标准化): insu_type={insu_type}, psn_type={psn_type}", flush=True)
                
                # 构建过滤表达式（使用标准化后的值）
                expr_parts = []
                if insu_type:
                    expr_parts.append(f'insu_type == "{insu_type}"')
                if psn_type:
                    expr_parts.append(f'(psn_type == "{psn_type}" or psn_type == "全部")')
                expr = " and ".join(expr_parts) if expr_parts else None
                
                print(f"[SKILL] 过滤表达式: {expr}", flush=True)
                
                # 获取问题
                question = context.question or "费用分解"
                results = engine.search(question, top_k=10, expr=expr)
                
                print(f"[SKILL] 搜索结果: {len(results)} 条", flush=True)
                
                return {
                    "status": "completed",
                    "tool_id": step.tool_id,
                    "output": {
                        "rules_count": len(results),
                        "rules": results[:5],  # 只返回前5条
                    },
                }
            except Exception as e:
                logger.error(f"Policy QA search error: {e}")
                return {"status": "failed", "tool_id": step.tool_id, "output": {"error": str(e)}}
        
        elif ref == "policy_qa.calculate_decomposition":
            # 计算费用分解
            from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
            from src.runtime.policy_qa.models import SQLQueryResult, PolicyRule
            try:
                # 从 accumulated 中获取 SQL 结果和政策规则
                sql_output = accumulated.get("query_sql_data", {}).get("output", {})
                rules_output = accumulated.get("search_rules", {}).get("output", {})
                
                # 构建 SQLQueryResult
                sql_result = SQLQueryResult()
                sql_result.yb_zyfdxx = sql_output.get("treatment", {})
                sql_result.yb_dyxxzy = sql_output.get("admission", {})
                sql_result.yb_brdjxx = sql_output.get("patient", {})
                
                # 构建 PolicyRule 列表
                policy_rules = []
                for rule_data in rules_output.get("rules", []):
                    policy_rules.append(PolicyRule(
                        rule_id=rule_data.get("rule_id", ""),
                        rule_type=rule_data.get("rule_type", ""),
                        payment_ratio=rule_data.get("payment_ratio", ""),
                        source_text=rule_data.get("source_text", ""),
                        insu_type=rule_data.get("insu_type", ""),
                        psn_type=rule_data.get("psn_type", ""),
                    ))
                
                # 执行分解
                skill = FeeDecompositionSkill()
                result = skill.decompose(sql_result, policy_rules)
                
                return {
                    "status": "completed",
                    "tool_id": step.tool_id,
                    "output": {
                        "total_fee": result.treatment.total_fee.value,
                        "in_scope": result.treatment.in_scope.value,
                        "deductible": result.treatment.deductible.value,
                        "pooling_payment": result.treatment.pooling_payment.value,
                        "pooling_self_pay": result.treatment.pooling_self_pay.value,
                        "major_payment": result.treatment.major_payment.value,
                        "major_self_pay": result.treatment.major_self_pay.value,
                        "personal_liability": result.treatment.personal_liability.value,
                        "out_of_scope": result.treatment.out_of_scope.value,
                        "evidence_count": len(result.evidence),
                    },
                }
            except Exception as e:
                logger.error(f"Policy QA decomposition error: {e}")
                return {"status": "failed", "tool_id": step.tool_id, "output": {"error": str(e)}}
        
        elif ref == "policy_qa.generate_explanation":
            # 生成解释（简化版，实际应该调用 LLM）
            decomposition_output = accumulated.get("calculate_decomposition", {}).get("output", {})
            return {
                "status": "completed",
                "tool_id": step.tool_id,
                "output": {
                    "explanation": f"费用分解完成：总费用 {decomposition_output.get('total_fee', 0):,.2f} 元",
                    "decomposition": decomposition_output,
                },
            }
        
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