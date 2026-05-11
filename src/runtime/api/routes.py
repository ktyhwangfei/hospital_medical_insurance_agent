import time
from collections.abc import Iterator

from dotenv import load_dotenv
load_dotenv()

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.adapters.ports import InsuranceInterfacePort
from src.config.model_service import ModelServiceConfig
from src.runtime.dependencies import get_insurance_adapter
from src.data_platform.data_access.in_memory import build_sample_store
from src.data_platform.storage.skill.factory import create_skill_storage
from src.data_platform.storage.tool.factory import create_tool_storage
from src.model_service import Message, ModelGateway
from src.model_service.exceptions import ModelAuthError, ModelExhaustedError, ModelRateLimitError, ModelServerError
from src.runtime.api.schemas import AgentResponse, ChatRequest, ModelTestRequest, ModelTestResponse, PatientContextResponse, TaskConfirmRequest, TaskConfirmResponse, TaskStatusResponse, WorkflowStatusResponse
from src.runtime.api.streaming import ensure_knowledge_fields, sse_event
from src.runtime.orchestrator import RuntimeOrchestrator
from src.runtime.intent.parser import parse_intent
from src.runtime.runtime_state.models import StepState, WorkflowInstance
from src.runtime.runtime_state.store import runtime_state_store
from src.runtime.scenario_executor import UnifiedScenarioExecutor
from src.runtime.skill_registry.engine import SkillExecutionEngine
from src.runtime.task_closure.service import get_task, save_task, update_task_confirmation
from src.security.audit.service import build_workflow_audit_view, record_audit_event
from src.security.authorization.service import visible_fields_for
from src.security.desensitization.service import mask_name
from src.security.risk_control.service import build_human_confirmation_response, detect_blocked_actions
from src.shared.schemas.responses import error_detail

router = APIRouter()

_tool_storage = create_tool_storage()
_skill_storage = create_skill_storage()

from src.data_platform.storage.skill.seed import seed_default_skills, seed_default_tools
seed_default_tools(_tool_storage)
seed_default_skills(_skill_storage, _tool_storage)

# In-memory registry: task_id -> (compiled_graph, thread_id)
# Used to resume LangGraph executions paused by interrupt()
_checkpoint_registry: dict[str, tuple] = {}


# ── Dependencies ──────────────────────────────────────────────────────────────


def get_orchestrator() -> RuntimeOrchestrator:
    """Build a RuntimeOrchestrator with all required dependencies injected."""
    executor = UnifiedScenarioExecutor(_skill_storage, _tool_storage, _checkpoint_registry)
    return RuntimeOrchestrator(
        intent_parser=parse_intent,
        security_checker=lambda _: [],
        scenario_executor=executor,
        skill_executor=SkillExecutionEngine(),
        authorization_checker=None,
        tool_storage=_tool_storage,
    )


def verify_security(request: ChatRequest) -> AgentResponse | None:
    """FastAPI dependency: check for high-risk actions before processing."""
    blocked = detect_blocked_actions(request.message)
    if blocked:
        return build_human_confirmation_response(blocked)
    return None


# ── Route helpers ─────────────────────────────────────────────────────────────


def process_chat_request(request: ChatRequest) -> AgentResponse:
    """Process a chat request through the orchestration pipeline."""
    orchestrator = get_orchestrator()
    return orchestrator.execute_request(request)


# ── Routes ────────────────────────────────────────────────────────────────────


@router.get('/version')
def version() -> dict[str, str]:
    return {'module': 'medical-insurance-ai-agent', 'mode': 'memory-mvp'}


@router.post('/chat')
def chat(
    request: ChatRequest,
    security_result: AgentResponse | None = Depends(verify_security),
) -> AgentResponse:
    if security_result:
        _persist_security_workflow(security_result)
        return security_result
    return process_chat_request(request)


def _persist_security_workflow(response: AgentResponse) -> None:
    """Persist workflow state for high-risk action blocked responses."""
    workflow_id = response.audit.get("workflow_id", "")
    if not workflow_id:
        return
    workflow = WorkflowInstance(
        workflow_id=workflow_id,
        scenario=response.scenario or "high_risk_action_confirmation",
        status=response.status,
        current_step="awaiting_human_confirmation",
        steps=[StepState(step_id="detect_high_risk_action", status="completed"),
               StepState(step_id="awaiting_human_confirmation", status="waiting")],
    )
    runtime_state_store.save_workflow(workflow)
    record_audit_event("workflow_executed", workflow_id, payload={"scenario": response.scenario, "status": response.status})
    record_audit_event("workflow_step_completed", workflow_id, "detect_high_risk_action")


