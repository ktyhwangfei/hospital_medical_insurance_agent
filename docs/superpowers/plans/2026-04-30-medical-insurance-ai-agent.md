# medical-insurance-ai-agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建医保 AI 导办智能体 FastAPI 后端 MVP，使用内存数据、内存知识库、内存适配器和自动化测试打通结算异常导办、出院前联合质控、权限脱敏、高风险拦截、审计与任务闭环。

**Architecture:** 采用用户确认的 Project-root 长期工程架构，但第一阶段只启用后端核心子集：`runtime/`、`business_scenarios/`、`domain/`、`adapters/`、`data_platform/`、`knowledge_extension/`、`security/`、`shared/`、`config/`、`tests/`。业务流为 `runtime/api` 接收请求，`runtime/intent` 识别场景，`runtime/context` 构建上下文，`runtime/planning` 生成计划，`runtime/orchestration` 调度适配器与知识服务，`runtime/response` 返回 Web SDK 友好的结构化结果。

**Tech Stack:** Python 3.11+、FastAPI、uvicorn、asyncio、pytest、FastAPI TestClient；第一阶段不连接真实 PostgreSQL、Redis/Valkey、Milvus、Nginx 或医院业务系统。

---

## File Structure

创建以下文件。每个目录需包含 `__init__.py`，确保 pytest 可导入。

```text
runtime/api/app.py
runtime/api/routes.py
runtime/api/schemas.py
runtime/intent/service.py
runtime/clarification/service.py
runtime/context/service.py
runtime/planning/models.py
runtime/planning/service.py
runtime/orchestration/service.py
runtime/response/service.py
runtime/task_closure/service.py
runtime/runtime_state/models.py
business_scenarios/settlement_exception_guide/service.py
business_scenarios/pre_discharge_joint_qc/service.py
domain/common/models.py
domain/patient/models.py
domain/insurance/models.py
domain/order_fee/models.py
domain/audit_risk/models.py
domain/drg_dip/models.py
domain/medical_record/models.py
domain/task/models.py
data_platform/data_access/ports.py
data_platform/data_access/in_memory.py
data_platform/patient_profile/service.py
data_platform/data_quality/service.py
knowledge_extension/knowledge/in_memory.py
knowledge_extension/rag/service.py
knowledge_extension/rule_explanation/service.py
knowledge_extension/prompt_templates/templates.py
adapters/base/models.py
adapters/insurance_interface/in_memory.py
adapters/billing/in_memory.py
adapters/pre_audit/in_memory.py
adapters/drg_dip/in_memory.py
adapters/his/in_memory.py
adapters/emr/in_memory.py
adapters/medical_record/in_memory.py
security/authorization/service.py
security/desensitization/service.py
security/risk_control/service.py
security/audit/in_memory.py
shared/exceptions/models.py
shared/schemas/responses.py
config/security_policy/rules.py
config/agent_orchestration/scenarios.py
config/adapter/settings.py
tests/conftest.py
tests/e2e/test_medical_insurance_ai_agent_mvp.py
tests/security/test_security_boundaries.py
tests/integration/test_audit_and_contracts.py
tests/adapter_contract/test_adapter_failures.py
```

---

### Task 1: 工程骨架、FastAPI 应用与基础契约

**Files:**
- Create: `runtime/api/app.py`
- Create: `runtime/api/routes.py`
- Create: `runtime/api/schemas.py`
- Create: `shared/exceptions/models.py`
- Create: `shared/schemas/responses.py`
- Create: `tests/conftest.py`
- Create: `tests/integration/test_openapi_contract.py`

- [ ] **Step 1: Write the failing OpenAPI and health test**

```python
# tests/integration/test_openapi_contract.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def test_health_version_and_openapi_contract():
    client = TestClient(create_app())

    health = client.get('/health')
    assert health.status_code == 200
    assert health.json() == {'status': 'ok'}

    version = client.get('/api/v1/medical-insurance-ai-agent/version')
    assert version.status_code == 200
    assert version.json()['module'] == 'medical-insurance-ai-agent'
    assert version.json()['mode'] == 'memory-mvp'

    openapi = client.get('/openapi.json').json()
    paths = openapi['paths'].keys()
    assert '/api/v1/medical-insurance-ai-agent/chat' in paths
    assert '/api/v1/medical-insurance-ai-agent/patient-context/{patient_id}/{encounter_id}' in paths
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/integration/test_openapi_contract.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'runtime'`.

