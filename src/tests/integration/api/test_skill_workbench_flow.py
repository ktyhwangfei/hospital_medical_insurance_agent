"""Skill 管理工作台端到端流程测试（P9 / T3）。

验证完整生命周期：创建草稿 → 保存 → 校验 → 物化 → 停用 → 恢复 → 归档。
所有依赖注入覆盖为内存存储 + 临时目录，无需外部服务。
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
from src.runtime.api.app import create_app
from src.runtime.api.infra_skill_routes import (
    get_skill_draft_service,
    get_skill_materializer,
    get_skill_lifecycle_service,
)
from src.runtime.skill_management.draft_service import SkillDraftService
from src.runtime.skill_management.lifecycle_service import SkillLifecycleService
from src.runtime.skill_management.materializer import SkillMaterializer

PREFIX = "/api/v1/medical-insurance-ai-agent"


def _control_token() -> str:
    payload = {
        "sub": "information-admin",
        "roles": ["information_department"],
        "permissions": ["skill:release:test", "skill:evaluate"],
        "exp": (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp(),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"test.{encoded}.signature"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_control_token()}"}


class _FakeVersionService:
    """版本登记桩：记录调用、返回固定 version_id。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def sync_version(self, skill_id, *, source_commit, created_by):
        self.calls.append((skill_id, created_by))
        return SimpleNamespace(
            version_id=f"ver-{len(self.calls)}",
            skill_id=skill_id,
            semantic_version="1.0.0",
            artifact_hash="a" * 64,
        )


class _FakeLoader:
    def __init__(self) -> None:
        self.skills: dict[str, SimpleNamespace] = {}

    def get(self, skill_id: str):
        return self.skills.get(skill_id)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SKILL_CONTROL_DEV_MODE", "1")
    app = create_app()

    # 共享内存存储（草稿 + 定义）
    storage = InMemorySkillDraftStorage()
    version_service = _FakeVersionService()
    loader = _FakeLoader()
    skills_root = tmp_path / "skills"
    skills_root.mkdir()

    draft_service = SkillDraftService(
        storage=storage, loader=loader, skills_root=str(skills_root)
    )
    materializer = SkillMaterializer(
        draft_service=draft_service,
        draft_storage=storage,
        version_service=version_service,
        skills_root=skills_root,
    )
    lifecycle_service = SkillLifecycleService(definition_storage=storage)

    app.dependency_overrides[get_skill_draft_service] = lambda: draft_service
    app.dependency_overrides[get_skill_materializer] = lambda: materializer
    app.dependency_overrides[get_skill_lifecycle_service] = lambda: lifecycle_service

    return TestClient(app)