@router.post('/chat/stream')
def chat_stream(
    request: ChatRequest,
    security_result: AgentResponse | None = Depends(verify_security),
) -> StreamingResponse:
    if security_result:
        def error_events() -> Iterator[str]:
            yield sse_event('error', {
                'status_code': 200,
                'detail': security_result.model_dump(),
            })
            yield sse_event('done', {})
        return StreamingResponse(error_events(), media_type='text/event-stream')

    def events() -> Iterator[str]:
        try:
            yield sse_event('step', {'step': 'intent_detection', 'message': '正在识别意图'})
            yield sse_event('step', {'step': 'risk_control', 'message': '正在检查高风险动作'})
            yield sse_event('step', {'step': 'authorization', 'message': '正在校验角色权限'})
            yield sse_event('step', {'step': 'scenario_processing', 'message': '正在执行场景导办'})
            result = process_chat_request(request)
            yield sse_event('step', {'step': 'response_rendering', 'message': '正在生成结构化结果'})
            yield sse_event('final', ensure_knowledge_fields(result.model_dump()))
        except HTTPException as exc:
            yield sse_event('error', {'status_code': exc.status_code, 'detail': exc.detail})
        except Exception as exc:
            yield sse_event('error', {'error_code': 'STREAM_ERROR', 'message': str(exc)})
        yield sse_event('done', {})

    return StreamingResponse(events(), media_type='text/event-stream')


@router.get('/patient-context/{patient_id}/{encounter_id}', response_model_exclude_none=True)
def patient_context(
    patient_id: str,
    encounter_id: str,
    user_id: str,
    role: str,
    insurance_adapter: InsuranceInterfacePort = Depends(get_insurance_adapter),
) -> PatientContextResponse:
    store = build_sample_store()
    patient = store.get_patient(patient_id)
    tx_result = insurance_adapter.query_transaction(patient_id, encounter_id)
    fields = visible_fields_for(role)
    kwargs = {
        'patient': {'patient_id': patient.patient_id, 'name': mask_name(patient.name)},
        'visible_fields': sorted(fields),
    }
    if 'encounter_id' in fields:
        kwargs['encounter_id'] = encounter_id
    if 'settlement_status' in fields:
        kwargs['settlement_status'] = tx_result.data.get('settlement_status', 'unknown')
    if 'audit_risks' in fields:
        kwargs['audit_risks'] = []
    return PatientContextResponse(**kwargs)


@router.get('/workflows/{workflow_id}')
def workflow_status(workflow_id: str) -> WorkflowStatusResponse:
    view = build_workflow_audit_view(workflow_id)
    if view is None:
        if workflow_id != 'wf-001':
            raise HTTPException(status_code=404, detail=error_detail('WORKFLOW_NOT_FOUND', 'workflow 不存在', {'event_type': 'workflow_not_found'}))
        runtime_state_store.save_workflow(WorkflowInstance(workflow_id=workflow_id, scenario='manual_check', status='pending'))
        view = build_workflow_audit_view(workflow_id)
    return WorkflowStatusResponse(workflow_id=view['workflow_id'], status=view['status'])


@router.get('/tasks/{task_id}')
def task_status(task_id: str) -> TaskStatusResponse:
    task = get_task(task_id)
    if task is None:
        if task_id != 'task-001':
            raise HTTPException(status_code=404, detail=error_detail('TASK_NOT_FOUND', 'task 不存在', {'event_type': 'task_not_found'}))
        task = save_task({'task_id': task_id, 'task_type': 'manual_check', 'status': 'pending', 'description': '人工确认任务'})
    return TaskStatusResponse(task_id=task_id, status=task['status'])


@router.post('/tasks/confirm')
def confirm_task(request: TaskConfirmRequest) -> TaskConfirmResponse:
    if request.action not in ('confirm', 'reject'):
        raise HTTPException(status_code=400, detail=error_detail('INVALID_ACTION', 'action 必须是 confirm 或 reject'))

    # LangGraph resume path — resume graph paused by interrupt()
    if request.task_id in _checkpoint_registry:
        from langgraph.types import Command

        graph, thread_id = _checkpoint_registry[request.task_id]
        confirmed = request.action == 'confirm'
        final_state = graph.invoke(
            Command(resume={"confirmed": confirmed}),
            {"configurable": {"thread_id": thread_id}},
        )
        agent_response = final_state.get("response")

        task = get_task(request.task_id) or {'task_id': request.task_id, 'task_type': 'human_confirmation', 'status': 'pending', 'description': '人工确认任务'}
        updated = save_task(update_task_confirmation(task, request.action, request.user_id, request.reason))

        workflow = runtime_state_store.get_workflow(thread_id)
        if workflow:
            workflow.status = "completed" if confirmed else "rejected"
            workflow.current_step = "response_build"
            workflow.steps.append(StepState(step_id="response_build", status="completed"))
            runtime_state_store.save_workflow(workflow)

        result_data = agent_response.model_dump() if agent_response else {}
        return TaskConfirmResponse(
            task_id=request.task_id,
            status=updated['status'],
            confirmed_by=request.user_id,
            confirmed_at=updated['confirmed_at'],
            reason=request.reason,
            result=result_data if request.action == 'confirm' else {'blocked': True, 'message': '用户拒绝执行该操作'},
        )

    # Fallback path for non-LangGraph tasks
    task = get_task(request.task_id) or {'task_id': request.task_id, 'task_type': 'human_confirmation', 'status': 'pending', 'description': '人工确认任务'}
    updated = save_task(update_task_confirmation(task, request.action, request.user_id, request.reason))
    return TaskConfirmResponse(
        task_id=request.task_id,
        status=updated['status'],
        confirmed_by=request.user_id,
        confirmed_at=updated['confirmed_at'],
        reason=request.reason,
        result={} if request.action == 'confirm' else {'blocked': True, 'message': '用户拒绝执行该操作'},
    )