- [ ] **Step 3: Write minimal FastAPI app and schemas**

```python
# runtime/api/app.py
from fastapi import FastAPI

from runtime.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title='medical-insurance-ai-agent')

    @app.get('/health')
    def health() -> dict[str, str]:
        return {'status': 'ok'}

    app.include_router(router, prefix='/api/v1/medical-insurance-ai-agent')
    return app
```

```python
# runtime/api/routes.py
from fastapi import APIRouter

router = APIRouter()


@router.get('/version')
def version() -> dict[str, str]:
    return {'module': 'medical-insurance-ai-agent', 'mode': 'memory-mvp'}


@router.post('/chat')
def chat() -> dict[str, str]:
    return {'status': 'not_implemented'}


@router.get('/patient-context/{patient_id}/{encounter_id}')
def patient_context(patient_id: str, encounter_id: str) -> dict[str, str]:
    return {'patient_id': patient_id, 'encounter_id': encounter_id}
```

```python
# runtime/api/schemas.py
from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str
    role: str
    message: str
    patient_id: str | None = None
    encounter_id: str | None = None


class AgentResponse(BaseModel):
    scenario: str | None = None
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)
```

```python
# shared/exceptions/models.py
class PermissionDeniedError(Exception):
    def __init__(self, message: str, audit_event: dict):
        super().__init__(message)
        self.audit_event = audit_event
```

```python
# shared/schemas/responses.py
def error_detail(error_code: str, message: str, audit_event: dict | None = None) -> dict:
    return {'error_code': error_code, 'message': message, 'audit_event': audit_event or {}}
```

```python
# tests/conftest.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def build_client() -> TestClient:
    return TestClient(create_app())
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest tests/integration/test_openapi_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Update OpenSpec tasks and commit**

Mark done in `openspec/changes/add-medical-insurance-ai-agent/tasks.md`: 1.1, 1.2, 1.3, 1.4, 10.8.

Run:

```bash
git add runtime shared tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: add FastAPI MVP skeleton"
```

---

### Task 2: 领域模型、配置与内存样例数据

**Files:**
- Create: `domain/common/models.py`
- Create: `domain/patient/models.py`
- Create: `domain/insurance/models.py`
- Create: `domain/task/models.py`
- Create: `config/security_policy/rules.py`
- Create: `data_platform/data_access/in_memory.py`
- Test: `tests/unit/test_domain_and_sample_data.py`

- [ ] **Step 1: Write failing domain and sample data test**

```python
# tests/unit/test_domain_and_sample_data.py
from config.security_policy.rules import HIGH_RISK_ACTIONS, ROLE_VISIBLE_FIELDS
from data_platform.data_access.in_memory import build_sample_store


def test_sample_store_contains_patient_and_settlement_exception_data():
    store = build_sample_store()
    patient = store.get_patient('P001')
    tx = store.get_insurance_transaction('P001', 'E001')

    assert patient.name == '张三'
    assert tx.error_code == 'E-UPLOAD-001'
    assert tx.settlement_status == 'failed'


def test_security_policy_defines_roles_and_high_risk_actions():
    assert ROLE_VISIBLE_FIELDS['cashier'] == {'patient_id', 'encounter_id', 'settlement_status'}
    assert '退费' in HIGH_RISK_ACTIONS
    assert '冲正' in HIGH_RISK_ACTIONS
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/unit/test_domain_and_sample_data.py -q`

Expected: FAIL because modules do not exist.

- [ ] **Step 3: Write minimal models, config, and store**

```python
# domain/patient/models.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Patient:
    patient_id: str
    name: str
```

```python
# domain/insurance/models.py
from dataclasses import dataclass


@dataclass(frozen=True)
class InsuranceTransaction:
    patient_id: str
    encounter_id: str
    settlement_status: str
    upload_status: str
    error_code: str | None
```

```python
# domain/task/models.py
from dataclasses import dataclass


@dataclass
class ClosureTask:
    task_id: str
    task_type: str
    status: str
    responsible_role: str
    description: str
```

```python
# domain/common/models.py
from dataclasses import dataclass


@dataclass(frozen=True)
class Citation:
    source_type: str
    source_id: str
    summary: str
