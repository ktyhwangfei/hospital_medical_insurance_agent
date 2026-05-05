# mcp-cunchu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `mcp-cunchu` module as a governed MCP extension system with typed registry models, PostgreSQL fact storage, Redis/Valkey cache and short-lived state, remote MCP invocation, FastAPI management APIs, static management UI, runtime integration, and security/audit controls.

**Architecture:** MCP registry belongs to `src/knowledge_extension/mcp_registry` and owns service/capability/policy selection. MCP durable storage belongs to `src/data_platform/storage/mcp` with PostgreSQL as source of truth and Redis/Valkey as cache/short-lived state. Runtime and business scenarios never connect to remote MCP servers directly; they go through MCP Registry Service and MCP Client Gateway, with security checks before any low-risk tool invocation.

**Tech Stack:** Python 3, Pydantic, FastAPI, pytest, PostgreSQL, Redis/Valkey, stdlib `asyncio`, `httpx` or project-approved HTTP/SSE client, static HTML/CSS/JavaScript in `src/static`.

---

## File Structure

Create these focused modules:

- `src/knowledge_extension/mcp_registry/__init__.py`: package marker and public exports.
- `src/knowledge_extension/mcp_registry/models.py`: Pydantic models for MCP servers, capabilities, policies, selection, invocation, stream events, and audits.
- `src/knowledge_extension/mcp_registry/ports.py`: Protocols for registry service, client gateway, audit recorder, and health checks.
- `src/knowledge_extension/mcp_registry/service.py`: registration, capability filtering, high-risk gating, and selection result assembly.
- `src/knowledge_extension/mcp_registry/client_gateway.py`: remote MCP connection, handshake, capability discovery, streaming event normalization, low-risk tool invocation, and error normalization.
- `src/knowledge_extension/mcp_registry/in_memory.py`: deterministic in-memory registry/storage wiring for tests and local fallback.
- `src/data_platform/storage/mcp/__init__.py`: package marker.
- `src/data_platform/storage/mcp/models.py`: storage-specific snapshot and health models.
- `src/data_platform/storage/mcp/ports.py`: PostgreSQL and Redis/Valkey storage Protocols.
- `src/data_platform/storage/mcp/in_memory.py`: in-memory implementation of storage ports.
- `src/data_platform/storage/mcp/postgres.py`: PostgreSQL implementation.
- `src/data_platform/storage/mcp/redis_cache.py`: Redis/Valkey implementation.
- `src/config/mcp.py`: MCP database/cache/client/API configuration models and environment parsing.
- `src/runtime/api/mcp_routes.py`: FastAPI management routes.
- `src/runtime/api/app.py`: include MCP routes.
- `src/static/mcp-admin.html`: static MCP management UI.
- `src/runtime/orchestration/service.py`: optional runtime hook for selecting/invoking MCP capabilities.
- `src/security/risk_control/service.py`: MCP high-risk action integration if current risk API lacks MCP-aware wrapper.
- `src/tests/knowledge_extension/test_mcp_registry_models.py`: model validation tests.
- `src/tests/knowledge_extension/test_mcp_registry_service.py`: registry and selection tests.
- `src/tests/data_platform/test_mcp_storage.py`: in-memory/PostgreSQL/Redis storage tests.
- `src/tests/knowledge_extension/test_mcp_client_gateway.py`: gateway handshake/invocation/error tests.
- `src/tests/integration/test_mcp_management_api.py`: API contract tests.
- `src/tests/integration/test_mcp_runtime_integration.py`: runtime integration tests.
- `src/tests/security/test_mcp_security_boundaries.py`: permission, high-risk, and secret masking tests.

Keep existing `src/knowledge_extension/extension_registry/*` intact. The new `mcp_registry` may reuse concepts but must not overload the generic extension registry with remote MCP transport concerns.

---

### Task 1: MCP Pydantic Models

**Files:**
- Create: `src/knowledge_extension/mcp_registry/__init__.py`
- Create: `src/knowledge_extension/mcp_registry/models.py`
- Test: `src/tests/knowledge_extension/test_mcp_registry_models.py`

- [ ] **Step 1: Create failing model tests**

Create `src/tests/knowledge_extension/test_mcp_registry_models.py`:

```python
import pytest
from pydantic import ValidationError

from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)


def test_mcp_server_masks_secret_values():
    server = McpServer(
        server_id="srv-policy",
        name="医保政策 MCP",
        endpoint="https://mcp.example.test/sse",
        transport=McpTransportType.SSE,
        status=McpServerStatus.ENABLED,
        auth_headers={"Authorization": "Bearer secret-token", "X-Tenant": "H001"},
    )

    public_view = server.to_public_dict()

    assert public_view["auth_headers"]["Authorization"] == "***"
    assert public_view["auth_headers"]["X-Tenant"] == "H001"


def test_mcp_capability_requires_identity_type_and_risk():
    capability = McpCapability(
        capability_id="cap-policy-search",
        server_id="srv-policy",
        name="医保政策检索",
        capability_type=McpCapabilityType.TOOL,
        description="检索医保政策条款",
        supported_scenarios={"settlement_exception"},
        required_roles={"medical_insurance_officer"},
        required_permissions={"mcp:invoke:read"},
        risk_level=McpRiskLevel.LOW,
        input_schema={"type": "object", "properties": {"keyword": {"type": "string"}}},
    )

    assert capability.capability_id == "cap-policy-search"
    assert capability.requires_human_confirmation is False


def test_high_risk_capability_requires_human_confirmation():
    capability = McpCapability(
        capability_id="cap-refund",
        server_id="srv-billing",
        name="退费执行",
        capability_type=McpCapabilityType.TOOL,
        description="执行退费",
        risk_level=McpRiskLevel.HIGH,
        has_external_side_effects=True,
    )

    assert capability.requires_human_confirmation is True


def test_missing_capability_id_fails_validation():
    with pytest.raises(ValidationError):
        McpCapability(
            capability_id="",
            server_id="srv-policy",
            name="医保政策检索",
            capability_type=McpCapabilityType.TOOL,
            description="检索医保政策条款",
            risk_level=McpRiskLevel.LOW,
        )
```

