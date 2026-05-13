# Knowledge Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `knowledge-extension` module from OpenSpec, including knowledge assets, RAG retrieval, rule explanation, prompt templates, extension registry, a runtime facade, scenario integration, API compatibility, and safety validation.

**Architecture:** Implement a contract-first, in-memory MVP. Shared Pydantic models and Protocol ports define boundaries; focused submodules implement assets, RAG, rule explanation, prompt templates, and extension registry; `src/knowledge_extension/service.py` becomes the runtime-facing facade that merges citations, uncertainties, degradation, and audit summaries.

**Tech Stack:** Python 3, Pydantic, Protocol from `typing`, pytest, FastAPI response schemas, existing `AgentResponse`, OpenSpec.

---

## Scope and Guardrails

- Follow import style with `src.` prefix for all project imports.
- Every new package directory must include `__init__.py`.
- Do not return raw `dict` from new knowledge-extension service APIs; use Pydantic `BaseModel`.
- Do not add real Milvus, Elasticsearch, database, MCP, A2A, or Tool execution dependencies.
- Do not let knowledge services call business adapters directly.
- Keep API compatibility by adding data to existing `AgentResponse.result`, `citations`, `uncertainties`, and `audit` fields.
- No application code comments unless a test name or model field is clearer than a comment.

## File Structure

### Create

- `src/knowledge_extension/common/__init__.py`
- `src/knowledge_extension/common/models.py`
- `src/knowledge_extension/assets/__init__.py`
- `src/knowledge_extension/assets/models.py`
- `src/knowledge_extension/assets/ports.py`
- `src/knowledge_extension/assets/in_memory.py`
- `src/knowledge_extension/rag/__init__.py`
- `src/knowledge_extension/rag/models.py`
- `src/knowledge_extension/rag/ports.py`
- `src/knowledge_extension/rag/in_memory.py`
- `src/knowledge_extension/rule_explanation/__init__.py`
- `src/knowledge_extension/rule_explanation/models.py`
- `src/knowledge_extension/rule_explanation/ports.py`
- `src/knowledge_extension/rule_explanation/in_memory.py`
- `src/knowledge_extension/prompt_templates/__init__.py`
- `src/knowledge_extension/prompt_templates/models.py`
- `src/knowledge_extension/prompt_templates/ports.py`
- `src/knowledge_extension/prompt_templates/in_memory.py`
- `src/knowledge_extension/extension_registry/__init__.py`
- `src/knowledge_extension/extension_registry/models.py`
- `src/knowledge_extension/extension_registry/ports.py`
- `src/knowledge_extension/extension_registry/in_memory.py`
- `src/knowledge_extension/service.py`
- `src/tests/knowledge_extension/__init__.py`
- `src/tests/knowledge_extension/test_common_models.py`
- `src/tests/knowledge_extension/test_assets.py`
- `src/tests/knowledge_extension/test_rag.py`
- `src/tests/knowledge_extension/test_rule_explanation.py`
- `src/tests/knowledge_extension/test_prompt_templates.py`
- `src/tests/knowledge_extension/test_extension_registry.py`
- `src/tests/knowledge_extension/test_service.py`
- `src/tests/integration/test_knowledge_extension_runtime.py`
- `src/tests/security/test_knowledge_extension_security.py`

### Modify

- `src/business_scenarios/settlement_exception_guide/service.py`
- `src/business_scenarios/pre_discharge_joint_qc/service.py`
- `src/runtime/runtime_state/models.py`
- `src/runtime/api/schemas.py` only if OpenAPI needs examples or field typing refinement; keep existing fields compatible.
- `src/runtime/api/streaming.py` if final SSE event needs citation/uncertainty propagation.
- `src/static/index.html`
- `openspec/changes/knowledge-extension/tasks.md` to mark completed tasks after implementation.

---

### Task 1: Shared Knowledge Extension Models

**Files:**
- Create: `src/knowledge_extension/common/__init__.py`
- Create: `src/knowledge_extension/common/models.py`
- Test: `src/tests/knowledge_extension/__init__.py`
- Test: `src/tests/knowledge_extension/test_common_models.py`

- [ ] **Step 1: Write failing tests for shared models**

Create `src/tests/knowledge_extension/__init__.py` as an empty file.

Create `src/tests/knowledge_extension/test_common_models.py`:

```python
from src.knowledge_extension.common.models import (
    AuditSummary,
    Citation,
    Degradation,
    KnowledgeExtensionStatus,
    VisibilityScope,
)


def test_citation_public_view_hides_internal_fields():
    citation = Citation(
        source_id="asset-policy-001",
        source_type="policy",
        title="医保结算政策说明",
        version="2026.1",
        section="第二章",
        chunk_id="chunk-001",
        evidence="结算异常需核对交易状态",
        retrieved_at="2026-05-04T00:00:00Z",
        score=0.91,
        internal_locator="D:/internal/policy.pdf#page=2",
    )

    public = citation.to_public_dict()

    assert public["source_id"] == "asset-policy-001"
    assert public["title"] == "医保结算政策说明"
    assert "internal_locator" not in public


def test_degradation_requires_status_and_reason():
    degradation = Degradation(
        status=KnowledgeExtensionStatus.NO_HIT,
        reason="未命中可用知识",
        user_message="当前知识库未找到可靠依据，建议人工复核",
    )

    assert degradation.status is KnowledgeExtensionStatus.NO_HIT
    assert "人工复核" in degradation.user_message


def test_visibility_scope_matches_role_and_tenant():
    scope = VisibilityScope(
        roles={"medical_insurance_officer"},
        tenant_ids={"tenant-a"},
        campus_ids={"north"},
    )

    assert scope.allows("medical_insurance_officer", "tenant-a", "north") is True
    assert scope.allows("doctor", "tenant-a", "north") is False


def test_audit_summary_masks_sensitive_values():
    audit = AuditSummary(
        event_type="extension_selection_denied",
        actor="u001",
        summary={"patient_name": "张三", "token": "secret", "reason": "permission_denied"},
    )

    masked = audit.masked_summary()

    assert masked["patient_name"] == "***"
    assert masked["token"] == "***"
    assert masked["reason"] == "permission_denied"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/knowledge_extension/test_common_models.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'src.knowledge_extension.common'`.

- [ ] **Step 3: Implement shared models**

Create `src/knowledge_extension/common/__init__.py` as an empty file.

Create `src/knowledge_extension/common/models.py`:

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeExtensionStatus(StrEnum):
    SUCCESS = "success"
    NO_HIT = "no_hit"
    PARTIAL_DEGRADED = "partial_degraded"
    PERMISSION_DENIED = "permission_denied"
    UNAVAILABLE = "unavailable"
    VERSION_MISMATCH = "version_mismatch"
    EVIDENCE_CONFLICT = "evidence_conflict"
    TEMPLATE_MISSING = "template_missing"
    HIGH_RISK_BLOCKED = "high_risk_blocked"


class VisibilityScope(BaseModel):
    roles: set[str] = Field(default_factory=set)
    tenant_ids: set[str] = Field(default_factory=set)
    campus_ids: set[str] = Field(default_factory=set)

    def allows(self, role: str, tenant_id: str | None = None, campus_id: str | None = None) -> bool:
        role_allowed = not self.roles or role in self.roles
        tenant_allowed = not self.tenant_ids or tenant_id in self.tenant_ids
        campus_allowed = not self.campus_ids or campus_id in self.campus_ids
        return role_allowed and tenant_allowed and campus_allowed


class Citation(BaseModel):
    source_id: str
    source_type: str
    title: str
    version: str | None = None
    section: str | None = None
    chunk_id: str | None = None
    evidence: str
    retrieved_at: str | None = None
    score: float | None = None
    internal_locator: str | None = None

    def dedupe_key(self) -> tuple[str, str | None, str | None, str]:
        return (self.source_id, self.version, self.chunk_id, self.evidence)

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True, exclude={"internal_locator"})
        return payload