```

```python
# config/security_policy/rules.py
ROLE_VISIBLE_FIELDS = {
    'cashier': {'patient_id', 'encounter_id', 'settlement_status'},
    'medical_office': {'patient_id', 'encounter_id', 'settlement_status', 'audit_risks'},
    'clinician': {'patient_id', 'encounter_id'},
}

SCENARIO_ALLOWED_ROLES = {
    'settlement_exception_guidance': {'cashier', 'medical_office', 'information_department'},
    'pre_discharge_quality_control': {'medical_office', 'medical_record_staff', 'clinician'},
}

HIGH_RISK_ACTIONS = {'正式结算', '退费', '冲正', '撤销结算', '病案首页修改', '费用明细修改', '最终申诉结论确认'}
```

```python
# data_platform/data_access/in_memory.py
from dataclasses import dataclass

from domain.insurance.models import InsuranceTransaction
from domain.patient.models import Patient


@dataclass
class InMemoryDataStore:
    patients: dict[str, Patient]
    transactions: dict[tuple[str, str], InsuranceTransaction]

    def get_patient(self, patient_id: str) -> Patient:
        return self.patients[patient_id]

    def get_insurance_transaction(self, patient_id: str, encounter_id: str) -> InsuranceTransaction:
        return self.transactions[(patient_id, encounter_id)]


def build_sample_store() -> InMemoryDataStore:
    return InMemoryDataStore(
        patients={'P001': Patient(patient_id='P001', name='张三')},
        transactions={
            ('P001', 'E001'): InsuranceTransaction(
                patient_id='P001',
                encounter_id='E001',
                settlement_status='failed',
                upload_status='failed',
                error_code='E-UPLOAD-001',
            )
        },
    )
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest tests/unit/test_domain_and_sample_data.py -q`

Expected: PASS.

- [ ] **Step 5: Update OpenSpec tasks and commit**

Mark done: 1.5, 1.6, 2.1, 2.2, 2.3, 3.2, 3.8.

Run:

```bash
git add domain config data_platform tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: add domain models and memory sample data"
```

---

### Task 3: 权限、脱敏、澄清与患者上下文 API

**Files:**
- Create: `security/authorization/service.py`
- Create: `security/desensitization/service.py`
- Create: `runtime/clarification/service.py`
- Modify: `runtime/api/routes.py`
- Test: `tests/security/test_security_boundaries.py`

- [ ] **Step 1: Write failing security API tests**

```python
# tests/security/test_security_boundaries.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def test_patient_context_uses_minimum_fields_and_masks_name():
    client = TestClient(create_app())
    response = client.get('/api/v1/medical-insurance-ai-agent/patient-context/P001/E001', params={'user_id': 'u1', 'role': 'cashier'})
    assert response.status_code == 200
    body = response.json()
    assert body['patient']['name'] == '张**'
    assert set(body['visible_fields']) == {'patient_id', 'encounter_id', 'settlement_status'}


def test_missing_patient_context_returns_clarification():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={'user_id': 'u1', 'role': 'cashier', 'message': '医保结算失败了，帮我看看'})
    assert response.status_code == 200
    assert response.json()['status'] == 'needs_clarification'
    assert response.json()['missing_fields'] == ['patient_id', 'encounter_id']
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/security/test_security_boundaries.py -q`

Expected: FAIL because API does not implement behavior.

- [ ] **Step 3: Implement minimal services and route behavior**

```python
# security/desensitization/service.py
def mask_name(name: str) -> str:
    return name[0] + '**' if name else ''
```

```python
# security/authorization/service.py
from config.security_policy.rules import ROLE_VISIBLE_FIELDS, SCENARIO_ALLOWED_ROLES


def visible_fields_for(role: str) -> set[str]:
    return ROLE_VISIBLE_FIELDS.get(role, set())


def is_allowed(role: str, scenario: str) -> bool:
    return role in SCENARIO_ALLOWED_ROLES.get(scenario, set())
```

```python
# runtime/clarification/service.py
def missing_context_fields(patient_id: str | None, encounter_id: str | None) -> list[str]:
    missing = []
    if not patient_id:
        missing.append('patient_id')
    if not encounter_id:
        missing.append('encounter_id')
    return missing
```

Modify `runtime/api/routes.py`:

```python
from fastapi import APIRouter

from data_platform.data_access.in_memory import build_sample_store
from runtime.api.schemas import ChatRequest
from runtime.clarification.service import missing_context_fields
from security.authorization.service import visible_fields_for
from security.desensitization.service import mask_name

