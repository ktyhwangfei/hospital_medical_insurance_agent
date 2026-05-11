"""
UnifiedScenarioExecutor — Handles all business scenarios by dispatching to the
correct execution path (skill engine, LangGraph, business scenario service).

This implements the ScenarioExecutor protocol used by RuntimeOrchestrator.
"""

import hashlib

from fastapi import HTTPException

from src.data_platform.storage.skill.ports import SkillStorage
from src.data_platform.storage.tool.ports import ToolStorage
from src.runtime.api.schemas import AgentResponse
from src.runtime.api.streaming import ensure_knowledge_fields
from src.runtime.clarification.service import missing_context_fields
from src.runtime.context.models import RuntimeContext
from src.runtime.context.service import build_runtime_context
from src.runtime.intent.models import IntentResult
from src.runtime.intent.parser import parse_intent
from src.runtime.intent.skill_matcher import match_skill_by_intent
from src.runtime.orchestrator import ScenarioExecutor
from src.runtime.runtime_state.models import StepState, WorkflowInstance
from src.runtime.runtime_state.store import runtime_state_store
from src.runtime.dependencies import get_billing_adapter, get_his_adapter, get_insurance_adapter
from src.runtime.skill_registry.engine import SkillExecutionEngine
from src.runtime.skill_registry.parser import parse_message
from src.security.audit.service import record_audit_event
from src.security.authorization.service import is_allowed
from src.shared.schemas.responses import error_detail

_SKILLS_REQUIRING_PATIENT_CONTEXT = frozenset({
    'settlement_exception_guidance',
    'pre_discharge_quality_control',
})

_MCP_KEYWORDS = frozenset({
    '画图', '画一下', '画个', 'drawio', 'diagram', '图表', '架构图', '流程图', '导出', 'export', 'draw',
})


def _looks_like_mcp_request(message: str) -> bool:
    return any(kw in message for kw in _MCP_KEYWORDS)


def _persist_workflow(workflow_id: str, scenario: str, status: str, steps: list[StepState]) -> None:
    workflow = WorkflowInstance(
        workflow_id=workflow_id,
        scenario=scenario,
        status=status,
        current_step=steps[-1].step_id if steps else None,
        steps=steps,
    )
    runtime_state_store.save_workflow(workflow)
    record_audit_event('workflow_executed', workflow_id, payload={'scenario': scenario, 'status': status})
    for step in steps:
        record_audit_event('workflow_step_completed', workflow_id, step.step_id)


def _state_to_agent_response_from_graph(scenario: str, state: dict, workflow_id: str) -> AgentResponse:
    """Convert a LangGraph final state to an AgentResponse."""
    if scenario == "settlement_exception_guidance":
        error_detail_body = state.get("error_detail", {})
        recommendation = state.get("recommendation", "")
        error_code = state.get("error_code", "")
        return AgentResponse(
            scenario="settlement_exception_guidance",
            status="completed",
            result={
                "exception_type": error_detail_body.get("exception_type", ""),
                "error_code": error_code,
                "error_explanation": error_detail_body.get("description", ""),
                "responsible_role": error_detail_body.get("responsible_role", ""),
                "recommended_steps": [recommendation] if recommendation else [],
                "requires_human_confirmation": False,
            },
            citations=state.get("citations", []),
            tasks=[],
            missing_fields=[],
            uncertainties=state.get("uncertainties", []),
            blocked_actions=state.get("blocked_actions", []),
            audit={
                "workflow_id": workflow_id,
                "steps": ["validate_claim", "check_high_risk", "query_error_knowledge", "build_recommendation"],
            },
        )

    if scenario == "pre_discharge_quality_control":
        quality_issues = state.get("quality_issues", [])
        risks = [
            {
                "risk_type": issue.get("risk", ""),
                "risk_level": issue.get("risk_level", "medium"),
                "responsible_role": issue.get("responsible_role", ""),
                "recommendation": issue.get("description", ""),
            }
            for issue in quality_issues
        ]
        tasks = [
            {
                "task_id": f"task-qc-{idx}",
                "task_type": "rectification",
                "status": "pending",
                "responsible_role": issue.get("responsible_role", ""),
                "description": issue.get("description", ""),
            }
            for idx, issue in enumerate(quality_issues, start=1)
        ]
        return AgentResponse(
            scenario="pre_discharge_quality_control",
            status="completed",
            result={"risks": risks},
            citations=state.get("citations", []),
            tasks=tasks,
            missing_fields=[],
            uncertainties=state.get("uncertainties", []),
            blocked_actions=[],
            audit={
                "workflow_id": workflow_id,
                "steps": ["get_patient_summary", "run_qc_rules", "check_qc_issues", "build_qc_report"],
            },
        )

    return AgentResponse(status="not_implemented", uncertainties=[f"未知场景: {scenario}"])