class Degradation(BaseModel):
    status: KnowledgeExtensionStatus
    reason: str
    user_message: str


class AuditSummary(BaseModel):
    event_type: str
    actor: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)

    def masked_summary(self) -> dict[str, Any]:
        sensitive_keys = {"patient_name", "id_card", "phone", "token", "authorization", "api_key"}
        return {key: "***" if key.lower() in sensitive_keys else value for key, value in self.summary.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/tests/knowledge_extension/test_common_models.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/knowledge_extension/common src/tests/knowledge_extension
git commit -m "feat: add knowledge extension shared models"
```

---

### Task 2: Knowledge Assets Models, Ports, and In-Memory Repository

**Files:**
- Create: `src/knowledge_extension/assets/__init__.py`
- Create: `src/knowledge_extension/assets/models.py`
- Create: `src/knowledge_extension/assets/ports.py`
- Create: `src/knowledge_extension/assets/in_memory.py`
- Test: `src/tests/knowledge_extension/test_assets.py`

- [ ] **Step 1: Write failing tests for asset repository**

Create `src/tests/knowledge_extension/test_assets.py`:

```python
from src.knowledge_extension.assets.in_memory import build_default_asset_repository
from src.knowledge_extension.assets.models import AssetQuery, KnowledgeAssetStatus, KnowledgeAssetType


def test_default_assets_include_policy_error_code_rule_and_template():
    repo = build_default_asset_repository()

    assets = repo.list_assets(AssetQuery(role="medical_insurance_officer"))
    types = {asset.asset_type for asset in assets}

    assert KnowledgeAssetType.ERROR_CODE in types
    assert KnowledgeAssetType.POLICY in types
    assert KnowledgeAssetType.AUDIT_RULE in types
    assert KnowledgeAssetType.APPEAL_TEMPLATE in types


def test_inactive_assets_are_filtered_and_audited():
    repo = build_default_asset_repository()

    assets = repo.list_assets(AssetQuery(role="medical_insurance_officer", include_inactive=False))


    assert all(asset.status is KnowledgeAssetStatus.PUBLISHED for asset in assets)
    assert repo.audit_events


def test_role_scope_filters_internal_policy_without_leaking_content():
    repo = build_default_asset_repository()

    assets = repo.list_assets(AssetQuery(role="doctor", tenant_id="tenant-a", campus_id="north"))

    assert all(asset.asset_id != "asset-internal-policy-001" for asset in assets)
    assert any(event.event_type == "knowledge_asset_filtered" for event in repo.audit_events)


def test_chunks_trace_to_asset_and_version():
    repo = build_default_asset_repository()

    chunks = repo.list_chunks(AssetQuery(role="medical_insurance_officer", scenario="settlement_exception"))

    assert chunks
    assert all(chunk.asset_id for chunk in chunks)
    assert all(chunk.asset_version for chunk in chunks)


def test_duplicate_published_version_is_rejected():
    repo = build_default_asset_repository()
    original = repo.get_asset("asset-policy-001")

    result = repo.add_asset(original)

    assert result.status.value == "version_mismatch"
    assert "重复" in result.user_message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/knowledge_extension/test_assets.py -v`

Expected: FAIL with missing `assets` module.

- [ ] **Step 3: Implement models and ports**

Create `src/knowledge_extension/assets/__init__.py` as an empty file.

Create `src/knowledge_extension/assets/models.py`:

```python
from enum import StrEnum

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, Degradation, VisibilityScope


class KnowledgeAssetType(StrEnum):
    POLICY = "policy"
    INTERNAL_POLICY = "internal_policy"
    ERROR_CODE = "error_code"
    AUDIT_RULE = "audit_rule"
    APPEAL_TEMPLATE = "appeal_template"
    BUSINESS_GUIDE = "business_guide"


class KnowledgeAssetStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    INACTIVE = "inactive"
    EXPIRED = "expired"


class IndexStatus(StrEnum):
    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"
    REBUILD_REQUIRED = "rebuild_required"


class KnowledgeAsset(BaseModel):
    asset_id: str
    asset_type: KnowledgeAssetType
    title: str
    summary: str
    source: str
    version: str
    status: KnowledgeAssetStatus
    effective_date: str | None = None
    expired_date: str | None = None
    imported_at: str
    visibility: VisibilityScope = Field(default_factory=VisibilityScope)
    index_status: IndexStatus = IndexStatus.NOT_INDEXED


class KnowledgeChunk(BaseModel):
    chunk_id: str
    asset_id: str
    asset_version: str
    title: str
    asset_type: KnowledgeAssetType
    section: str
    text: str
    summary: str
    tags: set[str] = Field(default_factory=set)
    scenario_tags: set[str] = Field(default_factory=set)
    visibility: VisibilityScope = Field(default_factory=VisibilityScope)
    locator: str | None = None
    index_status: IndexStatus = IndexStatus.INDEXED


class AssetQuery(BaseModel):
    role: str
    tenant_id: str | None = None
    campus_id: str | None = None
    scenario: str | None = None
    asset_types: set[KnowledgeAssetType] = Field(default_factory=set)
    include_inactive: bool = False


class AssetWriteResult(Degradation):
    asset_id: str | None = None


class AssetRepositorySnapshot(BaseModel):
    assets: list[KnowledgeAsset]
    chunks: list[KnowledgeChunk]
    audit_events: list[AuditSummary]
```

Create `src/knowledge_extension/assets/ports.py`:

```python
from typing import Protocol

from src.knowledge_extension.assets.models import AssetQuery, AssetWriteResult, KnowledgeAsset, KnowledgeChunk


class KnowledgeAssetRepository(Protocol):
    def add_asset(self, asset: KnowledgeAsset) -> AssetWriteResult: ...
    def get_asset(self, asset_id: str) -> KnowledgeAsset: ...
    def list_assets(self, query: AssetQuery) -> list[KnowledgeAsset]: ...


class KnowledgeChunkRepository(Protocol):
    def add_chunk(self, chunk: KnowledgeChunk) -> AssetWriteResult: ...
    def list_chunks(self, query: AssetQuery) -> list[KnowledgeChunk]: ...
```

- [ ] **Step 4: Implement in-memory repository**

Create `src/knowledge_extension/assets/in_memory.py`:

```python
from copy import deepcopy

from src.knowledge_extension.assets.models import (
    AssetQuery,
    AssetWriteResult,
    IndexStatus,
    KnowledgeAsset,
    KnowledgeAssetStatus,
    KnowledgeAssetType,
    KnowledgeChunk,
)
from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus, VisibilityScope


class InMemoryKnowledgeAssetRepository:
    def __init__(self, assets: list[KnowledgeAsset], chunks: list[KnowledgeChunk]):
        self._assets = {asset.asset_id: asset for asset in assets}
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self.audit_events: list[AuditSummary] = []

    def add_asset(self, asset: KnowledgeAsset) -> AssetWriteResult:
        existing = self._assets.get(asset.asset_id)
        if existing and existing.version == asset.version and existing.status is KnowledgeAssetStatus.PUBLISHED:
            self.audit_events.append(AuditSummary(event_type="knowledge_asset_duplicate_version", summary={"asset_id": asset.asset_id}))
            return AssetWriteResult(
                status=KnowledgeExtensionStatus.VERSION_MISMATCH,
                reason="duplicate_published_version",
                user_message="重复的已发布知识资产版本不能覆盖",
                asset_id=asset.asset_id,
            )
        self._assets[asset.asset_id] = asset.model_copy(deep=True)
        self.audit_events.append(AuditSummary(event_type="knowledge_asset_added", summary={"asset_id": asset.asset_id}))
        return AssetWriteResult(status=KnowledgeExtensionStatus.SUCCESS, reason="created", user_message="知识资产已保存", asset_id=asset.asset_id)

    def add_chunk(self, chunk: KnowledgeChunk) -> AssetWriteResult:
        self._chunks[chunk.chunk_id] = chunk.model_copy(deep=True)
        self.audit_events.append(AuditSummary(event_type="knowledge_chunk_added", summary={"chunk_id": chunk.chunk_id}))
        return AssetWriteResult(status=KnowledgeExtensionStatus.SUCCESS, reason="created", user_message="知识切片已保存", asset_id=chunk.asset_id)

    def get_asset(self, asset_id: str) -> KnowledgeAsset:
        return self._assets[asset_id].model_copy(deep=True)

    def list_assets(self, query: AssetQuery) -> list[KnowledgeAsset]:
        result = []
        for asset in self._assets.values():
            if not query.include_inactive and asset.status is not KnowledgeAssetStatus.PUBLISHED:
                self.audit_events.append(AuditSummary(event_type="knowledge_asset_filtered", summary={"asset_id": asset.asset_id, "reason": asset.status.value}))
                continue
            if query.asset_types and asset.asset_type not in query.asset_types:
                continue
            if not asset.visibility.allows(query.role, query.tenant_id, query.campus_id):
                self.audit_events.append(AuditSummary(event_type="knowledge_asset_filtered", summary={"asset_id": asset.asset_id, "reason": "visibility"}))
                continue
            result.append(asset.model_copy(deep=True))
        return result

    def list_chunks(self, query: AssetQuery) -> list[KnowledgeChunk]:
        visible_assets = {asset.asset_id for asset in self.list_assets(query)}
        result = []
        for chunk in self._chunks.values():
            if chunk.asset_id not in visible_assets:
                continue
            if query.scenario and query.scenario not in chunk.scenario_tags:
                continue
            if not chunk.visibility.allows(query.role, query.tenant_id, query.campus_id):
                self.audit_events.append(AuditSummary(event_type="knowledge_chunk_filtered", summary={"chunk_id": chunk.chunk_id, "reason": "visibility"}))
                continue
            result.append(chunk.model_copy(deep=True))
        return result


def build_default_asset_repository() -> InMemoryKnowledgeAssetRepository:
    officer_scope = VisibilityScope(roles={"medical_insurance_officer", "admin"}, tenant_ids={"tenant-a"}, campus_ids={"north"})
    clinical_scope = VisibilityScope(roles={"medical_insurance_officer", "doctor", "admin"})
    assets = [
        KnowledgeAsset(asset_id="asset-policy-001", asset_type=KnowledgeAssetType.POLICY, title="医保结算政策说明", summary="结算异常处理政策", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, effective_date="2026-01-01", imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-error-code-001", asset_type=KnowledgeAssetType.ERROR_CODE, title="医保错误码知识", summary="错误码解释", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-audit-rule-001", asset_type=KnowledgeAssetType.AUDIT_RULE, title="出院前审核规则", summary="审核规则说明", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-appeal-template-001", asset_type=KnowledgeAssetType.APPEAL_TEMPLATE, title="拒付申诉模板", summary="申诉材料模板", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=officer_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-internal-policy-001", asset_type=KnowledgeAssetType.INTERNAL_POLICY, title="院内医保运营制度", summary="内部制度", source="init", version="2026.1", status=KnowledgeAssetStatus.PUBLISHED, imported_at="2026-05-04T00:00:00Z", visibility=officer_scope, index_status=IndexStatus.INDEXED),
        KnowledgeAsset(asset_id="asset-expired-001", asset_type=KnowledgeAssetType.POLICY, title="过期政策", summary="过期政策", source="init", version="2025.1", status=KnowledgeAssetStatus.EXPIRED, imported_at="2026-05-04T00:00:00Z", visibility=clinical_scope, index_status=IndexStatus.REBUILD_REQUIRED),
    ]
    chunks = [
        KnowledgeChunk(chunk_id="chunk-policy-001", asset_id="asset-policy-001", asset_version="2026.1", title="医保结算政策说明", asset_type=KnowledgeAssetType.POLICY, section="结算异常", text="医保结算异常需核对交易状态、收费状态和错误码含义。", summary="结算异常处理", tags={"settlement", "error_code"}, scenario_tags={"settlement_exception"}, visibility=clinical_scope, locator="policy#1"),
        KnowledgeChunk(chunk_id="chunk-rule-001", asset_id="asset-audit-rule-001", asset_version="2026.1", title="出院前审核规则", asset_type=KnowledgeAssetType.AUDIT_RULE, section="事前审核", text="出院前应核对事前审核风险、DRG/DIP 风险和病案首页完整性。", summary="出院前质控", tags={"pre_audit", "drg_dip", "medical_record"}, scenario_tags={"pre_discharge_qc"}, visibility=clinical_scope, locator="rule#1"),
    ]
    return InMemoryKnowledgeAssetRepository(deepcopy(assets), deepcopy(chunks))
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/tests/knowledge_extension/test_assets.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/knowledge_extension/assets src/tests/knowledge_extension/test_assets.py
git commit -m "feat: add knowledge asset repository"
```

---

### Task 3: RAG Retrieval, Reranking, Context, and Citations

**Files:**
- Create: `src/knowledge_extension/rag/__init__.py`
- Create: `src/knowledge_extension/rag/models.py`
- Create: `src/knowledge_extension/rag/ports.py`
- Create: `src/knowledge_extension/rag/in_memory.py`
- Test: `src/tests/knowledge_extension/test_rag.py`

- [ ] **Step 1: Write failing tests for RAG**

Create `src/tests/knowledge_extension/test_rag.py`:

```python
from src.knowledge_extension.assets.in_memory import build_default_asset_repository
from src.knowledge_extension.rag.in_memory import InMemoryHybridRetriever
from src.knowledge_extension.rag.models import RetrievalFilter, RetrievalRequest


def test_retrieves_settlement_policy_with_citation():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="医保结算异常错误码", filters=RetrievalFilter(role="medical_insurance_officer", scenario="settlement_exception")))

    assert result.status.value == "success"
    assert result.citations
    assert result.citations[0].source_id == "asset-policy-001"