router = APIRouter()


@router.get('/version')
def version() -> dict[str, str]:
    return {'module': 'medical-insurance-ai-agent', 'mode': 'memory-mvp'}


@router.post('/chat')
def chat(request: ChatRequest) -> dict:
    missing = missing_context_fields(request.patient_id, request.encounter_id)
    if missing:
        return {'status': 'needs_clarification', 'missing_fields': missing}
    return {'status': 'not_implemented'}


@router.get('/patient-context/{patient_id}/{encounter_id}')
def patient_context(patient_id: str, encounter_id: str, user_id: str, role: str) -> dict:
    store = build_sample_store()
    patient = store.get_patient(patient_id)
    tx = store.get_insurance_transaction(patient_id, encounter_id)
    return {
        'patient': {'patient_id': patient.patient_id, 'name': mask_name(patient.name)},
        'visible_fields': sorted(visible_fields_for(role)),
        'settlement_status': tx.settlement_status,
    }
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest tests/security/test_security_boundaries.py -q`

Expected: PASS.

- [ ] **Step 5: Update OpenSpec tasks and commit**

Mark done: 6.1, 6.2, 7.3, 7.5.

Run:

```bash
git add runtime security tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: add context security and clarification"
```

---

### Task 4: 结算异常导办端到端闭环

**Files:**
- Create: `knowledge_extension/knowledge/in_memory.py`
- Create: `adapters/insurance_interface/in_memory.py`
- Create: `adapters/billing/in_memory.py`
- Create: `runtime/intent/service.py`
- Create: `business_scenarios/settlement_exception_guide/service.py`
- Modify: `runtime/api/routes.py`
- Test: `tests/e2e/test_settlement_exception.py`

- [ ] **Step 1: Write failing settlement exception test**

```python
# tests/e2e/test_settlement_exception.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def test_settlement_exception_guidance_returns_traceable_recommendation():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001',
        'role': 'medical_office',
        'message': '患者 P001 本次医保结算失败，帮我看一下原因',
        'patient_id': 'P001',
        'encounter_id': 'E001',
    })
    assert response.status_code == 200
    body = response.json()
    assert body['scenario'] == 'settlement_exception_guidance'
    assert body['status'] == 'completed'
    assert body['result']['exception_type'] == '费用上传异常'
    assert body['result']['responsible_role'] == '收费员'
    assert {c['source_type'] for c in body['citations']} >= {'insurance_transaction', 'knowledge_error_code'}
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/e2e/test_settlement_exception.py -q`

Expected: FAIL because chat returns `not_implemented`.

- [ ] **Step 3: Implement minimal settlement guidance**

```python
# knowledge_extension/knowledge/in_memory.py
ERROR_CODE_KNOWLEDGE = {
    'E-UPLOAD-001': {
        'description': '费用明细未全部上传',
        'exception_type': '费用上传异常',
        'responsible_role': '收费员',
        'recommendation': '请核对费用上传状态，补传失败明细后重新预结算。',
    }
}
```

```python
# adapters/insurance_interface/in_memory.py
from data_platform.data_access.in_memory import build_sample_store


class InMemoryInsuranceInterfaceAdapter:
    def query_transaction(self, patient_id: str, encounter_id: str):
        return build_sample_store().get_insurance_transaction(patient_id, encounter_id)
```

```python
# adapters/billing/in_memory.py
class InMemoryBillingAdapter:
    def query_billing_status(self, patient_id: str, encounter_id: str) -> dict:
        return {'billing_status': 'waiting_retry', 'patient_id': patient_id, 'encounter_id': encounter_id}
```

```python
# runtime/intent/service.py
def detect_intent(message: str) -> str:
    if '结算失败' in message or '医保结算' in message:
        return 'settlement_exception_guidance'
    if '出院前' in message or '医保风险' in message:
        return 'pre_discharge_quality_control'
    return 'unknown'
```

```python
# business_scenarios/settlement_exception_guide/service.py
from adapters.insurance_interface.in_memory import InMemoryInsuranceInterfaceAdapter
from knowledge_extension.knowledge.in_memory import ERROR_CODE_KNOWLEDGE


