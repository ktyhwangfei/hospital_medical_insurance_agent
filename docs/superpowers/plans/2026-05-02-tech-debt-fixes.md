# Tech Debt Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three known MVP tech debts: routes returning raw `dict` instead of `AgentResponse`, hardcoded risk data in `pre_discharge_joint_qc/service.py` violating the decoupling discipline, and hardcoded `task_id` in `build_human_confirmation_response`.

**Architecture:** Each debt is fixed independently. The `AgentResponse` Pydantic model already exists in `schemas.py` — we route all endpoints to return `AgentResponse` instances. The pre-discharge QC service is refactored to call the three in-memory adapters it should already be using. The risk control service generates deterministic unique task IDs from the blocked actions list. All changes are backward-compatible at the JSON level.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, pytest, FastAPI TestClient

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `runtime/api/routes.py` | Modify | Return `AgentResponse` Pydantic instances from `chat()`, `patient_context()`, `workflow_status()`, `task_status()`, `confirm_task()` |
| `runtime/api/schemas.py` | Modify | Add `PatientContextResponse`, `WorkflowStatusResponse`, `TaskStatusResponse`, `TaskConfirmResponse` models |
| `business_scenarios/pre_discharge_joint_qc/service.py` | Modify | Replace hardcoded risk data with calls to `InMemoryPreAuditAdapter`, `InMemoryDrgDipAdapter`, `InMemoryMedicalRecordAdapter` |
| `security/risk_control/service.py` | Modify | Replace hardcoded `'task-human-confirm-001'` with deterministic ID derived from actions |
| `tests/e2e/test_settlement_exception.py` | Modify | Assert response is valid `AgentResponse` |
| `tests/e2e/test_pre_discharge_joint_qc.py` | Modify | Assert risks come from adapter data |
| `tests/security/test_high_risk_and_permission.py` | Modify | Assert unique task_id for different blocked action sets |
| `tests/integration/test_full_mvp_contract.py` | Modify | Assert `AgentResponse` model validates all chat responses |
| `tests/unit/test_tech_debt_fixes.py` | Create | Unit tests for each debt fix |

---

### Task 1: Return `AgentResponse` from `chat()` endpoint

**Files:**
- Modify: `src/runtime/api/routes.py:22-39`
- Modify: `src/runtime/api/schemas.py:14-23`
- Create: `src/tests/unit/test_tech_debt_fixes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tech_debt_fixes.py
from src.runtime.api.schemas import AgentResponse


def test_chat_returns_agent_response_instance():
    from src.runtime.api.routes import chat
    from src.runtime.api.schemas import ChatRequest

    request = ChatRequest(
        user_id='u1',
        role='cashier',
        message='医保结算失败了',
    )
    result = chat(request)
    assert isinstance(result, AgentResponse)


def test_chat_missing_context_returns_agent_response():
    from src.runtime.api.routes import chat
    from src.runtime.api.schemas import ChatRequest

    request = ChatRequest(
        user_id='u1',
        role='cashier',
        message='医保结算失败了，帮我看看',
    )
    result = chat(request)
    assert isinstance(result, AgentResponse)
    assert result.status == 'needs_clarification'
    assert result.missing_fields == ['patient_id', 'encounter_id']
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py -v`
Expected: FAIL — `chat()` returns a `dict`, not an `AgentResponse`.

- [ ] **Step 3: Modify `chat()` to return `AgentResponse` instances**