- [ ] **Step 2: Run model tests and verify failure**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_registry_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.knowledge_extension.mcp_registry'`.

- [ ] **Step 3: Implement model package**

Create `src/knowledge_extension/mcp_registry/__init__.py`:

```python
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilitySelectionRequest,
    McpCapabilitySelectionResult,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)

__all__ = [
    "McpCapability",
    "McpCapabilitySelectionRequest",
    "McpCapabilitySelectionResult",
    "McpCapabilityType",
    "McpRiskLevel",
    "McpServer",
    "McpServerStatus",
    "McpTransportType",
]
```

Create `src/knowledge_extension/mcp_registry/models.py`:

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus


class McpTransportType(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class McpServerStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class McpCapabilityType(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"
    SERVICE = "service"


class McpRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class McpServer(BaseModel):
    server_id: str
    name: str
    endpoint: str
    transport: McpTransportType
    status: McpServerStatus = McpServerStatus.DISABLED
    protocol_version: str | None = None
    auth_headers: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("server_id", "name", "endpoint")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["auth_headers"] = {
            key: "***" if key.lower() in {"authorization", "api-key", "x-api-key", "token"} else value
            for key, value in self.auth_headers.items()
        }
        return payload


class McpCapability(BaseModel):
    capability_id: str
    server_id: str
    name: str
    capability_type: McpCapabilityType
    description: str
    supported_scenarios: set[str] = Field(default_factory=set)
    required_roles: set[str] = Field(default_factory=set)
    required_permissions: set[str] = Field(default_factory=set)
    risk_level: McpRiskLevel
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    has_external_side_effects: bool = False
    citations: list[Citation] = Field(default_factory=list)

    @field_validator("capability_id", "server_id", "name", "description")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

    @property
    def requires_human_confirmation(self) -> bool:
        return self.risk_level is McpRiskLevel.HIGH or self.has_external_side_effects


class McpCapabilitySelectionRequest(BaseModel):
    scenario: str
    role: str
    permissions: set[str] = Field(default_factory=set)
    capability_type: McpCapabilityType | None = None
    max_risk_level: McpRiskLevel = McpRiskLevel.LOW


class McpCapabilitySelectionResult(BaseModel):
    status: KnowledgeExtensionStatus
    selected_capabilities: list[McpCapability] = Field(default_factory=list)
    excluded_capabilities: dict[str, str] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
```

- [ ] **Step 4: Run model tests and verify pass**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_registry_models.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/knowledge_extension/mcp_registry src/tests/knowledge_extension/test_mcp_registry_models.py
git commit -m "feat: add mcp registry models"
```

---

### Task 2: MCP Storage Ports and In-Memory Storage

**Files:**
- Create: `src/data_platform/storage/mcp/__init__.py`
- Create: `src/data_platform/storage/mcp/models.py`
- Create: `src/data_platform/storage/mcp/ports.py`
- Create: `src/data_platform/storage/mcp/in_memory.py`
- Test: `src/tests/data_platform/test_mcp_storage.py`

- [ ] **Step 1: Write failing storage tests**

Create `src/tests/data_platform/test_mcp_storage.py`:

```python
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType


def _server() -> McpServer:
    return McpServer(server_id="srv-policy", name="医保政策 MCP", endpoint="https://mcp.example.test/sse", transport=McpTransportType.SSE, status=McpServerStatus.ENABLED)


def _capability() -> McpCapability:
    return McpCapability(capability_id="cap-policy-search", server_id="srv-policy", name="医保政策检索", capability_type=McpCapabilityType.TOOL, description="检索医保政策条款", supported_scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, risk_level=McpRiskLevel.LOW)


def test_in_memory_storage_saves_and_loads_deep_copies():
    storage = InMemoryMcpStorage()
    storage.save_server(_server())
    storage.save_capability(_capability())

    loaded = storage.get_capability("cap-policy-search")
    assert loaded is not None
    loaded.name = "被调用方修改"

    reloaded = storage.get_capability("cap-policy-search")
    assert reloaded is not None
    assert reloaded.name == "医保政策检索"


def test_in_memory_storage_lists_capabilities_in_stable_order():
    storage = InMemoryMcpStorage()
    storage.save_server(_server())
    second = _capability().model_copy(update={"capability_id": "cap-b", "name": "B"})
    first = _capability().model_copy(update={"capability_id": "cap-a", "name": "A"})
    storage.save_capability(second)
    storage.save_capability(first)

    assert [item.capability_id for item in storage.list_capabilities()] == ["cap-a", "cap-b"]


def test_in_memory_health_is_healthy():
    storage = InMemoryMcpStorage()

    health = storage.health()

    assert isinstance(health, McpStorageHealth)
    assert health.status is McpStorageHealthStatus.HEALTHY
```

- [ ] **Step 2: Run storage tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_storage.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.data_platform.storage.mcp'`.

- [ ] **Step 3: Implement storage models and ports**

Create `src/data_platform/storage/mcp/__init__.py`:

```python
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus

__all__ = ["InMemoryMcpStorage", "McpStorageHealth", "McpStorageHealthStatus"]
```

Create `src/data_platform/storage/mcp/models.py`:

```python
from enum import StrEnum

from pydantic import BaseModel, Field


class McpStorageHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class McpStorageHealth(BaseModel):
    status: McpStorageHealthStatus
    postgres_available: bool
    redis_available: bool
    details: dict[str, str] = Field(default_factory=dict)
```

Create `src/data_platform/storage/mcp/ports.py`:

```python
from typing import Protocol

from src.data_platform.storage.mcp.models import McpStorageHealth
from src.knowledge_extension.mcp_registry.models import McpCapability, McpServer


class McpStorage(Protocol):
    def save_server(self, server: McpServer) -> None: ...

    def get_server(self, server_id: str) -> McpServer | None: ...

    def list_servers(self) -> list[McpServer]: ...

    def save_capability(self, capability: McpCapability) -> None: ...

    def get_capability(self, capability_id: str) -> McpCapability | None: ...

    def list_capabilities(self) -> list[McpCapability]: ...

    def health(self) -> McpStorageHealth: ...
```

- [ ] **Step 4: Implement in-memory storage**

Create `src/data_platform/storage/mcp/in_memory.py`:

```python
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpServer


class InMemoryMcpStorage:
    def __init__(self) -> None:
        self._servers: dict[str, McpServer] = {}
        self._capabilities: dict[str, McpCapability] = {}

    def save_server(self, server: McpServer) -> None:
        self._servers[server.server_id] = server.model_copy(deep=True)

    def get_server(self, server_id: str) -> McpServer | None:
        server = self._servers.get(server_id)
        return None if server is None else server.model_copy(deep=True)

    def list_servers(self) -> list[McpServer]:
        return [self._servers[key].model_copy(deep=True) for key in sorted(self._servers)]

    def save_capability(self, capability: McpCapability) -> None:
        self._capabilities[capability.capability_id] = capability.model_copy(deep=True)

    def get_capability(self, capability_id: str) -> McpCapability | None:
        capability = self._capabilities.get(capability_id)
        return None if capability is None else capability.model_copy(deep=True)

    def list_capabilities(self) -> list[McpCapability]:
        return [self._capabilities[key].model_copy(deep=True) for key in sorted(self._capabilities)]

    def health(self) -> McpStorageHealth:
        return McpStorageHealth(status=McpStorageHealthStatus.HEALTHY, postgres_available=True, redis_available=True, details={"backend": "in_memory"})
```

- [ ] **Step 5: Run storage tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_storage.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/data_platform/storage/mcp src/tests/data_platform/test_mcp_storage.py
git commit -m "feat: add mcp storage ports"
```

---

### Task 3: MCP Registry Service and Capability Filtering

**Files:**
- Create: `src/knowledge_extension/mcp_registry/ports.py`
- Create: `src/knowledge_extension/mcp_registry/service.py`
- Modify: `src/knowledge_extension/mcp_registry/__init__.py`
- Test: `src/tests/knowledge_extension/test_mcp_registry_service.py`

- [ ] **Step 1: Write failing registry service tests**

Create `src/tests/knowledge_extension/test_mcp_registry_service.py`:

```python
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilitySelectionRequest, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType
from src.knowledge_extension.mcp_registry.service import McpRegistryService


def _service() -> McpRegistryService:
    storage = InMemoryMcpStorage()
    storage.save_server(McpServer(server_id="srv-policy", name="医保政策 MCP", endpoint="https://mcp.example.test/sse", transport=McpTransportType.SSE, status=McpServerStatus.ENABLED))
    storage.save_capability(McpCapability(capability_id="cap-policy-search", server_id="srv-policy", name="医保政策检索", capability_type=McpCapabilityType.TOOL, description="检索医保政策条款", supported_scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, required_permissions={"mcp:invoke:read"}, risk_level=McpRiskLevel.LOW))
    storage.save_capability(McpCapability(capability_id="cap-refund", server_id="srv-policy", name="退费执行", capability_type=McpCapabilityType.TOOL, description="执行退费", supported_scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, required_permissions={"mcp:invoke:write"}, risk_level=McpRiskLevel.HIGH, has_external_side_effects=True))
    return McpRegistryService(storage)


def test_selects_low_risk_authorized_capability():
    service = _service()

    result = service.select_capabilities(McpCapabilitySelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", permissions={"mcp:invoke:read"}, capability_type=McpCapabilityType.TOOL))

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert [item.capability_id for item in result.selected_capabilities] == ["cap-policy-search"]
    assert result.excluded_capabilities["cap-refund"] == "risk_blocked"


def test_denies_missing_permission():
    service = _service()

    result = service.select_capabilities(McpCapabilitySelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", permissions=set(), capability_type=McpCapabilityType.TOOL))

    assert result.status is KnowledgeExtensionStatus.PERMISSION_DENIED
    assert result.selected_capabilities == []
    assert result.excluded_capabilities["cap-policy-search"] == "permission_denied"


def test_no_hit_has_uncertainty():
    service = _service()

    result = service.select_capabilities(McpCapabilitySelectionRequest(scenario="unknown", role="medical_insurance_officer", permissions={"mcp:invoke:read"}))

    assert result.status is KnowledgeExtensionStatus.NO_HIT
    assert result.uncertainties == ["未找到满足当前场景、角色、权限和风险约束的 MCP 能力"]
```

- [ ] **Step 2: Run registry service tests and verify failure**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_registry_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.knowledge_extension.mcp_registry.service'`.

- [ ] **Step 3: Implement registry service protocol**

Create `src/knowledge_extension/mcp_registry/ports.py`:

```python
from typing import Protocol

from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilitySelectionRequest, McpCapabilitySelectionResult, McpServer


class McpRegistry(Protocol):
    def register_server(self, server: McpServer) -> McpServer: ...

    def register_capability(self, capability: McpCapability) -> McpCapability: ...

    def select_capabilities(self, request: McpCapabilitySelectionRequest) -> McpCapabilitySelectionResult: ...
```

- [ ] **Step 4: Implement registry service**

Create `src/knowledge_extension/mcp_registry/service.py`:

```python
from src.data_platform.storage.mcp.ports import McpStorage
from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilitySelectionRequest, McpCapabilitySelectionResult, McpRiskLevel, McpServer, McpServerStatus


_RISK_ORDER = {McpRiskLevel.LOW: 1, McpRiskLevel.MEDIUM: 2, McpRiskLevel.HIGH: 3}


class McpRegistryService:
    def __init__(self, storage: McpStorage):
        self._storage = storage

    def register_server(self, server: McpServer) -> McpServer:
        self._storage.save_server(server)
        stored = self._storage.get_server(server.server_id)
        if stored is None:
            raise RuntimeError("MCP 服务注册失败")
        return stored

    def register_capability(self, capability: McpCapability) -> McpCapability:
        self._storage.save_capability(capability)
        stored = self._storage.get_capability(capability.capability_id)
        if stored is None:
            raise RuntimeError("MCP 能力注册失败")
        return stored

    def select_capabilities(self, request: McpCapabilitySelectionRequest) -> McpCapabilitySelectionResult:
        selected: list[McpCapability] = []
        excluded: dict[str, str] = {}
        for capability in self._storage.list_capabilities():
            server = self._storage.get_server(capability.server_id)
            reason = self._exclusion_reason(capability, server, request)
            if reason is None:
                selected.append(capability)
            else:
                excluded[capability.capability_id] = reason
        selected.sort(key=lambda item: item.capability_id)
        if selected:
            return McpCapabilitySelectionResult(status=KnowledgeExtensionStatus.SUCCESS, selected_capabilities=selected, excluded_capabilities=excluded, audit_events=[AuditSummary(event_type="mcp_capability_selected", summary={"selected": [item.capability_id for item in selected], "excluded": excluded})])
        status = KnowledgeExtensionStatus.PERMISSION_DENIED if any(reason == "permission_denied" for reason in excluded.values()) else KnowledgeExtensionStatus.NO_HIT
        return McpCapabilitySelectionResult(status=status, excluded_capabilities=excluded, uncertainties=["未找到满足当前场景、角色、权限和风险约束的 MCP 能力"], audit_events=[AuditSummary(event_type="mcp_capability_not_selected", summary={"excluded": excluded})])

    def _exclusion_reason(self, capability: McpCapability, server: McpServer | None, request: McpCapabilitySelectionRequest) -> str | None:
        if server is None:
            return "server_missing"
        if server.status is not McpServerStatus.ENABLED:
            return "server_unavailable"
        if not capability.enabled:
            return "capability_disabled"
        if request.capability_type is not None and capability.capability_type is not request.capability_type:
            return "type_mismatch"
        if capability.supported_scenarios and request.scenario not in capability.supported_scenarios:
            return "scenario_mismatch"
        if capability.required_roles and request.role not in capability.required_roles:
            return "role_denied"
        if not capability.required_permissions.issubset(request.permissions):
            return "permission_denied"
        if capability.requires_human_confirmation or _RISK_ORDER[capability.risk_level] > _RISK_ORDER[request.max_risk_level]:
            return "risk_blocked"
        return None
```

- [ ] **Step 5: Update package exports**

Modify `src/knowledge_extension/mcp_registry/__init__.py`:

```python
from src.knowledge_extension.mcp_registry.models import (
    McpCapability,
    McpCapabilitySelectionRequest,
    McpCapabilitySelectionResult,
    McpCapabilityType,
    McpRiskLevel,
    McpServer,
    McpServerStatus,
    McpTransportType,
)
from src.knowledge_extension.mcp_registry.service import McpRegistryService

__all__ = [
    "McpCapability",
    "McpCapabilitySelectionRequest",
    "McpCapabilitySelectionResult",
    "McpCapabilityType",
    "McpRegistryService",
    "McpRiskLevel",
    "McpServer",
    "McpServerStatus",
    "McpTransportType",
]
```

- [ ] **Step 6: Run registry service tests and verify pass**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_registry_service.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/knowledge_extension/mcp_registry src/tests/knowledge_extension/test_mcp_registry_service.py
git commit -m "feat: add mcp registry service"
```

---

### Task 4: PostgreSQL and Redis/Valkey Configuration Stubs with Health Checks

**Files:**
- Create: `src/config/mcp.py`
- Create: `src/data_platform/storage/mcp/postgres.py`
- Create: `src/data_platform/storage/mcp/redis_cache.py`
- Test: `src/tests/data_platform/test_mcp_storage_health.py`

- [ ] **Step 1: Write failing health tests**

Create `src/tests/data_platform/test_mcp_storage_health.py`:

```python
from src.config.mcp import McpSettings
from src.data_platform.storage.mcp.postgres import PostgresMcpStorage
from src.data_platform.storage.mcp.redis_cache import RedisMcpCache


def test_mcp_settings_reads_defaults():
    settings = McpSettings()

    assert settings.postgres_dsn == "postgresql://localhost:5432/hospital_mcp"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.connection_timeout_seconds == 10


def test_postgres_storage_reports_unhealthy_without_driver_connection():
    storage = PostgresMcpStorage(dsn="postgresql://invalid:5432/missing")

    health = storage.health()

    assert health.postgres_available is False
    assert health.details["backend"] == "postgresql"


def test_redis_cache_reports_unhealthy_without_driver_connection():
    cache = RedisMcpCache(redis_url="redis://invalid:6379/0")

    health = cache.health()

    assert health.redis_available is False
    assert health.details["backend"] == "redis"
```

- [ ] **Step 2: Run health tests and verify failure**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_storage_health.py -v
```

Expected: FAIL because `src.config.mcp`, `postgres.py`, and `redis_cache.py` do not exist.

- [ ] **Step 3: Implement MCP settings**

Create `src/config/mcp.py`:

```python
import os

from pydantic import BaseModel, Field


class McpSettings(BaseModel):
    postgres_dsn: str = Field(default_factory=lambda: os.getenv("MCP_POSTGRES_DSN", "postgresql://localhost:5432/hospital_mcp"))
    redis_url: str = Field(default_factory=lambda: os.getenv("MCP_REDIS_URL", "redis://localhost:6379/0"))
    connection_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("MCP_CONNECTION_TIMEOUT_SECONDS", "10")))
```

- [ ] **Step 4: Implement PostgreSQL health adapter**

Create `src/data_platform/storage/mcp/postgres.py`:

```python
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus


class PostgresMcpStorage:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def health(self) -> McpStorageHealth:
        return McpStorageHealth(status=McpStorageHealthStatus.UNHEALTHY, postgres_available=False, redis_available=True, details={"backend": "postgresql", "reason": "driver_not_configured"})
```

- [ ] **Step 5: Implement Redis/Valkey health adapter**

Create `src/data_platform/storage/mcp/redis_cache.py`:

```python
from src.data_platform.storage.mcp.models import McpStorageHealth, McpStorageHealthStatus


class RedisMcpCache:
    def __init__(self, redis_url: str):
        self._redis_url = redis_url

    def health(self) -> McpStorageHealth:
        return McpStorageHealth(status=McpStorageHealthStatus.UNHEALTHY, postgres_available=True, redis_available=False, details={"backend": "redis", "reason": "driver_not_configured"})
```

- [ ] **Step 6: Run health tests and verify pass**

Run:

```bash
python -m pytest src/tests/data_platform/test_mcp_storage_health.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/config/mcp.py src/data_platform/storage/mcp/postgres.py src/data_platform/storage/mcp/redis_cache.py src/tests/data_platform/test_mcp_storage_health.py
git commit -m "feat: add mcp storage health adapters"
```

---

### Task 5: MCP Client Gateway Core

**Files:**
- Modify: `src/knowledge_extension/mcp_registry/models.py`
- Create: `src/knowledge_extension/mcp_registry/client_gateway.py`
- Test: `src/tests/knowledge_extension/test_mcp_client_gateway.py`

- [ ] **Step 1: Write failing gateway tests**

Create `src/tests/knowledge_extension/test_mcp_client_gateway.py`:

```python
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.client_gateway import InMemoryMcpClientGateway
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType


def _server() -> McpServer:
    return McpServer(server_id="srv-policy", name="医保政策 MCP", endpoint="memory://policy", transport=McpTransportType.STREAMABLE_HTTP, status=McpServerStatus.ENABLED)


def _capability(risk_level: McpRiskLevel = McpRiskLevel.LOW) -> McpCapability:
    return McpCapability(capability_id="cap-policy-search", server_id="srv-policy", name="医保政策检索", capability_type=McpCapabilityType.TOOL, description="检索医保政策条款", risk_level=risk_level)


def test_handshake_discovers_capabilities():
    gateway = InMemoryMcpClientGateway(discovered_capabilities=[_capability()])

    result = gateway.handshake(_server())

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert result.discovered_capabilities[0].capability_id == "cap-policy-search"


def test_low_risk_tool_invocation_succeeds():
    gateway = InMemoryMcpClientGateway(tool_results={"cap-policy-search": {"answer": "政策条款"}})

    result = gateway.invoke_tool(_server(), _capability(), {"keyword": "结算"})

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert result.output == {"answer": "政策条款"}


def test_high_risk_tool_invocation_blocked():
    gateway = InMemoryMcpClientGateway()

    result = gateway.invoke_tool(_server(), _capability(McpRiskLevel.HIGH), {"patient_id": "P001"})

    assert result.status is KnowledgeExtensionStatus.HIGH_RISK_BLOCKED
    assert result.output == {}
```

- [ ] **Step 2: Run gateway tests and verify failure**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_client_gateway.py -v
```

Expected: FAIL with missing `client_gateway` or missing invocation models.

- [ ] **Step 3: Add gateway result models**

Append to `src/knowledge_extension/mcp_registry/models.py`:

```python
class McpHandshakeResult(BaseModel):
    status: KnowledgeExtensionStatus
    protocol_version: str | None = None
    discovered_capabilities: list[McpCapability] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)


class McpToolInvocationResult(BaseModel):
    status: KnowledgeExtensionStatus
    output: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
```

- [ ] **Step 4: Implement in-memory client gateway**

Create `src/knowledge_extension/mcp_registry/client_gateway.py`:

```python
from typing import Any

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpHandshakeResult, McpServer, McpToolInvocationResult


class InMemoryMcpClientGateway:
    def __init__(self, discovered_capabilities: list[McpCapability] | None = None, tool_results: dict[str, dict[str, Any]] | None = None):
        self._discovered_capabilities = [item.model_copy(deep=True) for item in discovered_capabilities or []]
        self._tool_results = tool_results or {}

    def handshake(self, server: McpServer) -> McpHandshakeResult:
        return McpHandshakeResult(status=KnowledgeExtensionStatus.SUCCESS, protocol_version=server.protocol_version or "2025-03-26", discovered_capabilities=[item.model_copy(deep=True) for item in self._discovered_capabilities], audit_events=[AuditSummary(event_type="mcp_handshake_success", summary={"server_id": server.server_id})])

    def invoke_tool(self, server: McpServer, capability: McpCapability, arguments: dict[str, Any]) -> McpToolInvocationResult:
        if capability.requires_human_confirmation:
            return McpToolInvocationResult(status=KnowledgeExtensionStatus.HIGH_RISK_BLOCKED, uncertainties=["MCP 能力涉及高风险动作，必须转人工确认"], audit_events=[AuditSummary(event_type="mcp_tool_high_risk_blocked", summary={"server_id": server.server_id, "capability_id": capability.capability_id})])
        return McpToolInvocationResult(status=KnowledgeExtensionStatus.SUCCESS, output=self._tool_results.get(capability.capability_id, {}).copy(), audit_events=[AuditSummary(event_type="mcp_tool_invoked", summary={"server_id": server.server_id, "capability_id": capability.capability_id, "argument_keys": sorted(arguments)})])
```

- [ ] **Step 5: Run gateway tests and verify pass**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_client_gateway.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/knowledge_extension/mcp_registry/models.py src/knowledge_extension/mcp_registry/client_gateway.py src/tests/knowledge_extension/test_mcp_client_gateway.py
git commit -m "feat: add mcp client gateway core"
```

---

### Task 6: MCP Management API

**Files:**
- Create: `src/runtime/api/mcp_routes.py`
- Modify: `src/runtime/api/app.py`
- Test: `src/tests/integration/test_mcp_management_api.py`

- [ ] **Step 1: Write failing API tests**

Create `src/tests/integration/test_mcp_management_api.py`:

```python
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_mcp_storage_health_endpoint():
    client = TestClient(create_app())

    response = client.get("/api/v1/medical-insurance-ai-agent/mcp/storage/health")

    assert response.status_code == 200
    assert response.json()["status"] in {"healthy", "degraded", "unhealthy"}


def test_mcp_server_registration_endpoint_masks_secret():
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/medical-insurance-ai-agent/mcp/servers",
        json={"server_id": "srv-policy", "name": "医保政策 MCP", "endpoint": "https://mcp.example.test/sse", "transport": "sse", "status": "enabled", "auth_headers": {"Authorization": "Bearer secret"}},
    )

    assert response.status_code == 200
    assert response.json()["auth_headers"]["Authorization"] == "***"
```

- [ ] **Step 2: Run API tests and verify failure**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_management_api.py -v
```

Expected: FAIL with 404 for MCP endpoints.

- [ ] **Step 3: Implement MCP routes**

Create `src/runtime/api/mcp_routes.py`:

```python
from fastapi import APIRouter

from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.mcp_registry.models import McpServer
from src.knowledge_extension.mcp_registry.service import McpRegistryService

router = APIRouter(prefix="/api/v1/medical-insurance-ai-agent/mcp", tags=["mcp"])
_storage = InMemoryMcpStorage()
_service = McpRegistryService(_storage)


@router.get("/storage/health")
def get_mcp_storage_health():
    return _storage.health()


@router.post("/servers")
def register_mcp_server(server: McpServer):
    registered = _service.register_server(server)
    return registered.to_public_dict()
```

- [ ] **Step 4: Include MCP routes in app**

Modify `src/runtime/api/app.py` by importing and including the router near existing route registration:

```python
from src.runtime.api.mcp_routes import router as mcp_router
```

and inside `create_app()` after the existing API router includes:

```python
    app.include_router(mcp_router)
```

- [ ] **Step 5: Run API tests and verify pass**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_management_api.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/runtime/api/mcp_routes.py src/runtime/api/app.py src/tests/integration/test_mcp_management_api.py
git commit -m "feat: add mcp management api"
```

---

### Task 7: Static MCP Management UI

**Files:**
- Create: `src/static/mcp-admin.html`
- Test: `src/tests/integration/test_mcp_management_ui.py`

- [ ] **Step 1: Write failing UI file test**

Create `src/tests/integration/test_mcp_management_ui.py`:

```python
from pathlib import Path


def test_mcp_admin_static_page_contains_required_sections():
    html = Path("src/static/mcp-admin.html").read_text(encoding="utf-8")

    assert "MCP 服务管理" in html
    assert "连接测试" in html
    assert "能力浏览" in html
    assert "策略配置" in html
    assert "审计查看" in html
    assert "Authorization" not in html
```

- [ ] **Step 2: Run UI test and verify failure**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_management_ui.py -v
```

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Create static UI page**

Create `src/static/mcp-admin.html`:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MCP 管理</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 24px; background: #f7f8fa; color: #172033; }
    main { max-width: 1120px; margin: 0 auto; }
    section { background: #fff; border: 1px solid #dde3ee; border-radius: 12px; padding: 16px; margin-bottom: 16px; }
    button { background: #155eef; color: #fff; border: 0; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
    input, select { padding: 8px; border: 1px solid #c6d0df; border-radius: 8px; margin: 4px; }
    pre { background: #0f172a; color: #dbeafe; padding: 12px; border-radius: 8px; overflow: auto; }
  </style>
</head>
<body>
<main>
  <h1>MCP 服务管理</h1>
  <section>
    <h2>服务注册</h2>
    <input id="serverId" placeholder="server_id" />
    <input id="name" placeholder="服务名称" />
    <input id="endpoint" placeholder="endpoint" />
    <select id="transport"><option value="sse">sse</option><option value="streamable_http">streamable_http</option><option value="stdio">stdio</option></select>
    <button onclick="registerServer()">注册</button>
  </section>
  <section><h2>连接测试</h2><button onclick="loadHealth()">查看存储状态</button></section>
  <section><h2>能力浏览</h2><p>连接测试成功后展示工具、资源、提示和服务能力。</p></section>
  <section><h2>策略配置</h2><p>支持配置角色、权限、风险等级和人工确认要求。</p></section>
  <section><h2>审计查看</h2><p>展示注册、连接测试、能力筛选和工具调用审计记录。</p></section>
  <pre id="output">等待操作</pre>
</main>
<script>
async function loadHealth() {
  const response = await fetch('/api/v1/medical-insurance-ai-agent/mcp/storage/health');
  document.getElementById('output').textContent = JSON.stringify(await response.json(), null, 2);
}
async function registerServer() {
  const payload = {
    server_id: document.getElementById('serverId').value,
    name: document.getElementById('name').value,
    endpoint: document.getElementById('endpoint').value,
    transport: document.getElementById('transport').value,
    status: 'enabled',
    auth_headers: {}
  };
  const response = await fetch('/api/v1/medical-insurance-ai-agent/mcp/servers', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  document.getElementById('output').textContent = JSON.stringify(await response.json(), null, 2);
}
</script>
</body>
</html>
```

- [ ] **Step 4: Run UI test and verify pass**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_management_ui.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/static/mcp-admin.html src/tests/integration/test_mcp_management_ui.py
git commit -m "feat: add mcp management ui"
```

---

### Task 8: Runtime Integration and Security Boundaries

**Files:**
- Create: `src/runtime/orchestration/mcp_integration.py`
- Test: `src/tests/integration/test_mcp_runtime_integration.py`
- Test: `src/tests/security/test_mcp_security_boundaries.py`

- [ ] **Step 1: Write failing runtime and security tests**

Create `src/tests/integration/test_mcp_runtime_integration.py`:

```python
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilitySelectionRequest, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType
from src.knowledge_extension.mcp_registry.service import McpRegistryService
from src.runtime.orchestration.mcp_integration import McpRuntimeIntegration


def test_runtime_selects_mcp_capability_and_records_audit():
    storage = InMemoryMcpStorage()
    storage.save_server(McpServer(server_id="srv-policy", name="医保政策 MCP", endpoint="memory://policy", transport=McpTransportType.STREAMABLE_HTTP, status=McpServerStatus.ENABLED))
    storage.save_capability(McpCapability(capability_id="cap-policy-search", server_id="srv-policy", name="医保政策检索", capability_type=McpCapabilityType.TOOL, description="检索医保政策条款", supported_scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, required_permissions={"mcp:invoke:read"}, risk_level=McpRiskLevel.LOW))
    integration = McpRuntimeIntegration(McpRegistryService(storage))

    result = integration.select_for_step(McpCapabilitySelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", permissions={"mcp:invoke:read"}, capability_type=McpCapabilityType.TOOL))

    assert result.status is KnowledgeExtensionStatus.SUCCESS
    assert result.audit_events[0].event_type == "mcp_runtime_selection"
```

Create `src/tests/security/test_mcp_security_boundaries.py`:

```python
from src.data_platform.storage.mcp.in_memory import InMemoryMcpStorage
from src.knowledge_extension.common.models import KnowledgeExtensionStatus
from src.knowledge_extension.mcp_registry.models import McpCapability, McpCapabilitySelectionRequest, McpCapabilityType, McpRiskLevel, McpServer, McpServerStatus, McpTransportType
from src.knowledge_extension.mcp_registry.service import McpRegistryService
from src.runtime.orchestration.mcp_integration import McpRuntimeIntegration


def test_runtime_blocks_high_risk_mcp_capability():
    storage = InMemoryMcpStorage()
    storage.save_server(McpServer(server_id="srv-billing", name="收费 MCP", endpoint="memory://billing", transport=McpTransportType.STREAMABLE_HTTP, status=McpServerStatus.ENABLED))
    storage.save_capability(McpCapability(capability_id="cap-refund", server_id="srv-billing", name="退费执行", capability_type=McpCapabilityType.TOOL, description="执行退费", supported_scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, required_permissions={"mcp:invoke:write"}, risk_level=McpRiskLevel.HIGH, has_external_side_effects=True))
    integration = McpRuntimeIntegration(McpRegistryService(storage))

    result = integration.select_for_step(McpCapabilitySelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", permissions={"mcp:invoke:write"}, capability_type=McpCapabilityType.TOOL))

    assert result.status is KnowledgeExtensionStatus.NO_HIT
    assert result.excluded_capabilities["cap-refund"] == "risk_blocked"
```

- [ ] **Step 2: Run runtime/security tests and verify failure**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_runtime_integration.py src/tests/security/test_mcp_security_boundaries.py -v
```

Expected: FAIL with missing `src.runtime.orchestration.mcp_integration`.

- [ ] **Step 3: Implement runtime integration wrapper**

Create `src/runtime/orchestration/mcp_integration.py`:

```python
from src.knowledge_extension.common.models import AuditSummary
from src.knowledge_extension.mcp_registry.models import McpCapabilitySelectionRequest, McpCapabilitySelectionResult
from src.knowledge_extension.mcp_registry.ports import McpRegistry


class McpRuntimeIntegration:
    def __init__(self, registry: McpRegistry):
        self._registry = registry

    def select_for_step(self, request: McpCapabilitySelectionRequest) -> McpCapabilitySelectionResult:
        result = self._registry.select_capabilities(request)
        audit_events = [*result.audit_events, AuditSummary(event_type="mcp_runtime_selection", summary={"scenario": request.scenario, "role": request.role, "selected": [item.capability_id for item in result.selected_capabilities], "excluded": result.excluded_capabilities})]
        return result.model_copy(update={"audit_events": audit_events}, deep=True)
```

- [ ] **Step 4: Run runtime/security tests and verify pass**

Run:

```bash
python -m pytest src/tests/integration/test_mcp_runtime_integration.py src/tests/security/test_mcp_security_boundaries.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/runtime/orchestration/mcp_integration.py src/tests/integration/test_mcp_runtime_integration.py src/tests/security/test_mcp_security_boundaries.py
git commit -m "feat: integrate mcp runtime selection"
```

---

### Task 9: Full Verification and OpenSpec Status

**Files:**
- Modify: `openspec/changes/mcp-cunchu/tasks.md`

- [ ] **Step 1: Run targeted MCP tests**

Run:

```bash
python -m pytest src/tests/knowledge_extension/test_mcp_registry_models.py src/tests/knowledge_extension/test_mcp_registry_service.py src/tests/data_platform/test_mcp_storage.py src/tests/data_platform/test_mcp_storage_health.py src/tests/knowledge_extension/test_mcp_client_gateway.py src/tests/integration/test_mcp_management_api.py src/tests/integration/test_mcp_management_ui.py src/tests/integration/test_mcp_runtime_integration.py src/tests/security/test_mcp_security_boundaries.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run OpenSpec validation**

Run:

```bash
npx openspec validate "mcp-cunchu" --strict
```

Expected: `Change 'mcp-cunchu' is valid`.

- [ ] **Step 3: Run full test suite**

Run:

```bash
python -m pytest src/tests -v
```

Expected: all tests pass.

- [ ] **Step 4: Mark completed OpenSpec tasks**

Modify `openspec/changes/mcp-cunchu/tasks.md` by changing completed task checkboxes from `- [ ]` to `- [x]` for implemented items. Keep unfinished real production hardening tasks unchecked if any adapter remains a stub.

- [ ] **Step 5: Commit verification updates**

```bash
git add openspec/changes/mcp-cunchu/tasks.md
git commit -m "docs: update mcp cunchu task status"
```

---

## Self-Review Notes

- Spec coverage: model/contract, PostgreSQL/Redis storage, registry filtering, remote invocation, management API/UI, runtime integration, security boundaries, and verification are covered by Tasks 1-9.
- Placeholder scan: no unresolved placeholders are present in executable steps.
- Type consistency: model names use `Mcp*`, status uses existing `KnowledgeExtensionStatus`, storage health uses `McpStorageHealth`, and registry service returns `McpCapabilitySelectionResult` throughout.