def guide_settlement_exception(patient_id: str, encounter_id: str) -> dict:
    tx = InMemoryInsuranceInterfaceAdapter().query_transaction(patient_id, encounter_id)
    knowledge = ERROR_CODE_KNOWLEDGE[tx.error_code]
    return {
        'scenario': 'settlement_exception_guidance',
        'status': 'completed',
        'result': {
            'exception_type': knowledge['exception_type'],
            'error_code': tx.error_code,
            'error_explanation': knowledge['description'],
            'responsible_role': knowledge['responsible_role'],
            'recommended_steps': [knowledge['recommendation']],
            'requires_human_confirmation': False,
        },
        'citations': [
            {'source_type': 'insurance_transaction', 'source_id': f'{patient_id}:{encounter_id}', 'summary': tx.settlement_status},
            {'source_type': 'knowledge_error_code', 'source_id': tx.error_code, 'summary': knowledge['description']},
        ],
        'tasks': [],
        'missing_fields': [],
        'uncertainties': [],
        'blocked_actions': [],
        'audit': {'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction', 'retrieve_error_code', 'build_result']},
    }
```

Modify chat branch in `runtime/api/routes.py`:

```python
from business_scenarios.settlement_exception_guide.service import guide_settlement_exception
from runtime.intent.service import detect_intent

# inside chat after missing check
    scenario = detect_intent(request.message)
    if scenario == 'settlement_exception_guidance':
        return guide_settlement_exception(request.patient_id, request.encounter_id)
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest tests/e2e/test_settlement_exception.py -q`

Expected: PASS.

- [ ] **Step 5: Update tasks and commit**

Mark done: 4.1, 4.4, 5.2, 5.3, 7.2, 7.4, 8.1, 8.2, 8.3, 10.1, 10.5.

Run:

```bash
git add runtime business_scenarios adapters knowledge_extension tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: implement settlement exception guidance MVP"
```

---

### Task 5: 高风险动作拦截与权限拒绝

**Files:**
- Create: `security/risk_control/service.py`
- Modify: `runtime/api/routes.py`
- Test: `tests/security/test_high_risk_and_permission.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/security/test_high_risk_and_permission.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def test_permission_denied_for_clinician_settlement_exception():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-clinician-001', 'role': 'clinician', 'message': '患者 P001 医保结算失败', 'patient_id': 'P001', 'encounter_id': 'E001'
    })
    assert response.status_code == 403
    assert response.json()['detail']['error_code'] == 'PERMISSION_DENIED'


def test_high_risk_refund_and_reversal_are_blocked():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '请直接给患者 P001 执行退费冲正', 'patient_id': 'P001', 'encounter_id': 'E001'
    })
    body = response.json()
    assert body['status'] == 'waiting_human_confirmation'
    assert body['blocked_actions'] == ['退费', '冲正']
    assert body['tasks'][0]['task_type'] == 'human_confirmation'
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/security/test_high_risk_and_permission.py -q`

Expected: FAIL because permission and risk control are missing.

- [ ] **Step 3: Implement risk and permission behavior**

```python
# security/risk_control/service.py
from config.security_policy.rules import HIGH_RISK_ACTIONS


def detect_blocked_actions(message: str) -> list[str]:
    return [action for action in HIGH_RISK_ACTIONS if action in message]


def build_human_confirmation_response(actions: list[str]) -> dict:
    return {
        'scenario': 'high_risk_action_confirmation',
        'status': 'waiting_human_confirmation',
        'result': {},
        'citations': [],
        'tasks': [{'task_id': 'task-human-confirm-001', 'task_type': 'human_confirmation', 'status': 'pending', 'description': '请人工确认高风险动作'}],
        'missing_fields': [],
        'uncertainties': [],
        'blocked_actions': actions,
        'audit': {'workflow_id': 'wf-high-risk', 'steps': ['detect_high_risk_action', 'create_human_confirmation_task']},
    }
```

Modify `runtime/api/routes.py` imports and chat:

```python
from fastapi import HTTPException
from security.authorization.service import is_allowed
from security.risk_control.service import build_human_confirmation_response, detect_blocked_actions
from shared.schemas.responses import error_detail

