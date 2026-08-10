"""Skill 草稿管理 API 测试（T2a）。

覆盖草稿 CRUD、复制、乐观锁 409、权限门禁。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.data_platform.storage.skill.draft_in_memory import (
    InMemorySkillDraftStorage,
)
from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    get_skill_ai_authoring_service,
    get_skill_draft_service,
    get_skill_idempotency_store,
)
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationResponse,
    SkillAIOptimizationResponse,
)
from src.runtime.skill_management.ai_authoring.security import SkillAISecurityIssue
from src.runtime.skill_management.ai_authoring.service import (
    SkillAIModelError,
    SkillAIMetricNotFoundError,
    SkillAIMetricNotPublishedError,
    SkillAISecurityRejectedError,
)
from src.runtime.skill_management.draft_service import SkillDraftService

PREFIX = "/api/v1/medical-insurance-ai-agent"


def _control_token(
    user_id: str = "information-admin",
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
) -> str:
    payload = {
        "sub": user_id,
        "roles": roles or ["information_department"],
        "permissions": permissions or ["skill:release:test"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"test.{encoded}.signature"


def _auth_headers(token: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token or _control_token()}"}


class _FakeLoader:
    def __init__(self) -> None:
        self.skills: dict[str, SimpleNamespace] = {}

    def get(self, skill_id: str):
        return self.skills.get(skill_id)


def _proposal() -> SkillAIGenerationResponse:
    return SkillAIGenerationResponse.model_validate(
        {
            "generation_id": "gen-api-1",
            "proposal_hash": "a" * 64,
            "structured_config": {
                "basic": {
                    "skill_id": "deductible_explain",
                    "skill_name": "起付线解释",
                    "description": "解释医保结算起付线",
                    "owner": "medical_office",
                },
                "business_mounting": {
                    "business_action": "explain",
                    "business_object": "settlement",
                    "include_keywords": ["起付线"],
                    "excluded_intents": [],
                },
                "inputs": [
                    {
                        "metric_code": "settlement.total_amount",
                        "alias": "total_amount",
                        "required": True,
                        "purpose": "计算起付线",
                    }
                ],
                "schemas": {
                    "input": {"type": "object"},
                    "output": {"type": "object"},
                },
            },
            "raw_files": {
                "assembler.py": "def assemble(data):\n    return dict(data)\n",
                "prompt_template.yaml": "system: explain settlement\n",
            },
            "validation_preview": {
                "issues": [],
                "has_blocking": False,
                "blocking_ok": True,
            },
            "provenance": {
                "model_type": "test-model",
                "scene": "skill_authoring",
                "prompt_version": "skill-authoring-v1",
                "metric_versions": [
                    {
                        "metric_code": "settlement.total_amount",
                        "object_code": "Settlement",
                        "object_version": 3,
                        "status": "published",
                    }
                ],
                "generated_at": "2026-08-10T00:00:00Z",
                "content_hash": "b" * 64,
            },
            "citations": [
                {
                    "source_type": "metric_registry",
                    "source_id": "settlement.total_amount@3",
                    "summary": "已发布指标快照",
                }
            ],
            "uncertainties": ["政策适用范围需人工确认"],
        }
    )


class _FakeAIAuthoringService:
    def __init__(self) -> None:
        self.proposal = _proposal()
        self.generate_error: Exception | None = None
        self.verify_error: Exception | None = None
        self.metric_snapshot_hash = "c" * 64
        self.current_metric_snapshot_hash = self.metric_snapshot_hash
        self.optimize_calls = []

    def generate(self, _request):
        if self.generate_error:
            raise self.generate_error
        return self.proposal

    def generate_with_evidence(self, _request):
        if self.generate_error:
            raise self.generate_error
        return SimpleNamespace(
            proposal=self.proposal,
            metric_snapshot_hash=self.metric_snapshot_hash,
        )

    def verify_for_accept(self, _proposal, *, metric_snapshot_hash=None):
        if self.verify_error:
            raise self.verify_error
        if (
            metric_snapshot_hash is not None
            and metric_snapshot_hash != self.current_metric_snapshot_hash
        ):
            raise SkillAIMetricNotPublishedError("settlement.total_amount")

    def optimize(self, draft, request):
        self.optimize_calls.append((draft, request))
        proposal = self.proposal
        config = proposal.structured_config.model_copy(
            update={
                "basic": proposal.structured_config.basic.model_copy(
                    update={"skill_id": draft.skill_id, "skill_name": draft.skill_name}
                )
            }
        )
        return SkillAIOptimizationResponse(
            base_revision=draft.revision,
            proposal_hash="d" * 64,
            structured_config=config,
            raw_files=draft.raw_files,
            validation_preview=proposal.validation_preview,
            provenance=proposal.provenance,
            diff=(),
            citations=proposal.citations,
            uncertainties=proposal.uncertainties,
        )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")
    app = create_app()
    loader = _FakeLoader()
    storage = InMemorySkillDraftStorage()
    service = SkillDraftService(
        storage=storage,
        loader=loader,
        skills_root="/nonexistent-skills-root",
    )
    ai_service = _FakeAIAuthoringService()
    cache = InMemoryCacheClient()
    app.dependency_overrides[get_skill_draft_service] = lambda: service
    app.dependency_overrides[get_skill_ai_authoring_service] = lambda: ai_service
    app.dependency_overrides[get_skill_idempotency_store] = lambda: cache
    client = TestClient(app)
    client._loader = loader  # type: ignore[attr-defined]
    client._draft_storage = storage  # type: ignore[attr-defined]
    client._ai_service = ai_service  # type: ignore[attr-defined]
    client._cache = cache  # type: ignore[attr-defined]
    return client


# ── 创建 ──────────────────────────────────────────────────────────


def test_create_draft_returns_201(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={
            "skill_id": "my_skill",
            "skill_name": "My Skill",
            "business_action": "explain",
            "business_object": "settlement",
            "include_keywords": ["费用"],
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["skill_id"] == "my_skill"
    assert data["source_type"] == "template"
    assert data["status"] == "editing"
    assert data["revision"] == 1
    assert data["structured_config"]["business_mounting"]["business_action"] == "explain"


def test_create_draft_requires_auth(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
    )
    assert resp.status_code == 401


def test_create_draft_disabled_without_dev_mode(client, monkeypatch):
    monkeypatch.delenv("SKILL_CONTROL_DEV_MODE", raising=False)
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "SKILL_CONTROL_DISABLED"


def test_ai_generate_endpoint_returns_proposal(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/ai-generate",
        json={
            "description": "生成一个医保结算费用解释技能",
            "metric_codes": ["settlement.total_amount"],
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data) == {
        "generation_id",
        "proposal_hash",
        "structured_config",
        "raw_files",
        "validation_preview",
        "provenance",
        "citations",
        "uncertainties",
    }
    assert data["provenance"]["metric_versions"][0]["status"] == "published"


def test_ai_optimize_endpoint_returns_read_only_proposal(client):
    created = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "optimize_me", "skill_name": "Optimize Me"},
        headers=_auth_headers(),
    ).json()

    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/{created['draft_id']}/ai-optimize",
        json={
            "description": "优化说明",
            "metric_codes": ["settlement.total_amount"],
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["base_revision"] == 1
    stored = client._draft_storage.get_draft(created["draft_id"])  # type: ignore[attr-defined]
    assert stored.revision == 1
    assert stored.structured_config == created["structured_config"]


def test_ai_optimize_rejects_stale_revision_with_standard_conflict(client):
    created = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "stale_optimize", "skill_name": "Stale Optimize"},
        headers=_auth_headers(),
    ).json()

    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/{created['draft_id']}/ai-optimize",
        json={
            "description": "优化说明",
            "metric_codes": ["settlement.total_amount"],
            "expected_revision": 99,
        },
        headers=_auth_headers(),
    )

    assert resp.status_code == 409
    assert set(resp.json()["detail"]) == {"error_code", "message", "audit_event"}
    assert resp.json()["detail"]["error_code"] == "SKILL_DRAFT_CONFLICT"
    assert client._ai_service.optimize_calls == []  # type: ignore[attr-defined]


def test_ai_generate_requires_release_test_permission(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/ai-generate",
        json={"description": "生成解释技能", "metric_codes": ["m1"]},
        headers=_auth_headers(_control_token(permissions=["skill:evaluate"])),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["error_code"] == "SKILL_CONTROL_FORBIDDEN"


def test_ai_generate_rejects_dangerous_code_with_standard_error(client):
    client._ai_service.generate_error = SkillAISecurityRejectedError(  # type: ignore[attr-defined]
        [SkillAISecurityIssue(code="FORBIDDEN_CALL", message="exec forbidden")]
    )
    resp = client.post(
        f"{PREFIX}/infra-skills/ai-generate",
        json={"description": "生成解释技能", "metric_codes": ["m1"]},
        headers=_auth_headers(),
    )
    assert resp.status_code == 422
    assert set(resp.json()["detail"]) == {"error_code", "message", "audit_event"}
    assert resp.json()["detail"]["error_code"] == "SKILL_AI_SECURITY_REJECTED"


def test_ai_model_failure_does_not_create_draft(client):
    client._ai_service.generate_error = SkillAIModelError(category="timeout")  # type: ignore[attr-defined]
    resp = client.post(
        f"{PREFIX}/infra-skills/ai-generate",
        json={"description": "生成解释技能", "metric_codes": ["m1"]},
        headers=_auth_headers(),
    )
    assert resp.status_code == 503
    assert client._draft_storage.list_drafts() == []  # type: ignore[attr-defined]


def _generate_and_accept_payload(client) -> dict[str, object]:
    proposal = client.post(
        f"{PREFIX}/infra-skills/ai-generate",
        json={
            "description": "生成解释技能",
            "metric_codes": ["settlement.total_amount"],
        },
        headers=_auth_headers(),
    ).json()
    return {
        "generation_id": proposal["generation_id"],
        "proposal_hash": proposal["proposal_hash"],
        "skill_id": proposal["structured_config"]["basic"]["skill_id"],
        "skill_name": proposal["structured_config"]["basic"]["skill_name"],
        "structured_config": proposal["structured_config"],
        "raw_files": proposal["raw_files"],
        "provenance": proposal["provenance"],
    }


def test_accept_ai_proposal_creates_one_ai_generated_draft_idempotently(client):
    payload = _generate_and_accept_payload(client)
    headers = {**_auth_headers(), "Idempotency-Key": "accept-1"}
    first = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai", json=payload, headers=headers
    )
    second = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai", json=payload, headers=headers
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["draft_id"] == second.json()["draft_id"]
    assert first.json()["source_type"] == "ai_generated"
    assert first.json()["created_by"] == "information-admin"
    drafts = client._draft_storage.list_drafts()  # type: ignore[attr-defined]
    assert len(drafts) == 1
    assert "__generation_meta__.json" in drafts[0].raw_files


def test_accept_ai_proposal_uses_one_draft_across_different_idempotency_keys(client):
    payload = _generate_and_accept_payload(client)
    first = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json=payload,
        headers={**_auth_headers(), "Idempotency-Key": "proposal-key-1"},
    )
    second = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json=payload,
        headers={**_auth_headers(), "Idempotency-Key": "proposal-key-2"},
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json()["draft_id"] == first.json()["draft_id"]
    assert len(client._draft_storage.list_drafts()) == 1  # type: ignore[attr-defined]


def test_accept_ai_proposal_replays_completed_result_after_evidence_is_deleted(client):
    payload = _generate_and_accept_payload(client)
    headers = {**_auth_headers(), "Idempotency-Key": "accept-replay-expired"}
    first = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai", json=payload, headers=headers
    )
    assert first.status_code == 201, first.text
    stored = client._cache.get_result(  # type: ignore[attr-defined]
        "skill-governance:ai-draft:gen-api-1:accept-replay-expired"
    )
    assert set(stored or {}) == {"draft_id", "_request_hash"}

    client._cache.delete_state("skill-ai-authoring", payload["generation_id"])  # type: ignore[attr-defined]
    second = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai", json=payload, headers=headers
    )

    assert second.status_code == 201, second.text
    assert second.json()["draft_id"] == first.json()["draft_id"]
    assert len(client._draft_storage.list_drafts()) == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize("tamper", ["proposal_hash", "provenance"])
def test_accept_ai_proposal_rejects_client_tampering(client, tamper):
    payload = _generate_and_accept_payload(client)
    if tamper == "proposal_hash":
        payload["proposal_hash"] = "c" * 64
    else:
        payload["provenance"]["prompt_version"] = "forged"  # type: ignore[index]
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json=payload,
        headers={**_auth_headers(), "Idempotency-Key": f"tamper-{tamper}"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_AI_EVIDENCE_CONFLICT"
    assert client._draft_storage.list_drafts() == []  # type: ignore[attr-defined]


def test_accept_ai_proposal_rejects_expired_evidence(client):
    payload = _generate_and_accept_payload(client)
    client._cache.delete_state("skill-ai-authoring", payload["generation_id"])  # type: ignore[attr-defined]
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json=payload,
        headers={**_auth_headers(), "Idempotency-Key": "expired"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_AI_EVIDENCE_INVALID"


def test_accept_ai_proposal_rechecks_published_metric_snapshot(client):
    payload = _generate_and_accept_payload(client)
    client._ai_service.verify_error = SkillAIMetricNotPublishedError(  # type: ignore[attr-defined]
        "settlement.total_amount"
    )
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json=payload,
        headers={**_auth_headers(), "Idempotency-Key": "stale-metric"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_AI_EVIDENCE_STALE"


def test_accept_ai_proposal_maps_deleted_metric_to_stale_evidence(client):
    payload = _generate_and_accept_payload(client)
    client._ai_service.verify_error = SkillAIMetricNotFoundError(  # type: ignore[attr-defined]
        "settlement.total_amount"
    )

    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json=payload,
        headers={**_auth_headers(), "Idempotency-Key": "deleted-metric"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_AI_EVIDENCE_STALE"
    assert client._draft_storage.list_drafts() == []  # type: ignore[attr-defined]


def test_accept_ai_proposal_rejects_changed_snapshot_with_same_version(client):
    payload = _generate_and_accept_payload(client)
    client._ai_service.current_metric_snapshot_hash = "d" * 64  # type: ignore[attr-defined]

    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json=payload,
        headers={**_auth_headers(), "Idempotency-Key": "changed-snapshot"},
    )

    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_AI_EVIDENCE_STALE"
    assert client._draft_storage.list_drafts() == []  # type: ignore[attr-defined]


# ── 复制 ──────────────────────────────────────────────────────────


def test_copy_skill_creates_draft(client):
    client._loader.skills["src_skill"] = SimpleNamespace(  # type: ignore[attr-defined]
        skill_id="src_skill",
        skill_name="Source Skill",
        business_action="explain",
        business_object="settlement",
        include_keywords=["费用"],
        excluded_intents=[],
        manifest={"description": "源", "owner": "信息科"},
    )
    resp = client.post(
        f"{PREFIX}/infra-skills/src_skill/copy",
        json={"new_skill_id": "copied_skill"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source_type"] == "copy"
    assert data["source_skill_id"] == "src_skill"
    assert data["skill_id"] == "copied_skill"


def test_copy_skill_source_not_found(client):
    resp = client.post(
        f"{PREFIX}/infra-skills/missing/copy",
        json={"new_skill_id": "copied"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "SKILL_SOURCE_NOT_FOUND"


# ── 列表与详情 ────────────────────────────────────────────────────


def test_list_drafts(client):
    client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    )
    resp = client.get(f"{PREFIX}/infra-skills/drafts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(item["deleted_at"] is None for item in data["items"])


def test_get_draft(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    resp = client.get(f"{PREFIX}/infra-skills/drafts/{create['draft_id']}")
    assert resp.status_code == 200
    assert resp.json()["draft_id"] == create["draft_id"]


def test_get_draft_not_found(client):
    resp = client.get(f"{PREFIX}/infra-skills/drafts/missing")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "SKILL_DRAFT_NOT_FOUND"


# ── 保存（乐观锁）────────────────────────────────────────────────


def test_save_draft_updates_and_increments_revision(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    resp = client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={
            "structured_config": {
                "basic": {"skill_id": "s1", "skill_name": "Renamed"},
                "business_mounting": {
                    "business_action": "query",
                    "business_object": "benefit",
                    "include_keywords": [],
                    "excluded_intents": [],
                },
                "inputs": [],
                "schemas": {},
            },
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["revision"] == 2
    assert data["skill_name"] == "Renamed"


def test_save_draft_stale_revision_returns_409(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    # 第一次保存成功
    client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={
            "structured_config": {"basic": {"skill_name": "v2"}},
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    # 用过期 revision 再保存 → 409
    resp = client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={
            "structured_config": {"basic": {"skill_name": "v3"}},
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_DRAFT_CONFLICT"


def test_save_draft_not_found(client):
    resp = client.patch(
        f"{PREFIX}/infra-skills/drafts/missing",
        json={"structured_config": {}, "expected_revision": 1},
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


# ── 删除 ──────────────────────────────────────────────────────────


def test_delete_draft_soft_deletes(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    resp = client.delete(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}?expected_revision=1",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    # 再 GET 应 404
    assert client.get(f"{PREFIX}/infra-skills/drafts/{create['draft_id']}").status_code == 404


def test_delete_draft_stale_revision_returns_409(client):
    create = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={"skill_id": "s1", "skill_name": "S1"},
        headers=_auth_headers(),
    ).json()
    client.patch(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}",
        json={"structured_config": {}, "expected_revision": 1},
        headers=_auth_headers(),
    )
    resp = client.delete(
        f"{PREFIX}/infra-skills/drafts/{create['draft_id']}?expected_revision=1",
        headers=_auth_headers(),
    )
    assert resp.status_code == 409


# ── 导入端点（P3 实现）───────────────────────────────────


def test_import_zip_creates_draft(client):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "pkg/skill_manifest.yaml",
            "skill_id: imp\nskill_name: Imp\nbusiness_action: explain\nbusiness_object: settlement\n",
        )
        zf.writestr("pkg/SKILL.md", "# Imp")
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/import?source=zip",
        content=buf.getvalue(),
        headers={**_auth_headers(), "filename": "pkg.zip"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["source_type"] == "import"
    assert data["skill_id"] == "imp"
    assert "SKILL.md" in data["raw_files"]


def test_import_rejects_path_traversal(client):
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.yaml", "x")
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/import?source=zip",
        content=buf.getvalue(),
        headers={**_auth_headers(), "filename": "x.zip"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "SKILL_IMPORT_REJECTED"