```python
# src/runtime/api/routes.py (full replacement)
from fastapi import APIRouter, HTTPException

from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc
from src.business_scenarios.settlement_exception_guide.service import guide_settlement_exception
from src.data_platform.data_access.in_memory import build_sample_store
from src.runtime.api.schemas import AgentResponse, ChatRequest, TaskConfirmRequest
from src.runtime.clarification.service import missing_context_fields
from src.runtime.intent.service import detect_intent
from src.security.authorization.service import visible_fields_for, is_allowed
from src.security.desensitization.service import mask_name
from src.security.risk_control.service import detect_blocked_actions, build_human_confirmation_response
from src.shared.schemas.responses import error_detail

router = APIRouter()


@router.get('/version')
def version() -> dict[str, str]:
    return {'module': 'medical-insurance-ai-agent', 'mode': 'memory-mvp'}


@router.post('/chat')
def chat(request: ChatRequest) -> AgentResponse:
    missing = missing_context_fields(request.patient_id, request.encounter_id)
    if missing:
        return AgentResponse(status='needs_clarification', missing_fields=missing)
    blocked = detect_blocked_actions(request.message)
    if blocked:
        return build_human_confirmation_response(blocked)
    scenario = detect_intent(request.message)
    if scenario == 'settlement_exception_guidance':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return AgentResponse(**guide_settlement_exception(request.patient_id, request.encounter_id))
    if scenario == 'pre_discharge_quality_control':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return AgentResponse(**run_pre_discharge_qc(request.patient_id, request.encounter_id))
    return AgentResponse(status='not_implemented')
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_chat_returns_agent_response_instance src/tests/unit/test_tech_debt_fixes.py::test_chat_missing_context_returns_agent_response -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest src/tests -v`
Expected: All 15 existing tests + 2 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/runtime/api/routes.py src/tests/unit/test_tech_debt_fixes.py
git commit -m "fix: return AgentResponse Pydantic instance from chat endpoint"
```

---

### Task 2: Return typed models from all other API endpoints

**Files:**
- Modify: `src/runtime/api/schemas.py`
- Modify: `src/runtime/api/routes.py`

- [ ] **Step 1: Write the failing tests**

Add to `src/tests/unit/test_tech_debt_fixes.py`:

```python
from src.runtime.api.schemas import PatientContextResponse, WorkflowStatusResponse, TaskStatusResponse, TaskConfirmResponse


def test_patient_context_returns_typed_model():
    from src.runtime.api.routes import patient_context

    result = patient_context(patient_id='P001', encounter_id='E001', user_id='u1', role='cashier')
    assert isinstance(result, PatientContextResponse)


def test_workflow_status_returns_typed_model():
    from src.runtime.api.routes import workflow_status

    result = workflow_status(workflow_id='wf-001')
    assert isinstance(result, WorkflowStatusResponse)


def test_task_status_returns_typed_model():
    from src.runtime.api.routes import task_status

    result = task_status(task_id='task-001')
    assert isinstance(result, TaskStatusResponse)


def test_confirm_task_returns_typed_model():
    from src.runtime.api.routes import confirm_task
    from src.runtime.api.schemas import TaskConfirmRequest

    request = TaskConfirmRequest(task_id='task-001', action='confirm', user_id='u1')
    result = confirm_task(request)
    assert isinstance(result, TaskConfirmResponse)
    assert result.status == 'confirmed'
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_patient_context_returns_typed_model -v`
Expected: FAIL — `ImportError` for `PatientContextResponse` or `patient_context` returns `dict`.

- [ ] **Step 3: Add response models and update routes**

Add to `src/runtime/api/schemas.py`:

```python
class PatientContextResponse(BaseModel):
    patient: dict[str, Any] = Field(default_factory=dict)
    visible_fields: list[str] = Field(default_factory=list)
    encounter_id: str | None = None
    settlement_status: str | None = None
    audit_risks: list[Any] | None = None


class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str


class TaskConfirmResponse(BaseModel):
    task_id: str
    status: str
    confirmed_by: str
    confirmed_at: str
    reason: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
```

Update route handlers in `src/runtime/api/routes.py`:

```python
from src.runtime.api.schemas import AgentResponse, ChatRequest, PatientContextResponse, TaskConfirmRequest, TaskConfirmResponse, TaskStatusResponse, WorkflowStatusResponse


@router.get('/patient-context/{patient_id}/{encounter_id}')
def patient_context(patient_id: str, encounter_id: str, user_id: str, role: str) -> PatientContextResponse:
    store = build_sample_store()
    patient = store.get_patient(patient_id)
    tx = store.get_insurance_transaction(patient_id, encounter_id)
    fields = visible_fields_for(role)
    response = PatientContextResponse(
        patient={'patient_id': patient.patient_id, 'name': mask_name(patient.name)},
        visible_fields=sorted(fields),
    )
    if 'encounter_id' in fields:
        response.encounter_id = encounter_id
    if 'settlement_status' in fields:
        response.settlement_status = tx.settlement_status
    if 'audit_risks' in fields:
        response.audit_risks = []
    return response