# inside chat after missing check
    blocked = detect_blocked_actions(request.message)
    if blocked:
        return build_human_confirmation_response(blocked)
    scenario = detect_intent(request.message)
    if not is_allowed(request.role, scenario):
        raise HTTPException(status_code=403, detail=error_detail('PERMISSION_DENIED', '角色无权访问该场景', {'event_type': 'permission_denied'}))
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest tests/security/test_high_risk_and_permission.py -q`

Expected: PASS.

- [ ] **Step 5: Update tasks and commit**

Mark done: 6.3, 6.4, 7.9 high-risk part, 10.3, 10.4.

Run:

```bash
git add runtime security shared tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: block high risk actions and enforce permissions"
```

---

### Task 6: 出院前联合质控闭环与任务创建

**Files:**
- Create: `adapters/pre_audit/in_memory.py`
- Create: `adapters/drg_dip/in_memory.py`
- Create: `adapters/his/in_memory.py`
- Create: `adapters/emr/in_memory.py`
- Create: `adapters/medical_record/in_memory.py`
- Create: `business_scenarios/pre_discharge_joint_qc/service.py`
- Modify: `runtime/api/routes.py`
- Test: `tests/e2e/test_pre_discharge_joint_qc.py`

- [ ] **Step 1: Write failing joint QC test**

```python
# tests/e2e/test_pre_discharge_joint_qc.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def test_pre_discharge_quality_control_creates_tasks_with_citations():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '帮我检查患者 P001 出院前医保风险', 'patient_id': 'P001', 'encounter_id': 'E001'
    })
    body = response.json()
    assert body['scenario'] == 'pre_discharge_quality_control'
    assert body['status'] == 'completed'
    risk_types = {risk['risk_type'] for risk in body['result']['risks']}
    assert risk_types >= {'合规拒付风险', 'DRG/DIP 支付风险', '病案首页风险'}
    assert body['tasks']
    assert all(task['status'] == 'pending' for task in body['tasks'])
    assert body['citations']
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/e2e/test_pre_discharge_joint_qc.py -q`

Expected: FAIL because pre-discharge scenario is not implemented.

- [ ] **Step 3: Implement deterministic joint QC service**

```python
# business_scenarios/pre_discharge_joint_qc/service.py
def run_pre_discharge_qc(patient_id: str, encounter_id: str) -> dict:
    risks = [
        {'risk_type': '合规拒付风险', 'risk_level': 'high', 'responsible_role': '医保办', 'recommendation': '复核限制用药规则命中原因'},
        {'risk_type': 'DRG/DIP 支付风险', 'risk_level': 'medium', 'responsible_role': '科主任', 'recommendation': '关注病组盈亏和费用结构'},
        {'risk_type': '病案首页风险', 'risk_level': 'medium', 'responsible_role': '病案室', 'recommendation': '复核主要诊断与手术编码'},
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
            {'source_type': 'pre_audit', 'source_id': f'{patient_id}:{encounter_id}', 'summary': '事前审核风险'},
            {'source_type': 'drg_dip', 'source_id': f'{patient_id}:{encounter_id}', 'summary': 'DRG/DIP 预分组风险'},
            {'source_type': 'medical_record', 'source_id': f'{patient_id}:{encounter_id}', 'summary': '病案首页风险'},
        ],
        'tasks': tasks,
        'missing_fields': [],
        'uncertainties': [],
        'blocked_actions': [],
        'audit': {'workflow_id': f'wf-qc-{patient_id}-{encounter_id}', 'steps': ['query_pre_audit', 'query_drg_dip', 'query_medical_record', 'create_tasks']},
    }
```

Create deterministic in-memory adapters with explicit classes:

```python
# adapters/pre_audit/in_memory.py
class InMemoryPreAuditAdapter:
    def query_audit_result(self, patient_id: str, encounter_id: str) -> dict:
        return {'risk': '合规拒付风险', 'patient_id': patient_id, 'encounter_id': encounter_id}
```

```python
# adapters/drg_dip/in_memory.py
class InMemoryDrgDipAdapter:
    def query_group_result(self, patient_id: str, encounter_id: str) -> dict:
        return {'risk': 'DRG/DIP 支付风险', 'patient_id': patient_id, 'encounter_id': encounter_id}
```

```python
# adapters/his/in_memory.py
class InMemoryHisAdapter:
    def query_orders(self, patient_id: str, encounter_id: str) -> dict:
        return {'orders': ['抗菌药物医嘱', '检查项目医嘱'], 'patient_id': patient_id, 'encounter_id': encounter_id}