def _build_langgraph_initial(scenario: str, context: RuntimeContext) -> dict:
    """Build initial LangGraph state from runtime context."""
    if scenario == "settlement_exception_guidance":
        return {
            "intent": "settlement",
            "role": context.role,
            "workflow_id": context.workflow_id,
            "messages": [],
            "citations": [],
            "uncertainties": [],
            "requires_confirmation": False,
            "human_confirmed": False,
            "patient_id": context.patient_id or "",
            "encounter_id": context.encounter_id or "",
            "claim_detail": {},
            "error_code": "",
            "error_detail": {},
            "recommendation": "",
            "blocked_actions": [],
        }
    if scenario == "pre_discharge_quality_control":
        return {
            "intent": "pre_discharge",
            "role": context.role,
            "workflow_id": context.workflow_id,
            "messages": [],
            "citations": [],
            "uncertainties": [],
            "requires_confirmation": False,
            "human_confirmed": False,
            "patient_id": context.patient_id or "",
            "encounter_id": context.encounter_id or "",
            "patient_summary": {},
            "quality_issues": [],
            "rule_results": [],
            "qc_recommendation": "",
        }
    return {}


def _build_context_from_request_with_intent(request, intent_result: IntentResult | None = None):
    """Build RuntimeContext from request, optionally with a pre-parsed intent."""
    if intent_result is None:
        intent_result = IntentResult(intent='skill_execution', confidence=0.8, entities={}, citations=[], raw_message=request.message)
    return build_runtime_context(request, intent_result)


