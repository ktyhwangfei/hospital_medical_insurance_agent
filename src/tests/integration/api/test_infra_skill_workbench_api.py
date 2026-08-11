"""Portal Skill 管理工作台的兼容 API 测试。"""

import os
from datetime import datetime, timezone
from unittest.mock import patch

os.environ["USE_MEMORY_STORAGE"] = "1"

from fastapi.testclient import TestClient

from src.domain.skill.draft_models import (
    SkillDraft,
    SkillDraftSourceType,
    SkillDraftStatus,
)
from src.domain.skill.governance_models import (
    SkillEvalMetrics,
    SkillEvalRun,
    SkillEvalRunStatus,
    SkillReleaseEnvironment,
)
from src.domain.skill.version_models import SkillValidationStatus, SkillVersion
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    get_skill_draft_service,
    get_skill_governance_service,
    get_skill_version_service,
)
from src.runtime.skill_management.version_service import (
    SkillCatalogEntry,
    SkillCatalogPage,
)


PREFIX = "/api/v1/medical-insurance-ai-agent"
NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)
HASH = "a" * 64


def _version(skill_id: str) -> SkillVersion:
    return SkillVersion(
        version_id=f"version-{skill_id}",
        skill_id=skill_id,
        semantic_version="1.0.0",
        source_commit="abc1234",
        source_path=f"skills/{skill_id}",
        artifact_hash=HASH,
        manifest_snapshot={"skill_id": skill_id, "version": "1.0.0"},
        dependency_snapshot={},
        file_count=2,
        validation_status=SkillValidationStatus.PASSED,
        created_by="developer",
        created_at=NOW,
    )


def _entry(skill_id: str) -> SkillCatalogEntry:
    version = _version(skill_id)
    return SkillCatalogEntry(
        skill_id=skill_id,
        skill_name=f"{skill_id} name",
        business_action="explain",
        business_object="settlement",
        semantic_version=version.semantic_version,
        artifact_hash=version.artifact_hash,
        artifact_status="registered",
        file_count=version.file_count,
        registered_version=version,
    )


def _failed_run(skill_id: str) -> SkillEvalRun:
    return SkillEvalRun(
        run_id=f"run-{skill_id}",
        skill_id=skill_id,
        version_id=f"version-{skill_id}",
        baseline_version_id="version-baseline",
        suite_version=1,
        config_hash=HASH,
        routing_manifest_hash=HASH,
        status=SkillEvalRunStatus.FAILED,
        metrics=SkillEvalMetrics(
            total=1,
            passed=0,
            required_total=1,
            required_passed=0,
            top1_accuracy=0,
            baseline_top1_accuracy=1,
            regression_count=1,
            new_false_takeover_count=0,
            gate_passed=False,
        ),
        created_by="quality-user",
        created_at=NOW,
        completed_at=NOW,
    )


class _VersionService:
    def __init__(self) -> None:
        self.entries = [
            _entry("a-drafted"),
            _entry("b-blocked"),
            _entry("c-normal"),
        ]
        self.versions = {
            entry.registered_version.version_id: entry.registered_version
            for entry in self.entries
            if entry.registered_version is not None
        }

    def list_catalog(self, **_: object) -> SkillCatalogPage:
        return SkillCatalogPage(
            items=self.entries,
            page=1,
            page_size=10_000,
            total=len(self.entries),
        )

    def get_version(self, skill_id: str, version_id: str) -> SkillVersion:
        version = self.versions[version_id]
        assert version.skill_id == skill_id
        return version


class _GovernanceService:
    def list_eval_runs(self, skill_id: str) -> list[SkillEvalRun]:
        return [_failed_run(skill_id)] if skill_id != "c-normal" else []

    def list_releases(
        self,
        skill_id: str,
        environment: SkillReleaseEnvironment | str | None = None,
    ) -> list[object]:
        assert skill_id
        assert environment == SkillReleaseEnvironment.TEST
        return []


class _DraftService:
    def list_drafts(self, **_: object) -> list[SkillDraft]:
        return [
            SkillDraft(
                draft_id="draft-sensitive",
                skill_id="a-drafted",
                skill_name="Sensitive draft",
                source_type=SkillDraftSourceType.COPY,
                source_skill_id="a-drafted",
                structured_config={
                    "question_template": "SENSITIVE_QUESTION",
                    "approval_reason": "SENSITIVE_APPROVAL",
                    "patient_id": "SENSITIVE_PATIENT",
                },
                status=SkillDraftStatus.EDITING,
                created_by="developer",
                created_at=NOW,
                updated_at=NOW,
            )
        ]