@router.get('/workflows/{workflow_id}')
def workflow_status(workflow_id: str) -> WorkflowStatusResponse:
    return WorkflowStatusResponse(workflow_id=workflow_id, status='not_implemented')


@router.get('/tasks/{task_id}')
def task_status(task_id: str) -> TaskStatusResponse:
    return TaskStatusResponse(task_id=task_id, status='not_implemented')


@router.post('/tasks/confirm')
def confirm_task(request: TaskConfirmRequest) -> TaskConfirmResponse:
    if request.action not in ('confirm', 'reject'):
        raise HTTPException(status_code=400, detail=error_detail('INVALID_ACTION', 'action 必须是 confirm 或 reject'))

    return TaskConfirmResponse(
        task_id=request.task_id,
        status='confirmed' if request.action == 'confirm' else 'rejected',
        confirmed_by=request.user_id,
        confirmed_at='2026-05-02T00:00:00Z',
        reason=request.reason,
        result={} if request.action == 'confirm' else {'blocked': True, 'message': '用户拒绝执行该操作'},
    )
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py -v`
Expected: PASS for all 6 unit tests.

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest src/tests -v`
Expected: All 15 + 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/runtime/api/schemas.py src/runtime/api/routes.py src/tests/unit/test_tech_debt_fixes.py
git commit -m "fix: return typed Pydantic models from all API endpoints"
```

---

### Task 3: Replace hardcoded risk data in `pre_discharge_joint_qc` with adapter calls

**Files:**
- Modify: `src/business_scenarios/pre_discharge_joint_qc/service.py`
- Modify: `src/tests/e2e/test_pre_discharge_joint_qc.py`

- [ ] **Step 1: Write the failing test**

Add to `src/tests/unit/test_tech_debt_fixes.py`:

```python
def test_pre_discharge_qc_calls_adapters_not_hardcode():
    from unittest.mock import patch

    with (
        patch('src.business_scenarios.pre_discharge_joint_qc.service.InMemoryPreAuditAdapter') as mock_pre_audit,
        patch('src.business_scenarios.pre_discharge_joint_qc.service.InMemoryDrgDipAdapter') as mock_drg,
        patch('src.business_scenarios.pre_discharge_joint_qc.service.InMemoryMedicalRecordAdapter') as mock_mr,
    ):
        mock_pre_audit.return_value.query_audit_result.return_value = {
            'risk': 'test_audit_risk', 'risk_level': 'high', 'patient_id': 'P001', 'encounter_id': 'E001',
        }
        mock_drg.return_value.query_group_result.return_value = {
            'risk': 'test_drg_risk', 'risk_level': 'medium', 'patient_id': 'P001', 'encounter_id': 'E001',
        }
        mock_mr.return_value.query_homepage.return_value = {
            'risk': 'test_mr_risk', 'risk_level': 'low', 'patient_id': 'P001', 'encounter_id': 'E001',
        }

        from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc
        result = run_pre_discharge_qc('P001', 'E001')

        mock_pre_audit.return_value.query_audit_result.assert_called_once_with('P001', 'E001')
        mock_drg.return_value.query_group_result.assert_called_once_with('P001', 'E001')
        mock_mr.return_value.query_homepage.assert_called_once_with('P001', 'E001')
        assert result['result']['risks'][0]['risk_type'] == 'test_audit_risk'
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_pre_discharge_qc_calls_adapters_not_hardcode -v`
Expected: FAIL — `mock_pre_audit.return_value.query_audit_result.assert_called_once_with` fails because the function doesn't call the adapter.

- [ ] **Step 3: Refactor `run_pre_discharge_qc` to use adapters**

Replace `src/business_scenarios/pre_discharge_joint_qc/service.py`:

```python
from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter


def run_pre_discharge_qc(patient_id: str, encounter_id: str) -> dict:
    pre_audit = InMemoryPreAuditAdapter().query_audit_result(patient_id, encounter_id)
    drg = InMemoryDrgDipAdapter().query_group_result(patient_id, encounter_id)
    mr = InMemoryMedicalRecordAdapter().query_homepage(patient_id, encounter_id)

    risks = [
        {'risk_type': pre_audit['risk'], 'risk_level': pre_audit.get('risk_level', 'high'), 'responsible_role': '医保办', 'recommendation': '复核限制用药规则命中原因'},
        {'risk_type': drg['risk'], 'risk_level': drg.get('risk_level', 'medium'), 'responsible_role': '科主任', 'recommendation': '关注病组盈亏和费用结构'},
        {'risk_type': mr['risk'], 'risk_level': mr.get('risk_level', 'medium'), 'responsible_role': '病案室', 'recommendation': '复核主要诊断与手术编码'},
    ]
    tasks = [
        {'task_id': f'task-qc-{idx}', 'task_type': 'rectification', 'status': 'pending', 'responsible_role': risk['responsible_role'], 'description': risk['recommendation']}
        for idx, risk in enumerate(risks, start=1)
    ]
    return {
        'scenario': 'pre_discharge_quality_control',
        'status': 'completed',
        'result': {'risks': risks},
        'citations': [
            {'source_type': 'pre_audit', 'source_id': f'{patient_id}:{encounter_id}', 'summary': pre_audit['risk']},
            {'source_type': 'drg_dip', 'source_id': f'{patient_id}:{encounter_id}', 'summary': drg['risk']},
            {'source_type': 'medical_record', 'source_id': f'{patient_id}:{encounter_id}', 'summary': mr['risk']},
        ],
        'tasks': tasks,
        'missing_fields': [],
        'uncertainties': [],
        'blocked_actions': [],
        'audit': {'workflow_id': f'wf-qc-{patient_id}-{encounter_id}', 'steps': ['query_pre_audit', 'query_drg_dip', 'query_medical_record', 'create_tasks']},
    }
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_pre_discharge_qc_calls_adapters_not_hardcode -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest src/tests -v`
Expected: All tests pass. The existing e2e test `test_pre_discharge_quality_control_creates_tasks_with_citations` still passes because the in-memory adapters still return the same risk names.

- [ ] **Step 6: Commit**

```bash
git add src/business_scenarios/pre_discharge_joint_qc/service.py src/tests/unit/test_tech_debt_fixes.py
git commit -m "fix: replace hardcoded risk data with adapter calls in pre-discharge QC"
```

---

### Task 4: Replace hardcoded `task_id` in `build_human_confirmation_response`

**Files:**
- Modify: `src/security/risk_control/service.py`
- Modify: `src/tests/security/test_high_risk_and_permission.py`

- [ ] **Step 1: Write the failing test**

Add to `src/tests/unit/test_tech_debt_fixes.py`:

```python
def test_human_confirmation_task_id_is_deterministic_and_unique():
    from src.security.risk_control.service import build_human_confirmation_response

    r1 = build_human_confirmation_response(['退费'])
    r2 = build_human_confirmation_response(['退费', '冲正'])
    r3 = build_human_confirmation_response(['退费'])

    assert r1.tasks[0]['task_id'] == r3.tasks[0]['task_id']
    assert r1.tasks[0]['task_id'] != r2.tasks[0]['task_id']
    assert r1.tasks[0]['task_id'].startswith('task-confirm-')
    assert len(r2.tasks) >= 1


def test_human_confirmation_returns_agent_response():
    from src.runtime.api.schemas import AgentResponse
    from src.security.risk_control.service import build_human_confirmation_response

    result = build_human_confirmation_response(['退费'])
    assert isinstance(result, AgentResponse)
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_human_confirmation_task_id_is_deterministic_and_unique -v`
Expected: FAIL — current code always returns `'task-human-confirm-001'` regardless of actions.

- [ ] **Step 3: Replace hardcoded task_id with deterministic ID**

Replace `src/security/risk_control/service.py`:

```python
import hashlib

from src.config.security_policy.rules import HIGH_RISK_ACTIONS
from src.runtime.api.schemas import AgentResponse