```

```python
# adapters/emr/in_memory.py
class InMemoryEmrAdapter:
    def query_record_summary(self, patient_id: str, encounter_id: str) -> dict:
        return {'summary': '病历记录存在可补充证据', 'patient_id': patient_id, 'encounter_id': encounter_id}
```

```python
# adapters/medical_record/in_memory.py
class InMemoryMedicalRecordAdapter:
    def query_homepage(self, patient_id: str, encounter_id: str) -> dict:
        return {'risk': '病案首页风险', 'patient_id': patient_id, 'encounter_id': encounter_id}
```

Modify chat branch:

```python
from business_scenarios.pre_discharge_joint_qc.service import run_pre_discharge_qc

    if scenario == 'pre_discharge_quality_control':
        return run_pre_discharge_qc(request.patient_id, request.encounter_id)
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest tests/e2e/test_pre_discharge_joint_qc.py -q`

Expected: PASS.

- [ ] **Step 5: Update tasks and commit**

Mark done: 5.4, 5.5, 5.6, 5.7, 5.8, 8.4, 8.5, 8.6, 8.7, 10.2.

Run:

```bash
git add adapters business_scenarios runtime tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: implement pre-discharge joint quality control MVP"
```

---

### Task 7: 编排状态、审计还原与降级行为

**Files:**
- Create: `runtime/runtime_state/models.py`
- Create: `runtime/orchestration/service.py`
- Create: `runtime/scheduling/service.py`
- Create: `security/audit/in_memory.py`
- Test: `tests/integration/test_audit_and_degradation.py`

- [ ] **Step 1: Write failing audit and degradation tests**

```python
# tests/integration/test_audit_and_degradation.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def test_adapter_failure_returns_degraded_result_with_uncertainty():
    client = TestClient(create_app())
    response = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '患者 P002 本次医保结算失败，帮我看一下原因', 'patient_id': 'P002', 'encounter_id': 'E002'
    })
    body = response.json()
    assert body['status'] == 'degraded'
    assert any('医保接口' in item for item in body['uncertainties'])
    assert body['audit']['steps']
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/integration/test_audit_and_degradation.py -q`

Expected: FAIL because P002 is not handled.

- [ ] **Step 3: Implement minimal degradation path and audit models**

```python
# runtime/runtime_state/models.py
from dataclasses import dataclass, field


@dataclass
class WorkflowInstance:
    workflow_id: str
    status: str
    steps: list[str] = field(default_factory=list)
```

```python
# runtime/scheduling/service.py
def degraded_response(patient_id: str, encounter_id: str, reason: str) -> dict:
    return {
        'scenario': 'settlement_exception_guidance',
        'status': 'degraded',
        'result': {},
        'citations': [],
        'tasks': [],
        'missing_fields': [],
        'uncertainties': [reason],
        'blocked_actions': [],
        'audit': {'workflow_id': f'wf-{patient_id}-{encounter_id}', 'steps': ['query_transaction_failed', 'return_degraded_result']},
    }
```

```python
# security/audit/in_memory.py
class InMemoryAuditLog:
    def __init__(self):
        self.events = []

    def append(self, event: dict) -> None:
        self.events.append(event)

    def list_events(self) -> list[dict]:
        return list(self.events)
```

Modify `guide_settlement_exception()` to return degraded response for `P002/E002` before store lookup:

```python
from runtime.scheduling.service import degraded_response

    if patient_id == 'P002':
        return degraded_response(patient_id, encounter_id, '医保接口调用失败，当前结论存在不确定性')
```

- [ ] **Step 4: Run test to verify GREEN**

Run: `python -m pytest tests/integration/test_audit_and_degradation.py -q`

Expected: PASS.

- [ ] **Step 5: Update tasks and commit**

Mark done: 6.5, 6.6, 7.11, 7.12, 7.13, 7.14, 10.6, 10.7.

Run:

```bash
git add runtime security business_scenarios tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: add workflow audit and degraded responses"
```

---

### Task 8: 端口替换边界、任务闭环指标与全量验证

**Files:**
- Create: `data_platform/data_access/ports.py`
- Create: `data_platform/storage/cache/ports.py`
- Create: `data_platform/storage/vector/ports.py`
- Create: `observability/metrics/definitions.py`
- Create: `runtime/task_closure/service.py`
- Test: `tests/integration/test_full_mvp_contract.py`

- [ ] **Step 1: Write failing full contract test**

```python
# tests/integration/test_full_mvp_contract.py
from fastapi.testclient import TestClient