def test_retrieval_no_hit_returns_uncertainty():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="完全不存在的罕见政策", filters=RetrievalFilter(role="doctor", scenario="settlement_exception")))

    assert result.status.value == "no_hit"
    assert result.uncertainties


def test_context_budget_trims_results():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="医保 出院 审核 DRG DIP 病案", filters=RetrievalFilter(role="doctor", scenario="pre_discharge_qc"), context_budget=12))

    assert result.context.truncated_count >= 0
    assert len(result.context.context_text) <= 12


def test_public_citation_hides_locator():
    retriever = InMemoryHybridRetriever(build_default_asset_repository())
    result = retriever.retrieve(RetrievalRequest(query="医保结算异常", filters=RetrievalFilter(role="doctor", scenario="settlement_exception")))

    public = result.citations[0].to_public_dict()

    assert "internal_locator" not in public
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/knowledge_extension/test_rag.py -v`

Expected: FAIL with missing `rag` module.

- [ ] **Step 3: Implement RAG models and ports**

Create `src/knowledge_extension/rag/__init__.py` as an empty file.

Create `src/knowledge_extension/rag/models.py`:

```python
from pydantic import BaseModel, Field

from src.knowledge_extension.assets.models import KnowledgeAssetType, KnowledgeChunk
from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus


class RetrievalFilter(BaseModel):
    role: str
    tenant_id: str | None = None
    campus_id: str | None = None
    scenario: str | None = None
    asset_types: set[KnowledgeAssetType] = Field(default_factory=set)
    effective_date: str | None = None


class RetrievalRequest(BaseModel):
    query: str
    filters: RetrievalFilter
    max_results: int = 5
    context_budget: int = 1200
    trace_id: str | None = None


class RetrievalHit(BaseModel):
    chunk: KnowledgeChunk
    score: float
    matched_terms: list[str] = Field(default_factory=list)


