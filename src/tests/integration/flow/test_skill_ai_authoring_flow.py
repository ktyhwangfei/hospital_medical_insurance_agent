"""Batch A Skill AI 编写主流程：生成→接受→校验→包预览。"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.data_platform.cache.in_memory import InMemoryCacheClient
from src.data_platform.storage.skill.draft_in_memory import InMemorySkillDraftStorage
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    get_skill_ai_authoring_service,
    get_skill_draft_service,
    get_skill_idempotency_store,
)
from src.runtime.skill_management.ai_authoring.schemas import (
    SkillAIGenerationResponse,
    SkillAIOptimizationDiff,
    SkillAIOptimizationResponse,
)
from src.runtime.skill_management.draft_service import SkillDraftService


PREFIX = "/api/v1/medical-insurance-ai-agent"


class _FakeLoader:
    def get(self, _skill_id: str):
        return None


class _ControlledAuthoringService:
    def __init__(self) -> None:
        self.proposal = SkillAIGenerationResponse.model_validate(
            {
                "generation_id": "gen_abcdef123456_flow",
                "proposal_hash": "a" * 64,
                "structured_config": {
                    "basic": {
                        "skill_id": "flow_ai_skill",
                        "skill_name": "Flow AI Skill",
                        "description": "解释医保结算金额",
                        "owner": "information_department",
                    },
                    "business_mounting": {
                        "business_action": "explain",
                        "business_object": "settlement",
                        "include_keywords": ["结算"],
                        "excluded_intents": [],
                    },
                    "inputs": [
                        {
                            "metric_code": "settlement.total_amount",
                            "alias": "total_amount",
                            "required": True,
                            "purpose": "解释结算金额",
                        }
                    ],
                    "schemas": {
                        "input": {"type": "object"},
                        "output": {"type": "object"},
                    },
                },
                "raw_files": {
                    "assembler.py": "def load(config):\n    return config\n",
                    "prompt_template.yaml": "system: explain with citations\n",
                },
                "validation_preview": {
                    "issues": [],
                    "has_blocking": False,
                    "blocking_ok": True,
                },
                "provenance": {
                    "model_type": "controlled-model",
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

    def generate_with_evidence(self, _request):
        return SimpleNamespace(
            proposal=self.proposal,
            metric_snapshot_hash="c" * 64,
        )

    def verify_for_accept(self, _proposal, *, metric_snapshot_hash):
        assert metric_snapshot_hash == "c" * 64

    def optimize(self, draft, _request):
        config = self.proposal.structured_config.model_copy(
            update={
                "basic": self.proposal.structured_config.basic.model_copy(
                    update={"description": "优化后的结算金额解释"}
                )
            }
        )
        raw_files = dict(draft.raw_files)
        raw_files["prompt_template.yaml"] = "system: explain with concise examples\n"
        return SkillAIOptimizationResponse(
            base_revision=draft.revision,
            proposal_hash="d" * 64,
            structured_config=config,
            raw_files=raw_files,
            validation_preview=self.proposal.validation_preview,
            provenance=self.proposal.provenance,
            diff=(
                SkillAIOptimizationDiff(
                    scope="field",
                    change_type="changed",
                    path="structured_config.basic.description",
                    before="解释医保结算金额",
                    after="优化后的结算金额解释",
                ),
            ),
            citations=self.proposal.citations,
            uncertainties=self.proposal.uncertainties,
        )


def _auth_headers() -> dict[str, str]:
    payload = {
        "sub": "information-admin",
        "roles": ["information_department"],
        "permissions": ["skill:release:test"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return {"Authorization": f"Bearer test.{encoded}.signature"}


def test_skill_ai_generate_accept_validate_and_preview_package(monkeypatch) -> None:
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")
    app = create_app()
    storage = InMemorySkillDraftStorage()
    draft_service = SkillDraftService(
        storage=storage,
        loader=_FakeLoader(),
        skills_root="/nonexistent-skills-root",
    )
    authoring_service = _ControlledAuthoringService()
    cache = InMemoryCacheClient()
    app.dependency_overrides[get_skill_draft_service] = lambda: draft_service
    app.dependency_overrides[get_skill_ai_authoring_service] = lambda: authoring_service
    app.dependency_overrides[get_skill_idempotency_store] = lambda: cache
    client = TestClient(app)

    generated = client.post(
        f"{PREFIX}/infra-skills/ai-generate",
        json={
            "description": "解释医保结算金额",
            "metric_codes": ["settlement.total_amount"],
        },
        headers=_auth_headers(),
    )
    assert generated.status_code == 200, generated.text
    proposal = generated.json()
    accepted = client.post(
        f"{PREFIX}/infra-skills/drafts/from-ai",
        json={
            "generation_id": proposal["generation_id"],
            "proposal_hash": proposal["proposal_hash"],
            "skill_id": proposal["structured_config"]["basic"]["skill_id"],
            "skill_name": proposal["structured_config"]["basic"]["skill_name"],
            "structured_config": proposal["structured_config"],
            "raw_files": proposal["raw_files"],
            "provenance": proposal["provenance"],
        },
        headers={**_auth_headers(), "Idempotency-Key": "flow-accept"},
    )
    assert accepted.status_code == 201, accepted.text
    draft_id = accepted.json()["draft_id"]

    optimized = client.post(
        f"{PREFIX}/infra-skills/drafts/{draft_id}/ai-optimize",
        json={
            "description": "补充简明示例",
            "metric_codes": ["settlement.total_amount"],
            "expected_revision": accepted.json()["revision"],
        },
        headers=_auth_headers(),
    )
    assert optimized.status_code == 200, optimized.text
    optimization = optimized.json()
    assert storage.get_draft(draft_id).revision == accepted.json()["revision"]

    saved = client.patch(
        f"{PREFIX}/infra-skills/drafts/{draft_id}",
        json={
            "structured_config": optimization["structured_config"],
            "raw_files": optimization["raw_files"],
            "expected_revision": optimization["base_revision"],
        },
        headers=_auth_headers(),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == optimization["base_revision"] + 1
    assert (
        saved.json()["structured_config"]["basic"]["description"]
        == "优化后的结算金额解释"
    )

    validated = client.post(
        f"{PREFIX}/infra-skills/drafts/{draft_id}/validate",
        headers=_auth_headers(),
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["blocking_ok"] is True
    assert validated.json()["issues"] == []

    preview = client.get(f"{PREFIX}/infra-skills/drafts/{draft_id}/package-preview")
    assert preview.status_code == 200, preview.text
    paths = {item["path"] for item in preview.json()["files"]}
    assert "assembler.py" in paths
    assert "prompt_template.yaml" in paths
    assert "__generation_meta__.json" not in paths
