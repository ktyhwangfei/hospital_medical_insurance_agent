"""
UnifiedScenarioExecutor — Handles all business scenarios by dispatching to the
correct execution path (skill engine, LangGraph, business scenario service).

This implements the ScenarioExecutor protocol used by RuntimeOrchestrator.
"""

import hashlib
import logging
from collections.abc import Callable

from fastapi import HTTPException

logger = logging.getLogger(__name__)

from src.data_platform.storage.skill.ports import SkillStorage
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

# Fee/费用相关关键词 — 路由到 Policy QA 费用分解管道
_FEE_KEYWORDS = frozenset({
    '统筹自付', '自付', '统筹支付', '报销比例', '起付线', '封顶线',
    '费用分解', '费用明细', '费用构成', '为什么这么多', '怎么算的',
    '大额', '个人应负', '医保外', '医保内', '待遇分解', '自费',
    '报销多少', '能报多少', '报销了多少钱', '花了多少',
})


def _looks_like_mcp_request(message: str) -> bool:
    return any(kw in message for kw in _MCP_KEYWORDS)


def _looks_like_fee_question(message: str) -> bool:
    """检测是否为费用/报销相关的问题，应路由到 Policy QA 管道。"""
    return any(kw in message for kw in _FEE_KEYWORDS)


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