class ContextPackage(BaseModel):
    hits: list[RetrievalHit] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    context_text: str = ""
    truncated_count: int = 0


class RetrievalResult(BaseModel):
    status: KnowledgeExtensionStatus
    hits: list[RetrievalHit] = Field(default_factory=list)
    context: ContextPackage = Field(default_factory=ContextPackage)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
```

Create `src/knowledge_extension/rag/ports.py`:

```python
from typing import Protocol

from src.knowledge_extension.rag.models import ContextPackage, RetrievalHit, RetrievalRequest, RetrievalResult


class RagRetriever(Protocol):
    def retrieve(self, request: RetrievalRequest) -> RetrievalResult: ...


class RagReranker(Protocol):
    def rerank(self, hits: list[RetrievalHit]) -> list[RetrievalHit]: ...


class ContextAssembler(Protocol):
    def assemble(self, hits: list[RetrievalHit], budget: int) -> ContextPackage: ...
```

- [ ] **Step 4: Implement in-memory RAG**

Create `src/knowledge_extension/rag/in_memory.py`:

```python
from src.knowledge_extension.assets.models import AssetQuery
from src.knowledge_extension.assets.ports import KnowledgeChunkRepository
from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus
from src.knowledge_extension.rag.models import ContextPackage, RetrievalHit, RetrievalRequest, RetrievalResult


class InMemoryHybridRetriever:
    def __init__(self, chunk_repository: KnowledgeChunkRepository):
        self.chunk_repository = chunk_repository

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        query_terms = [term for term in request.query.lower().replace("/", " ").split() if term]
        chunks = self.chunk_repository.list_chunks(
            AssetQuery(
                role=request.filters.role,
                tenant_id=request.filters.tenant_id,
                campus_id=request.filters.campus_id,
                scenario=request.filters.scenario,
                asset_types=request.filters.asset_types,
            )
        )
        hits = []
        for chunk in chunks:
            searchable = " ".join([chunk.text, chunk.summary, " ".join(chunk.tags), " ".join(chunk.scenario_tags)]).lower()
            matched = [term for term in query_terms if term in searchable]
            chinese_match = any(token in chunk.text for token in ["医保", "结算", "出院", "审核", "DRG", "DIP", "病案"] if token in request.query)
            if matched or chinese_match:
                score = len(matched) + (1.0 if chinese_match else 0.0)
                hits.append(RetrievalHit(chunk=chunk, score=score, matched_terms=matched))
        reranked = sorted(hits, key=lambda hit: (-hit.score, hit.chunk.asset_type.value, hit.chunk.chunk_id))[: request.max_results]
        if not reranked:
            return RetrievalResult(status=KnowledgeExtensionStatus.NO_HIT, uncertainties=["未检索到可用知识依据，建议人工复核"], audit_events=[AuditSummary(event_type="rag_no_hit", summary={"query": request.query})])
        context = self._assemble(reranked, request.context_budget)
        return RetrievalResult(status=KnowledgeExtensionStatus.SUCCESS, hits=reranked, context=context, citations=context.citations, audit_events=[AuditSummary(event_type="rag_retrieved", summary={"hits": len(reranked)})])

    def _assemble(self, hits: list[RetrievalHit], budget: int) -> ContextPackage:
        context_parts = []
        citations = []
        used = 0
        truncated = 0
        for hit in hits:
            text = hit.chunk.text
            remaining = budget - used
            if remaining <= 0:
                truncated += 1
                continue
            selected = text[:remaining]
            used += len(selected)
            if len(selected) < len(text):
                truncated += 1
            context_parts.append(selected)
            citations.append(Citation(source_id=hit.chunk.asset_id, source_type=hit.chunk.asset_type.value, title=hit.chunk.title, version=hit.chunk.asset_version, section=hit.chunk.section, chunk_id=hit.chunk.chunk_id, evidence=hit.chunk.summary, score=hit.score, internal_locator=hit.chunk.locator))
        return ContextPackage(hits=hits, citations=citations, context_text="\n".join(context_parts), truncated_count=truncated)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/tests/knowledge_extension/test_rag.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/knowledge_extension/rag src/tests/knowledge_extension/test_rag.py
git commit -m "feat: add in-memory rag retrieval"
```

---

### Task 4: Rule Explanation

**Files:**
- Create: `src/knowledge_extension/rule_explanation/__init__.py`
- Create: `src/knowledge_extension/rule_explanation/models.py`
- Create: `src/knowledge_extension/rule_explanation/ports.py`
- Create: `src/knowledge_extension/rule_explanation/in_memory.py`
- Test: `src/tests/knowledge_extension/test_rule_explanation.py`

- [ ] **Step 1: Write failing tests for rule explanation**

Create `src/tests/knowledge_extension/test_rule_explanation.py`:

```python
from src.knowledge_extension.rule_explanation.in_memory import InMemoryRuleExplainer
from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleType


def test_explains_known_settlement_error_code_with_citation():
    explainer = InMemoryRuleExplainer()
    result = explainer.explain(RuleExplanationRequest(rule_type=RuleType.ERROR_CODE, rule_code="E001", scenario="settlement_exception", role="medical_insurance_officer"))

    assert result.status.value == "success"
    assert "错误码" in result.meaning
    assert result.citations


def test_unknown_rule_returns_uncertainty():
    explainer = InMemoryRuleExplainer()
    result = explainer.explain(RuleExplanationRequest(rule_type=RuleType.ERROR_CODE, rule_code="UNKNOWN", scenario="settlement_exception", role="doctor"))

    assert result.status.value == "no_hit"
    assert result.uncertainties