def _create_draft(client, skill_id="flow_skill") -> dict:
    """创建草稿并返回响应 JSON。"""
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts",
        json={
            "skill_id": skill_id,
            "skill_name": "Flow Skill",
            "business_action": "explain",
            "business_object": "settlement",
            "include_keywords": ["费用"],
        },
        headers={**_auth_headers(), "Idempotency-Key": f"create-{skill_id}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _validate_draft(client, draft_id: str) -> dict:
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/{draft_id}/validate",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_skill_lifecycle_flow(client):
    """P9 端到端：创建 → 保存 → 校验 → 物化 → 获取定义 → 停用 → 恢复 → 归档。"""

    # 1. 创建草稿
    draft = _create_draft(client)
    assert draft["status"] == "editing"
    assert draft["skill_id"] == "flow_skill"
    draft_id = draft["draft_id"]
    revision = draft["revision"]

    # 2. 保存草稿（PATCH，乐观锁）—— 包含 validator 所需的 basic 段
    save_resp = client.patch(
        f"{PREFIX}/infra-skills/drafts/{draft_id}",
        json={
            "structured_config": {
                "basic": {
                    "skill_id": "flow_skill",
                    "skill_name": "Flow Skill",
                    "description": "流程测试 Skill",
                    "owner": "信息科",
                },
                "business_mounting": {
                    "business_action": "explain",
                    "business_object": "settlement",
                    "keywords": ["费用", "结算"],
                },
            },
            "expected_revision": revision,
        },
        headers=_auth_headers(),
    )
    assert save_resp.status_code == 200, save_resp.text
    saved = save_resp.json()
    assert saved["revision"] == revision + 1
    revision = saved["revision"]

    # 3. 校验草稿
    validation = _validate_draft(client, draft_id)
    assert validation["blocking_ok"] is True

    # 4. 物化发布
    mat_resp = client.post(
        f"{PREFIX}/infra-skills/drafts/{draft_id}/materialize",
        json={
            "draft_id": draft_id,
            "expected_revision": revision,
            "reason": "首次物化发布",
        },
        headers={**_auth_headers(), "Idempotency-Key": f"mat-{draft_id}"},
    )
    assert mat_resp.status_code == 201, mat_resp.text
    materialized = mat_resp.json()
    assert materialized["artifact_written"] is True
    assert materialized["version_id"].startswith("ver-")

    # 5. 获取定义（应为 enabled）
    def_resp = client.get(
        f"{PREFIX}/infra-skills/definitions/flow_skill",
        headers=_auth_headers(),
    )
    assert def_resp.status_code == 200, def_resp.text
    definition = def_resp.json()
    assert definition["lifecycle_status"] == "enabled"
    def_revision = definition["revision"]

    # 6. 停用
    dis_resp = client.post(
        f"{PREFIX}/infra-skills/flow_skill/disable",
        json={"expected_revision": def_revision, "reason": "停用测试"},
        headers=_auth_headers(),
    )
    assert dis_resp.status_code == 200, dis_resp.text
    assert dis_resp.json()["lifecycle_status"] == "disabled"
    def_revision = dis_resp.json()["revision"]

    # 7. 恢复
    res_resp = client.post(
        f"{PREFIX}/infra-skills/flow_skill/restore",
        json={"expected_revision": def_revision, "reason": "恢复测试"},
        headers=_auth_headers(),
    )
    assert res_resp.status_code == 200, res_resp.text
    assert res_resp.json()["lifecycle_status"] == "enabled"
    def_revision = res_resp.json()["revision"]

    # 8. 归档
    arc_resp = client.post(
        f"{PREFIX}/infra-skills/flow_skill/archive",
        json={"expected_revision": def_revision, "reason": "归档测试"},
        headers=_auth_headers(),
    )
    assert arc_resp.status_code == 200, arc_resp.text
    assert arc_resp.json()["lifecycle_status"] == "archived"


def test_optimistic_lock_conflict_on_save(client):
    """乐观锁：过期 revision 保存应返回 409。"""
    draft = _create_draft(client, skill_id="lock_skill")
    draft_id = draft["draft_id"]

    # 第一次保存（revision 1 → 2）
    resp1 = client.patch(
        f"{PREFIX}/infra-skills/drafts/{draft_id}",
        json={
            "structured_config": draft["structured_config"],
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    assert resp1.status_code == 200

    # 用过期 revision=1 再保存 → 409
    resp2 = client.patch(
        f"{PREFIX}/infra-skills/drafts/{draft_id}",
        json={
            "structured_config": draft["structured_config"],
            "expected_revision": 1,
        },
        headers=_auth_headers(),
    )
    assert resp2.status_code == 409
    assert resp2.json()["detail"]["error_code"] == "SKILL_DRAFT_CONFLICT"


def test_materialize_requires_validated_status(client):
    """未校验的草稿不能物化。"""
    draft = _create_draft(client, skill_id="unvalidated")
    resp = client.post(
        f"{PREFIX}/infra-skills/drafts/{draft['draft_id']}/materialize",
        json={
            "draft_id": draft["draft_id"],
            "expected_revision": draft["revision"],
            "reason": "测试",
        },
        headers={**_auth_headers(), "Idempotency-Key": "mat-unvalidated"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error_code"] == "SKILL_MATERIALIZE_FAILED"


def test_package_preview_after_create(client):
    """创建后包预览应返回生成的文件。"""
    draft = _create_draft(client, skill_id="preview_skill")
    resp = client.get(
        f"{PREFIX}/infra-skills/drafts/{draft['draft_id']}/package-preview",
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    files = resp.json()["files"]
    paths = [f["path"] for f in files]
    assert "skill_manifest.yaml" in paths
    assert "SKILL.md" in paths


def test_delete_draft_then_not_found(client):
    """删除草稿后获取应返回 404。"""
    draft = _create_draft(client, skill_id="delete_me")
    draft_id = draft["draft_id"]

    del_resp = client.delete(
        f"{PREFIX}/infra-skills/drafts/{draft_id}?expected_revision={draft['revision']}",
        headers=_auth_headers(),
    )
    assert del_resp.status_code == 200

    get_resp = client.get(
        f"{PREFIX}/infra-skills/drafts/{draft_id}",
        headers=_auth_headers(),
    )
    assert get_resp.status_code == 404