class UnifiedScenarioExecutor:
    """ScenarioExecutor that dispatches to skill engine, LangGraph, or business service.

    Handles all known scenarios by trying each execution strategy in order:
    1. @-mention skill execution
    2. Keyword-based skill matching
    3. LangGraph / business scenario dispatch
    4. Fallback (not_implemented)
    """

    def __init__(
        self,
        skill_storage: SkillStorage,
        tool_storage: ToolStorage,
        checkpoint_registry: dict[str, tuple],
    ) -> None:
        self._skill_storage = skill_storage
        self._tool_storage = tool_storage
        self._checkpoint_registry = checkpoint_registry

    def can_handle(self, scenario: str) -> bool:
        return True

    def execute(self, context: RuntimeContext) -> AgentResponse:
        # Phase 1: Try @-mention skill execution
        result = self._try_mention_execution(context)
        if result is not None:
            return result

        # Phase 2: Try keyword-based skill matching
        result = self._try_skill_matching(context)
        if result is not None:
            return result

        # Phase 3: Try LangGraph / business scenario dispatch
        if context.intent in ('settlement_exception_guidance', 'pre_discharge_quality_control'):
            return self._execute_scenario_langgraph(context)

        # Phase 4: MCP tool invocation
        if context.intent == 'mcp_tool_invocation' or _looks_like_mcp_request(context.message):
            return self._execute_mcp(context)

        # Fallback
        return AgentResponse(
            status='not_implemented',
            uncertainties=[f'未识别的意图: {context.message}'],
            citations=[{'source_type': 'intent_recognition', 'source_id': c, 'summary': c} for c in context.intent_citations],
        )

    def _try_mention_execution(self, context: RuntimeContext) -> AgentResponse | None:
        """Try executing a skill via @-mention."""
        mention_result = parse_message(context.message)
        skill_ids = context.mentioned_skill_ids or mention_result.mentioned_skill_ids

        if not skill_ids:
            return None

        skill_id = skill_ids[0]
        skill = self._skill_storage.get_skill(skill_id)
        if skill is None:
            return AgentResponse(
                status="not_implemented",
                uncertainties=[f"未找到技能: {skill_id}"],
            )
        if not skill.enabled:
            return AgentResponse(
                status="not_implemented",
                uncertainties=[f"技能已禁用: {skill_id}"],
            )
        if skill.owner != context.role and context.role not in skill.required_roles:
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该技能', {'event_type': 'permission_denied'}))

        if skill.skill_id in _SKILLS_REQUIRING_PATIENT_CONTEXT or skill_id in _SKILLS_REQUIRING_PATIENT_CONTEXT:
            missing = missing_context_fields(context.patient_id, context.encounter_id)
            if missing:
                return AgentResponse(status='needs_clarification', missing_fields=missing)

        intent_result = parse_intent(mention_result.clean_message) if mention_result.clean_message else None
        exec_context = _build_context_from_request_with_intent(context, intent_result) if intent_result else context
        engine = SkillExecutionEngine(
            insurance_adapter=get_insurance_adapter(),
            his_adapter=get_his_adapter(),
            billing_adapter=get_billing_adapter(),
        )
        response = engine.execute_skill(skill, exec_context, self._tool_storage)
        response.audit["matched_skill"] = skill_id
        steps = [StepState(step_id=step_id, status="completed") for step_id in response.audit.get("steps", [])]
        _persist_workflow(exec_context.workflow_id, response.scenario, response.status, steps)
        return response

    def _try_skill_matching(self, context: RuntimeContext) -> AgentResponse | None:
        """Try matching and executing a skill based on intent keywords."""
        match = match_skill_by_intent(context.message, context.role, self._skill_storage)
        if not match:
            return None

        skill = self._skill_storage.get_skill(match.skill_id)
        if skill is None or not skill.enabled:
            return None

        if match.skill_id in _SKILLS_REQUIRING_PATIENT_CONTEXT:
            missing = missing_context_fields(context.patient_id, context.encounter_id)
            if missing:
                return AgentResponse(status='needs_clarification', missing_fields=missing)

        intent_result = parse_intent(context.message)
        exec_context = build_runtime_context(
            _RequestShim(message=context.message, role=context.role, patient_id=context.patient_id,
                         encounter_id=context.encounter_id, user_id=context.user_id,
                         mentioned_skill_ids=[]),
            intent_result,
        )
        engine = SkillExecutionEngine(
            insurance_adapter=get_insurance_adapter(),
            his_adapter=get_his_adapter(),
            billing_adapter=get_billing_adapter(),
        )
        response = engine.execute_skill(skill, exec_context, self._tool_storage)
        response.audit["matched_skill"] = match.skill_id
        response.audit["matched_keywords"] = match.matched_keywords
        steps = [StepState(step_id=step_id, status="completed") for step_id in response.audit.get("steps", [])]
        _persist_workflow(exec_context.workflow_id, response.scenario, response.status, steps)
        return response

    def _execute_scenario_langgraph(self, context: RuntimeContext) -> AgentResponse:
        """Execute a known business scenario via LangGraph."""
        missing = missing_context_fields(context.patient_id, context.encounter_id)
        if missing:
            return AgentResponse(status='needs_clarification', missing_fields=missing)

        if not is_allowed(context.role, context.intent):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))

        from src.runtime.langgraph.checkpoint import get_memory_checkpointer
        from src.runtime.langgraph.pre_discharge_qc import build_pre_discharge_qc_graph
        from src.runtime.langgraph.settlement_exception import build_settlement_exception_graph

        GRAPH_BUILDERS = {
            'settlement_exception_guidance': build_settlement_exception_graph,
            'pre_discharge_quality_control': build_pre_discharge_qc_graph,
        }

        memory = get_memory_checkpointer()
        graph = GRAPH_BUILDERS[context.intent](checkpointer=memory)
        thread_id = context.workflow_id
        thread_config = {"configurable": {"thread_id": thread_id}}

        initial = _build_langgraph_initial(context.intent, context)
        state = graph.invoke(initial, thread_config)

        snapshot = graph.get_state(thread_config)
        if snapshot.next:
            task_id = f"task-orch-{hashlib.md5(thread_id.encode()).hexdigest()[:8]}"
            self._checkpoint_registry[task_id] = (graph, thread_id)
            from src.runtime.task_closure.service import create_task
            task = create_task(task_id, 'human_confirmation', '需要人工确认后才能继续', '医保办', thread_id)
            steps = [StepState(step_id=snapshot.next[0], status="waiting")]
            runtime_state_store.save_workflow(WorkflowInstance(
                workflow_id=thread_id,
                scenario=context.intent,
                status="waiting_human_confirmation",
                current_step=snapshot.next[0],
                steps=steps,
            ))
            record_audit_event("workflow_executed", thread_id, payload={"scenario": context.intent, "status": "waiting_human_confirmation"})
            return AgentResponse(
                scenario=context.intent,
                status="waiting_human_confirmation",
                result={"message": "需要人工确认后才能继续执行"},
                citations=state.get("citations", []),
                tasks=[task],
                missing_fields=[],
                uncertainties=["需要人工确认后才能继续执行"],
                blocked_actions=state.get("blocked_actions", []),
                audit={"workflow_id": thread_id, "steps": [snapshot.next[0]]},
            )

        response = _state_to_agent_response_from_graph(context.intent, state, context.workflow_id)
        response.citations.extend(
            {'source_type': 'intent_recognition', 'source_id': c, 'summary': c} for c in context.intent_citations
        )
        steps = [StepState(step_id=s, status="completed") for s in response.audit.get("steps", [])]
        _persist_workflow(context.workflow_id, response.scenario, response.status, steps)
        return response

    def _execute_mcp(self, context: RuntimeContext) -> AgentResponse:
        """Execute MCP tool invocation."""
        if not is_allowed(context.role, 'mcp_tool_invocation'):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))

        from src.runtime.orchestration.service import execute_plan
        from src.runtime.planning.service import build_execution_plan

        plan = build_execution_plan(context)
        response = execute_plan(context, plan)
        response.citations.extend(
            {'source_type': 'intent_recognition', 'source_id': c, 'summary': c} for c in context.intent_citations
        )
        return response


class _RequestShim:
    """Minimal shim to convert RuntimeContext fields into ChatRequest-like object for build_runtime_context."""
    def __init__(self, message: str, role: str, patient_id: str | None,
                 encounter_id: str | None, user_id: str, mentioned_skill_ids: list[str]) -> None:
        self.message = message
        self.role = role
        self.patient_id = patient_id
        self.encounter_id = encounter_id
        self.user_id = user_id
        self.mentioned_skill_ids = mentioned_skill_ids