def test_high_impact_rule_requires_human_review():
    explainer = InMemoryRuleExplainer()
    result = explainer.explain(RuleExplanationRequest(rule_type=RuleType.DRG_DIP, rule_code="DRG_LOSS_RISK", scenario="pre_discharge_qc", role="doctor"))

    assert result.requires_human_review is True
    assert "人工" in result.review_hint
    assert "已完成" not in " ".join(result.suggestions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/knowledge_extension/test_rule_explanation.py -v`

Expected: FAIL with missing `rule_explanation` module.

- [ ] **Step 3: Implement models and port**

Create `src/knowledge_extension/rule_explanation/__init__.py` as an empty file.

Create `src/knowledge_extension/rule_explanation/models.py`:

```python
from enum import StrEnum

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus


class RuleType(StrEnum):
    ERROR_CODE = "error_code"
    POLICY = "policy"
    PRE_AUDIT = "pre_audit"
    DRG_DIP = "drg_dip"
    MEDICAL_RECORD = "medical_record"


class RuleEvidence(BaseModel):
    evidence_id: str
    title: str
    content: str
    citation: Citation | None = None


class RuleExplanationRequest(BaseModel):
    rule_type: RuleType
    rule_code: str
    scenario: str
    role: str
    evidences: list[RuleEvidence] = Field(default_factory=list)


class RuleExplanationResult(BaseModel):
    status: KnowledgeExtensionStatus
    rule_code: str
    meaning: str = ""
    conditions: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    requires_human_review: bool = False
    review_hint: str = ""
    audit_events: list[AuditSummary] = Field(default_factory=list)
```

Create `src/knowledge_extension/rule_explanation/ports.py`:

```python
from typing import Protocol

from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleExplanationResult


class RuleExplainer(Protocol):
    def explain(self, request: RuleExplanationRequest) -> RuleExplanationResult: ...
```

- [ ] **Step 4: Implement in-memory explainer**

Create `src/knowledge_extension/rule_explanation/in_memory.py`:

```python
from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus
from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleExplanationResult, RuleType


class InMemoryRuleExplainer:
    def explain(self, request: RuleExplanationRequest) -> RuleExplanationResult:
        if request.rule_type is RuleType.ERROR_CODE and request.rule_code == "E001":
            return RuleExplanationResult(
                status=KnowledgeExtensionStatus.SUCCESS,
                rule_code=request.rule_code,
                meaning="错误码 E001 表示医保结算交易状态或费用状态需要核对。",
                conditions=["医保结算异常导办", "存在交易或收费状态不一致"],
                suggestions=["核查医保交易状态", "核查收费明细状态", "必要时由人工在既有系统处理"],
                limitations=["该解释仅作为导办建议，不代表医保正式裁决"],
                citations=[Citation(source_id="asset-error-code-001", source_type="error_code", title="医保错误码知识", version="2026.1", section="E001", evidence="错误码 E001 常见于交易状态异常")],
                audit_events=[AuditSummary(event_type="rule_explained", summary={"rule_code": request.rule_code})],
            )
        if request.rule_type is RuleType.DRG_DIP and request.rule_code == "DRG_LOSS_RISK":
            return RuleExplanationResult(
                status=KnowledgeExtensionStatus.SUCCESS,
                rule_code=request.rule_code,
                meaning="DRG/DIP 风险提示表示当前费用或诊断组合可能存在分组亏损风险。",
                conditions=["出院前联合质控", "存在 DRG/DIP 风险命中"],
                suggestions=["核查诊断、手术和费用明细完整性", "由人工在既有业务系统复核"],
                limitations=["不代表正式分组结果"],
                citations=[Citation(source_id="asset-audit-rule-001", source_type="audit_rule", title="出院前审核规则", version="2026.1", section="DRG/DIP", evidence="DRG/DIP 风险需人工复核")],
                requires_human_review=True,
                review_hint="该风险影响费用与分组判断，需要人工在既有系统复核。",
                audit_events=[AuditSummary(event_type="rule_explained", summary={"rule_code": request.rule_code})],
            )
        return RuleExplanationResult(
            status=KnowledgeExtensionStatus.NO_HIT,
            rule_code=request.rule_code,
            uncertainties=[f"未找到规则 {request.rule_code} 的可靠解释依据，建议人工复核"],
            requires_human_review=True,
            review_hint="规则未知或证据不足，不能生成确定性处理结论。",
            audit_events=[AuditSummary(event_type="rule_unknown", summary={"rule_code": request.rule_code})],
        )
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/tests/knowledge_extension/test_rule_explanation.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/knowledge_extension/rule_explanation src/tests/knowledge_extension/test_rule_explanation.py
git commit -m "feat: add deterministic rule explanation"
```

---

### Task 5: Prompt Template Management

**Files:**
- Create: `src/knowledge_extension/prompt_templates/__init__.py`
- Create: `src/knowledge_extension/prompt_templates/models.py`
- Create: `src/knowledge_extension/prompt_templates/ports.py`
- Create: `src/knowledge_extension/prompt_templates/in_memory.py`
- Test: `src/tests/knowledge_extension/test_prompt_templates.py`

- [ ] **Step 1: Write failing tests for prompt templates**

Create `src/tests/knowledge_extension/test_prompt_templates.py`:

```python
from src.knowledge_extension.prompt_templates.in_memory import build_default_template_repository
from src.knowledge_extension.prompt_templates.models import TemplateSelectionRequest


def test_selects_role_specific_template():
    repo = build_default_template_repository()
    result = repo.select(TemplateSelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", output_format="agent_response", language="zh-CN", risk_level="low"))

    assert result.status.value == "success"
    assert result.template is not None
    assert result.template.requires_citations is True


def test_missing_template_degrades_safely():
    repo = build_default_template_repository()
    result = repo.select(TemplateSelectionRequest(scenario="unknown", role="doctor", output_format="agent_response", language="zh-CN", risk_level="low"))

    assert result.status.value == "template_missing"
    assert result.uncertainties


def test_render_rejects_missing_required_variable():
    repo = build_default_template_repository()
    selected = repo.select(TemplateSelectionRequest(scenario="settlement_exception", role="medical_insurance_officer", output_format="agent_response", language="zh-CN", risk_level="low"))

    rendered = repo.render(selected.template.template_id, {"message": "请解释异常"})

    assert rendered.status.value == "partial_degraded"
    assert "patient_id" in rendered.uncertainties[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/knowledge_extension/test_prompt_templates.py -v`

Expected: FAIL with missing `prompt_templates` module.

- [ ] **Step 3: Implement models and ports**

Create `src/knowledge_extension/prompt_templates/__init__.py` as an empty file.

Create `src/knowledge_extension/prompt_templates/models.py`:

```python
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    INACTIVE = "inactive"


class PromptTemplate(BaseModel):
    template_id: str
    scenario: str
    role: str
    output_format: str
    language: str
    risk_level: str
    version: str
    status: TemplateStatus
    content: str
    required_variables: set[str] = Field(default_factory=set)
    requires_citations: bool = True
    requires_uncertainties: bool = True
    blocks_high_risk_actions: bool = True


class TemplateSelectionRequest(BaseModel):
    scenario: str
    role: str
    output_format: str
    language: str
    risk_level: str


class TemplateSelectionResult(BaseModel):
    status: KnowledgeExtensionStatus
    template: PromptTemplate | None = None
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)


class TemplateRenderResult(BaseModel):
    status: KnowledgeExtensionStatus
    prompt: str = ""
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
```

Create `src/knowledge_extension/prompt_templates/ports.py`:

```python
from typing import Any, Protocol

from src.knowledge_extension.prompt_templates.models import TemplateRenderResult, TemplateSelectionRequest, TemplateSelectionResult


class PromptTemplateRepository(Protocol):
    def select(self, request: TemplateSelectionRequest) -> TemplateSelectionResult: ...
    def render(self, template_id: str, variables: dict[str, Any]) -> TemplateRenderResult: ...
```

- [ ] **Step 4: Implement in-memory templates**

Create `src/knowledge_extension/prompt_templates/in_memory.py`:

```python
from typing import Any

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.prompt_templates.models import PromptTemplate, TemplateRenderResult, TemplateSelectionRequest, TemplateSelectionResult, TemplateStatus


class InMemoryPromptTemplateRepository:
    def __init__(self, templates: list[PromptTemplate]):
        self._templates = {template.template_id: template for template in templates}

    def select(self, request: TemplateSelectionRequest) -> TemplateSelectionResult:
        candidates = [
            template for template in self._templates.values()
            if template.status is TemplateStatus.PUBLISHED
            and template.scenario == request.scenario
            and template.role in {request.role, "*"}
            and template.output_format == request.output_format
            and template.language == request.language
        ]
        if not candidates:
            return TemplateSelectionResult(status=KnowledgeExtensionStatus.TEMPLATE_MISSING, uncertainties=["未找到匹配提示词模板，已回退确定性响应"], audit_events=[AuditSummary(event_type="template_missing", summary=request.model_dump())])
        selected = sorted(candidates, key=lambda item: (item.role != request.role, item.risk_level != request.risk_level, item.template_id))[0]
        return TemplateSelectionResult(status=KnowledgeExtensionStatus.SUCCESS, template=selected.model_copy(deep=True), audit_events=[AuditSummary(event_type="template_selected", summary={"template_id": selected.template_id})])

    def render(self, template_id: str, variables: dict[str, Any]) -> TemplateRenderResult:
        template = self._templates[template_id]
        missing = sorted(template.required_variables - set(variables.keys()))
        if missing:
            return TemplateRenderResult(status=KnowledgeExtensionStatus.PARTIAL_DEGRADED, uncertainties=[f"模板变量缺失: {', '.join(missing)}"], audit_events=[AuditSummary(event_type="template_render_failed", summary={"template_id": template_id, "missing": missing})])
        prompt = template.content.format(**{key: str(value) for key, value in variables.items()})
        safety = "\n必须保留 citations 或 uncertainties；不得声称已执行高风险业务变更；不得泄露敏感信息。"
        return TemplateRenderResult(status=KnowledgeExtensionStatus.SUCCESS, prompt=prompt + safety, audit_events=[AuditSummary(event_type="template_rendered", summary={"template_id": template_id})])


def build_default_template_repository() -> InMemoryPromptTemplateRepository:
    templates = [
        PromptTemplate(template_id="tpl-settlement-officer", scenario="settlement_exception", role="medical_insurance_officer", output_format="agent_response", language="zh-CN", risk_level="low", version="2026.1", status=TemplateStatus.PUBLISHED, content="针对患者 {patient_id} 的结算异常请求：{message}", required_variables={"patient_id", "message"}),
        PromptTemplate(template_id="tpl-qc-doctor", scenario="pre_discharge_qc", role="doctor", output_format="agent_response", language="zh-CN", risk_level="medium", version="2026.1", status=TemplateStatus.PUBLISHED, content="针对患者 {patient_id} 的出院前质控：{message}", required_variables={"patient_id", "message"}),
    ]
    return InMemoryPromptTemplateRepository(templates)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/tests/knowledge_extension/test_prompt_templates.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/knowledge_extension/prompt_templates src/tests/knowledge_extension/test_prompt_templates.py
git commit -m "feat: add prompt template management"
```

---

### Task 6: Extension Registry

**Files:**
- Create: `src/knowledge_extension/extension_registry/__init__.py`
- Create: `src/knowledge_extension/extension_registry/models.py`
- Create: `src/knowledge_extension/extension_registry/ports.py`
- Create: `src/knowledge_extension/extension_registry/in_memory.py`
- Test: `src/tests/knowledge_extension/test_extension_registry.py`

- [ ] **Step 1: Write failing tests for extension registry**

Create `src/tests/knowledge_extension/test_extension_registry.py`:

```python
from src.knowledge_extension.extension_registry.in_memory import build_default_extension_registry
from src.knowledge_extension.extension_registry.models import ExtensionSelectionRequest


def test_selects_available_extension_for_allowed_role():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-fee-analysis", role="medical_insurance_officer", scenario="settlement_exception"))

    assert result.status.value == "success"
    assert result.extension.extension_id == "tool-fee-analysis"


def test_denies_extension_for_wrong_role():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-fee-analysis", role="doctor", scenario="settlement_exception"))

    assert result.status.value == "permission_denied"
    assert result.audit_events


def test_blocks_high_risk_extension():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-refund-executor", role="medical_insurance_officer", scenario="settlement_exception"))

    assert result.status.value == "high_risk_blocked"
    assert "人工" in result.uncertainties[0]


def test_unhealthy_extension_degrades():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="mcp-disabled", role="admin", scenario="settlement_exception"))

    assert result.status.value == "unavailable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/knowledge_extension/test_extension_registry.py -v`