def _client_with_in_memory_dependencies() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_skill_version_service] = _VersionService
    app.dependency_overrides[get_skill_governance_service] = _GovernanceService
    app.dependency_overrides[get_skill_draft_service] = _DraftService
    return TestClient(app)


def test_skill_overview_returns_loaded_skill_summary():
    with patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test")):
        response = TestClient(create_app()).get(f"{PREFIX}/infra-skills/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["skill_count"] >= 1
    assert body["skills"]
    assert {"skill_id", "loaded", "manifest_valid", "metric_count"}.issubset(body["skills"][0])


def test_skill_workbench_returns_daily_projection_and_filters_before_pagination():
    response = _client_with_in_memory_dependencies().get(
        f"{PREFIX}/infra-skills/workbench?priority=blocked&page=1&page_size=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["skill_id"] == "b-blocked"
    assert item["priority"] == "blocked"
    assert {
        "current_stage",
        "priority",
        "latest_eval_run_id",
        "candidate_version",
        "baseline_version",
        "regression_count",
        "required_failure_count",
        "linked_draft_id",
        "linked_draft_status",
        "waiting_since",
        "next_action",
        "next_action_reason",
    }.issubset(item)


def test_skill_workbench_keeps_old_fields_and_hides_sensitive_draft_values():
    response = _client_with_in_memory_dependencies().get(
        f"{PREFIX}/infra-skills/workbench"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total"] == 3
    assert {
        "healthy",
        "needs_evaluation",
        "pending_approval",
        "test_active",
        "updated_at",
    }.issubset(body["summary"])
    item = next(item for item in body["items"] if item["skill_id"] == "a-drafted")
    assert {
        "governance_status",
        "latest_eval_status",
        "test_release_status",
        "attention_reason",
    }.issubset(item)
    assert item["linked_draft_id"] == "draft-sensitive"
    assert item["linked_draft_status"] == "editing"
    for sensitive in (
        "question_template",
        "approval_reason",
        "patient_id",
        "SENSITIVE_QUESTION",
        "SENSITIVE_APPROVAL",
        "SENSITIVE_PATIENT",
    ):
        assert sensitive not in response.text


def test_skill_workbench_without_priority_preserves_existing_pagination():
    response = _client_with_in_memory_dependencies().get(
        f"{PREFIX}/infra-skills/workbench?page=2&page_size=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert [item["skill_id"] for item in body["items"]] == ["c-normal"]


def test_skill_workbench_rejects_invalid_priority():
    response = _client_with_in_memory_dependencies().get(
        f"{PREFIX}/infra-skills/workbench?priority=urgent"
    )

    assert response.status_code == 422


def test_skill_workbench_openapi_keeps_public_schema_with_projection_fields():
    schema = create_app().openapi()
    response_schema = schema["paths"][f"{PREFIX}/infra-skills/workbench"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]

    assert response_schema["$ref"].endswith("/SkillWorkbenchResponse")
    public_response = schema["components"]["schemas"]["SkillWorkbenchResponse"]
    assert public_response["properties"]["items"]["items"]["$ref"].endswith(
        "/SkillWorkbenchItemResponse"
    )
    public_item = schema["components"]["schemas"]["SkillWorkbenchItemResponse"]
    assert {
        "current_stage",
        "priority",
        "latest_eval_run_id",
        "candidate_version",
        "baseline_version",
        "regression_count",
        "required_failure_count",
        "linked_draft_id",
        "linked_draft_status",
        "waiting_since",
        "next_action",
        "next_action_reason",
    }.issubset(public_item["properties"])


def test_route_test_response_keeps_legacy_fields_and_adds_explanation():
    with patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test")):
        response = TestClient(create_app()).post(
            f"{PREFIX}/infra-skills/route-test",
            json={"question": "统筹自付怎么算？"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "统筹自付怎么算？"
    assert "matched_skill_id" in body
    assert isinstance(body["confidence"], float)
    assert isinstance(body["candidates"], list)


def test_route_test_rejects_empty_question():
    with patch("psycopg.connect", side_effect=Exception("No PostgreSQL available in test")):
        response = TestClient(create_app()).post(
            f"{PREFIX}/infra-skills/route-test",
            json={"question": ""},
        )

    assert response.status_code == 200
    assert response.json()["matched_skill_id"] is None
    assert response.json()["match_method"] == "none"