def detect_blocked_actions(message: str) -> list[str]:
    return [action for action in HIGH_RISK_ACTIONS if action in message]


def build_human_confirmation_response(actions: list[str]) -> AgentResponse:
    actions_key = '-'.join(sorted(actions))
    task_id = f'task-confirm-{hashlib.md5(actions_key.encode()).hexdigest()[:8]}'
    return AgentResponse(
        scenario='high_risk_action_confirmation',
        status='waiting_human_confirmation',
        result={},
        citations=[],
        tasks=[{'task_id': task_id, 'task_type': 'human_confirmation', 'status': 'pending', 'description': '请人工确认高风险动作'}],
        missing_fields=[],
        uncertainties=[],
        blocked_actions=actions,
        audit={'workflow_id': f'wf-high-risk-{task_id}', 'steps': ['detect_high_risk_action', 'create_human_confirmation_task']},
    )
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_human_confirmation_task_id_is_deterministic_and_unique src/tests/unit/test_tech_debt_fixes.py::test_human_confirmation_returns_agent_response -v`
Expected: PASS

- [ ] **Step 5: Update existing test for non-deterministic order**

The existing test `test_high_risk_refund_and_reversal_are_blocked` uses `set()` comparison for `blocked_actions`, but doesn't assert the specific `task_id`. Verify it still passes:

Run: `python -m pytest src/tests/security/test_high_risk_and_permission.py -v`
Expected: PASS — the existing test only checks `body['tasks'][0]['task_type'] == 'human_confirmation'`, not the specific task_id value.

- [ ] **Step 6: Update human confirmation integration test**

The test `test_human_confirmation_api_confirm` currently sends `task_id='task-human-confirm-001'` which is no longer generated. Update it to use the new deterministic ID format. Modify `src/tests/integration/test_human_confirmation.py`:

```python
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.security.risk_control.service import build_human_confirmation_response


def test_human_confirmation_api_confirm():
    client = TestClient(create_app())
    confirmation = build_human_confirmation_response(['退费'])
    task_id = confirmation.tasks[0]['task_id']
    response = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
        'task_id': task_id,
        'action': 'confirm',
        'user_id': 'u-medical-office-001',
        'reason': '确认执行退费操作'
    })
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'confirmed'
    assert body['task_id'] == task_id


def test_human_confirmation_api_reject():
    client = TestClient(create_app())
    confirmation = build_human_confirmation_response(['退费'])
    task_id = confirmation.tasks[0]['task_id']
    response = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
        'task_id': task_id,
        'action': 'reject',
        'user_id': 'u-medical-office-001',
        'reason': '风险过高，拒绝执行'
    })
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'rejected'
    assert body['result']['blocked'] is True


def test_human_confirmation_invalid_action():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/tasks/confirm', json={
        'task_id': 'task-001',
        'action': 'approve',
        'user_id': 'u001'
    })
    assert response.status_code == 400
```

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest src/tests -v`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/security/risk_control/service.py src/tests/unit/test_tech_debt_fixes.py src/tests/integration/test_human_confirmation.py
git commit -m "fix: replace hardcoded task_id with deterministic hash in risk control"
```

---

### Task 5: Upgrade remaining `dict` returns to `AgentResponse` across all scenario services

**Files:**
- Modify: `src/business_scenarios/settlement_exception_guide/service.py`
- Modify: `src/business_scenarios/pre_discharge_joint_qc/service.py`
- Modify: `src/runtime/scheduling/service.py`
- Modify: `src/runtime/api/routes.py`

- [ ] **Step 1: Write the failing test**

Add to `src/tests/unit/test_tech_debt_fixes.py`:

```python
def test_guide_settlement_exception_returns_agent_response():
    from src.runtime.api.schemas import AgentResponse
    from src.business_scenarios.settlement_exception_guide.service import guide_settlement_exception

    result = guide_settlement_exception('P001', 'E001')
    assert isinstance(result, AgentResponse)


def test_degraded_response_returns_agent_response():
    from src.runtime.api.schemas import AgentResponse
    from src.runtime.scheduling.service import degraded_response

    result = degraded_response('P002', 'E002', '医保接口调用失败')
    assert isinstance(result, AgentResponse)
    assert result.status == 'degraded'