Expected: FAIL with missing `extension_registry` module.

- [ ] **Step 3: Implement models and ports**

Create `src/knowledge_extension/extension_registry/__init__.py` as an empty file.

Create `src/knowledge_extension/extension_registry/models.py`:

```python
from enum import StrEnum

from pydantic import BaseModel, Field

from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus


class ExtensionType(StrEnum):
    TOOL = "tool"
    SKILL = "skill"
    MCP = "mcp"
    A2A = "a2a"


class ExtensionRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExtensionHealth(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ExtensionCapability(BaseModel):
    extension_id: str
    extension_type: ExtensionType
    name: str
    description: str
    scenarios: set[str] = Field(default_factory=set)
    required_roles: set[str] = Field(default_factory=set)
    risk_level: ExtensionRiskLevel
    health: ExtensionHealth
    enabled: bool = True
    high_risk_actions: set[str] = Field(default_factory=set)


class ExtensionSelectionRequest(BaseModel):
    extension_id: str
    role: str
    scenario: str


class ExtensionSelectionResult(BaseModel):
    status: KnowledgeExtensionStatus
    extension: ExtensionCapability | None = None
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)
```

Create `src/knowledge_extension/extension_registry/ports.py`:

```python
from typing import Protocol

from src.knowledge_extension.extension_registry.models import ExtensionSelectionRequest, ExtensionSelectionResult


class ExtensionRegistry(Protocol):
    def select(self, request: ExtensionSelectionRequest) -> ExtensionSelectionResult: ...
```

- [ ] **Step 4: Implement registry**

Create `src/knowledge_extension/extension_registry/in_memory.py`:

```python
from src.knowledge_extension.common.models import AuditSummary, KnowledgeExtensionStatus
from src.knowledge_extension.extension_registry.models import ExtensionCapability, ExtensionHealth, ExtensionRiskLevel, ExtensionSelectionRequest, ExtensionSelectionResult, ExtensionType


class InMemoryExtensionRegistry:
    def __init__(self, extensions: list[ExtensionCapability]):
        self._extensions = {extension.extension_id: extension for extension in extensions}

    def select(self, request: ExtensionSelectionRequest) -> ExtensionSelectionResult:
        extension = self._extensions.get(request.extension_id)
        if extension is None:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.NO_HIT, uncertainties=["未找到扩展能力"], audit_events=[AuditSummary(event_type="extension_missing", summary=request.model_dump())])
        if not extension.enabled or extension.health is not ExtensionHealth.HEALTHY:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.UNAVAILABLE, uncertainties=["扩展能力不可用"], audit_events=[AuditSummary(event_type="extension_unavailable", summary={"extension_id": extension.extension_id})])
        if extension.scenarios and request.scenario not in extension.scenarios:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.PERMISSION_DENIED, uncertainties=["扩展能力不适用于当前场景"], audit_events=[AuditSummary(event_type="extension_scope_denied", summary={"extension_id": extension.extension_id})])
        if extension.required_roles and request.role not in extension.required_roles:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.PERMISSION_DENIED, uncertainties=["当前角色无权使用该扩展能力"], audit_events=[AuditSummary(event_type="extension_permission_denied", summary={"extension_id": extension.extension_id})])
        if extension.risk_level is ExtensionRiskLevel.HIGH or extension.high_risk_actions:
            return ExtensionSelectionResult(status=KnowledgeExtensionStatus.HIGH_RISK_BLOCKED, uncertainties=["扩展能力涉及高风险动作，必须转人工确认"], audit_events=[AuditSummary(event_type="extension_high_risk_blocked", summary={"extension_id": extension.extension_id})])
        return ExtensionSelectionResult(status=KnowledgeExtensionStatus.SUCCESS, extension=extension.model_copy(deep=True), audit_events=[AuditSummary(event_type="extension_selected", summary={"extension_id": extension.extension_id})])


def build_default_extension_registry() -> InMemoryExtensionRegistry:
    return InMemoryExtensionRegistry([
        ExtensionCapability(extension_id="tool-fee-analysis", extension_type=ExtensionType.TOOL, name="费用明细分析", description="分析费用明细", scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer", "admin"}, risk_level=ExtensionRiskLevel.LOW, health=ExtensionHealth.HEALTHY),
        ExtensionCapability(extension_id="tool-refund-executor", extension_type=ExtensionType.TOOL, name="退费执行", description="高风险退费执行", scenarios={"settlement_exception"}, required_roles={"medical_insurance_officer"}, risk_level=ExtensionRiskLevel.HIGH, health=ExtensionHealth.HEALTHY, high_risk_actions={"refund"}),
        ExtensionCapability(extension_id="mcp-disabled", extension_type=ExtensionType.MCP, name="不可用 MCP", description="健康检查失败", scenarios={"settlement_exception"}, required_roles={"admin"}, risk_level=ExtensionRiskLevel.LOW, health=ExtensionHealth.UNHEALTHY),
    ])
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/tests/knowledge_extension/test_extension_registry.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/knowledge_extension/extension_registry src/tests/knowledge_extension/test_extension_registry.py
git commit -m "feat: add extension registry"
```

---

### Task 7: Knowledge Extension Facade