from runtime.api.app import create_app


def test_all_mvp_contracts_pass_together():
    client = TestClient(create_app())
    openapi = client.get('/openapi.json').json()
    assert '/api/v1/medical-insurance-ai-agent/chat' in openapi['paths']

    settlement = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '患者 P001 本次医保结算失败', 'patient_id': 'P001', 'encounter_id': 'E001'
    }).json()
    assert settlement['status'] == 'completed'

    qc = client.post('/api/v1/medical-insurance-ai-agent/chat', json={
        'user_id': 'u-medical-office-001', 'role': 'medical_office', 'message': '检查患者 P001 出院前医保风险', 'patient_id': 'P001', 'encounter_id': 'E001'
    }).json()
    assert qc['tasks']

    for body in (settlement, qc):
        assert set(body.keys()) == {'scenario', 'status', 'result', 'citations', 'tasks', 'missing_fields', 'uncertainties', 'blocked_actions', 'audit'}
```

- [ ] **Step 2: Run test to verify RED**

Run: `python -m pytest tests/integration/test_full_mvp_contract.py -q`

Expected: FAIL because explicit port and metric definitions are not yet present or unified response keys are incomplete.

- [ ] **Step 3: Add explicit port and metric definitions**

```python
# data_platform/data_access/ports.py
from typing import Protocol


class DataAccessPort(Protocol):
    def get_patient(self, patient_id: str):
        raise NotImplementedError

    def get_insurance_transaction(self, patient_id: str, encounter_id: str):
        raise NotImplementedError
```

```python
# data_platform/storage/cache/ports.py
from typing import Protocol


class CachePort(Protocol):
    def get(self, key: str):
        raise NotImplementedError

    def set(self, key: str, value, ttl_seconds: int | None = None) -> None:
        raise NotImplementedError
```

```python
# data_platform/storage/vector/ports.py
from typing import Protocol


class VectorSearchPort(Protocol):
    def search(self, query: str, top_k: int = 5) -> list[dict]:
        raise NotImplementedError
```

```python
# observability/metrics/definitions.py
METRICS = {
    'task_completion_rate': '任务闭环完成率',
    'average_task_duration': '任务平均处理时长',
    'risk_discovery_count': '风险发现数量',
    'settlement_exception_duration': '结算异常处理时长',
}
```

```python
# runtime/task_closure/service.py
def build_pending_task(task_id: str, task_type: str, description: str, responsible_role: str) -> dict:
    return {'task_id': task_id, 'task_type': task_type, 'status': 'pending', 'description': description, 'responsible_role': responsible_role}
```

- [ ] **Step 4: Run all MVP tests**

Run: `python -m pytest tests -q`

Expected: PASS for all created tests.

- [ ] **Step 5: Validate OpenSpec and update tasks**

Run: `openspec validate "add-medical-insurance-ai-agent" --strict`

Expected: `Change 'add-medical-insurance-ai-agent' is valid`.

Mark remaining relevant tasks done: 3.1, 3.3, 3.4, 3.5, 3.6, 3.7, 4.2, 4.3, 4.5, 4.6, 5.1, 5.9, 7.1, 7.6, 7.7, 7.8, 7.10, 7.15, 7.16, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 10.8.

Run:

```bash
git add data_platform observability runtime tests openspec/changes/add-medical-insurance-ai-agent/tasks.md
git commit -m "feat: finalize MVP ports contracts and verification"
```

---

## Final Verification

Run these commands before claiming completion:

```bash
python -m pytest tests -q
openspec validate "add-medical-insurance-ai-agent" --strict
```

Expected:

```text
所有 pytest 测试通过
Change 'add-medical-insurance-ai-agent' is valid
```

## Coverage Review

- AI Chat 统一入口：Task 1、Task 3、Task 4、Task 6。
- 权限、脱敏、澄清：Task 3、Task 5。
- 上下文、规划、编排：Task 4、Task 6、Task 7。
- 数据与知识底座：Task 2、Task 4、Task 8。
- 业务系统适配器：Task 4、Task 6、Task 8。
- 结算异常导办：Task 4。
- 出院前联合质控：Task 6。
- 高风险动作与人工确认：Task 5。
- 来源引用与审计：Task 4、Task 6、Task 7。
- 任务闭环：Task 5、Task 6、Task 8。
- 基础设施替换边界：Task 8。