def test_run_pre_discharge_qc_returns_agent_response():
    from src.runtime.api.schemas import AgentResponse
    from src.business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc

    result = run_pre_discharge_qc('P001', 'E001')
    assert isinstance(result, AgentResponse)
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_guide_settlement_exception_returns_agent_response src/tests/unit/test_tech_debt_fixes.py::test_degraded_response_returns_agent_response src/tests/unit/test_tech_debt_fixes.py::test_run_pre_discharge_qc_returns_agent_response -v`
Expected: FAIL — functions return raw `dict`.

- [ ] **Step 3: Refactor settlement exception guide to return `AgentResponse`**

Replace `src/business_scenarios/settlement_exception_guide/service.py`:

```python
from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.knowledge_extension.knowledge.in_memory import ERROR_CODE_KNOWLEDGE
from src.runtime.api.schemas import AgentResponse
from src.runtime.scheduling.service import degraded_response


def guide_settlement_exception(patient_id: str, encounter_id: str) -> AgentResponse:
    if patient_id == 'P002':
        return degraded_response(patient_id, encounter_id, '医保接口调用失败，当前结论存在不确定性')

    tx = InMemoryInsuranceInterfaceAdapter().query_transaction(patient_id, encounter_id)
    knowledge = ERROR_CODE_KNOWLEDGE[tx.error_code]
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='completed',
        result={
            'exception_type': knowledge['exception_type'],
            'error_code': tx.error_code,
            'error_explanation': knowledge['description'],
            'responsible_role': knowledge['responsible_role'],
            'recommended_steps': [knowledge['recommendation']],
            'requires_human_confirmation': False,
        },
        citations=[
            {'source_type': 'insurance_transaction', 'source_id': f'{patient_id}:{encounter_id}', 'summary': tx.settlement_status},
            {'source_type': 'knowledge_error_code', 'source_id': tx.error_code, 'summary': knowledge['description']},
        ],
        tasks=[],
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction', 'retrieve_error_code', 'build_result']},
    )
```

- [ ] **Step 4: Refactor `degraded_response` to return `AgentResponse`**

Replace `src/runtime/scheduling/service.py`:

```python
from src.runtime.api.schemas import AgentResponse


def degraded_response(patient_id: str, encounter_id: str, reason: str) -> AgentResponse:
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='degraded',
        result={},
        citations=[],
        tasks=[],
        missing_fields=[],
        uncertainties=[reason],
        blocked_actions=[],
        audit={'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction_failed', 'return_degraded_result']},
    )
```

- [ ] **Step 5: Refactor `run_pre_discharge_qc` to return `AgentResponse`**

Replace `src/business_scenarios/pre_discharge_joint_qc/service.py`:

```python
from src.adapters.drg_dip.in_memory import InMemoryDrgDipAdapter
from src.adapters.medical_record.in_memory import InMemoryMedicalRecordAdapter
from src.adapters.pre_audit.in_memory import InMemoryPreAuditAdapter
from src.runtime.api.schemas import AgentResponse