**Files:**
- Create: `src/knowledge_extension/service.py`
- Test: `src/tests/knowledge_extension/test_service.py`

- [ ] **Step 1: Write failing tests for facade**

Create `src/tests/knowledge_extension/test_service.py`:

```python
from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service


def test_facade_returns_deduped_citations_and_uncertainties():
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="医保结算异常错误码 E001", scenario="settlement_exception", role="medical_insurance_officer", patient_id="P001", rule_code="E001"))

    keys = [citation.dedupe_key() for citation in result.citations]
    assert result.status.value == "success"
    assert len(keys) == len(set(keys))
    assert result.to_agent_payload()["citations"]


def test_facade_no_evidence_returns_uncertainty():
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="完全不存在的知识", scenario="settlement_exception", role="doctor", patient_id="P001", rule_code="UNKNOWN"))

    assert result.uncertainties
    assert result.to_agent_payload()["uncertainties"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/tests/knowledge_extension/test_service.py -v`

Expected: FAIL with missing facade.

- [ ] **Step 3: Implement facade**

Create `src/knowledge_extension/service.py`:

```python
from pydantic import BaseModel, Field

from src.knowledge_extension.assets.in_memory import build_default_asset_repository
from src.knowledge_extension.common.models import AuditSummary, Citation, KnowledgeExtensionStatus
from src.knowledge_extension.extension_registry.in_memory import build_default_extension_registry
from src.knowledge_extension.prompt_templates.in_memory import build_default_template_repository
from src.knowledge_extension.prompt_templates.models import TemplateSelectionRequest
from src.knowledge_extension.rag.in_memory import InMemoryHybridRetriever
from src.knowledge_extension.rag.models import RetrievalFilter, RetrievalRequest
from src.knowledge_extension.rule_explanation.in_memory import InMemoryRuleExplainer
from src.knowledge_extension.rule_explanation.models import RuleExplanationRequest, RuleType


class KnowledgeEnhancementRequest(BaseModel):
    message: str
    scenario: str
    role: str
    patient_id: str | None = None
    tenant_id: str | None = None
    campus_id: str | None = None
    rule_code: str | None = None


class KnowledgeEnhancementResult(BaseModel):
    status: KnowledgeExtensionStatus
    citations: list[Citation] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    audit_events: list[AuditSummary] = Field(default_factory=list)

    def to_agent_payload(self) -> dict[str, list[dict] | list[str]]:
        return {
            "citations": [citation.to_public_dict() for citation in self.citations],
            "uncertainties": self.uncertainties,
            "audit_events": [event.masked_summary() for event in self.audit_events],
        }


class KnowledgeExtensionService:
    def __init__(self, retriever: InMemoryHybridRetriever, explainer: InMemoryRuleExplainer, templates, extensions):
        self.retriever = retriever
        self.explainer = explainer
        self.templates = templates
        self.extensions = extensions

    def enhance(self, request: KnowledgeEnhancementRequest) -> KnowledgeEnhancementResult:
        citations: list[Citation] = []
        uncertainties: list[str] = []
        audits: list[AuditSummary] = []

        template_result = self.templates.select(TemplateSelectionRequest(scenario=request.scenario, role=request.role, output_format="agent_response", language="zh-CN", risk_level="low"))
        uncertainties.extend(template_result.uncertainties)
        audits.extend(template_result.audit_events)

        retrieval = self.retriever.retrieve(RetrievalRequest(query=request.message, filters=RetrievalFilter(role=request.role, tenant_id=request.tenant_id, campus_id=request.campus_id, scenario=request.scenario)))
        citations.extend(retrieval.citations)
        uncertainties.extend(retrieval.uncertainties)
        audits.extend(retrieval.audit_events)

        if request.rule_code:
            rule_type = RuleType.ERROR_CODE if request.scenario == "settlement_exception" else RuleType.DRG_DIP
            explanation = self.explainer.explain(RuleExplanationRequest(rule_type=rule_type, rule_code=request.rule_code, scenario=request.scenario, role=request.role))
            citations.extend(explanation.citations)
            uncertainties.extend(explanation.uncertainties)
            audits.extend(explanation.audit_events)

        deduped = []
        seen = set()
        for citation in citations:
            key = citation.dedupe_key()
            if key not in seen:
                seen.add(key)
                deduped.append(citation)
        status = KnowledgeExtensionStatus.SUCCESS if deduped else KnowledgeExtensionStatus.NO_HIT
        if not deduped and not uncertainties:
            uncertainties.append("未获得可追溯知识依据，建议人工复核")
        return KnowledgeEnhancementResult(status=status, citations=deduped, uncertainties=uncertainties, audit_events=audits)


def build_default_knowledge_extension_service() -> KnowledgeExtensionService:
    assets = build_default_asset_repository()
    return KnowledgeExtensionService(
        retriever=InMemoryHybridRetriever(assets),
        explainer=InMemoryRuleExplainer(),
        templates=build_default_template_repository(),
        extensions=build_default_extension_registry(),
    )
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest src/tests/knowledge_extension/test_service.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/knowledge_extension/service.py src/tests/knowledge_extension/test_service.py
git commit -m "feat: add knowledge extension facade"
```

---

### Task 8: Runtime and Scenario Integration

**Files:**
- Modify: `src/business_scenarios/settlement_exception_guide/service.py`
- Modify: `src/business_scenarios/pre_discharge_joint_qc/service.py`
- Modify: `src/runtime/runtime_state/models.py`
- Test: `src/tests/integration/test_knowledge_extension_runtime.py`

- [ ] **Step 1: Write failing integration tests**

Create `src/tests/integration/test_knowledge_extension_runtime.py`:

```python
from fastapi.testclient import TestClient

from src.runtime.api.app import create_app


def test_settlement_exception_response_contains_knowledge_citations():
    client = TestClient(create_app())
    response = client.post("/api/v1/medical-insurance-ai-agent/chat", json={"user_id": "u001", "role": "medical_insurance_officer", "message": "患者医保结算异常，错误码 E001", "patient_id": "P001", "encounter_id": "E001"})

    assert response.status_code == 200
    data = response.json()
    assert data["citations"] or data["uncertainties"]
    assert "audit" in data
    assert "knowledge_extension" in data["audit"]


def test_pre_discharge_qc_response_contains_rule_explanation_or_uncertainty():
    client = TestClient(create_app())
    response = client.post("/api/v1/medical-insurance-ai-agent/chat", json={"user_id": "u002", "role": "doctor", "message": "请做出院前联合质控，关注 DRG DIP 和病案风险", "patient_id": "P001", "encounter_id": "E001"})

    assert response.status_code == 200
    data = response.json()
    assert data["citations"] or data["uncertainties"]
    assert "knowledge_extension" in data["audit"]
```

- [ ] **Step 2: Run test to see current gap**

Run: `python -m pytest src/tests/integration/test_knowledge_extension_runtime.py -v`

Expected: FAIL if responses do not include knowledge-enhanced citations/audit details.

- [ ] **Step 3: Integrate settlement exception service**

In `src/business_scenarios/settlement_exception_guide/service.py`, import facade and merge payload near final response assembly. The current function signature is `guide_settlement_exception(patient_id: str, encounter_id: str)`, so build the knowledge request from the transaction error code and patient context rather than from a `request` object.

```python
from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service
```

Add helper:

```python
def enhance_settlement_knowledge(error_code: str, patient_id: str | None) -> dict:
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message=f"医保结算异常错误码 {error_code}", scenario="settlement_exception", role="medical_insurance_officer", patient_id=patient_id, tenant_id="tenant-a", campus_id="north", rule_code=error_code))
    return result.to_agent_payload()
```

Replace the current direct `return AgentResponse(...)` with a local `response = AgentResponse(...)`, then merge and return:

```python
knowledge = enhance_settlement_knowledge(tx.error_code, patient_id)
response.citations.extend(knowledge["citations"])
response.uncertainties.extend(knowledge["uncertainties"])
response.audit["knowledge_extension"] = knowledge["audit_events"]
return response
```

Keep the existing transaction citation and existing error-code citation; append knowledge-extension citations rather than replacing them.

- [ ] **Step 4: Integrate pre-discharge QC service**

In `src/business_scenarios/pre_discharge_joint_qc/service.py`, import facade. The current function signature is `run_pre_discharge_qc(patient_id: str, encounter_id: str)`, so build the knowledge request from the deterministic QC context rather than from a `request` object:

```python
from src.knowledge_extension.service import KnowledgeEnhancementRequest, build_default_knowledge_extension_service
```

Add helper:

```python
def enhance_qc_knowledge(patient_id: str | None) -> dict:
    service = build_default_knowledge_extension_service()
    result = service.enhance(KnowledgeEnhancementRequest(message="出院前联合质控 DRG DIP 病案风险", scenario="pre_discharge_qc", role="doctor", patient_id=patient_id, rule_code="DRG_LOSS_RISK"))
    return result.to_agent_payload()
```

Replace the current direct `return AgentResponse(...)` with a local `response = AgentResponse(...)`, then merge and return:

```python
knowledge = enhance_qc_knowledge(patient_id)
response.citations.extend(knowledge["citations"])
response.uncertainties.extend(knowledge["uncertainties"])
response.audit["knowledge_extension"] = knowledge["audit_events"]
return response
```

- [ ] **Step 5: Extend runtime state model for knowledge events**

In `src/runtime/runtime_state/models.py`, the current model is a dataclass. Add fields to `WorkflowInstance` using `dataclasses.field`:

```python
knowledge_events: list[dict] = field(default_factory=list)
knowledge_degradation_reasons: list[str] = field(default_factory=list)
```

The final dataclass should be:

```python
from dataclasses import dataclass, field


@dataclass
class WorkflowInstance:
    workflow_id: str
    status: str
    steps: list[str] = field(default_factory=list)
    knowledge_events: list[dict] = field(default_factory=list)
    knowledge_degradation_reasons: list[str] = field(default_factory=list)
```

- [ ] **Step 6: Run integration tests**

Run: `python -m pytest src/tests/integration/test_knowledge_extension_runtime.py -v`

Expected: PASS.

- [ ] **Step 7: Run existing scenario tests**

Run: `python -m pytest src/tests/e2e/test_settlement_exception.py src/tests/e2e/test_pre_discharge_joint_qc.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/business_scenarios src/runtime/runtime_state src/tests/integration/test_knowledge_extension_runtime.py
git commit -m "feat: integrate knowledge extension runtime"
```

---

### Task 9: API, Streaming, Frontend, and Security Validation

**Files:**
- Modify: `src/runtime/api/streaming.py`
- Modify: `src/static/index.html`
- Test: `src/tests/security/test_knowledge_extension_security.py`
- Test: `src/tests/integration/test_openapi_contract.py`

- [ ] **Step 1: Write failing security tests**

Create `src/tests/security/test_knowledge_extension_security.py`:

```python
from src.knowledge_extension.common.models import Citation
from src.knowledge_extension.extension_registry.in_memory import build_default_extension_registry
from src.knowledge_extension.extension_registry.models import ExtensionSelectionRequest


def test_public_citation_does_not_expose_internal_locator():
    citation = Citation(source_id="a1", source_type="policy", title="内部政策", version="1", evidence="依据", internal_locator="D:/secret/file.pdf")

    public = citation.to_public_dict()

    assert "internal_locator" not in public
    assert "D:/secret" not in str(public)


def test_high_risk_extension_is_not_selected_for_execution():
    registry = build_default_extension_registry()
    result = registry.select(ExtensionSelectionRequest(extension_id="tool-refund-executor", role="medical_insurance_officer", scenario="settlement_exception"))

    assert result.status.value == "high_risk_blocked"
    assert result.extension is None
```

- [ ] **Step 2: Run security tests**

Run: `python -m pytest src/tests/security/test_knowledge_extension_security.py -v`

Expected: PASS if previous tasks are complete.

- [ ] **Step 3: Update streaming final event if needed**

Inspect `src/runtime/api/streaming.py`. If final SSE payload is built from `AgentResponse`, ensure the final event keeps `citations` and `uncertainties`:

```python
final_payload = response.model_dump() if hasattr(response, "model_dump") else response
final_payload.setdefault("citations", [])
final_payload.setdefault("uncertainties", ["流式响应未获得额外知识依据"] if not final_payload.get("citations") else [])
```

Run: `python -m pytest src/tests/integration/test_openapi_contract.py -v`

Expected: PASS.

- [ ] **Step 4: Update frontend display**

In `src/static/index.html`, add rendering for citations and uncertainties where chat response is displayed:

```javascript
const citations = data.citations || [];
const uncertainties = data.uncertainties || [];
const citationHtml = citations.map(item => `<li>${item.title || item.source_id}: ${item.evidence || ''}</li>`).join('');
const uncertaintyHtml = uncertainties.map(item => `<li>${item}</li>`).join('');
```

Attach the generated lists to the existing response container without removing current fields.

- [ ] **Step 5: Run API and security tests**

Run: `python -m pytest src/tests/security src/tests/integration/test_openapi_contract.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/runtime/api/streaming.py src/static/index.html src/tests/security/test_knowledge_extension_security.py src/tests/integration/test_openapi_contract.py
git commit -m "feat: validate knowledge extension api safety"
```

---

### Task 10: Full Regression, OpenSpec Validation, and Task Checklist Update

**Files:**
- Modify: `openspec/changes/knowledge-extension/tasks.md`
- Optionally modify any file required by failures from full regression.

- [ ] **Step 1: Run all knowledge extension tests**

Run: `python -m pytest src/tests/knowledge_extension -v`

Expected: PASS.

- [ ] **Step 2: Run integration and security tests**

Run: `python -m pytest src/tests/integration src/tests/security -v`

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest src/tests -v`

Expected: PASS.

- [ ] **Step 4: Validate OpenSpec**

Run: `npx openspec validate "knowledge-extension" --strict`

Expected: `Change 'knowledge-extension' is valid`.

- [ ] **Step 5: Update OpenSpec tasks checklist**

In `openspec/changes/knowledge-extension/tasks.md`, mark implemented items as completed. Example after all tasks pass:

```markdown
- [x] 1.1 新增 `src/knowledge_extension/assets/` 目录及 `__init__.py`
```

Apply the same `[x]` status to every implemented checklist item.

- [ ] **Step 6: Remove Python cache files from git tracking area if present**

Run: `git status --short`

If `__pycache__` files appear as untracked files, remove them with Windows cmd:

```cmd
for /d /r src %d in (__pycache__) do @if exist "%d" rmdir /s /q "%d"
```

Run: `git status --short`

Expected: no `__pycache__` entries.

- [ ] **Step 7: Commit validation updates**

Run:

```bash
git add openspec/changes/knowledge-extension/tasks.md
git commit -m "chore: complete knowledge extension checklist"
```

---

## Self-Review Checklist

- OpenSpec `knowledge-assets` is covered by Tasks 2 and 10.
- OpenSpec `rag-retrieval` is covered by Tasks 3 and 10.
- OpenSpec `rule-explanation` is covered by Task 4.
- OpenSpec `prompt-template-management` is covered by Task 5.
- OpenSpec `extension-registry` is covered by Task 6.
- OpenSpec runtime modifications are covered by Task 8, including concrete `AgentResponse` field merging and `WorkflowInstance` dataclass extension.
- OpenSpec security contract modifications are covered by Task 9.
- Full validation and task checklist completion are covered by Task 10.
- No real external storage, remote tools, or adapter calls are introduced in the knowledge service.
- New APIs use Pydantic models and Protocol ports rather than raw `dict` returns.