def _track_skill_metrics(skill_id: str) -> None:
    """技能执行后，从 manifest 读取 needed_objects，为引用的指标 usage_count +1。"""
    try:
        import yaml
        from pathlib import Path
        from src.config.production import SKILLS_DIR
        from src.runtime.api.semantic_routes import get_registry
        manifest_path = Path(SKILLS_DIR) / skill_id / "skill_manifest.yaml"
        if not manifest_path.exists():
            return
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        reg = get_registry()
        store = reg._store
        count = 0
        for obj_decl in manifest.get("needed_objects", []):
            obj_code = obj_decl.get("object_code", "")
            for mc in obj_decl.get("metrics", []):
                full_code = f"{obj_code}.{mc}"
                metric = store.get_metric(full_code)
                if metric:
                    metric.usage_count = (metric.usage_count or 0) + 1
                    store.save_metric(metric)
                    count += 1
        if count:
            logger.info("tracked usage for skill '%s': %d metrics", skill_id, count)
    except Exception as e:
        logger.debug("track_skill_metrics failed: %s", e)


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
        checkpoint_registry: dict[str, tuple],
    ) -> None:
        self._skill_storage = skill_storage
        self._checkpoint_registry = checkpoint_registry

    def can_handle(self, scenario: str) -> bool:
        return True

    def execute(self, context: RuntimeContext, on_event: Callable[[str, dict], None] | None = None) -> AgentResponse:
        """执行场景分发。

        Args:
            context: 运行时上下文
            on_event: 流式事件回调，透传给技能执行引擎
        """
        # Phase 1: Try @-mention skill execution
        result = self._try_mention_execution(context, on_event=on_event)
        if result is not None:
            return result

        # Phase 2: Try keyword-based skill matching
        result = self._try_skill_matching(context, on_event=on_event)
        if result is not None:
            return result

        # Phase 3: Try LangGraph / business scenario dispatch
        if context.intent in ('settlement_exception_guidance', 'pre_discharge_quality_control'):
            return self._execute_scenario_langgraph(context, on_event=on_event)

        # Phase 3.5: Fee/费用相关问题 → 路由到 Policy QA 费用分解管道
        if _looks_like_fee_question(context.message):
            return self._execute_policy_qa(context, on_event=on_event)

        # Phase 4: MCP tool invocation
        if context.intent == 'mcp_tool_invocation' or _looks_like_mcp_request(context.message):
            return self._execute_mcp(context, on_event=on_event)

        # Fallback
        return AgentResponse(
            status='not_implemented',
            uncertainties=[f'未识别的意图: {context.message}'],
            citations=[{'source_type': 'intent_recognition', 'source_id': c, 'summary': c} for c in context.intent_citations],
        )

    def execute_streaming(self, context: RuntimeContext, on_event: Callable[[str, dict], None]) -> AgentResponse:
        """流式执行入口，强制要求 on_event 回调。

        Args:
            context: 运行时上下文
            on_event: 流式事件回调，必需参数

        Returns:
            AgentResponse: 执行结果
        """
        return self.execute(context, on_event=on_event)

    def _try_mention_execution(
        self,
        context: RuntimeContext,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> AgentResponse | None:
        """Try executing a skill via @-mention.

        Args:
            context: 运行时上下文
            on_event: 流式事件回调，透传给技能执行引擎
        """
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
            on_event=on_event,
        )
        response = engine.execute_skill(skill, exec_context)
        _track_skill_metrics(skill_id)
        response.audit["matched_skill"] = skill_id
        steps = [StepState(step_id=step_id, status="completed") for step_id in response.audit.get("steps", [])]
        _persist_workflow(exec_context.workflow_id, response.scenario, response.status, steps)
        return response

    def _try_skill_matching(
        self,
        context: RuntimeContext,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> AgentResponse | None:
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
            on_event=on_event,
        )
        response = engine.execute_skill(skill, exec_context)
        _track_skill_metrics(match.skill_id)
        response.audit["matched_skill"] = match.skill_id
        response.audit["matched_keywords"] = match.matched_keywords
        steps = [StepState(step_id=step_id, status="completed") for step_id in response.audit.get("steps", [])]
        _persist_workflow(exec_context.workflow_id, response.scenario, response.status, steps)
        return response

    def _execute_scenario_langgraph(
        self,
        context: RuntimeContext,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> AgentResponse:
        """Execute a known business scenario via LangGraph.

        Args:
            context: 运行时上下文
            on_event: 流式事件回调，透传给 StreamingLangGraph 用于逐节点事件推送
        """
        missing = missing_context_fields(context.patient_id, context.encounter_id)
        if missing:
            return AgentResponse(status='needs_clarification', missing_fields=missing)

        if not is_allowed(context.role, context.intent):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))

        from src.runtime.langgraph.checkpoint import get_checkpointer
        from src.runtime.langgraph.pre_discharge_qc import build_pre_discharge_qc_graph
        from src.runtime.langgraph.settlement_exception import build_settlement_exception_graph
        from src.runtime.langgraph.streaming import StreamingLangGraph

        GRAPH_BUILDERS = {
            'settlement_exception_guidance': build_settlement_exception_graph,
            'pre_discharge_quality_control': build_pre_discharge_qc_graph,
        }

        checkpointer = get_checkpointer()
        graph = GRAPH_BUILDERS[context.intent](checkpointer=checkpointer)
        thread_id = context.workflow_id
        thread_config = {"configurable": {"thread_id": thread_id}}

        initial = _build_langgraph_initial(context.intent, context)
        streaming_graph = StreamingLangGraph(
            graph=graph,
            graph_builder_fn=GRAPH_BUILDERS[context.intent],
            scenario=context.intent,
            on_event=on_event,
        )
        state = streaming_graph.invoke(initial, thread_config)

        snapshot = streaming_graph.graph.get_state(thread_config)
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

        # 记录 LangGraph 场景执行任务（非阻塞）
        try:
            from src.runtime.task_closure.service import create_task as _create_task
            _create_task(
                f"task-orch-{hashlib.md5(context.workflow_id.encode()).hexdigest()[:8]}",
                "langgraph_execution",
                f"LangGraph场景: {context.intent}",
                context.role or "system",
                context.workflow_id,
                executor_type="langgraph",
                input_data={"scenario": context.intent, "thread_id": thread_id, "patient_id": context.patient_id},
                output_data={"state_keys": list(state.keys())} if state else {},
                status="completed",
            )
        except Exception as e:
            logger.warning(f"记录LangGraph执行任务失败 (非阻断): {e}")

        steps = [StepState(step_id=s, status="completed") for s in response.audit.get("steps", [])]
        _persist_workflow(context.workflow_id, response.scenario, response.status, steps)
        return response

    def _execute_mcp(
        self,
        context: RuntimeContext,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> AgentResponse:
        """Execute MCP tool invocation.

        Args:
            context: 运行时上下文
            on_event: 流式事件回调，透传给 McpRuntimeIntegration 用于 MCP 调用事件推送
        """
        if not is_allowed(context.role, 'mcp_tool_invocation'):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))

        from src.knowledge_extension.mcp_registry.models import (
            McpCapabilitySelectionRequest,
            McpCapabilityType,
            McpRiskLevel,
        )
        from src.knowledge_extension.mcp_registry import _service as mcp_registry
        from src.runtime.orchestration.mcp_integration import McpRuntimeIntegration

        # 构建 MCP 集成层，透传 on_event 以实现流式事件推送
        mcp_integration = McpRuntimeIntegration(
            registry=mcp_registry,
            on_event=on_event,
        )

        # 根据当前上下文选择 MCP 能力（emit tool_call / tool_result 事件）
        selection = mcp_integration.select_for_step(
            McpCapabilitySelectionRequest(
                scenario=context.intent,
                role=context.role,
                capability_type=McpCapabilityType.TOOL,
                max_risk_level=McpRiskLevel.LOW,
            ),
        )

        # 构建响应
        if selection.selected_capabilities:
            return AgentResponse(
                scenario="mcp_tool_invocation",
                status="completed",
                result={
                    "selected_capabilities": [
                        {"capability_id": c.capability_id, "name": c.name, "description": c.description}
                        for c in selection.selected_capabilities
                    ],
                },
                citations=[
                    {'source_type': 'mcp_registry', 'source_id': c.capability_id, 'summary': c.description}
                    for c in selection.selected_capabilities
                ]
                + [{'source_type': 'intent_recognition', 'source_id': c, 'summary': c} for c in context.intent_citations],
                uncertainties=selection.uncertainties,
            )

        return AgentResponse(
            scenario="mcp_tool_invocation",
            status="completed",
            result={"message": "未找到匹配的 MCP 工具", "excluded": selection.excluded_capabilities},
            uncertainties=selection.uncertainties
            or ["未找到满足当前场景、角色、权限和风险约束的 MCP 能力"],
            citations=[{'source_type': 'intent_recognition', 'source_id': c, 'summary': c} for c in context.intent_citations],
        )

    def _execute_policy_qa(
        self,
        context: RuntimeContext,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> AgentResponse:
        """将费用/报销相关问题路由到 Policy QA 费用分解管道。

        使用 PolicyQAOrchestrator 的 6 步流程（意图识别→SQL查询→问题重写→
        政策检索→费用分解→解释生成），基于真实结算数据 + 政策规则给出答案。

        Args:
            context: 运行时上下文
            on_event: 流式事件回调，透传 Policy QA 管道的步骤事件
        """
        import asyncio

        from src.runtime.policy_qa.models import PolicyQARequest
        from src.runtime.policy_qa.orchestrator import PolicyQAOrchestrator
        from src.runtime.policy_qa.question_rewriter import QuestionRewriter
        from src.runtime.policy_qa.fee_decomposition_skill import FeeDecompositionSkill
        from src.runtime.policy_qa.explanation_generator import ExplanationGenerator
        from src.runtime.policy_qa.sql_data_fetcher import SQLDataFetcher

        settlement_id = getattr(context, 'encounter_id', None) or '1671213'

        async def _run_pipeline() -> str:
            """运行 Policy QA 管道，返回文本解释。"""
            # 初始化组件
            sql_fetcher = None
            try:
                sql_fetcher = SQLDataFetcher()
            except Exception as e:
                logger.warning(f"SQL fetcher init failed: {e}")

            question_rewriter = QuestionRewriter()
            fee_skill = FeeDecompositionSkill()

            model_gateway = None
            try:
                from src.model_service.gateway import ModelGateway
                model_gateway = ModelGateway()
            except Exception as e:
                logger.warning(f"Model gateway init failed: {e}")

            explanation_gen = ExplanationGenerator(model_gateway=model_gateway)

            orchestrator = PolicyQAOrchestrator(
                model_gateway=model_gateway,
                sql_fetcher=sql_fetcher,
                question_rewriter=question_rewriter,
                fee_skill=fee_skill,
                explanation_generator=explanation_gen,
            )

            request = PolicyQARequest(
                question=context.message,
                settlement_id=settlement_id,
            )

            full_text = ""
            decomposition_data = None

            async for response in orchestrator.process(request):
                # 发射 stream:step 事件（用于前端执行步骤展示）
                if on_event:
                    step_data = {
                        "step": response.step,
                        "status": response.status,  # ★ 传递状态给前端，否则前端永远 running
                        "message": response.public_detail.get("summary", f"步骤: {response.step}")
                        if response.public_detail
                        else f"步骤: {response.step}",
                    }
                    on_event("stream:step", step_data)

                # 累积 explanation 的流式 chunks
                if response.step == "explain" and response.chunk:
                    full_text += response.chunk
                    if on_event:
                        on_event("stream:delta", {"content": response.chunk})

                # 捕获费用分解数据
                if response.step == "decomposition" and response.status == "done":
                    decomposition_data = response.detail

            return full_text, decomposition_data

        try:
            full_text, decomposition_data = asyncio.run(_run_pipeline())

            if not full_text:
                # 如果没有生成解释，构建基本摘要
                if decomposition_data:
                    treatment = decomposition_data.get("treatment", {})
                    full_text = (
                        f"根据您的结算数据，总费用为 {treatment.get('total_fee', 0):,.2f} 元。\n\n"
                        f"费用构成如下：\n"
                        f"• 医保内费用: {treatment.get('in_scope', 0):,.2f} 元\n"
                        f"• 起付线: {treatment.get('deductible', 0):,.2f} 元\n"
                        f"• 统筹支付: {treatment.get('pooling_payment', 0):,.2f} 元\n"
                        f"• 统筹自付: {treatment.get('pooling_self_pay', 0):,.2f} 元\n"
                        f"• 大额支付: {treatment.get('major_payment', 0):,.2f} 元\n"
                        f"• 大额自付: {treatment.get('major_self_pay', 0):,.2f} 元\n"
                        f"• 个人应负: {treatment.get('personal_liability', 0):,.2f} 元\n"
                        f"• 医保外: {treatment.get('out_of_scope', 0):,.2f} 元\n\n"
                        f"统筹自付部分由分段计算决定，具体取决于您的医保类型、在职/退休状态及费用分段。\n"
                        f"详细计算过程请查看费用分解卡片。"
                    )
                else:
                    full_text = "费用分解计算中，请检查结算数据是否完整。"

            result_data: dict = {"content": full_text}
            if decomposition_data:
                result_data["decomposition"] = decomposition_data

            return AgentResponse(
                scenario="policy_qa_fee_decomposition",
                status="completed",
                result=result_data,
                citations=[],
                tasks=[],
                missing_fields=[],
                uncertainties=[],
                blocked_actions=[],
                audit={"workflow_id": context.workflow_id, "steps": [
                    "intent", "sql_query", "rewrite", "search", "decomposition", "explain"
                ]},
            )
        except Exception as e:
            logger.exception(f"Policy QA pipeline failed: {e}")
            return AgentResponse(
                scenario="policy_qa_fee_decomposition",
                status="completed",
                result={"content": f"费用分析过程中遇到问题：{str(e)}\n请您稍后重试或联系医保办确认。"},
                citations=[],
                tasks=[],
                missing_fields=[],
                uncertainties=[f"费用分析异常: {str(e)}"],
                blocked_actions=[],
                audit={"workflow_id": context.workflow_id},
            )


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