def run_pre_discharge_qc(patient_id: str, encounter_id: str) -> AgentResponse:
    pre_audit = InMemoryPreAuditAdapter().query_audit_result(patient_id, encounter_id)
    drg = InMemoryDrgDipAdapter().query_group_result(patient_id, encounter_id)
    mr = InMemoryMedicalRecordAdapter().query_homepage(patient_id, encounter_id)

    risks = [
        {'risk_type': pre_audit['risk'], 'risk_level': pre_audit.get('risk_level', 'high'), 'responsible_role': '医保办', 'recommendation': '复核限制用药规则命中原因'},
        {'risk_type': drg['risk'], 'risk_level': drg.get('risk_level', 'medium'), 'responsible_role': '科主任', 'recommendation': '关注病组盈亏和费用结构'},
        {'risk_type': mr['risk'], 'risk_level': mr.get('risk_level', 'medium'), 'responsible_role': '病案室', 'recommendation': '复核主要诊断与手术编码'},
    ]
    tasks = [
        {'task_id': f'task-qc-{idx}', 'task_type': 'rectification', 'status': 'pending', 'responsible_role': risk['responsible_role'], 'description': risk['recommendation']}
        for idx, risk in enumerate(risks, start=1)
    ]
    return AgentResponse(
        scenario='pre_discharge_quality_control',
        status='completed',
        result={'risks': risks},
        citations=[
            {'source_type': 'pre_audit', 'source_id': f'{patient_id}:{encounter_id}', 'summary': pre_audit['risk']},
            {'source_type': 'drg_dip', 'source_id': f'{patient_id}:{encounter_id}', 'summary': drg['risk']},
            {'source_type': 'medical_record', 'source_id': f'{patient_id}:{encounter_id}', 'summary': mr['risk']},
        ],
        tasks=tasks,
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={'workflow_id': f'wf-qc-{patient_id}-{encounter_id}', 'steps': ['query_pre_audit', 'query_drg_dip', 'query_medical_record', 'create_tasks']},
    )
```

- [ ] **Step 6: Update `routes.py` to remove `AgentResponse(**...)` unwrapping**

Since all services now return `AgentResponse` directly, update `chat()` in `src/runtime/api/routes.py`:

```python
@router.post('/chat')
def chat(request: ChatRequest) -> AgentResponse:
    missing = missing_context_fields(request.patient_id, request.encounter_id)
    if missing:
        return AgentResponse(status='needs_clarification', missing_fields=missing)
    blocked = detect_blocked_actions(request.message)
    if blocked:
        return build_human_confirmation_response(blocked)
    scenario = detect_intent(request.message)
    if scenario == 'settlement_exception_guidance':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return guide_settlement_exception(request.patient_id, request.encounter_id)
    if scenario == 'pre_discharge_quality_control':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return run_pre_discharge_qc(request.patient_id, request.encounter_id)
    return AgentResponse(status='not_implemented')
```

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest src/tests -v`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/business_scenarios/settlement_exception_guide/service.py src/business_scenarios/pre_discharge_joint_qc/service.py src/runtime/scheduling/service.py src/runtime/api/routes.py src/tests/unit/test_tech_debt_fixes.py
git commit -m "fix: upgrade all scenario services to return AgentResponse"
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest src/tests/unit/test_tech_debt_fixes.py::test_guide_settlement_exception_returns_agent_response src/tests/unit/test_tech_debt_fixes.py::test_degraded_response_returns_agent_response -v`
Expected: FAIL — both functions return raw `dict`.

- [ ] **Step 3: Refactor settlement exception guide to return `AgentResponse`**

Replace `src/business_scenarios/settlement_exception_guide/service.py`:

```python
from src.adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from src.knowledge_extension.knowledge.in_memory import ERROR_CODE_KNOWLEDGE
from src.runtime.api.schemas import AgentResponse
from src.runtime.scheduling.service import degraded_response


def guide_settlement_exception(patient_id: str, encounter_id: str) -> AgentResponse:
    if patient_id == 'P002':
        return degraded_response(patient_id, encounter_id, '医保接口调用失败，当前结论存在不确定性')

    tx = InMemoryInsuranceInterfaceAdapter().query_transaction(patient_id, encounter_id)
    knowledge = ERROR_CODE_KNOWLEDGE[tx.error_code]
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='completed',
        result={
            'exception_type': knowledge['exception_type'],
            'error_code': tx.error_code,
            'error_explanation': knowledge['description'],
            'responsible_role': knowledge['responsible_role'],
            'recommended_steps': [knowledge['recommendation']],
            'requires_human_confirmation': False,
        },
        citations=[
            {'source_type': 'insurance_transaction', 'source_id': f'{patient_id}:{encounter_id}', 'summary': tx.settlement_status},
            {'source_type': 'knowledge_error_code', 'source_id': tx.error_code, 'summary': knowledge['description']},
        ],
        tasks=[],
        missing_fields=[],
        uncertainties=[],
        blocked_actions=[],
        audit={'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction', 'retrieve_error_code', 'build_result']},
    )