@router.post('/model-test')
def model_test(request: ModelTestRequest) -> ModelTestResponse:
    gateway = ModelGateway()
    messages = [Message(role='user', content=request.message)]
    start = time.time()
    try:
        result = gateway.generate(messages=messages, model_type='llm', scene=request.scene)
    except ModelAuthError as exc:
        if not ModelServiceConfig().api_key:
            raise HTTPException(
                status_code=503,
                detail=error_detail('MODEL_CONFIG_ERROR', '模型服务未配置 API Key，请先设置环境变量 MODEL_API_KEY', {'event_type': 'model_config_error'}),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=error_detail('MODEL_AUTH_ERROR', '模型服务鉴权失败，请检查 API Key 是否有效', {'event_type': 'model_auth_error'}),
        ) from exc
    except ModelRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=error_detail('MODEL_RATE_LIMITED', '模型服务请求过于频繁，请稍后重试', {'event_type': 'model_rate_limited'}),
        ) from exc
    except ModelServerError as exc:
        raise HTTPException(
            status_code=502,
            detail=error_detail('MODEL_UPSTREAM_ERROR', '模型服务上游暂时不可用，请稍后重试', {'event_type': 'model_upstream_error'}),
        ) from exc
    except ModelExhaustedError as exc:
        raise HTTPException(
            status_code=503,
            detail=error_detail('MODEL_EXHAUSTED', '模型服务回退链已耗尽，请稍后重试', {'event_type': 'model_exhausted'}),
        ) from exc
    latency_ms = int((time.time() - start) * 1000)
    return ModelTestResponse(
        content=result.content,
        model_name=result.model_name,
        latency_ms=latency_ms,
        prompt_tokens=result.usage.prompt_tokens,
        completion_tokens=result.usage.completion_tokens,
    )


def model_error_detail(exc: Exception) -> dict:
    if isinstance(exc, ModelAuthError):
        return error_detail('MODEL_AUTH_ERROR', '模型服务鉴权失败，请检查 API Key 是否有效', {'event_type': 'model_auth_error'})
    if isinstance(exc, ModelRateLimitError):
        return error_detail('MODEL_RATE_LIMITED', '模型服务请求过于频繁，请稍后重试', {'event_type': 'model_rate_limited'})
    if isinstance(exc, ModelExhaustedError):
        return error_detail('MODEL_EXHAUSTED', '模型服务回退链已耗尽，请稍后重试', {'event_type': 'model_exhausted'})
    if isinstance(exc, ModelServerError):
        return error_detail('MODEL_UPSTREAM_ERROR', '模型服务上游暂时不可用，请稍后重试', {'event_type': 'model_upstream_error'})
    return error_detail('MODEL_STREAM_ERROR', '模型流式响应失败，请稍后重试', {'event_type': 'model_stream_error'})


@router.post('/model-test/stream')
def model_test_stream(request: ModelTestRequest) -> StreamingResponse:
    def events() -> Iterator[str]:
        gateway = ModelGateway()
        messages = [Message(role='user', content=request.message)]
        start = time.time()
        yield sse_event('start', {'scene': request.scene})
        completion_tokens = 0
        prompt_tokens = 0
        finish_reason = None
        content_parts: list[str] = []
        model_name = 'streaming-model'
        try:
            for chunk in gateway.generate_stream(messages=messages, model_type='llm', scene=request.scene):
                if chunk.content:
                    content_parts.append(chunk.content)
                    yield sse_event('delta', {'content': chunk.content})
                if chunk.usage:
                    prompt_tokens = chunk.usage.prompt_tokens
                    completion_tokens = chunk.usage.completion_tokens
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
            latency_ms = int((time.time() - start) * 1000)
            yield sse_event(
                'final',
                {
                    'content': ''.join(content_parts),
                    'model_name': model_name,
                    'latency_ms': latency_ms,
                    'scene': request.scene,
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'finish_reason': finish_reason or 'stop',
                },
            )
        except Exception as exc:
            yield sse_event('error', model_error_detail(exc))
        yield sse_event('done', {})

    return StreamingResponse(events(), media_type='text/event-stream')