```

- [ ] **Step 4: Refactor `degraded_response` to return `AgentResponse`**

Replace `src/runtime/scheduling/service.py`:

```python
from src.runtime.api.schemas import AgentResponse


def degraded_response(patient_id: str, encounter_id: str, reason: str) -> AgentResponse:
    return AgentResponse(
        scenario='settlement_exception_guidance',
        status='degraded',
        result={},
        citations=[],
        tasks=[],
        missing_fields=[],
        uncertainties=[reason],
        blocked_actions=[],
        audit={'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction_failed', 'return_degraded_result']},
    )
```

- [ ] **Step 5: Update `routes.py` to avoid double-wrapping**

Since `guide_settlement_exception` and `build_human_confirmation_response` now return `AgentResponse` directly, update `chat()` in `src/runtime/api/routes.py`:

```python
@router.post('/chat')
def chat(request: ChatRequest) -> AgentResponse:
    missing = missing_context_fields(request.patient_id, request.encounter_id)
    if missing:
        return AgentResponse(status='needs_clarification', missing_fields=missing)
    blocked = detect_blocked_actions(request.message)
    if blocked:
        return build_human_confirmation_response(blocked)
    scenario = detect_intent(request.message)
    if scenario == 'settlement_exception_guidance':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return guide_settlement_exception(request.patient_id, request.encounter_id)
    if scenario == 'pre_discharge_quality_control':
        if not is_allowed(request.role, scenario):
            raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
        return AgentResponse(**run_pre_discharge_qc(request.patient_id, request.encounter_id))
    return AgentResponse(status='not_implemented')
```

- [ ] **Step 6: Run full test suite**

Run: `python -m pytest src/tests -v`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/business_scenarios/settlement_exception_guide/service.py src/runtime/scheduling/service.py src/runtime/api/routes.py src/tests/unit/test_tech_debt_fixes.py
git commit -m "fix: upgrade all scenario services to return AgentResponse"
```

---

### Task 6: Final integration verification

**Files:**
- Modify: `src/tests/integration/test_full_mvp_contract.py`

- [ ] **Step 1: Verify all chat responses conform to AgentResponse schema**

Update `src/tests/integration/test_full_mvp_contract.py`:

```python
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app
from src.runtime.api.schemas import AgentResponse


def test_all_mvp_contracts_pass_together():
    client = TestClient(create_app())
    openapi = client.get('/openapi.json').json()
    assert '/api/v1/medical-insurance-ai-agent/chat' in openapi['paths']

    settlement = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '患者 P001 本次医保结算失败', 'patient_id': 'P001', 'encounter_id': 'E001'
    }).json()
    assert settlement['status'] == 'completed'
    AgentResponse(**settlement)

    qc = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '检查患者 P001 出院前医保风险', 'patient_id': 'P001', 'encounter_id': 'E001'
    }).json()
    assert qc['tasks']
    AgentResponse(**qc)

    degraded = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '患者 P002 本次医保结算失败', 'patient_id': 'P002', 'encounter_id': 'E002'
    }).json()
    assert degraded['status'] == 'degraded'
    AgentResponse(**degraded)

    for body in (settlement, qc, degraded):
        assert set(body.keys()) == {'scenario', 'status', 'result', 'citations', 'tasks', 'missing_fields', 'uncertainties', 'blocked_actions', 'audit'}
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest src/tests -v`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/tests/integration/test_full_mvp_contract.py
git commit -m "test: add AgentResponse schema validation to full MVP contract test"
```

---

## Final Verification

Run these commands before claiming completion:

```bash
python -m pytest src/tests -v
```

Expected: All tests pass with no failures.

## Coverage Review

- **Tech debt 1** (`routes.py` returns raw `dict`): Covered by Tasks 1, 2, 5 — all endpoints now return Pydantic model instances.
- **Tech debt 2** (`pre_discharge_joint_qc/service.py` hardcoded risk data): Covered by Task 3 — risks now come from adapter calls.
- **Tech debt 3** (`build_human_confirmation_response` hardcoded `task_id`): Covered by Task 4 — task_id is now a deterministic hash of the blocked actions.
